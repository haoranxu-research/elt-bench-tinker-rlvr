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
from tinker_cookbook.renderers.base import Message, ParseTermination, RenderedMessage, Renderer, ToolCall, ToolSpec

from elt_rl.contracts import EpisodeConfig, TokenBudget
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

    def render_message(self, message, _context):
        calls = [{"tool": call.function.name, "arguments": json.loads(call.function.arguments)}
                 for call in message.get("tool_calls", [])]
        return RenderedMessage(header=[], output=list(json.dumps(calls).encode()))


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


@pytest.mark.parametrize("end", ["turn_limit", "length", "initial_overflow", "submitted"])
def test_terminal_rollout_cannot_start_grading_again(tmp_path, end):
    from tinker_cookbook.rl.types import InitialObservationOverflow

    verifier_calls = []
    task = local_task()

    def verify(backend):
        verifier_calls.append(backend)
        return task.verify(backend)

    async def run():
        builder = ELTGroupBuilder(
            EpisodeConfig(tmp_path, max_turns=3), cast(Renderer, ScriptedRenderer()), 1,
            task_factory=lambda: replace(task, verify=verify),
            budget=TokenBudget(context=1, per_turn=1) if end == "initial_overflow" else TokenBudget(),
        )
        env, = await builder.make_envs()
        episode, = builder.episodes
        actions = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]

        def tokens(*calls):
            return list(json.dumps(calls).encode())

        try:
            first = await env.initial_observation()
            if end == "initial_overflow":
                assert isinstance(first, InitialObservationOverflow)
                terminal = first
            else:
                await env.step(tokens(*actions[:3]))
                transformed = await env.step(tokens(actions[3], actions[6], actions[7]))
                assert "transform finished" in transformed.logs["tool_result_2"]
                if end == "length":
                    terminal = await env.step(tokens(actions[-1]), extra={"stop_reason": "length"})
                else:
                    terminal = await env.step(tokens(actions[-1] if end == "submitted" else actions[8]))
                assert terminal.episode_done
            submitted = end == "submitted"
            assert terminal.reward == int(submitted)
            assert episode.grade().submitted == submitted
            with pytest.raises(RuntimeError, match="episode already ended"):
                await env.step(tokens(actions[-1]))
            assert len(verifier_calls) == int(submitted)
            assert len(list(episode.workspace.glob("submission-*"))) == int(submitted)
        finally:
            await builder.cleanup()
        assert not episode.workspace.exists()

    asyncio.run(run())


