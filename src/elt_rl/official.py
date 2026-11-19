"""Run the pinned official books task against Airbyte and Snowflake."""

import ast
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

from .airbyte import GROUPS, AirbyteRun, private_environment, select_streams, streams, terraform_plan
from .contracts import EpisodeConfig, Grade, PipelineError, Stage, TaskDefinition, WarehouseBackend

BENCH_SHA = "3b068d5f15f64541d05fbc33a817e4b08c6bf173"
MODELS = ("publishers", "customers", "authors")
CREDENTIAL_FIELDS = ("account", "host", "user", "password", "role", "warehouse")


@dataclass(frozen=True)
class OfficialConfig:
    checkout: Path
    books_input: Path
    ground_truth: Path
    credential_file: Path
    airbyte_url: str
    terraform: str
    report_dir: Path
    service_timeout: int = 120

    @classmethod
    def from_environment(cls, report_dir: Path) -> "OfficialConfig":
        names = ("ELT_BENCH_ROOT", "ELT_BOOKS_INPUT_DIR", "ELT_GT_SNOWFLAKE",
                 "ELT_SNOWFLAKE_CREDENTIAL_JSON", "ELT_AIRBYTE_URL")
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ValueError("set " + ", ".join(missing))
        paths = [Path(os.environ[name]).expanduser().resolve() for name in names[:4]]
        return cls(*paths, os.environ[names[4]], os.environ.get("ELT_TERRAFORM") or "terraform", report_dir)


def _read_yaml(path: Path) -> dict:
    import yaml
    with path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML mapping in {path.name}")
    return data


def _pinned(config: OfficialConfig) -> None:
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(config.checkout), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL, timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        raise ValueError("ELT_BENCH_ROOT must be a Git checkout") from None
    if sha != BENCH_SHA:
        raise ValueError(f"ELT_BENCH_ROOT must be on {BENCH_SHA}")


def _source_sections(root: Path, public_config: dict) -> dict[str, str]:
    sections = {}
    for group, tables in streams(public_config).items():
        lines = []
        for name in tables:
            with (root / "elt-bench" / "schemas" / "books" / f"{name}.csv").open(
                encoding="utf-8-sig", newline="",
            ) as file:
                fields = [item["column_name"].strip() for item in csv.DictReader(file)]
            lines.append(f"{name}({', '.join(fields)})")
        sections[group] = "\n".join(lines)
    model = _read_yaml(root / "elt-bench" / "snowflake" / "books" / "data_model.yaml")
    for output in model["models"]:
        lines = [output["description"]]
        lines.extend(f"{column['name']}: {column['description']}" for column in output["columns"])
        sections[output["name"]] = "\n".join(lines)
    return sections


def _pack_grade(results_log: str, stage2: dict | None, raw_tables: frozenset[str]) -> Grade:
    lines = [line for line in results_log.splitlines()
             if line.startswith(("Success: books ", "Error: books "))]
    if len(lines) != 1:
        raise ValueError("official Stage 1 did not return exactly one books verdict")
    line = lines[0]
    if line.startswith("Success:"):
        if stage2 is None or not isinstance(stage2.get("books"), dict):
            raise ValueError("official Stage 2 results are missing")
        models = stage2["books"]
        matched = sum(models.get(name, {}).get("match") is True for name in MODELS)
        return Grade(1, matched / len(MODELS), True, True)
    match = re.search(r"Successful table:\s*(\[[^\]]*\])", line)
    if match is None:
        raise ValueError("could not parse official Stage 1 partial results")
    passed = set(ast.literal_eval(match.group(1)))
    if not passed <= raw_tables:
        raise ValueError("official Stage 1 returned unknown stream names")
    return Grade(len(passed) / len(raw_tables), 0, False, True)


