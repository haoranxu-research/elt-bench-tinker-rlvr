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
from .settings import OFFICIAL_NAMES, ConfigurationError

BENCH_SHA = "3b068d5f15f64541d05fbc33a817e4b08c6bf173"
MODELS = ("publishers", "customers", "authors")
CREDENTIAL_FIELDS = ("account", "host", "user", "password", "role", "warehouse")
CONNECTION_FIELDS = ("account", "host", "user", "role", "warehouse")
AIRBYTE_BINDINGS = ("username", "password", "workspace_id", "custom_api_definition_id")
EVALUATOR_FILES = ("eva.py", "eva_stage1.py", "eva_stage2.py", "db_connectors.py",
                   "table.json", "sort_key.json")
PINNED_PATHS = ("setup/main.tf", "evaluation/sql/books", "elt-bench/snowflake/books",
                "elt-bench/schemas/books", *(f"evaluation/{name}" for name in EVALUATOR_FILES))


@dataclass(frozen=True)
class OfficialConfig:
    checkout: Path
    books_input: Path
    ground_truth: Path
    credential_file: Path
    airbyte_url: str
    terraform: str
    report_dir: Path
    # The verified local sync took 339 seconds, including queue and startup time.
    service_timeout: int = 600

    @classmethod
    def from_environment(cls, report_dir: Path, settings: Mapping[str, str] = os.environ) -> "OfficialConfig":
        missing = [name for name in OFFICIAL_NAMES if not settings.get(name)]
        if missing:
            raise ConfigurationError("set " + ", ".join(missing))
        paths = [Path(settings[name]).expanduser().resolve() for name in OFFICIAL_NAMES[:4]]
        return cls(*paths, settings[OFFICIAL_NAMES[4]], settings.get("ELT_TERRAFORM") or "terraform", report_dir)


def _read_yaml(path: Path) -> dict:
    import yaml
    with path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML mapping in {path.name}")
    return data


