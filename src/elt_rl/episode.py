import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from threading import RLock

from .contracts import EpisodeConfig, Grade, PartialTransformError, PipelineError, TaskDefinition


@dataclass(frozen=True)
class ToolSpec:
    description: str
    arguments: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()

    def schema(self) -> dict:
        properties = {key: {"type": "string"} for key in (*self.arguments, *self.optional)}
        if "content" in properties:
            properties["content"] = {
                "type": ["string", "object"],
                "description": "SQL or JSON text. For load.json, a JSON object is also accepted.",
            }
        if "stage" in properties:
            properties["stage"]["enum"] = ["load", "transform"]
        if "file" in properties:
            properties["file"]["description"] = "Optional filename. Use load.json for load or one saved SQL filename for transform."
        if "mode" in properties:
            properties["mode"].update(enum=["complete", "partial"], default="complete")
        return {
            "type": "object",
            "properties": properties,
            "required": list(self.arguments),
            "additionalProperties": False,
        }


TOOLS = {
    "read_task": ToolSpec("Read the current ELT task and its input and output schemas."),
    "read_task_section": ToolSpec("Read a named task section listed by read_task.", ("section",)),
    "list_workspace": ToolSpec("List saved pipeline artifacts."),
    "write_pipeline_file": ToolSpec("Write or replace one approved file. Put the full SQL text in content, with no Markdown fences. Saving does not execute it.", ("path", "content")),
    "execute_pipeline": ToolSpec("Run saved files only. Pass stage=load for load.json or stage=transform for the SQL files. This tool does not accept SQL.", ("stage",)),
    "inspect_warehouse": ToolSpec("Read the current materialized table names and row counts."),
    "submit_pipeline": ToolSpec("Grade saved files in a fresh warehouse. Call with no arguments on a later turn after a successful transform. This tool does not accept SQL."),
}

BOOKS_TOOLS = {
    **TOOLS,
    "execute_pipeline": ToolSpec(
        "Load saved load.json with stage=load, optionally specifying file=load.json. To test one saved SQL file, pass "
        "stage=transform and file set to that filename. An omitted file tests the complete batch.",
        ("stage",), ("file",),
    ),
    "submit_pipeline": ToolSpec(
        "Call on a later turn to grade current tested files in a fresh warehouse. Pass mode=partial "
        "to submit the validated subset, or use {} after all files pass. Submit before the budget ends.",
        optional=("mode",),
    ),
}

