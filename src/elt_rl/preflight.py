"""Read-only preflight by default. Service probes require explicit flags."""

import argparse
import base64
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import uuid
from contextlib import closing
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from .airbyte import AirbyteRun, private_environment
from .contracts import LORA_RANK, PILOT_BUDGET, PILOT_TURNS
from .official import (MODELS, check_airbyte_url, check_checkout, read_bundle,
                       read_credentials, snowflake_connect_options)
from .settings import DEFAULT_MODEL, DEFAULT_RENDERER, ConfigurationError, check_model_id, read_settings


def _version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        raise ConfigurationError(f"install {distribution} in the active environment") from None


def _airbyte_probe(url: str, bundle: dict) -> str:
    auth = bundle["Airbyte"]["config"]
    client = AirbyteRun(Path("."), "", url, 15)
    client.auth = base64.b64encode(f"{auth['username']}:{auth['password']}".encode()).decode()
    workspace = auth["workspace_id"]
    # Only read the intended Airbyte workspace and its configured source inventory.
    if not isinstance(workspace, str):
        raise ConfigurationError("use a valid Airbyte workspace UUID")
    try:
        workspace = str(uuid.UUID(workspace))
    except ValueError:
        raise ConfigurationError("use a valid Airbyte workspace UUID") from None
    client._request("GET", f"/workspaces/{workspace}")
    query = urlencode({"workspaceIds": workspace, "limit": 100})
    sources = client._request("GET", f"/sources?{query}").get("data", [])
    if not any(item.get("definitionId") == auth["custom_api_definition_id"] or
               item.get("name") == "Elt Snowflake" for item in sources):
        raise ConfigurationError("publish and create the official Elt Snowflake source with setup/setup_airbyte.py")
    return "workspace and custom source visible; stream reachability still requires connector checks or sync"


def _snowflake_probe(credentials: dict, prove_namespace: bool) -> str:
    import snowflake.connector

    database = "ELT_RL_PREFLIGHT_" + uuid.uuid4().hex.upper()
    with closing(snowflake.connector.connect(
        **snowflake_connect_options(credentials),
        login_timeout=15, network_timeout=20, session_parameters={"QUERY_TAG": database},
    )) as connection, closing(connection.cursor()) as cursor:
        cursor.execute("SHOW WAREHOUSES", timeout=20)
        names = {column[0].lower(): i for i, column in enumerate(cursor.description)}
        matches = [row for row in cursor if str(row[names["name"]]).upper() == credentials["warehouse"].upper()]
        if not matches:
            raise ConfigurationError("grant the configured role access to the dedicated warehouse")
        if not prove_namespace:
            return "authenticated and warehouse visible; create/drop privileges still unverified"
        created = False
        try:
            cursor.execute(f"CREATE TRANSIENT DATABASE {database}", timeout=20)
            created = True
            cursor.execute(f"CREATE SCHEMA {database}.BOOKS", timeout=20)
        except Exception:
            raise ConfigurationError(
                f"namespace check failed; review create privileges and inspect run tag {database} for any residue"
            ) from None
        finally:
            if created:
                try:
                    cursor.execute(f"DROP DATABASE {database}", timeout=20)
                except Exception:
                    raise ConfigurationError(f"cleanup failed; remove owned probe database {database}") from None
    return "created and dropped one isolated transient database; no table workload"


def _check_gold(path: Path) -> str:
    for model in MODELS:
        try:
            with (path / "books" / f"{model}.csv").open(encoding="utf-8-sig", newline="") as file:
                rows = csv.reader(file)
                columns = next(rows)
                first = next(rows)
        except (OSError, UnicodeError, StopIteration, csv.Error):
            raise ConfigurationError(f"install the nonempty official books/{model}.csv reference") from None
        if not columns or len(columns) != len(first):
            raise ConfigurationError(f"replace malformed official books/{model}.csv")
    return "three nonempty reference files readable; provenance is operator-supplied"


def _report(name: str, action: Callable[[], str]) -> dict[str, str]:
    try:
        return {"check": name, "status": "pass", "detail": action()}
    except ConfigurationError as exc:
        return {"check": name, "status": "blocked", "detail": str(exc)}
    except Exception as exc:
        return {"check": name, "status": "blocked",
                "detail": f"{type(exc).__name__}; check permissions, dependencies and configuration"}


