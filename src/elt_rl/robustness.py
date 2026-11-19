"""Optional host-only comparison using the same trace and a changed source."""

import argparse
import io
import json
import shutil
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

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


def _trace_with(trace: str, artifact: str, sql: str) -> str:
    calls = [json.loads(line) for line in trace.splitlines()]
    for call in reversed(calls):
        if call["tool"] == "write_pipeline_file" and call["arguments"]["path"] == artifact:
            call["arguments"]["content"] = sql
            return "\n".join(json.dumps(call) for call in calls) + "\n"
    raise ValueError(f"trace does not contain {artifact}")


def _original_sql(trace: str, artifact: str) -> str:
    return next(action["arguments"]["content"] for action in map(json.loads, reversed(trace.splitlines()))
                if action["tool"] == "write_pipeline_file" and action["arguments"]["path"] == artifact)


def _variant(root: Path, name: str, customers: str, transform) -> Path:
    path = root / name
    shutil.copytree(FIXTURE, path)
    (path / "customers.csv").write_text(customers, encoding="utf-8")
    gold = json.loads((FIXTURE / "gold.json").read_text(encoding="utf-8"))
    transform(gold, gold["models"]["customer_totals"]["rows"])
    (path / "gold.json").write_text(json.dumps(gold), encoding="utf-8")
    return path


def _run(trace: str, fixture: Path, config: EpisodeConfig, repeat: bool = False) -> Grade:
    with ELTEpisodeState(local_task(fixture), config) as episode:
        if not repeat:
            return run_trace(io.StringIO(trace), io.StringIO(), episode)
        # Repeat in the same live warehouse before fresh submission. Checking only
        # the final replay would hide append-on-retry bugs in the working namespace.
        sql = {name: _original_sql(trace, name) for name in episode.task.transform_artifacts}
        load = {"load.json": _original_sql(trace, "load.json")}
        first = None
        for _ in range(2):
            episode.backend.execute("load", load)
            episode.backend.execute("transform", sql)
            grade = episode.task.verify(episode.backend)
            if first is not None and grade != first:
                raise RuntimeError("repeated local execution changed the warehouse grade")
            first = grade
        return grade


def run_suite(examples: Path, config: EpisodeConfig, repetitions: int) -> list[dict]:
    correct = (examples / "customer_orders.jsonl").read_text(encoding="utf-8")
    static = (examples / "static_answer.jsonl").read_text(encoding="utf-8")
    customer_model = "customer_totals.sql"
    sql = _original_sql(correct, customer_model)
    existing = (FIXTURE / "customers.csv").read_text(encoding="utf-8")
    counterfactual = FIXTURE.with_name("counterfactual")
    with TemporaryDirectory(prefix="elt-perturbations-", dir=config.work_root) as directory:
        root = Path(directory)

        def add_customer(targets, rows):
            targets["raw_counts"]["raw_customers"] = 5
            rows.append([5, "Lin", 0, 0.0])

        added = _variant(root, "added", existing + "5,Lin\n", add_customer)
        nullable = _variant(root, "nullable", existing.replace("1,Ada", "1,"),
                            lambda _, rows: rows[0].__setitem__(1, None))
        def increase_amount(targets, rows):
            # The one order rose by $10. Customer 1's sum increases by
            # $10 and the four-order mean increases by $2.50.
            rows[0][3] = 33.25
            targets["models"]["order_totals"]["rows"] = [[4, 12.1875]]

        high_value = _variant(root, "high-value", existing, increase_amount)
        orders = (FIXTURE / "orders.csv").read_text(encoding="utf-8")
        (high_value / "orders.csv").write_text(orders.replace("11,1,12.75", "11,1,22.75"), encoding="utf-8")
        lines = existing.splitlines()
        reordered = _variant(root, "reordered", "\n".join(lines[:1] + lines[:0:-1]) + "\n",
                             lambda *_: None)
        cases = [
            ("data-derived control", "change assignments and amounts", correct, counterfactual,
             "positive control for data-dependent SQL", False),
            ("hard-coded aggregates", "change assignments and amounts", static, counterfactual,
             "static outputs can match all original answers", False),
            ("amount cutoff", "increase one order above 20", _trace_with(
                correct, "order_totals.sql",
                "SELECT COUNT(*) AS order_count, AVG(amount) AS average_amount FROM raw_orders WHERE amount <= 20",
            ), high_value, "unjustified cutoff drops a legitimate order", False),
            ("missing row", "add one customer without orders", _trace_with(
                correct, customer_model, sql.replace("GROUP BY", "WHERE c.customer_id <= 4 GROUP BY"),
            ), added, "new customer must be included", False),
            ("duplicate key", "add a customer sharing an existing name", _trace_with(
                correct, customer_model,
                sql.replace("SELECT c.customer_id,", "SELECT CASE WHEN c.customer_id=5 THEN 2 ELSE c.customer_id END AS customer_id,"),
            ), added, "duplicate IDs fail the unique-key check", False),
            ("null assumption", "make a second customer's name NULL", _trace_with(
                correct, customer_model,
                sql.replace("SELECT c.customer_id, c.name,", "SELECT c.customer_id, CASE WHEN c.customer_id=4 THEN NULL ELSE COALESCE(c.name,'Unknown') END AS name,"),
            ), nullable, "the task requires preserving all NULL names", False),
            ("order invariance", "reverse source order and emit descending keys", _trace_with(
                correct, customer_model, sql + " ORDER BY c.customer_id DESC",
            ), reordered, "row order alone must not cause rejection", False),
            ("repeat execution", "load and transform twice in the same warehouse", correct, FIXTURE,
             "local full refresh and replace semantics preserve tables and counts", True),
        ]
        results = []
        for failure_mode, intervention, trace, fixture, detects, repeat in cases:
            times = []
            for _ in range(repetitions):
                start = perf_counter()
                original = _run(trace, FIXTURE, config)
                before_changed = perf_counter()
                changed = _run(trace, fixture, config, repeat)
                times.append(((before_changed - start) * 1000, (perf_counter() - before_changed) * 1000))
            results.append({"failure_mode": failure_mode, "intervention": intervention,
                            "original_reward": original.reward, "robust_reward": changed.reward,
                            "robust_stage1": changed.stage1, "robust_stage2": changed.stage2,
                            "detects": detects, "original_ms": round(median(t[0] for t in times), 2),
                            "additional_ms": round(median(t[1] for t in times), 2)})
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare local static and counterfactual fixture rewards.")
    parser.add_argument("trace", type=Path, nargs="?")
    parser.add_argument("--suite", action="store_true")
    parser.add_argument("--examples", type=Path, default=Path("examples"))
    parser.add_argument("--repetitions", type=int, choices=range(1, 11), default=3)
    args = parser.parse_args()
    if args.suite == bool(args.trace):
        parser.error("provide either a trace or --suite")
    with TemporaryDirectory(prefix="elt-counterfactual-") as workspace:
        config = EpisodeConfig(Path(workspace))
        if args.suite:
            print(json.dumps(run_suite(args.examples, config, args.repetitions), indent=2))
            return 0
        static, changed = compare(args.trace.read_text(encoding="utf-8"), config)
    passed = static.reward == changed.reward == 1
    print(json.dumps({"static_reward": static.reward, "changed_input_reward": changed.reward, "passes_both": passed}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
