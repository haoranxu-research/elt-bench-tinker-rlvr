"""Run the pinned official books task against Airbyte and Snowflake."""

import ast
import csv
import json
import math
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
from .contracts import (EpisodeConfig, Grade, PartialTransformError, PipelineError, Stage, TaskDefinition,
                        WarehouseBackend, grading_time_left)
from .settings import OFFICIAL_NAMES, ConfigurationError

BENCH_SHA = "3b068d5f15f64541d05fbc33a817e4b08c6bf173"
MODELS = ("publishers", "customers", "authors")
MAX_TRANSFORM_ATTEMPTS = 7  # Three first checks and up to four repairs before submission.
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
    transform_attempt_limit: int = MAX_TRANSFORM_ATTEMPTS

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
                fields = list(csv.DictReader(file))
            lines.append(f"{name}({', '.join(item['column_name'].strip() for item in fields)})")
            for item in fields:
                mapping = re.search(r"maps to (\w+)\s*\(\s*(\w+)\s*\)", item["column_description"], re.IGNORECASE)
                if mapping:
                    lines.append(f"{name}.{item['column_name'].strip()} -> {mapping[1]}." + mapping[2])
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
    transform_attempt_limit = MAX_TRANSFORM_ATTEMPTS
    grading_deadline: float | None = None

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
        self.transform_attempt_limit = config.transform_attempt_limit
        self.report = config.report_dir / self.database
        self.report.mkdir(parents=True, mode=0o700)

    def _connection_options(self) -> dict:
        timeout = math.ceil(grading_time_left(self.grading_deadline, self.query_timeout))
        return {
            **snowflake_connect_options(self.credentials),
            "login_timeout": math.ceil(grading_time_left(self.grading_deadline, 15)), "network_timeout": timeout,
            "session_parameters": {"STATEMENT_TIMEOUT_IN_SECONDS": timeout,
                                   "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": timeout,
                                   "QUERY_TAG": self.database},
        }

    def set_grading_deadline(self, deadline: float) -> None:
        self.grading_deadline = deadline

    def _run_sql(self, statements: list[str], *, artifact_names: Mapping[int, str] | None = None):
        import snowflake.connector
        artifact = None
        tested_files = []
        try:
            with closing(snowflake.connector.connect(**self._connection_options())) as connection:
                with closing(connection.cursor()) as cursor:
                    for index, statement in enumerate(statements):
                        artifact = artifact_names.get(index) if artifact_names else None
                        timeout = math.ceil(grading_time_left(self.grading_deadline, self.query_timeout))
                        cursor.execute(statement, timeout=timeout, num_statements=1)
                        if artifact is not None:
                            tested_files.append(artifact)
                    artifact = None
                    return cursor.fetchall()
        except snowflake.connector.errors.Error as error:
            # Syntax/identifier errors are repairable. Never echo connector config or raw errors.
            state = error.sqlstate or ""
            if not re.fullmatch(r"[A-Z0-9]{5}", state):
                state = "unknown"
            detail = ""
            if state in {"22000", "22007", "22018"} and isinstance(error.msg, str):
                if re.search(r"Function\s+(EXTRACT|DATE_PART|YEAR)\s+does not support\s+(?:VARCHAR|TEXT)",
                             error.msg, re.IGNORECASE):
                    detail = (": a date-part function received text. Check the actual column type and parse the date first. "
                              "Use TRY_TO_DATE with the observed format when the input can be invalid.")
                elif re.search(r"(?:Date|Timestamp) '[^'\r\n]+' is not recognized", error.msg, re.IGNORECASE):
                    detail = ": a date or timestamp conversion failed. Check the input format."
            if state.startswith("42") and isinstance(error.msg, str):
                identifier = re.search(r"(invalid identifier|unexpected) '[A-Z0-9_.$]{1,80}'",
                                       error.msg, re.IGNORECASE)
                location = re.search(r"\bline [0-9]{1,6} at position [0-9]{1,6}\b", error.msg, re.IGNORECASE)
                if identifier:
                    detail += f": {identifier[0]}"
                if location:
                    detail += f" ({'generated statement, ' if artifact else ''}{location[0]})"
            prefix = f"{artifact}: " if artifact else ""
            message = f"{prefix}Snowflake query failed (SQLSTATE {state}){detail}"
            if tested_files:
                raise PartialTransformError(message, tuple(tested_files)) from None
            raise PipelineError(message) from None

    @property
    def remaining_transform_attempts(self) -> int:
        return max(0, self.transform_attempt_limit - self.transform_attempts)

    def execute(self, stage: Stage, artifacts: Mapping[str, str]) -> str:
        if stage == "load":
            selected = select_streams(artifacts["load.json"], streams(self.bundle))
            if self.load_attempts >= 2:
                raise PipelineError("official load attempt limit reached")
            self.load_attempts += 1
            self._load(selected)
            return "Airbyte load finished. " + self.inspect()
        from .official_sql import safe_select
        models = {}
        errors = []
        for name in MODELS:
            filename = f"{name}.sql"
            if filename not in artifacts:
                continue
            try:
                models[name] = safe_select(artifacts[filename], self.raw_tables)
            except PipelineError as error:
                errors.append(f"{filename}: {error}")
        if errors:
            raise PipelineError("Fix the SQL files below before running transform:\n" + "\n".join(errors))
        if not models:
            raise PipelineError("provide at least one saved SQL file")
        if not self.remaining_transform_attempts:
            raise PipelineError("official transform attempt limit reached")
        self.transform_attempts += 1
        self._run_sql([
            f"USE DATABASE {self.database}", "USE SCHEMA BOOKS",
            *(f"CREATE OR REPLACE TABLE {self.database}.BOOKS.{name} AS {sql}"
              for name, sql in models.items()),
        ], artifact_names={index: f"{name}.sql" for index, name in enumerate(models, start=2)})
        return "Snowflake transform finished."

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
        self.airbyte.grading_deadline = self.grading_deadline
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

    def columns(self) -> dict[str, list[str]]:
        if not self.created:
            return {}
        rows = self._run_sql([
            f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM {self.database}.INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = 'BOOKS' ORDER BY TABLE_NAME, ORDINAL_POSITION"
        ])
        return self._column_catalog(rows)

    def _column_catalog(self, rows) -> dict[str, list[str]]:
        tables = {}
        self.temporal_columns = {}
        allowed = self.raw_tables | set(MODELS)
        for table, column, data_type in rows:
            if table.lower() in allowed:
                tables.setdefault(table.lower(), []).append(column.lower())
                if data_type.upper().startswith(("DATE", "TIME")) or column.lower().endswith(("_date", "_time")):
                    self.temporal_columns[table.lower(), column.lower()] = data_type.upper()
        return tables

    def lookup_values(self, table: str, column: str, contains: str) -> list:
        lookup_columns = {
            "book_language": {"language_id", "language_code", "language_name"},
            "shipping_method": {"method_id", "method_name"},
            "country": {"country_id", "country_name"},
        }
        if column not in lookup_columns.get(table, ()):
            raise PipelineError("use a column from book_language, shipping_method, or country")
        if contains and not re.fullmatch(r"[a-zA-Z0-9 .'-]{1,48}", contains):
            raise PipelineError("use up to 48 letters, digits, spaces, or simple punctuation in contains")
        literal = contains.lower().replace("'", "''")
        predicate = f"WHERE LOWER(CAST({column} AS VARCHAR)) LIKE '%{literal}%'" if literal else ""
        query = f"SELECT DISTINCT {column} FROM {self.database}.BOOKS.{table} {predicate} ORDER BY 1 LIMIT 30"
        return [row[0] for row in self._lookup_rows(query)]

    def _lookup_rows(self, query: str):
        return self._run_sql([query])

    def source_labels(self, materialized: dict[str, list[str]]) -> dict:
        fields = {"book_language": ("language_code", "language_name"), "shipping_method": ("method_name",)}
        return {table: self._lookup_rows(
            f"SELECT DISTINCT {', '.join(columns)} FROM {self.database}.BOOKS.{table} ORDER BY 1 LIMIT 30"
        ) for table, columns in fields.items() if set(columns) <= set(materialized.get(table, ()))}

    def output_shape(self, model: str, expected: tuple[str, ...]) -> str | None:
        catalog = self.columns()
        fields = set(catalog.get(model, ()))
        missing = set(expected) - fields
        extra = fields - set(expected)
        if missing or extra:
            return f"columns missing {sorted(missing)}, unexpected {sorted(extra)}"
        source = model.removesuffix("s")
        key = expected[0]
        if key not in catalog.get(source, ()):
            return None
        name = f"{self.database}.BOOKS."
        rows, distinct_ids, source_rows, missing_ids = self._lookup_rows(
            f"SELECT COUNT(*), COUNT(DISTINCT {key}), "
            f"(SELECT COUNT(*) FROM {name}{source}), "
            f"(SELECT COUNT(*) FROM {name}{source} s WHERE NOT EXISTS "
            f"(SELECT 1 FROM {name}{model} o WHERE o.{key} = s.{key})) FROM {name}{model}"
        )[0]
        if rows == distinct_ids == source_rows and missing_ids == 0:
            return None
        return (f"expected one row per source {key}. Output has {rows} rows and {distinct_ids} distinct IDs "
                f"against {source_rows} source rows, with {missing_ids} source IDs missing. "
                "Check the grain of each CTE and join.")

    def author_page_check(self, sources: dict[str, list[str]]) -> str | None:
        required = {"book": {"book_id", "num_pages"}, "book_author": {"author_id", "book_id"}}
        if not all(columns <= set(sources.get(table, ())) for table, columns in required.items()):
            return None
        # With nonnegative page counts and at least one positive authored book,
        # authors with no book relationship are necessarily below the average.
        schema = f"{self.database}.BOOKS."
        flag = "CAST(o.wrote_fewer_total_pages_than_the_average AS VARCHAR)"
        (failures, defined_rates), = self._lookup_rows(
            f"WITH unlinked AS (SELECT o.* FROM {schema}authors o WHERE NOT EXISTS "
            f"(SELECT 1 FROM {schema}book_author ba WHERE ba.author_id = o.author_id)) "
            f"SELECT (SELECT COUNT(*) FROM unlinked o WHERE COALESCE(TRY_CAST({flag} AS DOUBLE), 0) <> 1 "
            f"AND LOWER(COALESCE({flag}, '')) <> 'true' "
            f"AND EXISTS (SELECT 1 FROM {schema}book b JOIN {schema}book_author ba "
            "ON b.book_id = ba.book_id WHERE b.num_pages > 0) "
            f"AND NOT EXISTS (SELECT 1 FROM {schema}book WHERE num_pages < 0)), "
            "(SELECT COUNT(per_book_published_1992) FROM unlinked)"
        )
        notes = []
        if failures:
            notes.append(f"{failures} authors with no related books are marked as not below the page average. "
                         "Their page total is zero and some authors have positive page totals. "
                         "Check the preserved author key, the input population of the average, and the final comparison.")
        if defined_rates:
            notes.append(f"{defined_rates} authors with no related books have a defined 1992 publication rate. "
                         "The denominator is zero for those authors, so the rate is undefined.")
        return " ".join(notes) or None

    def customer_rate_check(self, sources: dict[str, list[str]]) -> str | None:
        required = {"cust_order": {"customer_id", "shipping_method_id"},
                    "shipping_method": {"method_id", "method_name"}}
        if not all(columns <= set(sources.get(table, ())) for table, columns in required.items()):
            return None
        schema = f"{self.database}.BOOKS."
        (shipping, book_range, invalid_labels, defined_rates), = self._lookup_rows(
            "WITH domestic_only AS ("
            f"SELECT co.customer_id FROM {schema}cust_order co LEFT JOIN {schema}shipping_method sm "
            "ON sm.method_id = co.shipping_method_id GROUP BY co.customer_id "
            "HAVING COUNT(*) = COUNT(sm.method_name) "
            "AND SUM(CASE WHEN UPPER(sm.method_name) = 'INTERNATIONAL' THEN 1 ELSE 0 END) = 0"
            ") SELECT "
            f"(SELECT COUNT(*) FROM {schema}customers o JOIN domestic_only d ON o.customer_id = d.customer_id "
            "WHERE COALESCE(TRY_CAST(CAST(o.per_order_shipped_internationally AS VARCHAR) AS DOUBLE), -1) <> 0), "
            f"(SELECT COUNT(*) FROM {schema}customers WHERE "
            "TRY_CAST(CAST(per_books_over_13 AS VARCHAR) AS DOUBLE) NOT BETWEEN 0 AND 100.000001), "
            f"(SELECT COUNT(*) FROM {schema}customers o WHERE o.preferred_shipping_method IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {schema}shipping_method sm "
            "WHERE sm.method_name = CAST(o.preferred_shipping_method AS VARCHAR))), "
            f"(SELECT COUNT(*) FROM {schema}customers o WHERE "
            "(o.per_books_over_13 IS NOT NULL OR o.per_order_shipped_internationally IS NOT NULL) "
            f"AND NOT EXISTS (SELECT 1 FROM {schema}cust_order co WHERE co.customer_id = o.customer_id))"
        )
        notes = []
        if shipping:
            notes.append(f"{shipping} customers whose orders use only non-International shipping methods "
                         "do not have a zero international rate. Check the shipping-method label and denominator.")
        if book_range:
            notes.append(f"{book_range} customer book-price percentages fall outside 0 to 100. "
                         "Use the same grain in both counts. Repeat purchases of a title are separate ordered books.")
        if invalid_labels:
            notes.append(f"{invalid_labels} non-NULL preferred shipping methods are not observed shipping method names. "
                         "Return the method name, rather than its numeric identifier.")
        if defined_rates:
            notes.append(f"{defined_rates} customers without orders have a defined purchase or shipping percentage. "
                         "With no orders, these rates have a zero denominator and are undefined.")
        return " ".join(notes) or None

    def author_title_check(self, sources: dict[str, list[str]]) -> str | None:
        required = {"book": {"book_id", "title"}, "book_author": {"author_id", "book_id"},
                    "order_line": {"book_id", "price"}}
        if not all(columns <= set(sources.get(table, ())) for table, columns in required.items()):
            return None
        schema = f"{self.database}.BOOKS."
        (failures,), = self._lookup_rows(
            "WITH priced AS ("
            f"SELECT ba.author_id, b.title, ol.price FROM {schema}book_author ba "
            f"JOIN {schema}book b ON b.book_id = ba.book_id "
            f"JOIN {schema}order_line ol ON ol.book_id = b.book_id WHERE ol.price IS NOT NULL"
            "), candidate AS ("
            f"SELECT o.author_id, MAX(p.price) AS selected_price FROM {schema}authors o LEFT JOIN priced p "
            "ON p.author_id = o.author_id AND p.title = CAST(o.most_expensive_book AS VARCHAR) GROUP BY o.author_id"
            ") SELECT COUNT(*) FROM candidate c WHERE EXISTS "
            "(SELECT 1 FROM priced p WHERE p.author_id = c.author_id "
            "AND (c.selected_price IS NULL OR p.price > c.selected_price))"
        )
        if failures:
            return (f"{failures} proposed most-expensive books have no priced sale or are beaten by a higher sale "
                    "for that author. Check the title ranking against observed sale prices. "
                    "An average sale price can change the ranking.")
        return None

    def _clear(self) -> None:
        try:
            if self.airbyte:
                self.airbyte.cleanup()
                self.airbyte = None
        finally:
            if self.created:
                self._run_sql([f"DROP DATABASE IF EXISTS {self.database}"])
                self.created = False

    def close(self) -> None:
        self.grading_deadline = None
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
            ], cwd=cwd, env=private_environment(),
                timeout=grading_time_left(self.grading_deadline, self.config.service_timeout),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except (OSError, subprocess.SubprocessError):
            raise PipelineError("official evaluator failed or timed out") from None
        finally:
            credential.unlink(missing_ok=True)
        grading_time_left(self.grading_deadline, self.config.service_timeout)
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


