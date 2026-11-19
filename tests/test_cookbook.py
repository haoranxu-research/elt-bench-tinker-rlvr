"""Scripted token actions through the real pinned Cookbook environment."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

pytest.importorskip("tinker_cookbook", reason="optional pinned Cookbook dependency")

import tinker
from tinker_cookbook.renderers.base import Message, ParseTermination, Renderer, ToolCall, ToolSpec

from elt_rl.contracts import EpisodeConfig
from elt_rl.cookbook import ELTGroupBuilder

TRACE = Path(__file__).resolve().parents[1] / "examples" / "customer_orders.jsonl"


class ScriptedRenderer:
    """Byte encoding for test actions. The real wrapper handles turns and rewards."""

    def get_stop_sequences(self) -> list[str]:
        return ["<stop>"]

    def create_conversation_prefix_with_tools(self, *, tools: list[ToolSpec],
                                              system_prompt: str) -> list[Message]:
        return [{"role": "system", "content": system_prompt + json.dumps(tools)}]

    def build_generation_prompt(self, messages: list[Message]) -> tinker.ModelInput:
        def encode(value: object) -> object:
            assert isinstance(value, ToolCall)
            return value.model_dump()
        return tinker.ModelInput.from_ints(list(json.dumps(messages, default=encode).encode()))

    def parse_response(self, action: list[int]) -> tuple[Message, ParseTermination]:
        calls = [
            ToolCall(function=ToolCall.FunctionBody(
                name=item["tool"], arguments=json.dumps(item["arguments"]),
            ), id=f"call-{index}")
            for index, item in enumerate(json.loads(bytes(action)))
        ]
        return {"role": "assistant", "content": "", "tool_calls": calls}, ParseTermination.STOP_SEQUENCE


def test_cookbook_token_env_group(tmp_path):
    async def run() -> None:
        builder = ELTGroupBuilder(EpisodeConfig(tmp_path), cast(Renderer, ScriptedRenderer()), 2)
        left, right = await builder.make_envs()
        workspaces = [episode.workspace for episode in builder.episodes]
        actions = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]

        def tokens(*calls: dict) -> list[int]:
            return list(json.dumps(calls).encode())

        try:
            left_initial, right_initial = await asyncio.gather(
                left.initial_observation(), right.initial_observation(),
            )
            assert left_initial[0].length == right_initial[0].length > 0
            # In a single assistant message, the stateful writes and load must run in order.
            load = await left.step(tokens(*actions[:3]))
            assert "raw_orders=4" in load.logs["tool_result_2"]
            no_load = await right.step(tokens(actions[0], actions[8]))
            assert "(empty warehouse)" in no_load.logs["tool_result_1"]
            incomplete = await right.step(tokens())
            assert incomplete.episode_done and incomplete.reward == 0
            for index, action in enumerate(actions[3:], start=3):
                result = await left.step(tokens(action))
                if index == 5:
                    assert "wrong_amount" in result.logs["tool_result_0"]
                    assert not result.episode_done
            assert result.episode_done and result.reward == 1
            assert result.metrics["stage1"] == result.metrics["stage2"] == 1
        finally:
            await builder.cleanup()
        assert not builder.episodes
        assert all(not path.exists() for path in workspaces)

    asyncio.run(run())


def test_cookbook_rollouts_produce_real_advantages_and_datums(tmp_path):
    from tinker_cookbook.completers import TokensWithLogprobs
    from tinker_cookbook.rl.rollouts import do_group_rollout
    from elt_rl.cookbook import ELTDataset
    from elt_rl.training import datums_for_group, group_evidence, optimize_once

    actions = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]

    class ScriptedPolicy:
        def __init__(self, varied):
            partial = [dict(action) for action in actions]
            partial[1] = {"tool": "write_pipeline_file", "arguments": {
                "path": "load.json", "content": '{"sources":{"customers.csv":null,"orders.csv":3}}',
            }}
            self.traces = iter((actions, partial if varied else actions))
            self.active = {}

        async def __call__(self, model_input, stop, *, max_tokens=None):
            key = asyncio.current_task()
            if key not in self.active:
                self.active[key] = iter(next(self.traces))
            token_ids = list(json.dumps([next(self.active[key])]).encode())
            assert max_tokens is None or len(token_ids) <= max_tokens
            await asyncio.sleep(0)
            return TokensWithLogprobs(token_ids, [-0.5] * len(token_ids))

    async def run():
        builder = ELTGroupBuilder(EpisodeConfig(tmp_path), cast(Renderer, ScriptedRenderer()), 2)
        dataset = ELTDataset(builder)
        assert len(dataset) == 1 and dataset.get_batch(0) == (builder,)
        constant = await do_group_rollout(builder, ScriptedPolicy(varied=False))
        assert constant.get_total_rewards() == [1.0, 1.0]
        assert datums_for_group(constant) == []
        group = await do_group_rollout(builder, ScriptedPolicy(varied=True))
        assert sorted(group.get_total_rewards()) == [0.175, 1.0]
        assert not builder.episodes
        evidence = group_evidence(group)
        assert all(any(turn["metrics"].get("submitted") for turn in item["turns"]) for item in evidence)
        datums = datums_for_group(group)
        assert datums
        values = [value for datum in datums for value in datum.loss_fn_inputs["advantages"].data]
        assert min(values) < 0 < max(values)
        print(f"Scripted warehouse rewards {sorted(group.get_total_rewards())}, {len(datums)} training datums")

        calls = []

        class FakeTrainingClient:
            def forward_backward(self, batch, loss_fn):
                assert loss_fn == "importance_sampling"
                assert batch and all("mask" not in datum.loss_fn_inputs for datum in batch)
                calls.append("forward_backward")
                return asyncio.sleep(0, result=SimpleNamespace(metrics={}, loss_fn_outputs=batch))

            def optim_step(self, params):
                assert params.learning_rate == 4e-5
                calls.append("optim_step")
                return asyncio.sleep(0, result=SimpleNamespace(metrics={}))

            async def save_state(self, name, ttl_seconds):
                calls.append("save_state")
                return SimpleNamespace(path="fake-test-checkpoint")

        result = {}
        await optimize_once(FakeTrainingClient(), datums, lambda **fields: result.update(fields))
        assert calls == ["forward_backward", "optim_step", "save_state"]
        assert result["forward_backward"]["result_count"] == len(datums)
        assert result["optim_step"]["status"] == "completed"
        assert result["checkpoint"] == "fake-test-checkpoint"

    asyncio.run(run())