def test_books_text_only_turn_gets_one_tool_reminder(tmp_path):
    async def run():
        task = replace(local_task(), task_id="books", partial_transforms=True)
        builder = ELTGroupBuilder(EpisodeConfig(tmp_path), cast(Renderer, ScriptedRenderer()), 1,
                                  task_factory=lambda: task)
        env, = await builder.make_envs()
        episode, = builder.episodes
        try:
            await env.initial_observation()
            reminder = await env.step(list(b"[]"))
            assert not reminder.episode_done and reminder.metrics["text_recovery"] == 1
            messages = json.loads(bytes(reminder.next_observation.to_ints()))
            assert "No tool call was received" in messages[-1]["content"]
            assert "23 turns left" in messages[-1]["content"]
            assert episode.grade().reward == 0 and not episode.submitted_files
            terminal = await env.step(list(b"[]"))
            assert terminal.episode_done and terminal.reward == 0
            assert not list(episode.workspace.glob("submission-*"))
        finally:
            await builder.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize("boundary,final", [
    ("sampled", "submit"), ("sampled", "length"), ("turn", "submit"),
    ("call", "submit"), ("unknown", "submit"), ("turn", "edit"), ("turn", "refuse"), ("turn", "bad_submit"),
])
def test_books_submission_reserve_keeps_one_explicit_action(tmp_path, boundary, final):
    from tinker_cookbook.completers import TokensWithLogprobs
    from tinker_cookbook.rl.rollouts import do_group_rollout
    from elt_rl.cookbook import BooksRollout, submission_call_tokens

    task = replace(local_task(), task_id="books", partial_transforms=True)
    renderer = cast(Renderer, ScriptedRenderer())
    reserve = 2 * max(len(submission_call_tokens(renderer, mode)) for mode in ("complete", "partial"))
    actions = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]
    first_turn = actions[:3]
    if boundary == "unknown":
        first_turn.append({"tool": "unknown_tool", "arguments": {}})
    start = [list(json.dumps(batch).encode()) for batch in (first_turn, [actions[3], actions[6], actions[7]])]
    config = EpisodeConfig(tmp_path, max_turns=3 if boundary == "turn" else 5,
                           max_tool_calls={"call": 7, "unknown": 8}.get(boundary, 16), max_submissions=1)
    if boundary == "call":
        start[-1] = start[-1][:-1] + list(b',' + json.dumps(actions[8]).encode() + b']')
    # Leave exactly 24 working tokens after two tested files are available.
    budget = TokenBudget(context=16_384, sampled=sum(map(len, start)) + reserve + 24)
    builder = ELTGroupBuilder(config, renderer, 1, task_factory=lambda: task, budget=budget,
                              submission_reserve=reserve)
    work = list(json.dumps([actions[6]]).encode())
    used = []

    async def policy(prompt, _stop, *, max_tokens):
        text = bytes(prompt.to_ints()).decode()
        if len(used) < len(start):
            response = start[len(used)]
            if len(used) == 1:
                assert "Sampled tokens left" in text
        elif boundary == "sampled" and len(used) == len(start):
            assert max_tokens == 24
            response = work
        else:
            assert max_tokens == reserve
            assert "Final turn. Current tested files: customer_totals.sql, order_totals.sql." in text
            assert '"name": "write_pipeline_file"' not in text
            cases = {
                "submit": submission_call_tokens(renderer, "complete"),
                "length": submission_call_tokens(renderer, "complete") + [32] * reserve,
                "edit": work, "refuse": list(b"[]"),
                "bad_submit": list(json.dumps([{"tool": "submit_pipeline", "arguments": {"mode": "bad"}}]).encode()),
            }
            response = cases[final]
        used.append(max_tokens)
        return TokensWithLogprobs(response[:max_tokens], None,
                                  stop_reason="length" if len(response) > max_tokens else "stop")

    group = asyncio.run(do_group_rollout(builder, policy, strategy=BooksRollout()))
    trajectory, = group.trajectories_G
    assert len(used) == (4 if boundary == "sampled" else 3)
    assert sum(len(turn.ac.tokens) for turn in trajectory.transitions) <= budget.sampled
    assert group.get_total_rewards() == [float(final == "submit")]
    assert bool(trajectory.transitions[-1].metrics.get("submitted")) == (final == "submit")
    if boundary == "sampled":
        interrupted = trajectory.transitions[-2]
        assert interrupted.metrics["work_action_truncated"] == 1
        assert not interrupted.episode_done
        assert not any(key.startswith("tool_call_") for key in interrupted.logs)
    if boundary == "call":
        assert trajectory.transitions[-2].logs["tool_calls_skipped_for_submission"] == 1


def test_books_interrupted_first_sql_resumes_from_loaded_state(tmp_path, monkeypatch):
    class RecoveryRenderer(ScriptedRenderer):
        def build_generation_prompt(self, messages):
            return super().build_generation_prompt([*messages, {"role": "user", "content": "Recovery renderer"}])

    monkeypatch.setattr("elt_rl.cookbook.finalization_renderer", lambda _: RecoveryRenderer())

    async def run():
        task = replace(local_task(), task_id="books", partial_transforms=True)
        renderer = cast(Renderer, ScriptedRenderer())
        builder = ELTGroupBuilder(EpisodeConfig(tmp_path), renderer, 1, task_factory=lambda: task,
                                  budget=TokenBudget(context=16384, sampled=20480, per_turn=4096),
                                  submission_reserve=200)
        env, = await builder.make_envs()
        actions = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]
        try:
            await env.initial_observation()
            await env.step(list(json.dumps(actions[:3]).encode()))
            interrupted = await env.step(list(b'[{"tool":"write_pipeline_file"') + [32] * 4000,
                                         extra={"stop_reason": "length"})
            prompt = bytes(interrupted.next_observation.to_ints()).decode()
            assert "Your first action is read_task" not in prompt
            assert "Source loading succeeded." in prompt
            assert "Use read_pipeline_file for their exact contents." not in prompt
            assert "The interrupted action made no changes. Respond with a single tool call." in prompt
            assert "The source data is loaded. Write only customer_totals.sql with write_pipeline_file." in prompt
            assert "Recovery renderer" in prompt
            assert interrupted.metrics["interrupted_action_recovery"] == 1 and not interrupted.episode_done
            assert not (builder.episodes[0].artifact_dir / "customer_totals.sql").exists()
            read = [{"tool": "list_workspace", "arguments": {}}]
            after_read = await env.step(list(json.dumps(read).encode()))
            assert "Recovery renderer" in bytes(after_read.next_observation.to_ints()).decode()
            after_save = await env.step(list(json.dumps([actions[3]]).encode()))
            assert "Recovery renderer" not in bytes(after_save.next_observation.to_ints()).decode()
            interrupted = await env.step([32] * 4096, extra={"stop_reason": "length"})
            prompt = bytes(interrupted.next_observation.to_ints()).decode()
            assert "The source data is loaded. Test saved customer_totals.sql" in prompt
            assert (builder.episodes[0].artifact_dir / "customer_totals.sql").is_file()
        finally:
            await builder.cleanup()

    asyncio.run(run())