def pinned_books_bundle(checkout: Path, books_input: Path) -> dict:
    check_checkout(checkout, extra_paths=("setup/elt_snowflake.yaml",))
    public = _read_yaml(checkout / "elt-bench" / "snowflake" / "books" / "config.yaml")
    bound = read_bundle(books_input)
    available = streams(public)
    if streams(bound) != available:
        raise ConfigurationError("generated input stream manifest differs from pinned books")
    # Only the local Airbyte workspace binding is variable. Source addresses,
    # connector IDs and the destination namespace come from the verified checkout.
    private = bound["Airbyte"]["config"]
    public["Airbyte"]["config"].update({name: private[name] for name in AIRBYTE_BINDINGS})
    return public


def snowflake_task(config: OfficialConfig, *, allow_paid: bool = False) -> TaskDefinition:
    if not allow_paid:
        raise ConfigurationError("official execution requires explicit paid-service approval")
    check_airbyte_url(config.airbyte_url)
    if not shutil.which(config.terraform):
        raise ConfigurationError("install Terraform or set ELT_TERRAFORM to its executable")
    public = pinned_books_bundle(config.checkout, config.books_input)
    raw_tables = frozenset(name for group in streams(public).values() for name in group)
    credentials = read_credentials(config.credential_file)
    if any(not (config.ground_truth / "books" / f"{name}.csv").is_file() for name in MODELS):
        raise ConfigurationError("ELT_GT_SNOWFLAKE must contain official books ground truth CSVs")
    return books_task_definition(
        config.checkout, public,
        partial(SnowflakeBooksBackend, config=config, bundle=public, credentials=credentials, raw_tables=raw_tables),
        _verify,
    )


