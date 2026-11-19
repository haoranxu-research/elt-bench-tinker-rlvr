"""Optional Cookbook environment integration. Importing it creates no API client."""

import asyncio
import logging
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tinker_cookbook.renderers.base import Message, Renderer, ToolSpec
from tinker_cookbook.rl.message_env import EnvFromMessageEnv, MessageStepResult
from tinker_cookbook.rl.rollout_limits import RolloutLimits
from tinker_cookbook.rl.types import Env, EnvGroupBuilder, Metrics, RLDataset
from tinker_cookbook.tool_use import AgentToolMessageEnv, Tool, ToolInput, ToolResult, simple_tool_result

from .contracts import EpisodeConfig, TaskDefinition
from .episode import INITIAL_INSTRUCTION, TOOLS, ELTEpisodeState
from .local import local_task

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenBudget:
    context: int = 16_384
    sampled: int = 8_192
    per_turn: int = 2_048


@dataclass
class EpisodeTool:
    name: str
    turn: Callable[[], int]
    episode: ELTEpisodeState

    @property
    def description(self) -> str:
        return TOOLS[self.name].description

    @property
    def parameters_schema(self) -> dict:
        return TOOLS[self.name].schema()

    def to_spec(self) -> ToolSpec:
        return {"name": self.name, "description": self.description, "parameters": self.parameters_schema}

    async def run(self, input: ToolInput) -> ToolResult:
        feedback = await asyncio.to_thread(
            self.episode.dispatch, self.name, input.arguments, turn=self.turn(),
        )
        return simple_tool_result(
            feedback.text, call_id=input.call_id or "", name=self.name, should_stop=feedback.submitted,
        )


class ELTMessageEnv(AgentToolMessageEnv):
    """Reuse the Cookbook's dispatcher while tracking the feedback turn explicitly."""

    def __init__(self, episode: ELTEpisodeState, renderer: Renderer):
        self.turn = 0
        tools: list[Tool] = [EpisodeTool(name, lambda: self.turn, episode) for name in TOOLS]
        messages = renderer.create_conversation_prefix_with_tools(
            tools=[tool.to_spec() for tool in tools],
            system_prompt=INITIAL_INSTRUCTION,
        )
        messages.append({"role": "user", "content": "Complete the ELT task."})

        async def reward_fn(_: list[Message]) -> tuple[float, Metrics]:
            grade = episode.grade()
            return grade.reward, grade.metrics()

        super().__init__(
            tools=tools, initial_messages=messages, reward_fn=reward_fn,
            max_turns=episode.config.max_turns, max_tool_calls=episode.config.max_tool_calls,
            failed_parse_reward=0.0, tool_execution="sequential",
        )

    async def step(self, message: Message) -> MessageStepResult:
        self.turn += 1
        return await super().step(message)


class ELTGroupBuilder(EnvGroupBuilder):
    """Create isolated members and release them after Cookbook group grading."""

    def __init__(self, config: EpisodeConfig, renderer: Renderer, group_size: int,
                 task_factory: Callable[[], TaskDefinition] = local_task,
                 budget: TokenBudget = TokenBudget(), evidence_dir: Path | None = None):
        if group_size < 1:
            raise ValueError("group_size must be positive")
        self.config = config
        self.renderer = renderer
        self.group_size = group_size
        self.task_factory = task_factory
        self.budget = budget
        self.evidence_dir = evidence_dir
        self.episodes: list[ELTEpisodeState] = []

    async def make_envs(self) -> Sequence[Env]:
        if self.episodes:
            raise RuntimeError("clean up the previous rollout group first")
        envs: list[Env] = []
        try:
            for _ in range(self.group_size):
                episode = ELTEpisodeState(self.task_factory(), self.config)
                self.episodes.append(episode)
                envs.append(EnvFromMessageEnv(
                    self.renderer, ELTMessageEnv(episode, self.renderer),
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
                ))
        except Exception:
            await self.cleanup()
            raise
        return envs

    async def cleanup(self) -> None:
        for episode in self.episodes:
            try:
                if self.evidence_dir and episode.grade().submitted:
                    await asyncio.to_thread(shutil.copytree, episode.artifact_dir,
                                            self.evidence_dir / episode.workspace.name)
            except OSError:
                logger.error("Could not retain submitted pipeline artifacts")
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
