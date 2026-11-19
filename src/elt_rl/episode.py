from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from threading import RLock

from .contracts import EpisodeConfig, Grade, PipelineError, TaskDefinition


@dataclass(frozen=True)
class ToolSpec:
    description: str
    arguments: tuple[str, ...] = ()

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {key: {"type": "string"} for key in self.arguments},
            "required": list(self.arguments),
            "additionalProperties": False,
        }


TOOLS = {
    "read_task": ToolSpec("Read the current ELT task and its input and output schemas."),
    "list_workspace": ToolSpec("List saved pipeline artifacts."),
    "write_pipeline_file": ToolSpec("Save text to a task-approved artifact.", ("path", "content")),
    "execute_pipeline": ToolSpec("Run and get feedback for load or transform.", ("stage",)),
    "inspect_warehouse": ToolSpec("Read the current materialized table names and row counts."),
    "submit_pipeline": ToolSpec("Submit the tested pipeline for fresh replay and grading."),
}

INITIAL_INSTRUCTION = (
    "Read the task with read_task. Configure and execute load, then write and run "
    "transformations. Use feedback to repair errors and submit the successfully "
    "tested artifacts. Use a separate turn after execution feedback to submit."
)


@dataclass(frozen=True)
class Feedback:
    text: str
    submitted: bool = False


class ELTEpisodeState:
    """One rollout's artifact versions, execution state, and isolated warehouse."""

    def __init__(self, task: TaskDefinition, config: EpisodeConfig):
        self.task = task
        self.config = config
        config.work_root.mkdir(parents=True, exist_ok=True)
        self._temp = TemporaryDirectory(prefix="episode-", dir=config.work_root)
        self.workspace = Path(self._temp.name)
        self.artifact_dir = self.workspace / "pipeline"
        self.artifact_dir.mkdir()
        try:
            self.backend = task.open_backend(self.workspace, config)
        except Exception:
            self._temp.cleanup()
            raise
        self._lock = RLock()
        self._closed = False
        self._inspected_task = False
        self._loaded = False
        self._tested_turn: int | None = None
        self._last_turn = 0
        self._calls = 0
        self._grade: Grade | None = None

    def __enter__(self) -> "ELTEpisodeState":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self.backend.close()
                self._temp.cleanup()
                self._closed = True

    def grade(self) -> Grade:
        """Host-only terminal reward. An unsubmitted rollout scores zero."""
        with self._lock:
            return self._grade or Grade()

    def dispatch(self, name: str, arguments: object, *, turn: int) -> Feedback:
        with self._lock:
            if self._closed or self._grade is not None:
                return Feedback("ERROR: episode already ended")
            if not self._last_turn <= turn <= self.config.max_turns or turn < 1:
                return Feedback("ERROR: invalid turn or turn limit reached")
            self._last_turn = turn
            if self._calls >= self.config.max_tool_calls:
                return Feedback("ERROR: tool call limit reached")
            self._calls += 1
            try:
                value = self._call(name, arguments, turn)
            except PipelineError as exc:
                value = f"ERROR: {exc}"
            return Feedback(value[:self.config.max_output_chars], self._grade is not None)

    def _call(self, name: str, arguments: object, turn: int) -> str:
        spec = TOOLS.get(name)
        if spec is None:
            raise PipelineError("unknown tool")
        if not isinstance(arguments, dict) or set(arguments) != set(spec.arguments):
            raise PipelineError("invalid tool arguments")
        if any(type(value) is not str for value in arguments.values()):
            raise PipelineError("tool arguments must be strings")
        if name == "read_task":
            self._inspected_task = True
            return self.task.instructions
        if not self._inspected_task:
            raise PipelineError("call read_task first")
        handlers: dict[str, Callable[..., str]] = {
            "list_workspace": self._list_workspace,
            "write_pipeline_file": self._write,
            "execute_pipeline": lambda stage: self._execute(stage, turn),
            "inspect_warehouse": self.backend.inspect,
            "submit_pipeline": lambda: self._submit(turn),
        }
        return handlers[name](**arguments)

    @property
    def _allowed(self) -> tuple[str, ...]:
        return self.task.load_artifacts + self.task.transform_artifacts

    def _list_workspace(self) -> str:
        return ", ".join(name for name in self._allowed if (self.artifact_dir / name).is_file()) or "(empty)"

    def _write(self, path: str, content: str) -> str:
        if path not in self._allowed:
            raise PipelineError("path must be an approved artifact name")
        if path in self.task.transform_artifacts and not self._loaded:
            raise PipelineError("execute load successfully before writing transformations")
        try:
            encoded = content.encode("utf-8")
        except UnicodeEncodeError:
            raise PipelineError("artifact must be valid UTF-8") from None
        if len(encoded) > self.config.max_artifact_bytes:
            raise PipelineError("artifact exceeds size limit")
        (self.artifact_dir / path).write_bytes(encoded)
        self._tested_turn = None
        if path in self.task.load_artifacts:
            self._loaded = False
        return f"saved {path}"

    def _read(self, names: tuple[str, ...]) -> dict[str, str]:
        if any(not (self.artifact_dir / name).is_file() for name in names):
            raise PipelineError("write all required artifacts for this stage")
        return {name: (self.artifact_dir / name).read_text(encoding="utf-8") for name in names}

    def _execute(self, stage: str, turn: int) -> str:
        if stage == "load":
            self._loaded = False
            self._tested_turn = None
            result = self.backend.execute("load", self._read(self.task.load_artifacts))
            self._loaded = True
            return result
        if stage == "transform":
            self._tested_turn = None
            if not self._loaded:
                raise PipelineError("execute load successfully first")
            result = self.backend.execute("transform", self._read(self.task.transform_artifacts))
            self._tested_turn = turn
            return result
        raise PipelineError("stage must be load or transform")

    def _submit(self, turn: int) -> str:
        if self._tested_turn is None or self._tested_turn >= turn:
            raise PipelineError("successfully execute current artifacts in an earlier turn before submitting")
        self._tested_turn = None
        replay_path = Path(mkdtemp(prefix="submission-", dir=self.workspace))
        replay = self.task.open_backend(replay_path, self.config)
        try:
            replay.execute("load", self._read(self.task.load_artifacts))
            replay.execute("transform", self._read(self.task.transform_artifacts))
            self._grade = self.task.verify(replay)
        finally:
            replay.close()
        return "pipeline submitted and graded"
