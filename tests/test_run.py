from pathlib import Path

import pytest

from elt_rl.contracts import EpisodeConfig
from elt_rl.robustness import compare
from elt_rl.run import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize(("trace", "replay"), [
    ("customer_orders.jsonl", 1.0),
    ("static_answer.jsonl", 0.35),
])
def test_baseline_vs_changed_input(tmp_path, trace, replay):
    grades = compare((EXAMPLES / trace).read_text(encoding="utf-8"), EpisodeConfig(tmp_path))
    assert [grade.reward for grade in grades] == [1.0, replay]
    assert all(grade.stage1 == 1 for grade in grades)


@pytest.mark.parametrize(("mode", "approval"), [
    ("official-rollout", ["--allow-paid"]),
    ("train-one", []),
    ("train-one", ["--allow-paid"]),
])
def test_remote_cli_blocks_unapproved_or_missing_credentials(tmp_path, mode, approval, monkeypatch):
    monkeypatch.delenv("TINKER_API_KEY", raising=False)
    out = tmp_path / "remote"
    with pytest.raises(SystemExit, match="2"):
        main([mode, "--budget-usd", "1", "--out", str(out), *approval])
    assert not out.exists()