def books_task_definition(checkout, public, open_backend, verify) -> TaskDefinition:
    available = streams(public)
    instructions = (
        "Official ELT-Bench Snowflake task: books. Write load.json with a top-level "
        "sources object. In sources, map each listed group to an array of all its stream names. "
        "Pass the object as content in write_pipeline_file with path=load.json. "
        "Stage 2 requires every stream to pass Stage 1. Run the load stage. "
        "Read the model sections, then write publishers.sql, customers.sql and authors.sql "
        "as one Snowflake SELECT each using unqualified raw table names. Ordinary SQL joins, "
        "aggregates, CTEs and window functions are allowed. The host materializes the SELECTs. "
        "Run transform and repair the named files. To isolate a fault, call execute_pipeline "
        "with stage=transform and file set to one saved filename. If you cannot finish all "
        "three, test at least one file and use submit_pipeline with mode=partial on a later turn.\n"
        + "\n".join(f"{name}: {', '.join(available[name])}" for name in GROUPS)
    )
    return TaskDefinition(
        "books", instructions, ("load.json",), tuple(f"{name}.sql" for name in MODELS),
        open_backend, verify, _source_sections(checkout, public), partial_transforms=True,
        load_streams=available,
        output_columns={model["name"] + ".sql": tuple(col["name"].strip().lower() for col in model["columns"])
                        for model in _read_yaml(checkout / "elt-bench/snowflake/books/data_model.yaml")["models"]},
    )
