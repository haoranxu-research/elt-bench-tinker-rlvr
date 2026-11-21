"""Optional Cookbook environment integration. Importing it creates no API client."""

import asyncio
import json
import logging
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tinker_cookbook.completers import TokenCompleter
from tinker_cookbook.renderers.base import Message, RenderContext, Renderer, ToolCall, ToolSpec
from tinker_cookbook.rl import types
from tinker_cookbook.rl.message_env import EnvFromMessageEnv, MessageStepResult
from tinker_cookbook.rl.rollout_limits import RolloutLimits
from tinker_cookbook.rl.rollout_runner import run_rollout
from tinker_cookbook.rl.rollout_strategy import RolloutResult, RolloutStrategy
from tinker_cookbook.rl.types import Env, EnvGroupBuilder, Metrics, RLDataset
from tinker_cookbook.tool_use import AgentToolMessageEnv, Tool, ToolInput, ToolResult, simple_tool_result

from .contracts import EpisodeConfig, TaskDefinition, TokenBudget
from .episode import BOOKS_INSTRUCTION, BOOKS_REQUEST, INITIAL_INSTRUCTION, ELTEpisodeState
from .local import local_task

logger = logging.getLogger(__name__)


@dataclass
class EpisodeTool:
    name: str
    turn: Callable[[], int]
    episode: ELTEpisodeState
    trace_file: Path | None = None

    @property
    def description(self) -> str:
        return self.episode.tools[self.name].description

    @property
    def parameters_schema(self) -> dict:
        return self.episode.tool_schema(self.name)

    def to_spec(self) -> ToolSpec:
        return {"name": self.name, "description": self.description, "parameters": self.parameters_schema}

    async def run(self, input: ToolInput) -> ToolResult:
        turn = self.turn()
        feedback = await asyncio.to_thread(
            self.episode.dispatch, self.name, input.arguments, turn=turn,
        )
        if self.trace_file is not None:
            with self.trace_file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"turn": turn, "tool": self.name, "call_id": input.call_id,
                                         "arguments": input.arguments, "feedback": feedback.text,
                                         "submitted": feedback.submitted}) + "\n")
        return simple_tool_result(
            feedback.text, call_id=input.call_id or "", name=self.name, should_stop=feedback.submitted,
        )


def submission_call_tokens(renderer: Renderer, mode: str) -> list[int]:
    """Measure the sampled part of the renderer's actual tool serialization."""
    args = {"mode": mode}
    message: Message = {"role": "assistant", "content": "", "tool_calls": [
        ToolCall(function=ToolCall.FunctionBody(name="submit_pipeline", arguments=json.dumps(args))),
    ]}
    rendered = renderer.render_message(
        message, RenderContext(idx=2, is_last=True, last_user_index=1, in_last_assistant_turn=True),
    )
    tokens = rendered.output
    if not all(isinstance(token, int) for token in tokens):
        tokens = [token for chunk in tokens for token in chunk.tokens]
    parsed, stop = renderer.parse_response(tokens)
    calls = parsed.get("tool_calls", ())
    if (not stop.is_clean or len(calls) != 1 or calls[0].function.name != "submit_pipeline"
            or json.loads(calls[0].function.arguments) != args):
        raise ValueError("renderer did not round-trip the submission action")
    return tokens