def check_checkout(root: Path, *, extra_paths: tuple[str, ...] = ()) -> None:
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL, timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        raise ConfigurationError("ELT_BENCH_ROOT must be a Git checkout") from None
    if sha != BENCH_SHA:
        raise ConfigurationError(f"ELT_BENCH_ROOT must be on {BENCH_SHA}")
    try:
        paths = (*PINNED_PATHS, *extra_paths)
        subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", *paths],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        untracked = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "--others", "--", *paths],
            stderr=subprocess.DEVNULL, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        raise ConfigurationError("restore the pinned evaluator and books task files") from None
    if untracked:
        raise ConfigurationError("remove extra files from the pinned evaluator or task directories")


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
        if any(not isinstance(models.get(name), dict) for name in MODELS):
            raise ValueError("official Stage 2 omitted a required books model")
        matched = sum(models[name].get("status") == "ok" and models[name].get("match") is True
                      for name in MODELS)
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
        self.create_uncertain = False
        self.load_attempts = 0
        self.transform_attempts = 0
        self.report = config.report_dir / self.database
        self.report.mkdir(parents=True, mode=0o700)

    def _connection_options(self) -> dict:
        return {
            **snowflake_connect_options(self.credentials),
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
        if self.create_uncertain:
            raise PipelineError("warehouse create outcome is uncertain; start a new run after operator review")
        if self.airbyte or self.created:
            self._clear()
        prefix = self.directory / f"airbyte-{uuid.uuid4().hex}"
        plan = terraform_plan(self.bundle, selected, self.database, self.credentials, self.config.airbyte_url)
        self.create_uncertain = True
        self._run_sql([f"CREATE TRANSIENT DATABASE {self.database}"])
        self.create_uncertain = False
        self.created = True
        self._run_sql([f"CREATE SCHEMA {self.database}.BOOKS"])
        self.airbyte = AirbyteRun(prefix, self.config.terraform, self.config.airbyte_url, self.config.service_timeout)
        try:
            airbyte_auth = self.bundle["Airbyte"]["config"]
            self.airbyte.provision(self.config.checkout / "setup" / "main.tf", plan,
                                   airbyte_auth["username"], airbyte_auth["password"])
        finally:
            (self.report / f"airbyte-jobs-{self.load_attempts}.json").write_text(
                json.dumps(self.airbyte.jobs), encoding="utf-8")

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
            if self.create_uncertain:
                raise PipelineError("warehouse create outcome was ambiguous")
        except PipelineError:
            (self.report / "cleanup-required.txt").write_text(
                f"Review owned Airbyte resources and Snowflake database {self.database}. "
                "Keep private-recovery confidential.\n", encoding="utf-8",
            )
            if self.airbyte and self.airbyte.directory.is_dir():
                shutil.copytree(self.airbyte.directory, self.report / "private-recovery",
                                ignore=shutil.ignore_patterns(".terraform"), dirs_exist_ok=True)
            raise PipelineError("official cleanup requires operator review") from None

    def evaluate(self) -> Grade:
        root = self.config.checkout / "evaluation"
        cwd = self.directory / "official-evaluation"
        cwd.mkdir()
        for name in EVALUATOR_FILES:
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
        try:
            stage1 = (files / "results.log").read_text(encoding="utf-8")
            (self.report / "results.log").write_text(stage1, encoding="utf-8")
            stage2_file = files / "stage2.json"
            stage2 = json.loads(stage2_file.read_text(encoding="utf-8")) if stage2_file.exists() else None
            if stage2 is not None and (not isinstance(stage2, dict) or set(stage2) - {"books"}):
                raise ValueError("unexpected Stage 2 scope")
            models = (stage2 or {}).get("books", {})
            if not isinstance(models, dict) or any(not isinstance(result, dict) for result in models.values()):
                raise ValueError("invalid Stage 2 verdicts")
            grade = _pack_grade(stage1, stage2, self.raw_tables)
        except (OSError, ValueError, SyntaxError, TypeError):
            raise PipelineError("official evaluator returned missing or invalid results") from None
        if stage2 is not None:
            # Upstream error strings can contain statements and connection details.
            for result in models.values():
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


def check_airbyte_url(url: str) -> None:
    endpoint = urlsplit(url)
    if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username or
        endpoint.password or endpoint.query or endpoint.fragment or
        endpoint.path.rstrip("/") != "/api/public/v1" or endpoint.hostname.endswith("airbyte.com") or
        (endpoint.scheme == "http" and endpoint.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise ConfigurationError("use a self-hosted Airbyte public API URL (HTTPS or loopback HTTP)")


def snowflake_connect_options(credentials: dict) -> dict:
    options = {key: credentials[key] for key in CONNECTION_FIELDS}
    if "private_key_file" in credentials:
        options.update(authenticator="SNOWFLAKE_JWT", private_key_file=credentials["private_key_file"])
        if credentials.get("private_key_file_pwd"):
            options["private_key_file_pwd"] = credentials["private_key_file_pwd"]
    else:
        options["password"] = credentials["password"]
    return options


def read_credentials(file: Path) -> dict:
    try:
        credentials = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigurationError("provide a readable Snowflake credential JSON") from None
    if not isinstance(credentials, dict) or any(not isinstance(credentials.get(key), str)
                                               or not credentials[key].strip() for key in CONNECTION_FIELDS):
        raise ConfigurationError("Snowflake credential JSON requires " + ", ".join(CONNECTION_FIELDS))
    if "private_key_file" not in credentials:
        if not isinstance(credentials.get("password"), str) or not credentials["password"].strip():
            raise ConfigurationError("configure private_key_file for the Snowflake service user")
        return credentials
    key_file = credentials["private_key_file"]
    passphrase = credentials.get("private_key_file_pwd")
    if (not isinstance(key_file, str) or not key_file.strip() or
        (passphrase is not None and not isinstance(passphrase, str))):
        raise ConfigurationError("configure private_key_file and its optional text passphrase")
    path = (file.resolve().parent / Path(key_file).expanduser()).resolve()
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

        pem = path.read_bytes()
        if not pem.startswith((b"-----BEGIN PRIVATE KEY-----", b"-----BEGIN ENCRYPTED PRIVATE KEY-----")):
            raise ValueError("expected PKCS#8")
        key = serialization.load_pem_private_key(pem, passphrase.encode("utf-8") if passphrase else None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("expected RSA")
    except (OSError, ValueError, TypeError):
        raise ConfigurationError("Snowflake private_key_file must be a readable RSA PKCS#8 PEM with its correct passphrase") from None
    credentials["private_key_file"] = str(path)
    return credentials


def read_bundle(root: Path) -> dict:
    try:
        bundle = _read_yaml(root / "config.yaml")
        airbyte = bundle["Airbyte"]["config"]
        if not all(isinstance(airbyte.get(field), str) and airbyte[field].strip() for field in AIRBYTE_BINDINGS):
            raise ConfigurationError("bind books inputs with the Airbyte workspace credentials and custom definition ID")
        streams(bundle)
    except (OSError, KeyError, TypeError, AttributeError):
        raise ConfigurationError("generate the official books input bundle with elt_rl.books_setup bind-airbyte") from None
    return bundle


def snowflake_task(config: OfficialConfig, *, allow_paid: bool = False) -> TaskDefinition:
    if not allow_paid:
        raise ConfigurationError("official execution requires explicit paid-service approval")
    check_checkout(config.checkout)
    check_airbyte_url(config.airbyte_url)
    if not shutil.which(config.terraform):
        raise ConfigurationError("install Terraform or set ELT_TERRAFORM to its executable")
    public_root = config.checkout / "elt-bench" / "snowflake" / "books"
    public = _read_yaml(public_root / "config.yaml")
    bound = read_bundle(config.books_input)
    available = streams(public)
    if streams(bound) != available:
        raise ConfigurationError("generated input stream manifest differs from pinned books")
    # Only the local Airbyte workspace binding is variable. Source addresses,
    # connector IDs and the destination namespace come from the verified checkout.
    private = bound["Airbyte"]["config"]
    public["Airbyte"]["config"].update({name: private[name] for name in AIRBYTE_BINDINGS})
    credentials = read_credentials(config.credential_file)
    if any(not (config.ground_truth / "books" / f"{name}.csv").is_file() for name in MODELS):
        raise ConfigurationError("ELT_GT_SNOWFLAKE must contain official books ground truth CSVs")
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
        partial(SnowflakeBooksBackend, config=config, bundle=public, credentials=credentials, raw_tables=raw_tables),
        _verify, _source_sections(config.checkout, public),
    )