class SnowflakeBooksBackend:
    def __init__(self, directory: Path, episode: EpisodeConfig, config: OfficialConfig,
                 bundle: dict, credentials: dict, raw_tables: frozenset[str]):
        self.directory = directory
        self.config = config
        self.bundle = bundle
        self.credentials = credentials
        self.raw_tables = raw_tables
        self.database = "ELT_RL_" + uuid.uuid4().hex.upper()
        self.query_timeout = max(1, int(episode.execution_seconds))
        self.airbyte: AirbyteRun | None = None
        self.created = False
        self.load_attempts = 0
        self.transform_attempts = 0
        self.report = config.report_dir / self.database
        self.report.mkdir(parents=True, mode=0o700)

    def _connection_options(self) -> dict:
        return {
            **{name: self.credentials[name] for name in CREDENTIAL_FIELDS},
            "login_timeout": 15, "network_timeout": self.query_timeout,
            "session_parameters": {"STATEMENT_TIMEOUT_IN_SECONDS": self.query_timeout,
                                   "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": self.query_timeout,
                                   "QUERY_TAG": self.database},
        }

    def _run_sql(self, statements: list[str]):
        import snowflake.connector
        try:
            with closing(snowflake.connector.connect(**self._connection_options())) as connection:
                with closing(connection.cursor()) as cursor:
                    for statement in statements:
                        cursor.execute(statement, timeout=self.query_timeout, num_statements=1)
                    return cursor.fetchall()
        except snowflake.connector.errors.Error as error:
            # Syntax/identifier errors are repairable. Never echo connector config or raw errors.
            state = error.sqlstate or ""
            if not re.fullmatch(r"[A-Z0-9]{5}", state):
                state = "unknown"
            detail = ""
            if state.startswith("42") and isinstance(error.msg, str):
                match = re.search(r"(invalid identifier '[A-Z0-9_.$]+'|unexpected '[A-Z0-9_.$]+'|line \d+ at position \d+)",
                                  error.msg, re.IGNORECASE)
                if match:
                    detail = ": " + match.group(0)
            raise PipelineError(f"Snowflake query failed (SQLSTATE {state}){detail}") from None

    def execute(self, stage: Stage, artifacts: Mapping[str, str]) -> str:
        if stage == "load":
            selected = select_streams(artifacts["load.json"], streams(self.bundle))
            if self.load_attempts >= 2:
                raise PipelineError("official load attempt limit reached")
            self.load_attempts += 1
            self._load(selected)
            return "Airbyte load finished. " + self.inspect()
        from .official_sql import safe_select
        models = {name: safe_select(artifacts[f"{name}.sql"], self.raw_tables) for name in MODELS}
        if self.transform_attempts >= 4:
            raise PipelineError("official transform attempt limit reached")
        self.transform_attempts += 1
        self._run_sql([
            f"USE DATABASE {self.database}", "USE SCHEMA BOOKS",
            *(f"CREATE OR REPLACE TABLE {self.database}.BOOKS.{name} AS {sql}"
              for name, sql in models.items()),
        ])
        return "Snowflake transform finished. " + self.inspect()

    def _load(self, selected: dict[str, list[str]]) -> None:
        if self.airbyte or self.created:
            self._clear()
        prefix = self.directory / f"airbyte-{uuid.uuid4().hex}"
        plan = terraform_plan(self.bundle, selected, self.database, self.credentials, self.config.airbyte_url)
        self._run_sql([f"CREATE TRANSIENT DATABASE {self.database}"])
        self.created = True
        self._run_sql([f"CREATE SCHEMA {self.database}.BOOKS"])
        self.airbyte = AirbyteRun(prefix, self.config.terraform, self.config.airbyte_url, self.config.service_timeout)
        try:
            airbyte_auth = self.bundle["Airbyte"]["config"]
            self.airbyte.provision(self.config.checkout / "setup" / "main.tf", plan,
                                   airbyte_auth["username"], airbyte_auth["password"])
        finally:
            (self.report / "airbyte-jobs.json").write_text(json.dumps(self.airbyte.jobs), encoding="utf-8")

    def inspect(self) -> str:
        if not self.created:
            return "(empty warehouse)"
        rows = self._run_sql([
            f"SELECT TABLE_NAME, ROW_COUNT FROM {self.database}.INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = 'BOOKS' AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME"
        ])
        allowed = self.raw_tables | set(MODELS)
        return ", ".join(f"{name.lower()}={count}" for name, count in rows if name.lower() in allowed) or "(empty warehouse)"

    def _clear(self) -> None:
        if self.airbyte:
            self.airbyte.cleanup()
            self.airbyte = None
        if self.created:
            self._run_sql([f"DROP DATABASE IF EXISTS {self.database}"])
            self.created = False

    def close(self) -> None:
        try:
            self._clear()
        except PipelineError:
            # Preserve only this failed run's private IaC state for manual recovery.
            if self.airbyte and self.airbyte.directory.is_dir():
                shutil.copytree(self.airbyte.directory, self.report / "private-recovery",
                                ignore=shutil.ignore_patterns(".terraform"), dirs_exist_ok=True)
            (self.report / "cleanup-required.txt").write_text(
                f"Review owned Airbyte resources and Snowflake database {self.database}. "
                "Keep private-recovery confidential.\n", encoding="utf-8",
            )

    def evaluate(self) -> Grade:
        root = self.config.checkout / "evaluation"
        cwd = self.directory / "official-evaluation"
        cwd.mkdir()
        for name in ("eva.py", "eva_stage1.py", "eva_stage2.py", "db_connectors.py",
                     "table.json", "sort_key.json"):
            shutil.copyfile(root / name, cwd / name)
        shutil.copytree(root / "sql" / "books", cwd / "sql" / "books")
        credential = cwd / "credential.json"
        credential.write_text(json.dumps(self._connection_options()), encoding="utf-8")
        try:
            subprocess.run([
                sys.executable, "eva.py", "--folder", "graded", "--db-type", "snowflake",
                "--database", self.database, "--only", "books", "--credential", str(credential.resolve()),
                "--gt-folder", str(self.config.ground_truth),
            ], cwd=cwd, env=private_environment(), timeout=self.config.service_timeout,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except (OSError, subprocess.SubprocessError):
            raise PipelineError("official evaluator failed or timed out") from None
        finally:
            credential.unlink(missing_ok=True)
        files = cwd / "agent_results" / "graded"
        stage1 = (files / "results.log").read_text(encoding="utf-8")
        (self.report / "results.log").write_text(stage1, encoding="utf-8")
        stage2_file = files / "stage2.json"
        stage2 = json.loads(stage2_file.read_text(encoding="utf-8")) if stage2_file.exists() else None
        grade = _pack_grade(stage1, stage2, self.raw_tables)
        if stage2 is not None:
            # Upstream error strings can contain statements and connection details.
            for result in stage2["books"].values():
                if "error" in result:
                    result["error"] = "see official evaluator diagnostics on the private host"
            (self.report / "stage2.json").write_text(json.dumps(stage2, indent=2), encoding="utf-8")
        (self.report / "grade.json").write_text(
            json.dumps({"task": "books", "database": self.database,
                        "reward": grade.reward, **grade.metrics()}, indent=2), encoding="utf-8",
        )
        return grade


def _verify(backend: WarehouseBackend) -> Grade:
    if not isinstance(backend, SnowflakeBooksBackend):
        raise TypeError("official task requires Snowflake")
    return backend.evaluate()


def snowflake_task(config: OfficialConfig, *, allow_paid: bool = False) -> TaskDefinition:
    if not allow_paid:
        raise ValueError("official execution requires explicit paid-service approval")
    _pinned(config)
    endpoint = urlsplit(config.airbyte_url)
    if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username or
        endpoint.password or endpoint.query or endpoint.fragment or
        endpoint.path.rstrip("/") != "/api/public/v1" or endpoint.hostname.endswith("airbyte.com") or
        (endpoint.scheme == "http" and endpoint.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ValueError("ELT_AIRBYTE_URL must be a self-hosted Airbyte public API base URL")
    if not shutil.which(config.terraform):
        raise ValueError("Terraform executable was not found")
    public_root = config.checkout / "elt-bench" / "snowflake" / "books"
    public = _read_yaml(public_root / "config.yaml")
    bundle = _read_yaml(config.books_input / "config.yaml")
    available = streams(public)
    if streams(bundle) != available:
        raise ValueError("generated input stream manifest differs from the pinned books task")
    airbyte = bundle["Airbyte"]["config"]
    if not all(airbyte.get(field) for field in ("username", "password", "workspace_id", "custom_api_definition_id")):
        raise ValueError("official generated books input is missing Airbyte credentials or definition ID")
    credentials = json.loads(config.credential_file.read_text(encoding="utf-8"))
    if not isinstance(credentials, dict) or any(not isinstance(credentials.get(key), str)
                                               or not credentials[key] for key in CREDENTIAL_FIELDS):
        raise ValueError("Snowflake credential JSON requires " + ", ".join(CREDENTIAL_FIELDS))
    if any(not (config.ground_truth / "books" / f"{name}.csv").is_file() for name in MODELS):
        raise ValueError("ELT_GT_SNOWFLAKE must contain official books ground truth CSVs")
    instructions = (
        "Official ELT-Bench Snowflake task: books. Configure load.json as "
        '{"sources":{"postgres":["address"]}} using the source groups below. '
        "Select every required stream for a complete load. Run the load stage. "
        "Read the model sections, then write publishers.sql, customers.sql and authors.sql "
        "as one Snowflake SELECT each using unqualified raw table names. Ordinary SQL joins, "
        "aggregates, CTEs and window functions are allowed. The host materializes the SELECTs. "
        "Run the transform stage, use the warehouse feedback to repair errors, and submit.\n"
        + "\n".join(f"{name}: {', '.join(available[name])}" for name in GROUPS)
    )
    raw_tables = frozenset(name for group in available.values() for name in group)
    return TaskDefinition(
        "books", instructions, ("load.json",), tuple(f"{name}.sql" for name in MODELS),
        partial(SnowflakeBooksBackend, config=config, bundle=bundle, credentials=credentials, raw_tables=raw_tables),
        _verify, _source_sections(config.checkout, public),
    )