class ELTMessageEnv(AgentToolMessageEnv):
    """Reuse the Cookbook's dispatcher while tracking the feedback turn explicitly."""

    def __init__(self, episode: ELTEpisodeState, renderer: Renderer, trace_file: Path | None = None,
                 reserve_submission: bool = False):
        self.turn = 0
        self.finished = False
        self._used_text_recovery = False
        self._episode = episode
        self.reserve_submission = reserve_submission
        tools: list[Tool] = [EpisodeTool(name, lambda: self.turn, episode, trace_file) for name in episode.tools]
        self._tool_specs = [tool.to_spec() for tool in tools]
        messages = renderer.create_conversation_prefix_with_tools(
            tools=self._tool_specs,
            system_prompt=BOOKS_INSTRUCTION if episode.task.partial_transforms else INITIAL_INSTRUCTION,
        )
        messages.append({"role": "user", "content": BOOKS_REQUEST if episode.task.partial_transforms
                         else "Complete the ELT task."})

        async def reward_fn(_: list[Message]) -> tuple[float, Metrics]:
            grade = episode.grade()
            return grade.reward, grade.metrics()

        super().__init__(
            tools=tools, initial_messages=messages, reward_fn=reward_fn,
            max_turns=episode.config.max_turns, max_tool_calls=episode.config.max_tool_calls,
            failed_parse_reward=0.0, tool_execution="sequential",
        )

    @property
    def remaining_tool_calls(self) -> int:
        # Cookbook counts unknown tool names even though the episode does not dispatch them.
        return self.max_tool_calls - self._tool_calls_made

    async def step(self, message: Message) -> MessageStepResult:
        if self.finished:
            raise RuntimeError("episode already ended")
        self.turn += 1
        calls = message.get("tool_calls", [])
        if self._episode.finalizing:
            if len(calls) != 1 or calls[0].function.name != "submit_pipeline" or message.get("unparsed_tool_calls"):
                self.finished = True
                return MessageStepResult(0.0, True, self.history,
                                         metrics={**self._episode.grade().metrics(), "stop/completed": 1},
                                         logs={"finalization": "no single explicit submit_pipeline call"})
        skipped = 0
        if self.reserve_submission and not self._episode.finalizing:
            working_calls = self.remaining_tool_calls - 1
            if len(calls) > working_calls:
                skipped = len(calls) - working_calls
                message = {**message, "tool_calls": calls[:working_calls]}
        result = await super().step(message)
        if skipped:
            result.logs["tool_calls_skipped_for_submission"] = skipped
        if self._episode.finalizing and not result.episode_done:
            result.episode_done = True
            result.metrics.update(self._episode.grade().metrics())
            result.metrics["stop/completed"] = 1
        if result.metrics.get("stop/completed") and not self._used_text_recovery:
            hint = self._episode.continuation_hint(self.turn)
            if hint is not None:
                self._used_text_recovery = True
                result.episode_done = False
                result.metrics.pop("stop/completed")
                result.metrics["text_recovery"] = 1
                result.next_messages.append({"role": "user", "content": hint})
        self.finished = result.episode_done
        return result

    def begin_finalization(self, renderer: Renderer, turn: int, reserve: int) -> list[Message]:
        self.turn = turn
        self._episode.finalizing = True
        spec = next(tool for tool in self._tool_specs if tool["name"] == "submit_pipeline")
        messages = renderer.create_conversation_prefix_with_tools(
            tools=[spec], system_prompt="The work phase has ended. Only submit_pipeline is available.",
        )
        tested = ", ".join(self._episode.tested_files)
        mode = "partial" if self._episode.tested_files != self._episode.task.transform_artifacts else "complete"
        messages.append({"role": "user", "content": (
            f"Final turn. Current tested files: {tested}. You have {reserve} output tokens. "
            f'Call submit_pipeline once with mode="{mode}" to grade your tested files. '
            "Output the tool call without prose."
        )})
        self.history = messages
        return self.history


class ELTTokenEnv(EnvFromMessageEnv):
    """Keep token-level termination final even when no message was dispatched."""

    _finished = False

    async def initial_observation(self) -> tuple[types.Observation, types.StopCondition] | types.InitialObservationOverflow:
        if self._finished:
            raise RuntimeError("episode already ended")
        result = await super().initial_observation()
        self._finished = isinstance(result, types.InitialObservationOverflow)
        return result

    async def step(self, action: types.Action, *, extra: types.ActionExtra | None = None) -> types.StepResult:
        if self._finished:
            raise RuntimeError("episode already ended")
        result = await super().step(action, extra=extra)
        self._finished = result.episode_done
        return result


class BooksTokenEnv(ELTTokenEnv):
    """Hold back one sampled action and one tool/turn slot for explicit submission."""

    def __init__(self, renderer, message_env: ELTMessageEnv, *, reserve: int, **kwargs):
        super().__init__(renderer, message_env, **kwargs)
        self.books_messages = message_env
        self.episode = message_env._episode
        self.reserve = reserve
        self.tokens_spent = 0
        self.turns_used = 0

    @property
    def sampled_left(self) -> int:
        return self.rollout_limits.max_sampled_tokens - self.tokens_spent

    async def sample(self, policy, observation, stop, max_tokens=None):
        available = self.reserve if self.episode.finalizing else self.sampled_left - self.reserve
        cap = min(available, max_tokens) if max_tokens is not None else available
        if cap <= 0 or (self.episode.finalizing and cap < self.reserve):
            raise RuntimeError("rollout did not preserve the reserved submission request")
        response = await policy(observation, stop, max_tokens=cap)
        if len(response.tokens) > cap:
            raise RuntimeError("sampler exceeded its requested token limit")
        return response

    async def step(self, action, *, extra=None):
        self.tokens_spent += len(action)
        self.turns_used += 1
        self.episode.sampled_tokens_left = (self.sampled_left, self.reserve)
        result = await super().step(action, extra=extra)
        if self.episode.finalizing:
            return result
        interrupted = (extra or {}).get("stop_reason") == "length"
        context_full = bool(result.metrics.get("context_overflow"))
        if result.episode_done and not (interrupted or context_full):
            return result
        last_turn = self.turns_used + 1 >= self.rollout_limits.max_turns
        last_call = self.books_messages.remaining_tool_calls <= 1
        low_tokens = self.sampled_left <= self.reserve + 1
        if not (interrupted or context_full or last_turn or last_call or low_tokens):
            return result
        if not self.episode.tested_files or self.turns_used >= self.rollout_limits.max_turns:
            if not result.episode_done:
                reason = "max_turns" if last_turn else "max_tool_calls" if last_call else "max_sampled_tokens"
                result.metrics[f"stop/{reason}"] = 1
                result.episode_done = self._finished = True
            return result
        messages = self.books_messages.begin_finalization(self.renderer, self.turns_used, self.reserve)
        observation = await self._render_in_thread(messages)
        if observation.length + self.reserve > self.rollout_limits.max_trajectory_tokens:
            raise RuntimeError("submission prompt exceeds the configured context budget")
        self._finished = False
        metrics = {key: value for key, value in result.metrics.items() if not key.startswith("stop/")}
        metrics.update(submission_reserve=self.reserve, work_action_truncated=int(interrupted))
        return types.StepResult(0.0, False, observation, self._base_stop_condition, metrics=metrics, logs=result.logs)


