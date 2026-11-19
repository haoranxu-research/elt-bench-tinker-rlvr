"""Scripted token actions through the real pinned Cookbook environment."""

import asyncio
import json
from pathlib import Path
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
