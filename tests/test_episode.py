import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest

from elt_rl.cli import run_trace
from elt_rl.contracts import EpisodeConfig, Grade
from elt_rl.episode import ELTEpisodeState, Feedback
from elt_rl.local import FIXTURE, local_task

TRACE = Path(__file__).resolve().parents[1] / "examples" / "customer_orders.jsonl"
ACTIONS = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]


@dataclass
class Driver:
    episode: ELTEpisodeState
    turn: int = 0

    def call(self, name: str, **args: str) -> Feedback:
        self.turn += 1
        return self.episode.dispatch(name, args, turn=self.turn)

    def prepare(self, limit: int | None = None, order_sql: str | None = None) -> None:
        assert "Local customer orders" in self.call("read_task").text
        load = json.dumps({"sources": {"customers.csv": None, "orders.csv": limit}})
        assert self.call("write_pipeline_file", path="load.json", content=load).text == "saved load.json"
        assert self.call("execute_pipeline", stage="load").text.startswith("load finished")
        assert self.call("write_pipeline_file", **ACTIONS[3]["arguments"]).text.startswith("saved")
        sql = ACTIONS[6]["arguments"]["content"] if order_sql is None else order_sql
        assert self.call("write_pipeline_file", path="order_totals.sql", content=sql).text.startswith("saved")


@pytest.fixture
def episode(tmp_path):
    with ELTEpisodeState(local_task(), EpisodeConfig(tmp_path)) as state:
        yield state


def test_full_trace_repairs_failure_and_materializes_submitted_warehouse(episode):
    output = io.StringIO()
    with TRACE.open(encoding="utf-8") as actions:
        score = run_trace(actions, output, episode)
    lines = output.getvalue()
    assert "no such column: wrong_amount" in lines
    assert "transform finished. customer_totals=4, order_totals=1" in lines
    assert score == Grade(1.0, 1.0, True, True)
    assert score.reward == 1.0
    submitted_db, = episode.workspace.glob("submission-*/warehouse.sqlite")
    with closing(sqlite3.connect(submitted_db)) as connection:
        assert connection.execute("SELECT * FROM order_totals").fetchall() == [(4, 9.6875)]
        assert connection.execute("SELECT * FROM customer_totals WHERE customer_id=4").fetchone() == (
            4, None, 1, 9.25,
        )


@pytest.mark.parametrize(("limit", "sql", "grade", "reward"), [
    (3, None, Grade(0.5, 0, False, True), 0.175),
    (None, "SELECT COUNT(*) AS order_count, SUM(amount) AS average_amount FROM raw_orders",
     Grade(1, 0.5, True, True), 0.675),
])
def test_staged_scoring(episode, limit, sql, grade, reward):
    driver = Driver(episode)
    driver.prepare(limit, sql)
    assert driver.call("execute_pipeline", stage="transform").text.startswith("transform finished")
    assert driver.call("submit_pipeline").submitted
    assert episode.grade() == grade
    assert episode.grade().reward == reward


def test_submission_requires_a_later_turn_and_current_execution(episode):
    driver = Driver(episode)
    driver.prepare()
    assert driver.call("execute_pipeline", stage="transform").text.startswith("transform finished")
    assert not episode.dispatch("submit_pipeline", {}, turn=driver.turn).submitted
    assert episode.grade() == Grade()
    driver.call("write_pipeline_file", **ACTIONS[6]["arguments"])
    assert not driver.call("submit_pipeline").submitted
    assert episode.grade().reward == 0
    assert driver.call("execute_pipeline", stage="transform").text.startswith("transform finished")
    assert driver.call("submit_pipeline").submitted
    assert "already ended" in driver.call("execute_pipeline", stage="load").text


def test_trace_ending_without_submission_has_zero_reward(episode):
    actions = io.StringIO("\n".join(json.dumps(action) for action in ACTIONS[:-1]))
    output = io.StringIO()
    assert run_trace(actions, output, episode) == Grade()
    assert "transform finished. customer_totals=4, order_totals=1" in output.getvalue()
    assert list(episode.workspace.glob("submission-*")) == []


def test_invalid_execution_rolls_back_both_models(episode):
    driver = Driver(episode)
    driver.prepare(order_sql="SELECT nope FROM raw_orders")
    assert "no such column" in driver.call("execute_pipeline", stage="transform").text
    assert driver.call("inspect_warehouse").text == "raw_customers=4, raw_orders=4"
    assert not driver.call("submit_pipeline").submitted
    driver.call("write_pipeline_file", **ACTIONS[6]["arguments"])
    assert driver.call("execute_pipeline", stage="transform").text.startswith("transform finished")
    assert driver.call("submit_pipeline").submitted


