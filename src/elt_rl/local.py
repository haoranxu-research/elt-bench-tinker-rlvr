import csv
import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from time import monotonic

from .contracts import EpisodeConfig, Grade, PipelineError, Stage, TaskDefinition, WarehouseBackend
from .verifier import verify_fixture

FIXTURE = Path(__file__).with_name("fixture")
SOURCES = {
    "customers.csv": ("raw_customers", ("customer_id", "name"), (int, str)),
    "orders.csv": ("raw_orders", ("order_id", "customer_id", "amount"), (int, int, float)),
}
MODELS = {
    "customer_totals.sql": ("customer_totals", ("customer_id", "name", "order_count", "total_amount")),
    "order_totals.sql": ("order_totals", ("order_count", "average_amount")),
}
SQL_FUNCTIONS = {
    "abs", "avg", "cast", "coalesce", "count", "ifnull", "length", "lower",
    "max", "min", "nullif", "round", "substr", "sum", "total", "trim", "upper",
}
MAX_RESULT_ROWS = 256


class SQLiteBackend:
    def __init__(self, workspace: Path, config: EpisodeConfig):
        self.db = sqlite3.connect(
            workspace / "warehouse.sqlite", timeout=config.execution_seconds, cached_statements=0,
            check_same_thread=False,
        )
        self.seconds = config.execution_seconds
        self.raw_tables = {source[0] for source in SOURCES.values()}
        self.db.executescript("""
            PRAGMA trusted_schema = OFF;
            PRAGMA journal_mode = DELETE;
            PRAGMA temp_store = MEMORY;
            PRAGMA max_page_count = 1024;
        """)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 16_384)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 40)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 12)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 32)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH, 512)

    def close(self) -> None:
        self.db.close()

    def execute(self, stage: Stage, artifacts: Mapping[str, str]) -> str:
        try:
            if stage == "load":
                self._load(artifacts["load.json"])
                return "load finished. " + self.inspect()
            self._transform(artifacts)
            return "transform finished. " + self.inspect()
        except sqlite3.Error as exc:
            if getattr(exc, "sqlite_errorname", "") == "SQLITE_INTERRUPT":
                raise PipelineError("SQL execution budget exceeded") from None
            raise PipelineError(f"SQLite: {exc}") from None

    def _load(self, config_text: str) -> None:
        try:
            config = json.loads(config_text)
        except (ValueError, RecursionError):
            raise PipelineError("load.json must contain valid JSON") from None
        if not isinstance(config, dict) or set(config) != {"sources"}:
            raise PipelineError("load.json must be an object with a sources field")
        sources = config["sources"]
        if not isinstance(sources, dict) or not sources or not sources.keys() <= SOURCES.keys():
            raise PipelineError("sources must map approved source names to a row limit or null")
        if any(value is not None and (type(value) is not int or not 0 <= value <= 256)
               for value in sources.values()):
            raise PipelineError("row limits must be null or an integer between 0 and 256")

        with self.db:
            self.db.execute("BEGIN")
            # Only names from the host manifest are interpolated into statements.
            for table in sorted(self.raw_tables | {model[0] for model in MODELS.values()}):
                self.db.execute(f"DROP TABLE IF EXISTS {table}")
            for filename, limit in sources.items():
                table, columns, converters = SOURCES[filename]
                types = {int: "INTEGER", str: "TEXT", float: "REAL"}
                definitions = ", ".join(
                    f"{column} {types[converter]}" for column, converter in zip(columns, converters)
                )
                self.db.execute(f"CREATE TABLE {table} ({definitions})")
                with (FIXTURE / filename).open(encoding="utf-8", newline="") as stream:
                    reader = csv.reader(stream)
                    if tuple(next(reader)) != columns:
                        raise RuntimeError("fixture source header differs from the trusted manifest")
                    rows = [
                        tuple(convert(value) if value else None for value, convert in zip(row, converters, strict=True))
                        for row in reader
                    ][:limit]
                placeholders = ", ".join("?" for _ in columns)
                self.db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)

    def _transform(self, artifacts: Mapping[str, str]) -> None:
        with self.db:
            self.db.execute("BEGIN")
            for filename, (table, columns) in MODELS.items():
                try:
                    rows = self._select(artifacts[filename], columns)
                except (sqlite3.Error, PipelineError) as exc:
                    if getattr(exc, "sqlite_errorname", "") == "SQLITE_INTERRUPT":
                        raise
                    raise PipelineError(f"{filename}: {exc}") from None
                self.db.execute(f"DROP TABLE IF EXISTS {table}")
                self.db.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
                placeholders = ", ".join("?" for _ in columns)
                self.db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)

    def _select(self, sql: str, columns: tuple[str, ...]) -> list[tuple]:
        read_raw = False

        def authorize(action: int, first: str | None, second: str | None,
                      schema: str | None, origin: str | None) -> int:
            nonlocal read_raw
            if action == sqlite3.SQLITE_READ and first in self.raw_tables and schema in ("main", None):
                read_raw = True
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and second in SQL_FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        deadline = monotonic() + self.seconds
        instructions = 0

        def interrupted() -> int:
            nonlocal instructions
            instructions += 1_000
            return int(monotonic() >= deadline or instructions >= 500_000)

        self.db.set_authorizer(authorize)
        self.db.set_progress_handler(interrupted, 1_000)
        try:
            with closing(self.db.execute(sql)) as cursor:
                if not read_raw:
                    raise PipelineError("the SELECT must read loaded source tables")
                actual = tuple(column[0].lower() for column in cursor.description or ())
                if actual != columns:
                    raise PipelineError(f"expected SELECT columns {', '.join(columns)}")
                rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
                if len(rows) > MAX_RESULT_ROWS:
                    raise PipelineError("transform exceeds result row limit")
                return rows
        finally:
            self.db.set_progress_handler(None, 0)
            self.db.set_authorizer(None)

    def inspect(self) -> str:
        tables = self.db.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' ORDER BY name"
        ).fetchall()
        counts = [f"{name}={self.db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]}"
                  for (name,) in tables]
        return ", ".join(counts) or "(empty warehouse)"

    def count(self, table: str) -> int | None:
        exists = self.db.execute(
            "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        return self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] if exists else None

    def rows(self, table: str) -> tuple[tuple[str, ...], list[tuple]]:
        cursor = self.db.execute(f"SELECT * FROM {table}")
        return tuple(column[0] for column in cursor.description), cursor.fetchall()


def local_task() -> TaskDefinition:
    def verify(backend: WarehouseBackend) -> Grade:
        if not isinstance(backend, SQLiteBackend):
            raise TypeError("fixture verifier requires the SQLite backend")
        return verify_fixture(backend, FIXTURE / "gold.json")

    return TaskDefinition(
        task_id="customer-orders-local",
        instructions=(FIXTURE / "task.md").read_text(encoding="utf-8"),
        load_artifacts=("load.json",),
        transform_artifacts=tuple(MODELS),
        open_backend=SQLiteBackend,
        verify=verify,
    )
