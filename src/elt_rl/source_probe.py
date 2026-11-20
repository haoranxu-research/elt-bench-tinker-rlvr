"""Run the pinned books sources into a disposable local PostgreSQL database."""

import base64
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import mkdtemp
from urllib.parse import urlsplit
from uuid import uuid4

from .airbyte import AirbyteRun, private_environment, terraform_plan
from .books_setup import _expectations
from .contracts import PipelineError
from .official import _read_yaml, check_airbyte_url, pinned_books_bundle
from .settings import ConfigurationError


def check_published_manifest(checkout: Path, url: str, auth: dict) -> None:
    """Compare the bound Builder definition and its published version to upstream."""
    api = url.rstrip("/").removesuffix("/api/public/v1") + "/api/v1"
    client = AirbyteRun(Path("."), "", api, 30)
    client.auth = base64.b64encode(f"{auth['username']}:{auth['password']}".encode()).decode()
    scope = {"workspaceId": auth["workspace_id"]}
    try:
        projects = client._request("POST", "/connector_builder_projects/list", scope)["projects"]
        project, = [item for item in projects if item.get("sourceDefinitionId") == auth["custom_api_definition_id"]]
        result = client._request("POST", "/connector_builder_projects/get_with_manifest", {
            **scope, "builderProjectId": project["builderProjectId"],
            "version": project["activeDeclarativeManifestVersion"],
        })
        published = result["declarativeManifest"]["manifest"]
    except (PipelineError, KeyError, TypeError, AttributeError, ValueError):
        raise ConfigurationError("could not read the bound published Airbyte connector; verify and rebind Elt Snowflake") from None
    if published != _read_yaml(checkout / "setup/elt_snowflake.yaml"):
        raise ConfigurationError("the bound Airbyte manifest differs from the pinned Elt Snowflake manifest")


def books_source_probe(checkout: Path, inputs: Path, url: str, terraform: str, docker: str,
                       docker_context: str | None, evidence: dict) -> str:
    check_airbyte_url(url)
    if urlsplit(url).hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError("the source probe requires a loopback Airbyte URL")
    if not shutil.which(docker) or not shutil.which(terraform):
        raise ConfigurationError("install local Docker and Terraform or configure their executables")
    config = pinned_books_bundle(checkout, inputs)
    auth = config["Airbyte"]["config"]
    check_published_manifest(checkout, url, auth)
    evidence["custom_connector_manifest"] = "matches pinned published definition"
    _, groups = _expectations(checkout)
    expected = {name: count for tables in groups.values() for name, count in tables.items()}
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) or type(count) is not int or count < 0
           for name, count in expected.items()):
        raise ConfigurationError("invalid table name or row count in the pinned Stage 1 manifest")

    database = "books_probe_" + uuid4().hex
    commands = [docker, *(["--context", docker_context] if docker_context else []),
                "exec", "elt-postgres", "psql", "-X", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-At"]

    def sql(db: str, statement: str, operation: str) -> str:
        try:
            return subprocess.check_output([*commands, "-d", db, "-c", statement], stderr=subprocess.DEVNULL,
                                           env=private_environment(), text=True, timeout=60).strip()
        except (OSError, subprocess.SubprocessError):
            raise ConfigurationError(f"local PostgreSQL {operation} failed; check the elt-postgres container") from None

    # Generate the same source resources, streams, and sync modes as a live load.
    selected = {group: list(tables) for group, tables in groups.items()}
    plan = terraform_plan(config, selected, database, None, url)
    work = Path(mkdtemp(prefix="elt-books-source-"))
    run = AirbyteRun(work / "terraform", terraform, url, 900)
    evidence.update(database=database, planned_rows=expected, connections=len(plan["output"]["connections"]["value"]),
                    jobs=run.jobs, rows={}, cleanup="pending")
    try:
        sql("postgres", f"CREATE DATABASE {database}", "database creation")
    except ConfigurationError:
        work.rmdir()
        evidence["cleanup"] = "database creation unconfirmed"
        raise ConfigurationError(f"local PostgreSQL create could not be confirmed; check for database {database}") from None
    try:
        run.provision(checkout / "setup/main.tf", plan, auth["username"], auth["password"])
        inventory = set(sql(database, "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'books_probe'",
                            "table inventory").splitlines())
        if inventory != expected.keys():
            missing = ", ".join(sorted(expected.keys() - inventory))
            raise ConfigurationError(f"local sync produced an unexpected table inventory; missing: {missing or 'none'}")
        counts = evidence["rows"]
        for name in sorted(expected):
            counts[name] = int(sql(database, f'SELECT count(*) FROM books_probe."{name}"', f"{name} count"))
        wrong = [f"{name}: {counts[name]} vs {expected[name]}" for name in counts if counts[name] != expected[name]]
        if wrong:
            raise ConfigurationError("local counts differ from Stage 1: " + ", ".join(wrong))
    except PipelineError as error:
        raise ConfigurationError(str(error)) from None
    finally:
        # Keep the private Terraform state if cleanup is ambiguous or unsuccessful.
        evidence["cleanup"] = "required"
        try:
            run.cleanup()
            sql("postgres", f"DROP DATABASE {database}", "database cleanup")
            shutil.rmtree(work)
        except Exception:
            raise ConfigurationError(f"source probe cleanup failed for {database}; private recovery state: {work}") from None
        evidence["cleanup"] = "complete"
    return f"{len(expected)} pinned streams matched Stage 1 row counts through local Airbyte and PostgreSQL"
