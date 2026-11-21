"""One bounded LoRA update using Cookbook rollouts and training data."""

import asyncio
import hashlib
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from importlib.metadata import version
from pathlib import Path

import tinker
from tinker.lib.base_url import DEFAULT_BASE_URL
from tinker.lib.retry_handler import RetryConfig
from tinker_cookbook.completers import TinkerTokenCompleter
from tinker_cookbook.rl.data_processing import assemble_training_data, compute_advantages
from tinker_cookbook.rl.rollouts import do_group_rollout
from tinker_cookbook.rl.types import PARSE_ERROR_MASKED_METRIC_KEY, TrajectoryGroup
from tinker_cookbook.utils.cost_estimation import TokenCostRates, TokenUsage, fetch_model_pricing

from .contracts import LORA_RANK, PILOT_BUDGET, EpisodeConfig, TaskDefinition, TokenBudget
from .cookbook import BooksRollout, ELTDataset, ELTGroupBuilder, finalization_renderer, submission_call_tokens
from .rendering import QWEN_TOKENIZER_REVISIONS, make_renderer
from .settings import DEFAULT_RENDERER, ConfigurationError
from .tinker_once import single_attempt_sdk

COOKBOOK_SHA = "28de41edfcdd07ba3e7980f35d53a586024a2184"
LOSS = "importance_sampling"


@dataclass
class RecordedTokenCompleter(TinkerTokenCompleter):
    trace_file: Path | None = None
    prompt_trace_file: Path | None = None

    async def __call__(self, model_input, stop, *, max_tokens=None):
        if self.prompt_trace_file is not None:
            with self.prompt_trace_file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"prompt_token_ids": model_input.to_ints(), "stop": stop,
                                         "max_tokens": max_tokens}, allow_nan=False) + "\n")
        sample = await super().__call__(model_input, stop, max_tokens=max_tokens)
        logprobs = sample.logprobs
        if (len(sample.tokens) != len(logprobs) or not all(math.isfinite(p) for p in logprobs)
            or (sample.tokens and not sample.sequence_id)):
            raise RuntimeError("sample returned missing or invalid behavior log probabilities or provenance")
        if self.trace_file is not None:
            with self.trace_file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "sequence_id": sample.sequence_id, "tokens": sample.tokens, "logprobs": logprobs,
                    "stop_reason": sample.stop_reason, "prompt_tokens": model_input.length,
                    "prefill_cached_tokens": sample.prompt_cache_hit_tokens,
                }, allow_nan=False) + "\n")
        return sample


def datums_for_group(group: TrajectoryGroup, *, require_provenance: bool = False) -> list[tinker.Datum]:
    rewards = group.get_total_rewards()
    # Cookbook's standalone filter preserves a fallback constant group.
    if len(set(rewards)) < 2:
        return []
    groups = [group]
    (advantages,) = compute_advantages(groups)
    # Runner stops can add synthetic transitions carrying reward/metrics
    # without a sampled action. Preserve their reward in the advantage,
    # while keeping their unsampled observation out of training provenance.
    training_group = replace(group, trajectories_G=[
        replace(trajectory, transitions=[transition for transition in trajectory.transitions if transition.ac.tokens])
        for trajectory in group.trajectories_G
    ])
    datums, mapping = assemble_training_data([training_group], [advantages])
    if require_provenance and any(
        transition.ac.tokens and not transition.ac.sequence_id
        for trajectory in group.trajectories_G for transition in trajectory.transitions
    ):
        raise RuntimeError("live sampled actions lack Tinker sequence IDs")
    selected = []
    for index, trajectory in enumerate(group.trajectories_G):
        chosen = [datum for datum, meta in zip(datums, mapping, strict=True)
                  if meta["traj_idx"] == index and any(datum.loss_fn_inputs["advantages"].data)]
        if not chosen:
            continue
        expected = [(token, logprob) for transition in trajectory.transitions
                    if transition.ac.tokens and not transition.metrics.get(PARSE_ERROR_MASKED_METRIC_KEY, 0)
                    for token, logprob in zip(transition.ac.tokens, transition.ac.logprobs, strict=True)]
        actual = []
        for datum in chosen:
            fields = datum.loss_fn_inputs
            if require_provenance and datum.loss_fn_input_spans is None:
                raise RuntimeError("live training datum lacks sampling provenance")
            for target, logprob, advantage, mask in zip(
                fields["target_tokens"].data, fields["logprobs"].data,
                fields["advantages"].data, fields["mask"].data, strict=True,
            ):
                if mask:
                    if not math.isfinite(logprob) or advantage != float(advantages[index]):
                        raise RuntimeError("sampled training target has invalid log probability or advantage")
                    actual.append((target, logprob))
                elif advantage:
                    raise RuntimeError("prompt or masked target has nonzero advantage")
        if len(expected) != len(actual) or any(
            token != observed or not math.isclose(logprob, observed_lp, rel_tol=1e-6, abs_tol=1e-7)
            for (token, logprob), (observed, observed_lp) in zip(expected, actual)
        ):
            raise RuntimeError("training targets do not match the recorded sampled actions")
        selected.extend(chosen)
    return selected


