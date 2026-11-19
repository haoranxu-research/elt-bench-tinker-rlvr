from pathlib import Path

import pytest

from elt_rl.contracts import EpisodeConfig
from elt_rl.preflight import main as preflight
from elt_rl.robustness import compare, run_suite
from elt_rl.run import main
from elt_rl.settings import NAMES

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
        main([mode, "--env-file", str(tmp_path / ".env"), "--budget-usd", "1", "--out", str(out), *approval])
    assert not out.exists()


def test_robustness_suite_identifies_specific_failures(tmp_path):
    rows = {row["failure_mode"]: row for row in run_suite(EXAMPLES, EpisodeConfig(tmp_path), 1)}
    assert {name: row["robust_reward"] for name, row in rows.items()} == {
        "data-derived control": 1, "hard-coded aggregates": 0.35, "amount cutoff": 0.675,
        "missing row": 0.675, "duplicate key": 0.675, "null assumption": 0.675,
        "order invariance": 1, "repeat execution": 1,
    }
    assert all(row["original_reward"] == row["robust_stage1"] == 1 for row in rows.values())
    assert all(row["additional_ms"] >= 0 for row in rows.values())


def test_default_preflight_has_no_service_calls_or_secret_output(tmp_path, monkeypatch, capsys):
    import json
    import elt_rl.preflight as checks

    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("TINKER_API_KEY=local-secret-marker\nUNRECOGNIZED_SECRET=hidden-marker\n", encoding="utf-8")
    def unexpected(*args, **kwargs):
        pytest.fail("offline preflight attempted a service probe")
    monkeypatch.setattr(checks, "_snowflake_probe", unexpected)
    monkeypatch.setattr(checks, "_airbyte_probe", unexpected)
    monkeypatch.setattr(checks, "_renderer_probe", lambda *args: "renderer available")
    assert preflight(["official", "--env-file", str(env)]) == 2
    output = capsys.readouterr().out
    assert "local-secret-marker" not in output
    official = {check["check"]: check["status"] for check in json.loads(output)["checks"]}
    assert official["snowflake"] == official["namespace_isolation"] == "unverified"
    assert preflight(["tinker", "--env-file", str(env)]) == 0
    output = capsys.readouterr().out
    assert "local-secret-marker" not in output and "hidden-marker" not in output
    tinker = {check["check"]: check["status"] for check in json.loads(output)["checks"]}
    assert tinker == {"tinker_key": "pass", "renderer_and_tokenizer": "pass",
                      "pilot_budget": "pass", "model_access": "unverified"}
    assert preflight(["tinker", "--env-file", str(env), "--budget-usd", "0.01"]) == 2


def test_local_key_reaches_only_authorized_client_boundary(tmp_path, monkeypatch, capsys):
    import sys
    from types import SimpleNamespace

    monkeypatch.delenv("TINKER_API_KEY", raising=False)
    monkeypatch.setenv("TINKER_TELEMETRY", "0")
    env = tmp_path / ".env"
    env.write_text("TINKER_API_KEY=private-test-marker\n", encoding="utf-8")
    out = tmp_path / "run"

    async def fail(*args, api_key, **kwargs):
        assert api_key == "private-test-marker"
        raise ValueError(api_key)

    monkeypatch.setitem(sys.modules, "elt_rl.training", SimpleNamespace(run_remote=fail))
    assert main(["train-one", "--allow-paid", "--env-file", str(env), "--budget-usd", "1", "--out", str(out)]) == 1
    capture = capsys.readouterr()
    assert "private-test-marker" not in capture.err + capture.out
    assert "private-test-marker" not in (out / "manifest.json").read_text(encoding="utf-8")
