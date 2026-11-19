"""Scripted token actions through the real pinned Cookbook environment."""

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

pytest.importorskip("tinker_cookbook", reason="optional pinned Cookbook dependency")

import tinker
from tinker_cookbook.renderers.base import Message, ParseTermination, Renderer, ToolCall, ToolSpec

from elt_rl.contracts import EpisodeConfig
from elt_rl.cookbook import ELTGroupBuilder
from elt_rl.local import local_task

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


def test_official_tool_trace_retains_feedback_even_without_submission(tmp_path):
    async def run():
        builder = ELTGroupBuilder(
            EpisodeConfig(tmp_path), cast(Renderer, ScriptedRenderer()), 1,
            task_factory=lambda: replace(local_task(), task_id="books"), evidence_dir=tmp_path,
        )
        env, = await builder.make_envs()
        await env.initial_observation()
        try:
            action = [{"tool": "write_pipeline_file", "arguments": {"path": "load.json", "content": "{}"}}]
            await env.step(list(json.dumps(action).encode()))
            await env.step(list(b"[]"))
        finally:
            await builder.cleanup()
        trace, = tmp_path.glob("*.tools.jsonl")
        record = json.loads(trace.read_bytes())
        assert record["turn"] == 1 and record["tool"] == action[0]["tool"]
        assert record["arguments"] == action[0]["arguments"]
        assert record["feedback"] == "ERROR: call read_task first" and not record["submitted"]

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
            return TokensWithLogprobs(token_ids, [-0.5] * len(token_ids), sequence_id="offline-test-sequence")

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
        datums = datums_for_group(group, require_provenance=True)
        assert datums
        values = [value for datum in datums for value in datum.loss_fn_inputs["advantages"].data]
        assert min(values) < 0 < max(values)
        print(f"Scripted warehouse rewards {sorted(group.get_total_rewards())}, {len(datums)} training datums")

        calls = []

        class FakeTrainingClient:
            def result(self, batch, logprob):
                return SimpleNamespace(metrics={}, loss_fn_outputs=[
                    {"logprobs": tinker.TensorData(data=[logprob] * datum.model_input.length, dtype="float32")}
                    for datum in batch
                ])

            def forward_backward(self, batch, loss_fn):
                assert loss_fn == "importance_sampling"
                assert batch and all("mask" not in datum.loss_fn_inputs for datum in batch)
                calls.append("forward_backward")
                return asyncio.sleep(0, result=self.result(batch, -0.5))

            def optim_step(self, params):
                assert params.learning_rate == 4e-5
                calls.append("optim_step")
                return asyncio.sleep(0, result=SimpleNamespace(metrics={}))

            def forward(self, batch, loss_fn):
                calls.append("forward")
                return asyncio.sleep(0, result=self.result(batch, -0.51))

            async def save_state(self, name, ttl_seconds):
                calls.append("save_state")
                return SimpleNamespace(path="fake-test-checkpoint")

        result = {}
        async def inspect(path):
            assert path == "fake-test-checkpoint"
            calls.append("inspect_checkpoint")
            return {"base_model": "test", "lora_rank": 16}
        assert await optimize_once(FakeTrainingClient(), datums, lambda **fields: result.update(fields),
                                   inspect_checkpoint=inspect)
        assert calls == ["forward_backward", "optim_step", "forward", "save_state", "inspect_checkpoint"]
        assert result["forward_backward"]["result_count"] == len(datums)
        assert result["optim_step"]["status"] == "completed"
        assert result["updated_state"]["status"] == "verified"
        assert result["checkpoint"] == "fake-test-checkpoint"
        assert result["checkpoint_verification"]["status"] == "verified"

        class BrokenBackward(FakeTrainingClient):
            async def forward_backward(self, batch, loss_fn):
                raise OSError("synthetic failure")

        calls.clear()
        result.clear()
        with pytest.raises(OSError):
            await optimize_once(BrokenBackward(), datums, lambda **fields: result.update(fields))
        assert not calls and "optim_step" not in result
        assert result["forward_backward"]["status"] == "failed_or_unconfirmed"

        class StaticWeights(FakeTrainingClient):
            def forward(self, batch, loss_fn):
                return asyncio.sleep(0, result=self.result(batch, -0.5))

        result.clear()
        assert not await optimize_once(StaticWeights(), datums, lambda **fields: result.update(fields))
        assert result["updated_state"]["status"] == "inconclusive"

    asyncio.run(run())


def test_actual_qwen_renderer_tool_turns_offline(tmp_path):
    if os.environ.get("ELT_TEST_REAL_RENDERER") != "1":
        pytest.skip("set ELT_TEST_REAL_RENDERER=1 with the pinned public tokenizer cached")
    from elt_rl.rendering import make_renderer
    from elt_rl.settings import DEFAULT_MODEL, DEFAULT_RENDERER

    async def run():
        renderer = make_renderer(DEFAULT_MODEL, DEFAULT_RENDERER, offline=True)
        builder = ELTGroupBuilder(EpisodeConfig(tmp_path), renderer, 1)
        env, = await builder.make_envs()
        actions = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]
        saw_bad_query = False
        try:
            prompt, stop = await env.initial_observation()
            assert prompt.length > 0 and stop
            for action in actions:
                body = "\n".join(f"<parameter={key}>\n{value}\n</parameter>"
                                 for key, value in action["arguments"].items())
                response = (
                    f"<tool_call>\n<function={action['tool']}>\n{body}\n</function>\n</tool_call><|im_end|>"
                )
                tokens = renderer.tokenizer.encode(response, add_special_tokens=False)
                step = await env.step(tokens)
                if action["tool"] == "execute_pipeline" and "wrong_amount" in str(step.logs):
                    assert not step.episode_done
                    saw_bad_query = True
            assert saw_bad_query
            assert step.episode_done and step.reward == 1.0
        finally:
            await builder.cleanup()

    asyncio.run(run())


def test_pilot_sdk_does_not_resubmit_transport_or_backpressure(monkeypatch):
    import httpx
    from tinker._client import AsyncTinker
    from tinker.lib.internal_client_holder import InternalClientHolder
    from tinker.lib.public_interfaces.sampling_client import SamplingClient
    from elt_rl.tinker_once import single_attempt_sdk

    async def run():
        calls = []

        async def transport_failure():
            calls.append("transport")
            raise httpx.ConnectError("synthetic")

        async def backpressure(*args, **kwargs):
            calls.append("sample")
            return None

        monkeypatch.setattr(SamplingClient, "_send_asample_request", backpressure)
        with single_attempt_sdk():
            with pytest.raises(httpx.ConnectError):
                await InternalClientHolder.execute_with_retries(None, transport_failure)
            with pytest.raises(RuntimeError, match="resubmission is disabled"):
                await SamplingClient._send_asample_request(None)
            async with AsyncTinker(api_key="tml-synthetic", max_retries=3) as client:
                assert client.max_retries == 0
        assert calls == ["transport", "sample"]

    asyncio.run(run())
