"""One bounded LoRA update using Cookbook rollouts and training data."""

import asyncio
import math
from collections.abc import Callable
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path

import tinker
from tinker_cookbook.completers import TinkerTokenCompleter
from tinker_cookbook.renderers import get_renderer
from tinker_cookbook.rl.data_processing import assemble_training_data, compute_advantages
from tinker_cookbook.rl.rollouts import do_group_rollout
from tinker_cookbook.rl.types import TrajectoryGroup
from tinker_cookbook.tokenizer_utils import get_tokenizer
from tinker_cookbook.utils.cost_estimation import TokenCostRates, TokenUsage, fetch_model_pricing

from .contracts import EpisodeConfig, TaskDefinition
from .cookbook import ELTDataset, ELTGroupBuilder, TokenBudget

COOKBOOK_SHA = "28de41edfcdd07ba3e7980f35d53a586024a2184"
LOSS = "importance_sampling"


def datums_for_group(group: TrajectoryGroup) -> list[tinker.Datum]:
    rewards = group.get_total_rewards()
    # Cookbook's standalone filter preserves a fallback constant group.
    if len(set(rewards)) < 2:
        return []
    groups = [group]
    datums, _ = assemble_training_data(groups, compute_advantages(groups))
    return [datum for datum in datums if any(datum.loss_fn_inputs["advantages"].data)]


def estimated_bound(prices: TokenCostRates, config: EpisodeConfig, budget: TokenBudget,
                    members: int, train: bool) -> float:
    token_positions = members * config.max_turns * budget.context
    usage = TokenUsage(
        sampled=members * min(budget.sampled, config.max_turns * budget.per_turn),
        prefill_uncached=token_positions,
        trained=token_positions if train else 0,
    )
    return prices.estimate_usd(usage)


def group_evidence(group: TrajectoryGroup) -> list[dict]:
    result = []
    for trajectory, reward in zip(group.trajectories_G, group.get_total_rewards(), strict=True):
        turns = []
        for transition in trajectory.transitions:
            feedback = [str(value)[:2048] for key, value in transition.logs.items()
                        if key.startswith("tool_result_")]
            calls = [str(value).split("(", 1)[0] for key, value in transition.logs.items()
                     if key.startswith("tool_call_")]
            turns.append({"tools": calls, "feedback": feedback, "metrics": transition.metrics,
                          "prompt_tokens": transition.ob.length,
                          "prefill_cached_tokens": transition.ac.prompt_cache_hit_tokens,
                          "sampled_tokens": len(transition.ac.tokens)})
        result.append({"reward": reward, "stop_reason": trajectory.stop_reason, "turns": turns})
    return result


def observed_usage(evidence: list[dict], datums: list[tinker.Datum]) -> TokenUsage:
    turns = [turn for item in evidence for turn in item["turns"] if turn["sampled_tokens"]]
    return TokenUsage(
        sampled=sum(turn["sampled_tokens"] for turn in turns),
        prefill_cached=sum(turn["prefill_cached_tokens"] for turn in turns),
        prefill_uncached=sum(max(0, turn["prompt_tokens"] - turn["prefill_cached_tokens"]) for turn in turns),
        trained=sum(datum.model_input.length for datum in datums),
    )


async def optimize_once(training_client: tinker.TrainingClient, datums: list[tinker.Datum],
                        record: Callable[..., None]) -> None:
    if not datums:
        raise ValueError("training requires nonempty datums")
    send = [replace(datum, loss_fn_inputs={key: value for key, value in datum.loss_fn_inputs.items()
                                           if key != "mask"}) for datum in datums]
    forward_future = training_client.forward_backward(send, LOSS)
    record(forward_backward={"status": "submitted"})
    # Queue the pair in order, as the pinned Cookbook trainer does.
    optim_future = training_client.optim_step(tinker.AdamParams(
        learning_rate=4e-5, beta1=0.9, beta2=0.95, eps=1e-8,
    ))
    record(optim_step={"status": "submitted"})
    forward, optimizer = await asyncio.gather(forward_future, optim_future, return_exceptions=True)
    if isinstance(forward, BaseException):
        record(forward_backward={"status": "failed", "error": type(forward).__name__})
    else:
        record(forward_backward={"status": "completed", "metrics": forward.metrics,
                                 "result_count": len(forward.loss_fn_outputs)})
    if isinstance(optimizer, BaseException):
        record(optim_step={"status": "failed", "error": type(optimizer).__name__})
    else:
        record(optim_step={"status": "completed", "metrics": optimizer.metrics})
    if isinstance(forward, BaseException) or isinstance(optimizer, BaseException):
        raise RuntimeError("Tinker forward/backward or optimizer request failed")
    checkpoint = await training_client.save_state("elt-one-step", ttl_seconds=86_400)
    record(checkpoint=checkpoint.path)


