import json
from math import isclose
from pathlib import Path
from typing import Protocol

from .contracts import Grade


class FixtureReader(Protocol):
    def count(self, table: str) -> int | None: ...
    def rows(self, table: str) -> tuple[tuple[str, ...], list[tuple]]: ...


def _cell_matches(actual: object, expected: object) -> bool:
    if isinstance(expected, float):
        return type(actual) in (int, float) and isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-8)
    return type(actual) is type(expected) and actual == expected


def _matches(actual: list[tuple], expected: list[list], key_index: int) -> bool:
    if len(actual) != len(expected):
        return False
    # Exact key types and uniqueness keep rows aligned even when query order differs.
    actual_by_key = {(type(row[key_index]), row[key_index]): row for row in actual}
    if len(actual_by_key) != len(expected):
        return False
    for gold_row in expected:
        key = gold_row[key_index]
        actual_row = actual_by_key.get((type(key), key))
        if actual_row is None or len(actual_row) != len(gold_row):
            return False
        if not all(_cell_matches(value, gold) for value, gold in zip(actual_row, gold_row)):
            return False
    return True


def verify_fixture(warehouse: FixtureReader, gold_path: Path) -> Grade:
    """Read host-only targets and grade the freshly replayed warehouse."""
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    raw = gold["raw_counts"]
    stage1 = sum(warehouse.count(table) == count for table, count in raw.items()) / len(raw)
    if stage1 != 1:
        return Grade(stage1=stage1, submitted=True)

    models = gold["models"]
    matched = 0
    for table, target in models.items():
        if warehouse.count(table) is None:
            continue
        columns, rows = warehouse.rows(table)
        if columns == tuple(target["columns"]) and _matches(rows, target["rows"], target["key_index"]):
            matched += 1
    return Grade(stage1, matched / len(models), stage2_ran=True, submitted=True)