def estimated_bound(prices: TokenCostRates, config: EpisodeConfig, budget: TokenBudget,
                    members: int, train: bool) -> float:
    token_positions = members * config.max_turns * budget.context
    usage = TokenUsage(
        sampled=members * min(budget.sampled, config.max_turns * budget.per_turn),
        prefill_uncached=token_positions,
        trained=token_positions + budget.context if train else 0,
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


def alignment_evidence(datums: list[tinker.Datum]) -> dict:
    """Fingerprint the audited targets without storing raw text in the manifest."""
    digest = hashlib.sha256()
    action_count = 0
    for datum in datums:
        fields = datum.loss_fn_inputs
        for token, logprob, advantage, mask in zip(
            fields["target_tokens"].data, fields["logprobs"].data,
            fields["advantages"].data, fields["mask"].data, strict=True,
        ):
            if mask:
                digest.update(json.dumps([token, logprob, advantage], separators=(",", ":")).encode() + b"\n")
                action_count += 1
    return {"aligned_action_tokens": action_count, "aligned_targets_sha256": digest.hexdigest()}


def _action_logprobs(output, index: int, datum: tinker.Datum) -> list[float]:
    values = output.loss_fn_outputs[index]["logprobs"].data
    selected = [value for value, advantage in zip(
        values, datum.loss_fn_inputs["advantages"].data, strict=True,
    ) if advantage]
    if not selected or not all(math.isfinite(value) for value in selected):
        raise RuntimeError("trainer returned unusable action log probabilities")
    return selected


async def optimize_once(training_client: tinker.TrainingClient, datums: list[tinker.Datum],
                        record: Callable[..., None], *,
                        inspect_checkpoint: Callable[[str], Awaitable[dict]] | None = None) -> bool:
    if not datums:
        raise ValueError("training requires nonempty datums")
    send = [replace(datum, loss_fn_inputs={key: value for key, value in datum.loss_fn_inputs.items()
                                           if key != "mask"}) for datum in datums]
    forward_future = training_client.forward_backward(send, LOSS)
    record(forward_backward={"status": "submitted", "request_input_tokens": sum(d.model_input.length for d in send)})
    try:
        async with asyncio.timeout(180):
            forward = await forward_future
        if len(forward.loss_fn_outputs) != len(send):
            raise RuntimeError("forward/backward returned an unexpected result count")
        probe = max(range(len(send)), key=lambda i: sum(bool(a) for a in send[i].loss_fn_inputs["advantages"].data))
        before = _action_logprobs(forward, probe, send[probe])
    except Exception as exc:
        record(forward_backward={"status": "failed_or_unconfirmed", "error": type(exc).__name__})
        raise
    record(forward_backward={"status": "completed", "metrics": forward.metrics,
                             "result_count": len(forward.loss_fn_outputs),
                             "request_input_tokens": sum(d.model_input.length for d in send)})
    # Await valid gradients before submitting the only paid optimizer request.
    optim_future = training_client.optim_step(tinker.AdamParams(
        learning_rate=4e-5, beta1=0.9, beta2=0.95, eps=1e-8,
    ))
    record(optim_step={"status": "submitted"})
    try:
        async with asyncio.timeout(180):
            optimizer = await optim_future
    except Exception as exc:
        record(optim_step={"status": "failed_or_unconfirmed", "error": type(exc).__name__})
        raise
    record(optim_step={"status": "completed", "metrics": optimizer.metrics})
    verified = False
    try:
        async with asyncio.timeout(180):
            result = await training_client.forward([send[probe]], LOSS)
        after = _action_logprobs(result, 0, send[probe])
        delta = max(abs(x - y) for x, y in zip(before, after, strict=True))
        verified = delta > 1e-6
        record(updated_state={"status": "verified" if verified else "inconclusive",
                              "max_action_logprob_delta": delta, "probed_tokens": len(after),
                              "verification_input_tokens": send[probe].model_input.length})
    except Exception as exc:
        record(updated_state={"status": "unverified", "error": type(exc).__name__})
    async with asyncio.timeout(180):
        checkpoint = await training_client.save_state("elt-one-step", ttl_seconds=86_400)
    record(checkpoint=checkpoint.path)
    if inspect_checkpoint is not None:
        try:
            async with asyncio.timeout(30):
                metadata = await inspect_checkpoint(checkpoint.path)
        except Exception as exc:
            record(checkpoint_verification={"status": "unverified", "error": type(exc).__name__})
            return False
        record(checkpoint_verification={"status": "verified", **metadata})
    return verified


async def run_remote(
    mode: str, task: TaskDefinition, config: EpisodeConfig, out: Path, model: str,
    renderer_name: str, members: int, max_usd: float, record: Callable[..., None],
    *, api_key: str, project_id: str | None = None, seed: int = 0,
    token_budget: TokenBudget | None = None, preflight_only: bool = False,
) -> int:
    train = mode == "train-one"
    budget = token_budget or (PILOT_BUDGET if train else TokenBudget())
    prices = await asyncio.to_thread(fetch_model_pricing, model, timeout=25.0)
    if prices is None:
        raise ConfigurationError("live pricing unavailable for this model")
    if any(not math.isfinite(rate) or rate < 0 for rate in asdict(prices).values()):
        raise ConfigurationError("published token rates are invalid")
    estimate = estimated_bound(prices, config, budget, members, train)
    if not math.isfinite(estimate) or estimate <= 0 or estimate > max_usd:
        raise ConfigurationError(f"estimated Tinker token cost exceeds the bound or is invalid ({estimate:.4f} USD)")
    record(model=model, renderer=renderer_name, task=task.task_id, seed=seed,
           tokenizer_revision=(QWEN_TOKENIZER_REVISIONS.get(model)
                               if renderer_name in {DEFAULT_RENDERER, "qwen3_5"} else None),
           cookbook_sha=COOKBOOK_SHA, tinker_version=version("tinker"),
           lora_rank=LORA_RANK if train else None, loss=LOSS if train else None,
           token_budget=asdict(budget), members=members, max_turns=config.max_turns,
           max_tool_calls=config.max_tool_calls, rollout_seconds=config.rollout_seconds,
           token_prices=asdict(prices), estimated_upper_usd=estimate,
           spending_limit_usd=max_usd, actual_spend_usd=None, balance_pre=None, balance_post=None)
    renderer = make_renderer(model, renderer_name, offline=True)
    reserve = 0
    if not train and task.partial_transforms:
        closing_renderer = finalization_renderer(renderer)
        sizes = {mode: len(submission_call_tokens(closing_renderer, mode)) for mode in ("complete", "partial")}
        reserve = 2 * max(sizes.values())
        if members != 1 or reserve > budget.per_turn or reserve + 1 >= budget.sampled:
            raise ConfigurationError("token budget cannot accommodate the serialized submission reserve")
        record(submission_call_tokens=sizes, submission_reserve=reserve, working_sampled_tokens=budget.sampled - reserve)
    rest = tinker.RestClient(api_key=api_key, base_url=DEFAULT_BASE_URL)
    capabilities = await rest.get_server_capabilities()
    supported = next((item for item in capabilities.supported_models if item.model_name == model), None)
    if supported is None or supported.sampleable is False or (train and supported.trainable is False):
        raise ConfigurationError("configured Tinker project does not support this model for the requested action")
    if supported.max_context_length and supported.max_context_length < budget.context:
        raise ConfigurationError("model context length is smaller than the rollout budget")
    if preflight_only:
        record(status="read_only_preflight_passed", sampleable=supported.sampleable,
               max_context_length=supported.max_context_length, session_creation="not_started")
        print(f"Read-only preflight passed for {model}. Estimated uncached token bound: USD {estimate:.8f}.")
        return 0
    with single_attempt_sdk(), tinker.ServiceClient(
        display_name=f"elt-{mode}", api_key=api_key, project_id=project_id, base_url=DEFAULT_BASE_URL,
    ) as service:
        record(submission_attempts_per_request=1, session_creation="started")
        training_client = None
        if train:
            training_client = await service.create_lora_training_client(model, rank=LORA_RANK, seed=seed)
            record(session_url=service.get_console_url(), session_creation="completed")
            sampling_client = await training_client.save_weights_and_get_sampling_client(
                retry_config=RetryConfig(enable_retry_logic=False),
            )
        else:
            sampling_client = await service.create_sampling_client(
                base_model=model, retry_config=RetryConfig(enable_retry_logic=False),
            )
            record(session_url=service.get_console_url(), session_creation="completed")
        policy = RecordedTokenCompleter(sampling_client, max_tokens=budget.per_turn,
                                        temperature=0.8, context_window=budget.context,
                                        trace_file=out / "sampled-actions.jsonl",
                                        prompt_trace_file=None if train else out / "prompt-inputs.jsonl")
        dataset = ELTDataset(ELTGroupBuilder(
            config, renderer, members, task_factory=lambda: task, budget=budget, evidence_dir=out / "pipelines",
            submission_reserve=reserve,
        ))
        builder, = dataset.get_batch(0)
        record(sampling="started")
        group = await do_group_rollout(builder, policy, strategy=BooksRollout() if reserve else None)
        evidence = group_evidence(group)
        record(sampling="completed", rewards=group.get_total_rewards(), trajectories=evidence,
               sampled_actions_verified=True)
        datums = datums_for_group(group, require_provenance=True) if train else []
        usage = observed_usage(evidence, datums)
        sample_usage = replace(usage, trained=0)
        record(sampling_token_usage=asdict(sample_usage), estimated_sampling_usd=prices.estimate_usd(sample_usage))
        if not train:
            submitted = any(turn["metrics"].get("submitted", 0) for item in evidence for turn in item["turns"])
            if any((out / "official").glob("*/cleanup-required.txt")):
                record(status="cleanup_required", submitted=submitted)
                return 2
            record(status="rollout_submitted" if submitted else "rollout_unsubmitted", submitted=submitted)
            return 0 if submitted else 2
        record(training_datum_count=len(datums), planned_training_input_tokens=usage.trained,
               **alignment_evidence(datums))
        if not datums:
            record(status="no_training_signal", reason="constant rewards or no usable datums")
            return 2
        assert training_client is not None
        async def inspect_checkpoint(path: str) -> dict:
            weights = await rest.get_weights_info_by_tinker_path(path)
            if weights.base_model != model or not weights.is_lora or weights.lora_rank != LORA_RANK:
                raise RuntimeError("saved checkpoint metadata differs from the expected model or LoRA rank")
            return {"base_model": weights.base_model, "lora_rank": weights.lora_rank}

        verified = await optimize_once(training_client, datums, record, inspect_checkpoint=inspect_checkpoint)
        record(status="checkpoint_saved" if verified else "checkpoint_saved_state_unverified",
               post_training_evaluation=False)
        return 0 if verified else 2