async def run_remote(
    mode: str, task: TaskDefinition, config: EpisodeConfig, out: Path, model: str,
    renderer_name: str, members: int, max_usd: float, record: Callable[..., None],
    *, seed: int = 0,
) -> int:
    train = mode == "train-one"
    budget = TokenBudget()
    prices = await asyncio.to_thread(fetch_model_pricing, model)
    if prices is None:
        raise ValueError("live pricing unavailable for this model")
    estimate = estimated_bound(prices, config, budget, members, train)
    if not math.isfinite(estimate) or estimate <= 0 or estimate > max_usd:
        raise ValueError(f"estimated Tinker token cost exceeds the bound or is invalid ({estimate:.4f} USD)")
    record(model=model, renderer=renderer_name, task=task.task_id, seed=seed,
           cookbook_sha=COOKBOOK_SHA, tinker_version=version("tinker"),
           lora_rank=16 if train else None, loss=LOSS if train else None,
           token_budget=asdict(budget), members=members, max_turns=config.max_turns,
           max_tool_calls=config.max_tool_calls, rollout_seconds=config.rollout_seconds,
           token_prices=asdict(prices), estimated_upper_usd=estimate,
           spending_limit_usd=max_usd, actual_spend_usd=None, balance_pre=None, balance_post=None)
    renderer = get_renderer(renderer_name, get_tokenizer(model))
    capabilities = await tinker.RestClient().get_server_capabilities()
    supported = next((item for item in capabilities.supported_models if item.model_name == model), None)
    if supported is None or supported.sampleable is False or (train and supported.trainable is False):
        raise ValueError("configured Tinker project does not support this model for the requested action")
    if supported.max_context_length and supported.max_context_length < budget.context:
        raise ValueError("model context length is smaller than the rollout budget")
    with tinker.ServiceClient(display_name=f"elt-{mode}") as service:
        training_client = None
        if train:
            training_client = await service.create_lora_training_client(model, rank=16, seed=seed)
            sampling_client = await training_client.save_weights_and_get_sampling_client()
        else:
            sampling_client = await service.create_sampling_client(base_model=model)
        record(session_url=service.get_console_url())
        policy = TinkerTokenCompleter(sampling_client, max_tokens=budget.per_turn,
                                      temperature=0.8, context_window=budget.context)
        dataset = ELTDataset(ELTGroupBuilder(
            config, renderer, members, task_factory=lambda: task, budget=budget, evidence_dir=out / "pipelines",
        ))
        builder, = dataset.get_batch(0)
        record(sampling="started")
        group = await do_group_rollout(builder, policy)
        evidence = group_evidence(group)
        record(sampling="completed", rewards=group.get_total_rewards(), trajectories=evidence)
        datums = datums_for_group(group) if train else []
        usage = observed_usage(evidence, datums)
        record(observed_token_usage=asdict(usage), estimated_observed_usd=prices.estimate_usd(usage))
        if not train:
            submitted = any(turn["metrics"].get("submitted", 0) for item in evidence for turn in item["turns"])
            record(status="rollout_submitted" if submitted else "rollout_unsubmitted")
            return 0 if submitted else 2
        record(training_datum_count=len(datums))
        if not datums:
            record(status="no_training_signal", reason="constant rewards or no usable datums")
            return 2
        assert training_client is not None
        await optimize_once(training_client, datums, record)
        record(status="checkpoint_saved", post_training_evaluation=False)
    return 0