class BooksRollout(RolloutStrategy):
    """Run one sampling-only episode with the host's submission budget."""

    async def execute(self, env_group_builder, policy: TokenCompleter) -> RolloutResult:
        env, = await env_group_builder.make_envs()

        async def capped_policy(observation, stop, *, max_tokens=None):
            return await env.sample(policy, observation, stop, max_tokens)

        trajectory = await run_rollout(capped_policy, env)
        return RolloutResult([trajectory], [env], [])


class ELTGroupBuilder(EnvGroupBuilder):
    """Create isolated members and release them after Cookbook group grading."""

    def __init__(self, config: EpisodeConfig, renderer: Renderer, group_size: int,
                 task_factory: Callable[[], TaskDefinition] = local_task,
                 budget: TokenBudget = TokenBudget(), evidence_dir: Path | None = None,
                 submission_reserve: int = 0):
        if group_size < 1:
            raise ValueError("group_size must be positive")
        self.config = config
        self.renderer = renderer
        self.group_size = group_size
        self.task_factory = task_factory
        self.budget = budget
        self.evidence_dir = evidence_dir
        if submission_reserve and (
            group_size != 1 or config.max_turns < 2 or config.max_tool_calls < 2
            or not 1 < submission_reserve <= budget.per_turn or submission_reserve + 1 >= budget.sampled
        ):
            raise ValueError("submission reserve needs one episode and room for a working and final action")
        self.submission_reserve = submission_reserve
        self.episodes: list[ELTEpisodeState] = []

    async def make_envs(self) -> Sequence[Env]:
        if self.episodes:
            raise RuntimeError("clean up the previous rollout group first")
        envs: list[Env] = []
        try:
            for _ in range(self.group_size):
                episode = ELTEpisodeState(self.task_factory(), self.config)
                self.episodes.append(episode)
                trace_file = None
                if self.evidence_dir is not None and episode.task.task_id == "books":
                    trace_file = self.evidence_dir / f"{episode.workspace.name}.tools.jsonl"
                env = BooksTokenEnv if self.submission_reserve else ELTTokenEnv
                options = {"reserve": self.submission_reserve} if self.submission_reserve else {}
                envs.append(env(
                    self.renderer, ELTMessageEnv(episode, self.renderer, trace_file, bool(self.submission_reserve)),
                    failed_parse_reward=0.0, context_overflow_reward=0.0,
                    rollout_limits=RolloutLimits(
                        max_turns=self.config.max_turns,
                        max_tool_calls=self.config.max_tool_calls,
                        max_trajectory_tokens=self.budget.context,
                        max_sampled_tokens=self.budget.sampled,
                        max_turn_tokens=self.budget.per_turn,
                        rollout_timeout_seconds=self.config.rollout_seconds,
                    ),
                    max_trajectory_tokens=self.budget.context, max_generation_tokens=self.budget.per_turn,
                    **options,
                ))
        except Exception:
            await self.cleanup()
            raise
        return envs

    async def cleanup(self) -> None:
        for episode in self.episodes:
            try:
                submitted = episode.grade().submitted
                has_official_artifacts = episode.task.partial_transforms and any(episode.artifact_dir.iterdir())
                if self.evidence_dir and (submitted or has_official_artifacts):
                    await asyncio.to_thread(shutil.copytree, episode.artifact_dir,
                                            self.evidence_dir / episode.workspace.name)
                    if episode.task.partial_transforms:
                        metadata = self.evidence_dir / f"{episode.workspace.name}.submission.json"
                        await asyncio.to_thread(metadata.write_text,
                                                json.dumps({"submitted": submitted,
                                                            "transforms": episode.submitted_files}), encoding="utf-8")
            except OSError:
                logger.error("Could not retain pipeline artifacts")
            finally:
                try:
                    await asyncio.to_thread(episode.close)
                except Exception:
                    logger.error("Episode workspace cleanup failed")
        self.episodes.clear()


class ELTDataset(RLDataset):
    """One task batch containing a group of independent rollouts."""

    def __init__(self, builder: EnvGroupBuilder):
        self.builder = builder

    def __len__(self) -> int:
        return 1

    def get_batch(self, index: int) -> Sequence[EnvGroupBuilder]:
        if index != 0:
            raise IndexError(index)
        return (self.builder,)
