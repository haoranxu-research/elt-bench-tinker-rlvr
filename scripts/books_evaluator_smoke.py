"""Host-only evaluator smoke. Reference SQL and row data stay outside Git."""

import argparse
import hashlib
import json
import runpy
import shutil
import sys
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from elt_rl.airbyte import streams
from elt_rl.contracts import EpisodeConfig, Grade
from elt_rl.official import (
    BENCH_SHA, EVALUATOR_FILES, MODELS, OfficialConfig, _pack_grade, check_checkout, snowflake_task,
)
from elt_rl.official_sql import safe_select
from elt_rl.settings import read_settings


REFERENCE_HASHES = {
    "publishers": "a9b2d1ace59c594f7696d66f23f2eecb02b8eccd71f4e7eebc50ee839296f906",
    "customers": "4042eeb5b38df4e93dfc93c0ff203e2a79f7aa586d649b378b4535e1fec39f71",
    "authors": "1221bea8c2d1d7d4b129c032ed7f18970b6a0dae878033fdc595611f9e53aef9",
}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reference_identity(sql_dir, ground_truth):
    refs = {name: sha256(ground_truth / "books" / f"{name}.csv") for name in MODELS}
    if refs != REFERENCE_HASHES:
        raise ValueError("reference CSVs do not match the pinned published Snowflake books dataset")
    return {
        "benchmark_sha": BENCH_SHA,
        "sql_sha256": {name: sha256(sql_dir / f"{name}.sql") for name in MODELS},
        "references_sha256": refs,
    }


def result_fields(grade):
    return {"stage1": grade.stage1, "stage2": grade.stage2, "stage2_ran": grade.stage2_ran,
            "evaluator_score": grade.reward}


def save_result(out, report):
    encoded = json.dumps(report, indent=2)
    (out / "result.json").write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


def load_local_inputs(connection, assets, tables, *, book_publication_date_text=False):
    connection.execute('CREATE SCHEMA "BOOKS"')
    for table in tables:
        if table == "address_status":
            source = connection.read_json(str(assets / "flat-files/address_status.jsonl"))
        else:
            path = next(path for folder in ("flat-files", "data-api/data/books", "data-db/data/books")
                        if (path := assets / folder / f"{table}.csv").is_file())
            # Airbyte delivered this CSV field as TEXT to Snowflake. Override
            # inference at ingestion so the original strings survive unaltered.
            options = {"dtype": {"publication_date": "VARCHAR"}} if table == "book" and book_publication_date_text else {}
            source = connection.read_csv(str(path), header=True, **options)
        source.create(f"books.{table}")
    connection.execute("SET schema = 'BOOKS'")


def check_local_database(connection, assets, expected, queries):
    load_local_inputs(connection, assets, expected)
    for name, query in queries.items():
        connection.execute(f"CREATE TABLE books.{name} AS {query}")


def evaluate_local(connection, checkout, ground_truth, out, label, expected):
    """Run the pinned entry point and connector with only Snowflake wire I/O replaced."""
    import snowflake.connector

    cwd = out / label
    cwd.mkdir()
    source = checkout / "evaluation"
    for name in EVALUATOR_FILES:
        shutil.copyfile(source / name, cwd / name)
    shutil.copytree(source / "sql/books", cwd / "sql/books")

    class Cursor:
        def __init__(self):
            self.cursor = connection.cursor()

        def execute(self, sql):
            statements.append(sql)
            self.cursor.execute(sql.replace("memory.information_schema.", "information_schema."))

        @property
        def description(self):
            return self.cursor.description

        def fetchall(self):
            return self.cursor.fetchall()

        def close(self):
            self.cursor.close()

    class LocalWire:
        def cursor(self):
            return Cursor()

        def close(self):
            pass  # The host owns the database across both independent evaluator invocations.

    statements = []
    credential = cwd / "credential.json"
    credential.write_text("{}", encoding="utf-8")
    script = cwd / "eva.py"
    argv = [str(script), "--folder", "graded", "--db-type", "snowflake", "--database", "memory",
            "--only", "books", "--credential", str(credential), "--gt-folder", str(ground_truth)]
    module_names = ("db_connectors", "eva_stage1", "eva_stage2")
    try:
        with (chdir(cwd), patch.object(sys, "argv", argv), patch.object(sys, "path", [str(cwd), *sys.path]),
              patch.object(snowflake.connector, "connect", return_value=LocalWire())):
            runpy.run_path(str(script), run_name="__main__")
    finally:
        credential.unlink(missing_ok=True)
        for name in module_names:
            sys.modules.pop(name, None)

    results = cwd / "agent_results/graded"
    counts = (results / "results.log").read_text(encoding="utf-8")
    stage2_file = results / "stage2.json"
    stage2 = json.loads(stage2_file.read_bytes()) if stage2_file.exists() else None
    return _pack_grade(counts, stage2, frozenset(expected)), {
        "count_queries": sum(statement.startswith("SELECT COUNT(*)") for statement in statements),
        "model_queries": sum(statement.startswith("SELECT * FROM memory.books.") for statement in statements),
    }