def test_books_partial_submit_asks_to_test_saved_repair_before_deadline(tmp_path):
    from elt_rl.contracts import Grade, PipelineError
    from elt_rl.episode import ELTEpisodeState

    class SingleFileBackend:
        def execute(self, stage, files):
            if stage == "transform" and any("wrong_amount" in sql for sql in files.values()):
                raise PipelineError("order_totals.sql: invalid column wrong_amount")
            return "executed"

        def close(self):
            pass

    task = replace(local_task(), task_id="books", partial_transforms=True,
                   open_backend=lambda *_: SingleFileBackend(),
                   verify=lambda _: Grade(stage1=1, stage2=0.5, stage2_ran=True, submitted=True))
    actions = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]
    with ELTEpisodeState(task, EpisodeConfig(tmp_path, max_turns=23, max_tool_calls=32)) as episode:
        for turn, action in enumerate(actions[:5], 1):
            episode.dispatch(action["tool"], action["arguments"], turn=turn)
        episode.dispatch("execute_pipeline", {"stage": "transform", "file": "customer_totals.sql"}, turn=6)
        failed = episode.dispatch("execute_pipeline", {"stage": "transform", "file": "order_totals.sql"}, turn=7)
        assert failed.text.startswith("ERROR:")
        repair = actions[6]
        episode.dispatch(repair["tool"], repair["arguments"], turn=19)
        partial = {"mode": "partial"}
        blocked = episode.dispatch("submit_pipeline", partial, turn=20)
        assert not blocked.submitted and "Test the newly saved SQL before partial submission: order_totals.sql" in blocked.text
        episode.finalizing = True
        allowed = episode.dispatch("submit_pipeline", partial, turn=23)
        assert allowed.submitted


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


def test_unsubmitted_official_artifact_is_retained_with_no_graded_files(tmp_path):
    async def run():
        evidence = tmp_path / "pipelines"
        evidence.mkdir()
        builder = ELTGroupBuilder(
            EpisodeConfig(tmp_path), cast(Renderer, ScriptedRenderer()), 1,
            task_factory=lambda: replace(local_task(), task_id="books", partial_transforms=True),
            evidence_dir=evidence,
        )
        env, = await builder.make_envs()
        episode, = builder.episodes
        name = episode.workspace.name
        actions = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]
        try:
            await env.initial_observation()
            await env.step(list(json.dumps(actions[:4]).encode()))
            assert not (await env.step(list(b"[]"))).episode_done
            result = await env.step(list(b"[]"))
            assert result.episode_done and result.reward == 0
        finally:
            await builder.cleanup()
        assert not episode.workspace.exists()
        assert (evidence / name / "customer_totals.sql").read_text(encoding="utf-8") == actions[3]["arguments"]["content"]
        assert json.loads((evidence / f"{name}.submission.json").read_bytes()) == {
            "submitted": False, "transforms": [],
        }

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
        from elt_rl.cookbook import finalization_renderer, submission_call_tokens

        reasoning = make_renderer(DEFAULT_MODEL, "qwen3_5", offline=True)
        closing = finalization_renderer(reasoning)
        assert closing.disables_thinking and not reasoning.disables_thinking
        action = submission_call_tokens(closing, "partial")
        decoded, status = reasoning.parse_response(action)
        assert status.is_clean and decoded["tool_calls"][0].function.name == "submit_pipeline"
        builder = ELTGroupBuilder(EpisodeConfig(tmp_path), renderer, 1,
                                  task_factory=lambda: replace(local_task(), partial_transforms=True))
        env, = await builder.make_envs()
        actions = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]
        actions[-1]["arguments"]["mode"] = "complete"
        saw_bad_query = False
        try:
            prompt, stop = await env.initial_observation()
            assert prompt.length > 0 and stop
            request = ("<tool_call>\n<function=execute_pipeline>\n"
                       "<parameter=stage>\ntransform\n</parameter>\n"
                       "<parameter=file>\norder_totals.sql\n</parameter>\n"
                       "</function>\n</tool_call><|im_end|>")
            message, termination = renderer.parse_response(renderer.tokenizer.encode(request, add_special_tokens=False))
            assert termination.is_clean
            call, = message["tool_calls"]
            assert json.loads(call.function.arguments) == {"stage": "transform", "file": "order_totals.sql"}
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