def _pending(name: str, detail: str) -> dict[str, str]:
    return {"check": name, "status": "unverified", "detail": detail}


def official_checks(args: argparse.Namespace, settings: dict[str, str]) -> list[dict[str, str]]:
    def require(name: str) -> str:
        if not settings.get(name):
            raise ConfigurationError(f"set {name} in the environment or local .env")
        return settings[name]

    def checkout() -> str:
        suggested = Path("../upstream-elt-bench")
        root = Path(settings["ELT_BENCH_ROOT"]) if settings["ELT_BENCH_ROOT"] else suggested
        check_checkout(root)
        return "pinned checkout and scoped assets verified" + (
            "; set ELT_BENCH_ROOT for the live command" if not settings["ELT_BENCH_ROOT"] else "")

    def terraform() -> str:
        if not shutil.which(settings["ELT_TERRAFORM"] or "terraform"):
            raise ConfigurationError("install Terraform or set ELT_TERRAFORM")
        return "Terraform executable located"

    checks = [
        _report("ELT_BENCH_ROOT", lambda: "configured" if require("ELT_BENCH_ROOT") else ""),
        _report("pinned_books_assets", checkout),
        _report("terraform", terraform),
        *(_report(name, lambda name=name: _version(name)) for name in ("PyYAML", "snowflake-connector-python", "pandas", "sqlglot")),
        _report("generated_books_inputs", lambda: "Airbyte and source config present" if
                read_bundle(Path(require("ELT_BOOKS_INPUT_DIR"))) else ""),
        _report("ground_truth", lambda: _check_gold(Path(require("ELT_GT_SNOWFLAKE")))),
        _report("snowflake_credentials", lambda: "required fields present" if
                read_credentials(Path(require("ELT_SNOWFLAKE_CREDENTIAL_JSON"))) else ""),
    ]
    if args.airbyte_probe:
        def airbyte() -> str:
            url = require("ELT_AIRBYTE_URL")
            check_airbyte_url(url)
            return _airbyte_probe(url, read_bundle(Path(require("ELT_BOOKS_INPUT_DIR"))))
        checks.append(_report("airbyte", airbyte))
    else:
        def endpoint() -> str:
            check_airbyte_url(require("ELT_AIRBYTE_URL"))
            return "URL shape accepted"
        checks.append(_report("airbyte_url", endpoint))
        checks.append(_pending("airbyte", "use --airbyte-probe to inspect the self-hosted workspace and sources"))
    if args.snowflake_probe:
        checks.append(_report("snowflake", lambda: _snowflake_probe(
            read_credentials(Path(require("ELT_SNOWFLAKE_CREDENTIAL_JSON"))), args.namespace_probe,
        )))
    else:
        checks.append(_pending("snowflake", "use --snowflake-probe after approval to verify login and warehouse visibility"))
    if not args.namespace_probe:
        checks.append(_pending("namespace_isolation", "use both Snowflake flags after authorization to verify create/drop"))
    if args.source_probe:
        from .source_probe import books_source_probe

        evidence = {}
        probe = _report("source_sync", lambda: books_source_probe(
            Path(require("ELT_BENCH_ROOT")).resolve(), Path(require("ELT_BOOKS_INPUT_DIR")).resolve(),
            require("ELT_AIRBYTE_URL"), settings["ELT_TERRAFORM"] or "terraform",
            args.docker, args.docker_context, evidence,
        ))
        probe["evidence"] = evidence
        checks.append(probe)
    else:
        checks.append(_pending("source_sync", "use --source-probe to discover and count all pinned streams locally"))
    return checks