INITIAL_INSTRUCTION = (
    "First call read_task. Save load.json and each SQL file with write_pipeline_file(path, content). "
    "Only write_pipeline_file persists SQL. Execute load, save each SQL file, then execute transform. "
    "For a SQL error, rewrite the named file and execute again. Reserve a later turn to submit after execution succeeds."
)
BOOKS_INSTRUCTION = (
    "Use tools to complete the ELT task. Start with read_task. Save load.json with write_pipeline_file, "
    "then execute_pipeline with stage=load. "
    "Use bare filenames for every tool, without directory prefixes. Read the relevant source and model sections. "
    "For each model, use write_pipeline_file(path, content) to save the full SQL query, then test just "
    "that file with execute_pipeline(stage=transform, file=filename). Rewrite the named file when it fails. "
    "Only write_pipeline_file accepts SQL text. Follow the remaining budget and tested files in tool feedback. "
    "Submit on a later turn after testing. If time or transform attempts are running out, "
    'call submit_pipeline with {"mode":"partial"} to grade the current tested subset. '
    "The last turn and last tool call are reserved for submission."
)
BOOKS_REQUEST = "Complete the ELT task using the tools. Your first action is read_task with {}."


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
        self._tested_files: dict[str, int] = {}
        self._last_turn = 0
        self._calls = 0
        self._submission_attempts = 0
        self._grade: Grade | None = None
        self.submitted_files: tuple[str, ...] = ()

    def __enter__(self) -> "ELTEpisodeState":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self.backend.close()
                finally:
                    self._temp.cleanup()

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
                if self.task.partial_transforms and name != "submit_pipeline" and (
                    turn == self.config.max_turns or self._calls == self.config.max_tool_calls
                ):
                    raise PipelineError("final turn or tool call reserved for submit_pipeline")
                value = self._call(name, arguments, turn)
            except PipelineError as exc:
                value = f"ERROR: {exc}"
            if self.task.partial_transforms and self._grade is None:
                budget = "\n" + self._submission_status(turn)
                room = max(0, self.config.max_output_chars - len(budget))
                return Feedback((value[:room] + budget)[:self.config.max_output_chars])
            return Feedback(value[:self.config.max_output_chars], self._grade is not None)

    def _submission_status(self, turn: int) -> str:
        turns = self.config.max_turns - turn
        calls = self.config.max_tool_calls - self._calls
        attempts = getattr(self.backend, "remaining_transform_attempts", None)
        tested = ", ".join(name for name in self.task.transform_artifacts if name in self._tested_files)
        status = f"After this turn: {turns} turns left. Tool calls left: {calls}."
        if attempts is not None:
            status += f" Warehouse transform attempts left: {attempts}."
        status += f" Current tested files: {tested or 'none'}."
        if self._tested_files and (turns <= 3 or calls <= 3 or attempts == 0):
            arguments = "{}" if len(self._tested_files) == len(self.task.transform_artifacts) else '{"mode":"partial"}'
            status += f" Use the next turn to call submit_pipeline with {arguments}."
        return status

    def continuation_hint(self, turn: int) -> str | None:
        if not self.task.partial_transforms or turn >= self.config.max_turns:
            return None
        if self._calls >= self.config.max_tool_calls or self._grade is not None:
            return None
        return (
            "No tool call was received. Text or JSON in chat does not change the pipeline. "
            "Use a tool for your next action. " + self._submission_status(turn)
        )

    def _call(self, name: str, arguments: object, turn: int) -> str:
        spec = self.tools.get(name)
        if spec is None:
            raise PipelineError("unknown tool")
        if (not isinstance(arguments, dict) or not set(spec.arguments) <= arguments.keys()
                or arguments.keys() - set((*spec.arguments, *spec.optional))):
            allowed = ", ".join((*spec.arguments, *spec.optional)) or "no arguments"
            hint = " Save SQL using write_pipeline_file(path, content)." if name in {"execute_pipeline", "submit_pipeline"} else ""
            raise PipelineError(f"invalid tool arguments for {name}; allowed: {allowed}.{hint}")
        # The Qwen XML parser decodes a JSON-looking parameter into a Python
        # object even when the model intended to write that JSON verbatim.
        if name == "write_pipeline_file" and arguments["path"] == "load.json" and isinstance(arguments["content"], dict):
            try:
                arguments = {**arguments, "content": json.dumps(arguments["content"], allow_nan=False)}
            except (TypeError, ValueError, RecursionError):
                raise PipelineError("load.json content must be valid JSON") from None
        if any(type(value) is not str for value in arguments.values()):
            raise PipelineError("tool arguments must be strings")
        if name == "read_task":
            self._inspected_task = True
            sections = ", ".join(self.task.sections)
            return self.task.instructions + (f"\nTask sections: {sections}" if sections else "")
        if not self._inspected_task:
            raise PipelineError("call read_task first")
        handlers: dict[str, Callable[..., str]] = {
            "list_workspace": self._list_workspace,
            "read_task_section": self._read_task_section,
            "write_pipeline_file": self._write,
            "execute_pipeline": lambda stage, file=None: self._execute(stage, turn, file),
            "inspect_warehouse": self.backend.inspect,
            "submit_pipeline": lambda mode="complete": self._submit(turn, mode),
        }
        return handlers[name](**arguments)

    @property
    def tools(self) -> dict[str, ToolSpec]:
        return BOOKS_TOOLS if self.task.partial_transforms else TOOLS

    def tool_schema(self, name: str) -> dict:
        schema = self.tools[name].schema()
        if self.task.partial_transforms:
            choices = {
                "write_pipeline_file": ("path", self._allowed),
                "read_task_section": ("section", tuple(self.task.sections)),
                "execute_pipeline": ("file", self._allowed),
            }
            if name in choices:
                key, values = choices[name]
                if values:
                    schema["properties"][key]["enum"] = list(values)
        return schema

    def _read_task_section(self, section: str) -> str:
        if section not in self.task.sections:
            raise PipelineError("unknown task section")
        return self.task.sections[section]

    @property
    def _allowed(self) -> tuple[str, ...]:
        return self.task.load_artifacts + self.task.transform_artifacts

    def _list_workspace(self) -> str:
        if self.task.partial_transforms:
            return ", ".join(
                f"{name}: " + (
                    "tested" if name in self._tested_files or (name in self.task.load_artifacts and self._loaded)
                    else "saved, needs execution" if (self.artifact_dir / name).is_file() else "missing"
                )
                for name in self._allowed
            )
        return ", ".join(name for name in self._allowed if (self.artifact_dir / name).is_file()) or "(empty)"

    def _write(self, path: str, content: str) -> str:
        if path not in self._allowed:
            if self.task.partial_transforms:
                raise PipelineError("path must be one bare filename: " + ", ".join(self._allowed))
            raise PipelineError("path must be an approved artifact name")
        if path in self.task.transform_artifacts and not self._loaded:
            raise PipelineError("execute load successfully before writing transformations")
        try:
            encoded = content.encode("utf-8")
        except UnicodeEncodeError:
            raise PipelineError("artifact must be valid UTF-8") from None
        if len(encoded) > self.config.max_artifact_bytes:
            raise PipelineError("artifact exceeds size limit")
        target = self.artifact_dir / path
        if self.task.partial_transforms and target.is_file() and target.read_bytes() == encoded:
            return f"{path} already contains these bytes. Use list_workspace to check execution status."
        target.write_bytes(encoded)
        self._tested_turn = None
        self._tested_files.pop(path, None)
        if path in self.task.load_artifacts:
            self._loaded = False
            self._tested_files.clear()
        if not self.task.partial_transforms:
            return f"saved {path}"
        stage = "load" if path in self.task.load_artifacts else "transform"
        target_args = f" and file={path}" if stage == "transform" else ""
        return f"saved {path} ({len(encoded)} bytes). Next: execute_pipeline with stage={stage}{target_args}."

    def _read(self, names: tuple[str, ...]) -> dict[str, str]:
        missing = [name for name in names if not (self.artifact_dir / name).is_file()]
        if missing:
            raise PipelineError("write missing files using write_pipeline_file: " + ", ".join(missing))
        return {name: (self.artifact_dir / name).read_text(encoding="utf-8") for name in names}

    def _execute(self, stage: str, turn: int, file: str | None = None) -> str:
        if stage == "load":
            if file is not None and file not in self.task.load_artifacts:
                raise PipelineError("for stage=load, omit file or use " + ", ".join(self.task.load_artifacts))
            if self.task.partial_transforms and self._loaded:
                return "load.json is already loaded. Save the required SQL files and execute transform."
            self._loaded = False
            self._tested_turn = None
            self._tested_files.clear()
            result = self.backend.execute("load", self._read(self.task.load_artifacts))
            self._loaded = True
            return result
        if stage == "transform":
            if file is not None and file not in self.task.transform_artifacts:
                raise PipelineError("for stage=transform, use a saved SQL filename: "
                                    + ", ".join(self.task.transform_artifacts))
            self._tested_turn = None
            if not self._loaded:
                raise PipelineError("execute load successfully first")
            names = (file,) if file is not None else self.task.transform_artifacts
            if file is not None:
                self._tested_files.pop(file, None)
            try:
                result = self.backend.execute("transform", self._read(names))
            except PartialTransformError as error:
                self._tested_files.update(dict.fromkeys(
                    (name for name in error.tested_files if name in names), turn,
                ))
                raise
            self._tested_turn = turn
            self._tested_files.update(dict.fromkeys(names, turn))
            if self.task.partial_transforms:
                return result + " Tested: " + ", ".join(names) + ". Submit on a later turn once ready."
            return result
        raise PipelineError("stage must be load or transform")

    def _submit(self, turn: int, mode: str) -> str:
        names = self.task.transform_artifacts
        if self.task.partial_transforms:
            if mode not in {"complete", "partial"}:
                raise PipelineError("mode must be complete or partial")
            if turn in self._tested_files.values():
                raise PipelineError("submit on a later turn after reading the transform result")
            ready = tuple(name for name in names if self._tested_files.get(name, turn) < turn)
            if not ready:
                raise PipelineError("execute current saved SQL successfully on an earlier turn before submitting")
            if mode == "complete" and ready != names:
                missing = ", ".join(name for name in names if name not in ready)
                raise PipelineError(f"test these current SQL files on an earlier turn: {missing}. Or submit with mode=partial.")
            names = ready
        elif self._tested_turn is None or self._tested_turn >= turn:
            raise PipelineError("successfully execute current artifacts in an earlier turn before submitting")
        if self._submission_attempts >= self.config.max_submissions:
            raise PipelineError("submission replay limit reached")
        self._submission_attempts += 1
        self._tested_turn = None
        self._tested_files.clear()
        replay_path = Path(mkdtemp(prefix="submission-", dir=self.workspace))
        replay = self.task.open_backend(replay_path, self.config)
        try:
            replay.execute("load", self._read(self.task.load_artifacts))
            replay.execute("transform", self._read(names))
            grade = self.task.verify(replay)
        finally:
            replay.close()
        if not grade.submitted:
            raise PipelineError("the verifier did not accept this replay")
        self.submitted_files = names
        self._grade = grade
        if not self.task.partial_transforms:
            return "pipeline submitted and graded"
        stage2 = f"{grade.stage2:.6g}" if grade.stage2_ran else "skipped"
        return (f"pipeline submitted and graded. Stage 1: {grade.stage1:.6g}. "
                f"Stage 2: {stage2}. Reward: {grade.reward:.6g}.")
