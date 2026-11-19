import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TextIO

from .contracts import EpisodeConfig, Grade
from .episode import INITIAL_INSTRUCTION, TOOLS, ELTEpisodeState
from .local import local_task


def run_trace(actions: TextIO, output: TextIO, episode: ELTEpisodeState) -> Grade:
    print(INITIAL_INSTRUCTION, file=output, flush=True)
    for turn in range(1, episode.config.max_turns + 1):
        line = actions.readline(65_537)
        if not line:
            break
        if len(line) > 65_536:
            print("ERROR: input exceeds line limit", file=output)
            break
        try:
            action = json.loads(line)
        except (ValueError, RecursionError):
            action = None
        name, args = "", {}
        if isinstance(action, dict) and set(action) == {"tool", "arguments"} and isinstance(action["tool"], str):
            name, args = action["tool"], action["arguments"]
        feedback = episode.dispatch(name, args, turn=turn)
        label = name if name in TOOLS else "(invalid action)"
        print(f"{turn:02} {label}: {feedback.text}", file=output, flush=True)
        if feedback.submitted:
            break
    grade = episode.grade()
    print(json.dumps({"reward": grade.reward, **grade.metrics()}), file=output)
    return grade


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local ELT episode from JSONL tool calls.")
    parser.add_argument("trace", nargs="?", type=Path, help="Trace file. Omit to read from stdin.")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="elt-") as root:
        with ELTEpisodeState(local_task(), EpisodeConfig(Path(root))) as episode:
            if args.trace is None:
                grade = run_trace(sys.stdin, sys.stdout, episode)
            else:
                with args.trace.open(encoding="utf-8") as actions:
                    grade = run_trace(actions, sys.stdout, episode)
    return 0 if grade.submitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