def offline(args, artifacts):
    import duckdb
    from sqlglot import transpile

    checkout = args.checkout.resolve()
    assets = args.assets.resolve()
    ground_truth = assets / "gt_snowflake"
    check_checkout(checkout)
    expected = json.loads((checkout / "evaluation/table.json").read_bytes())["books"]
    queries = {
        name: transpile(safe_select(artifacts[f"{name}.sql"], frozenset(expected)),
                        read="snowflake", write="duckdb")[0]
        for name in MODELS
    }
    identity = reference_identity(args.sql_dir, ground_truth)
    args.out.mkdir(parents=True)
    with duckdb.connect() as connection:
        check_local_database(connection, assets, expected, queries)
        positive, positive_queries = evaluate_local(connection, checkout, ground_truth, args.out, "matched", expected)
        connection.execute("DROP TABLE books.authors")
        partial, partial_queries = evaluate_local(connection, checkout, ground_truth, args.out, "partial", expected)
        connection.execute("DELETE FROM books.address_status WHERE status_id = (SELECT MIN(status_id) FROM books.address_status)")
        negative, negative_queries = evaluate_local(connection, checkout, ground_truth, args.out, "stage1-fail", expected)
    passed = (positive == Grade(1, 1, True, True) and positive_queries == {"count_queries": 15, "model_queries": 3}
              and partial == Grade(1, 2 / 3, True, True)
              and partial_queries == {"count_queries": 15, "model_queries": 3}
              and negative == Grade(14 / 15, 0, False, True)
              and negative_queries == {"count_queries": 15, "model_queries": 0})
    save_result(args.out, {
        "kind": "host_reference", "warehouse": "duckdb_transport", "passed": passed, **identity,
        "matched": {**result_fields(positive), **positive_queries},
        "partial": {**result_fields(partial), **partial_queries},
        "stage1_fail": {**result_fields(negative), **negative_queries},
    })
    return 0 if passed else 2


def live(args, artifacts):
    settings = read_settings(args.env_file)
    config = OfficialConfig.from_environment(args.out / "official", settings)
    verification = json.loads(args.verification.read_bytes())
    identity = reference_identity(args.sql_dir, config.ground_truth)
    if (verification.get("kind"), verification.get("warehouse"), verification.get("passed")) != (
        "host_reference", "duckdb_transport", True
    ) or any(verification.get(key) != value for key, value in identity.items()):
        raise ValueError("run offline verification on the exact reference SQL and ground truth first")
    task = snowflake_task(config, allow_paid=True)
    expected = json.loads((config.checkout / "evaluation/table.json").read_bytes())["books"]
    for name in MODELS:
        safe_select(artifacts[f"{name}.sql"], frozenset(expected))
    args.out.mkdir(parents=True)
    with TemporaryDirectory(prefix="books-evaluator-reference-", dir=args.out) as directory:
        path = Path(directory)
        backend = task.open_backend(path, EpisodeConfig(path, execution_seconds=60))
        try:
            backend.execute("load", {"load.json": json.dumps({"sources": streams(backend.bundle)})})
            backend.execute("transform", artifacts)
            grade = backend.evaluate()
        finally:
            backend.close()
    passed = grade == Grade(1, 1, True, True)
    save_result(args.out, {"kind": "host_reference", "warehouse": "snowflake", "passed": passed,
                           **identity, **result_fields(grade), "cleanup": "complete"})
    return 0 if passed else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("offline", "snowflake"))
    parser.add_argument("--sql-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--verification", type=Path)
    parser.add_argument("--allow-warehouse", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    if args.mode == "offline" and (args.checkout is None or args.assets is None):
        parser.error("offline requires --checkout and --assets")
    if args.mode == "snowflake" and not (args.allow_warehouse and args.verification):
        parser.error("Snowflake requires separate authorization, --allow-warehouse and --verification")
    args.out = args.out.resolve()
    if args.out.exists():
        parser.error("--out must be a new private directory")
    artifacts = {f"{name}.sql": (args.sql_dir / f"{name}.sql").read_text(encoding="utf-8") for name in MODELS}
    if args.mode == "offline":
        return offline(args, artifacts)
    try:
        return live(args, artifacts)
    except Exception as error:
        print(f"Reference run stopped ({type(error).__name__}). Check the private output and cleanup markers.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