def test_reset_and_independent_concurrent_group_members(tmp_path):
    config = EpisodeConfig(tmp_path)
    with (
        ELTEpisodeState(local_task(), config) as left,
        ELTEpisodeState(local_task(), config) as right,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        def run(episode: ELTEpisodeState, limit: int | None) -> Grade:
            driver = Driver(episode)
            driver.prepare(limit)
            assert driver.call("execute_pipeline", stage="transform").text.startswith("transform finished")
            assert driver.call("submit_pipeline").submitted
            return episode.grade()

        left_result = executor.submit(run, left, None)
        right_result = executor.submit(run, right, 3)
        assert left_result.result().reward == 1.0
        assert right_result.result().reward == 0.175
        left_path, right_path = left.workspace, right.workspace
        assert left_path != right_path
    assert not left_path.exists() and not right_path.exists()
    with ELTEpisodeState(local_task(), config) as reset:
        driver = Driver(reset)
        driver.call("read_task")
        assert driver.call("list_workspace").text == "(empty)"
        assert driver.call("inspect_warehouse").text == "(empty warehouse)"
        assert reset.grade().reward == 0


def test_repeat_replay_and_repeated_load_are_deterministic(tmp_path):
    observed = []
    for _ in range(2):
        with ELTEpisodeState(local_task(), EpisodeConfig(tmp_path)) as episode:
            driver = Driver(episode)
            driver.prepare()
            for _ in range(2):
                assert driver.call("execute_pipeline", stage="load").text.endswith("raw_customers=4, raw_orders=4")
                assert driver.call("execute_pipeline", stage="transform").text.startswith("transform finished")
            assert driver.call("submit_pipeline").submitted
            observed.append(episode.grade())
    assert observed == [Grade(1, 1, True, True)] * 2


def test_traversal_and_spoofed_artifacts_are_rejected(episode):
    driver = Driver(episode)
    driver.call("read_task")
    for path in ("../gold.json", "..\\gold.json", str(FIXTURE / "gold.json"), "results.log", "stage2.json"):
        assert "approved artifact" in driver.call("write_pipeline_file", path=path, content="fake").text
    load = json.dumps({"sources": {str(FIXTURE / "gold.json"): None}})
    driver.call("write_pipeline_file", path="load.json", content=load)
    assert "approved source names" in driver.call("execute_pipeline", stage="load").text
    assert list(episode.artifact_dir.iterdir()) == [episode.artifact_dir / "load.json"]
    assert episode.grade().reward == 0


@pytest.mark.parametrize("sql", [
    "SELECT readfile('gold.json') AS order_count, 1 AS average_amount FROM raw_orders",
    "SELECT COUNT(*) AS order_count, 1 AS average_amount FROM gold",
    "SELECT COUNT(*) AS order_count, 1 AS average_amount FROM sqlite_schema",
    "SELECT 4 AS order_count, 9.6875 AS average_amount",
    "ATTACH DATABASE 'gold.json' AS hidden",
    "CREATE TABLE raw_orders AS SELECT 1",
    "DELETE FROM raw_orders",
    "SELECT COUNT(*) AS order_count, AVG(amount) AS average_amount FROM raw_orders; PRAGMA writable_schema=ON",
])
def test_sql_cannot_read_gold_mutate_raw_or_manufacture_load(episode, sql):
    driver = Driver(episode)
    assert driver.call("execute_pipeline", stage="transform").text == "ERROR: call read_task first"
    driver.prepare(order_sql=sql)
    assert driver.call("execute_pipeline", stage="transform").text.startswith("ERROR:")
    assert driver.call("inspect_warehouse").text == "raw_customers=4, raw_orders=4"
    assert not driver.call("submit_pipeline").submitted
    assert episode.grade().reward == 0


def test_execution_budget_and_recovery(episode):
    driver = Driver(episode)
    aliases = ", ".join(f"raw_orders t{index}" for index in range(11))
    driver.prepare(order_sql=f"SELECT COUNT(*) AS order_count, AVG(t0.amount) AS average_amount FROM {aliases}")
    assert "execution budget exceeded" in driver.call("execute_pipeline", stage="transform").text
    driver.call("write_pipeline_file", **ACTIONS[6]["arguments"])
    assert driver.call("execute_pipeline", stage="transform").text.startswith("transform finished")
    assert driver.call("submit_pipeline").submitted


def test_malformed_payload_and_limits(tmp_path):
    config = EpisodeConfig(tmp_path, max_tool_calls=3, max_turns=4, max_artifact_bytes=4, max_output_chars=64)
    with ELTEpisodeState(local_task(), config) as episode:
        output = io.StringIO()
        actions = io.StringIO(
            '{bad json\n{"tool":"read_task","arguments":{}}\n'
            '{"tool":"write_pipeline_file","arguments":{"path":"load.json","content":"12345"}}\n'
            '{"tool":"list_workspace","arguments":{}}\n{"tool":"submit_pipeline","arguments":{}}\n'
        )
        assert run_trace(actions, output, episode).reward == 0
        assert "unknown tool" in output.getvalue()
        assert "artifact exceeds size limit" in output.getvalue()
        assert "tool call limit reached" in output.getvalue()
        assert "05 " not in output.getvalue()
        assert list(episode.artifact_dir.iterdir()) == []


def test_gold_comparison_handles_order_and_rounding(episode):
    driver = Driver(episode)
    driver.prepare(order_sql="SELECT COUNT(*) AS order_count, AVG(amount)+0.000001 AS average_amount FROM raw_orders")
    customer = ACTIONS[3]["arguments"]["content"]
    driver.call("write_pipeline_file", path="customer_totals.sql", content=customer + " ORDER BY c.customer_id DESC")
    assert driver.call("execute_pipeline", stage="transform").text.startswith("transform finished")
    assert driver.call("submit_pipeline").submitted
    assert episode.grade().stage2 == 1


def test_duplicate_keys_fail_full_table_comparison(episode):
    driver = Driver(episode)
    driver.prepare()
    customer = ACTIONS[3]["arguments"]["content"]
    customer = customer.replace("SELECT c.customer_id,", "SELECT 1 AS customer_id,")
    driver.call("write_pipeline_file", path="customer_totals.sql", content=customer)
    assert driver.call("execute_pipeline", stage="transform").text.startswith("transform finished")
    assert driver.call("submit_pipeline").submitted
    assert episode.grade().stage2 == 0.5
