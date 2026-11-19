"""Optional host-only comparison using the same trace and a changed source."""

import argparse
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .cli import run_trace
from .contracts import EpisodeConfig, Grade
from .episode import ELTEpisodeState
from .local import FIXTURE, local_task


def compare(trace: str, config: EpisodeConfig) -> tuple[Grade, Grade]:
    grades = []
    for fixture in (FIXTURE, FIXTURE.with_name("counterfactual")):
        with ELTEpisodeState(local_task(fixture), config) as episode:
            grades.append(run_trace(io.StringIO(trace), io.StringIO(), episode))
    return grades[0], grades[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare local static and counterfactual fixture rewards.")
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="elt-counterfactual-") as workspace:
        static, changed = compare(args.trace.read_text(encoding="utf-8"), EpisodeConfig(Path(workspace)))
    passed = static.reward == changed.reward == 1
    print(json.dumps({"static_reward": static.reward, "changed_input_reward": changed.reward, "passes_both": passed}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
