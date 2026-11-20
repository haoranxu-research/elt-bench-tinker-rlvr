from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

Stage = Literal["load", "transform"]


class PipelineError(ValueError):
    """A bounded, model-safe pipeline error that the agent can repair."""


@dataclass(frozen=True)
class EpisodeConfig:
    work_root: Path
    max_turns: int = 24
    max_tool_calls: int = 24
    max_artifact_bytes: int = 8_192
    max_output_chars: int = 2_048
    execution_seconds: float = 1.0
    rollout_seconds: float = 90.0
    max_submissions: int = 2


@dataclass(frozen=True)
class TokenBudget:
    context: int = 16_384
    sampled: int = 8_192
    per_turn: int = 2_048


PILOT_BUDGET = TokenBudget(context=8192, sampled=4096, per_turn=1024)
PILOT_TURNS = 18
LORA_RANK = 16


@dataclass(frozen=True)
class Grade:
    stage1: float = 0.0
    stage2: float = 0.0
    stage2_ran: bool = False
    submitted: bool = False

    @property
    def reward(self) -> float:
        return (35 * self.stage1 + 65 * self.stage2) / 100 if self.submitted else 0.0

    def metrics(self) -> dict[str, float | int]:
        return {
            "stage1": self.stage1,
            "stage2": self.stage2,
            "stage2_ran": int(self.stage2_ran),
            "submitted": int(self.submitted),
        }


class WarehouseBackend(Protocol):
    """Run trusted stage entry points in an episode-owned destination namespace."""

    def execute(self, stage: Stage, artifacts: Mapping[str, str]) -> str: ...
    def inspect(self) -> str: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    instructions: str
    load_artifacts: tuple[str, ...]
    transform_artifacts: tuple[str, ...]
    open_backend: Callable[[Path, EpisodeConfig], WarehouseBackend]
    verify: Callable[[WarehouseBackend], Grade]
    sections: Mapping[str, str] = field(default_factory=dict)
    partial_transforms: bool = False