def _renderer_probe(model: str, renderer: str) -> str:
    check_model_id(model)
    if _version("tinker") != "0.39.2" or _version("tinker-cookbook") != "0.7.0":
        raise ConfigurationError("install SDK 0.39.2 and Cookbook at the pinned SHA")
    script = (
        "import json,sys;"
        "sys.path.extend(json.loads(sys.argv[3]));"
        "from elt_rl.rendering import make_renderer;"
        "r=make_renderer(sys.argv[1],sys.argv[2],offline=True);"
        "assert r.build_generation_prompt([{'role':'user','content':'Offline renderer probe'}]).length>0;"
        "s='<tool_call><function=read_task></function></tool_call><|im_end|>';"
        "m,state=r.parse_response(r.tokenizer.encode(s,add_special_tokens=False));"
        "assert state.is_clean and m['tool_calls'][0].function.name=='read_task'"
        if renderer == DEFAULT_RENDERER else
        "import json,sys;sys.path.extend(json.loads(sys.argv[3]));"
        "from elt_rl.rendering import make_renderer;"
        "assert make_renderer(sys.argv[1],sys.argv[2],offline=True).get_stop_sequences()"
    )
    env = private_environment()
    env.update({key: os.environ[key] for key in ("HF_HOME", "HF_HUB_CACHE") if key in os.environ})
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               HF_HUB_DISABLE_IMPLICIT_TOKEN="1", HF_TRUST_REMOTE_CODE="0")
    result = subprocess.run([sys.executable, "-c", script, model, renderer, json.dumps(sys.path)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    if result.returncode:
        raise ConfigurationError("cache the selected public tokenizer and verify the pinned renderer on this platform")
    return "pinned tokenizer and Cookbook renderer exercised offline"


def tinker_checks(args: argparse.Namespace, settings: dict[str, str]) -> list[dict[str, str]]:
    model = args.model or settings["TINKER_MODEL"] or DEFAULT_MODEL

    def budget() -> str:
        if model != DEFAULT_MODEL:
            raise ConfigurationError("the offline price snapshot is for the default Qwen model")
        if not math.isfinite(args.budget_usd) or args.budget_usd <= 0:
            raise ConfigurationError("set a finite positive --budget-usd")
        turns = args.group_size * PILOT_TURNS
        estimate = (turns * PILOT_BUDGET.context * (0.33 + 0.737) +
                    args.group_size * PILOT_BUDGET.sampled * 1.005 +
                    PILOT_BUDGET.context * 0.737) / 1_000_000
        if estimate > args.budget_usd:
            raise ConfigurationError(f"offline reference token estimate {estimate:.4f} USD exceeds --budget-usd")
        return f"rank {LORA_RANK}, {args.group_size} rollouts, reference token estimate {estimate:.4f} USD"

    checks = [{"check": "tinker_key", "status": "pass" if settings["TINKER_API_KEY"] else "blocked",
               "detail": "configured; validity untested" if settings["TINKER_API_KEY"] else "set TINKER_API_KEY"}]
    checks.extend([
        _report("renderer_and_tokenizer", lambda: _renderer_probe(model, args.renderer)),
        _report("pilot_budget", budget),
        _pending("model_access", "only an authorized remote run can confirm project support and live pricing"),
    ])
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("official", "tinker"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--airbyte-probe", action="store_true")
    parser.add_argument("--source-probe", action="store_true",
                        help="Sync all pinned streams into disposable PostgreSQL on local Docker")
    parser.add_argument("--docker", default="docker", help="Docker executable for --source-probe")
    parser.add_argument("--docker-context", help="Local Docker context for --source-probe")
    parser.add_argument("--snowflake-probe", action="store_true")
    parser.add_argument("--namespace-probe", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--renderer", default=DEFAULT_RENDERER)
    parser.add_argument("--group-size", type=int, choices=(2, 3, 4), default=3)
    parser.add_argument("--budget-usd", type=float, default=0.60)
    args = parser.parse_args(argv)
    if args.namespace_probe and not args.snowflake_probe:
        parser.error("--namespace-probe requires --snowflake-probe and warehouse authorization")
    if args.target == "tinker" and (args.airbyte_probe or args.source_probe or args.snowflake_probe):
        parser.error("warehouse probe flags are only for the official preflight")
    settings = read_settings(args.env_file)
    checks = official_checks(args, settings) if args.target == "official" else tinker_checks(args, settings)
    print(json.dumps({"target": args.target, "checks": checks}, indent=2))
    return 2 if any(check["status"] == "blocked" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
