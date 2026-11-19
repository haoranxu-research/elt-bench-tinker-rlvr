"""Prepare and check the pinned books sources without starting cloud services."""

import argparse
import csv
import json
import runpy
import shutil
import uuid
from contextlib import chdir
from pathlib import Path
from threading import Thread
from urllib.request import ProxyHandler, build_opener

from .airbyte import streams
from .official import _read_yaml, check_checkout
from .settings import ConfigurationError

TASK = Path("elt-bench/snowflake/books")
CONNECTOR_CHECK_FILE = Path("data/address/alias.csv")
RUNTIME_FILES = (
    "elt-docker/docker-compose.yml", "elt-docker/rest_api/app.py",
    "elt-docker/rest_api/requirements.txt", "setup/sources/books/data.sh",
    "setup/sources/books/postgres.sh", "setup/mongo.py", "setup/setup_airbyte.py",
    "setup/requirements.txt", "setup/elt_snowflake.yaml",
)
AIRBYTE_FIELDS = {
    "username": "username", "password": "password", "workspace_id": "workspace_id",
    "custom_api_definition_id": "api_definition_id",
}


def _expectations(checkout: Path) -> tuple[dict, dict]:
    config = _read_yaml(checkout / TASK / "config.yaml")
    expected = json.loads((checkout / "evaluation/table.json").read_bytes())["books"]
    groups = streams(config)
    names = [name for group in groups.values() for name in group]
    if len(names) != len(expected) or set(names) != set(expected):
        raise ConfigurationError("pinned books source and Stage 1 manifests disagree")
    return config, {group: {name: expected[name] for name in names}
                    for group, names in groups.items()}


def _row_count(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as file:
        if path.suffix == ".jsonl":
            count = 0
            for line in file:
                if not isinstance(json.loads(line), dict):
                    raise ConfigurationError(f"{path.name} contains a non-object record")
                count += 1
            return count
        rows = csv.reader(file, strict=True)
        header = next(rows, None)
        if not header or not all(header) or len(set(header)) != len(header):
            raise ConfigurationError(f"{path.name} has an invalid CSV header")
        count = 0
        for row in rows:
            if len(row) != len(header):
                raise ConfigurationError(f"{path.name} contains a malformed CSV row")
            count += 1
        return count


def stage(checkout: Path, assets: Path, out: Path) -> dict:
    config, expected = _expectations(checkout)
    flat_formats = {item["table"]: item["format"] for item in config["flat_files"]}
    source_files = {}
    for group, tables in expected.items():
        for name, count in tables.items():
            if group == "flat_files":
                file = assets / "flat-files" / f"{name}.{flat_formats[name]}"
            else:
                tree = "data-api" if group == "custom_api" else "data-db"
                file = assets / tree / "data/books" / f"{name}.csv"
            try:
                observed = _row_count(file)
            except (OSError, ValueError, csv.Error):
                raise ConfigurationError(f"cannot read staged {group}/{file.name}") from None
            if observed != count:
                raise ConfigurationError(f"{group}/{name} has {observed} rows; Stage 1 expects {count}")
            source_files[group, name] = file

    # The pinned shared declarative connector uses address/alias in CheckStream.
    # It is needed for Airbyte's source health check, outside the books stream set.
    check_file = assets / "data-api" / CONNECTOR_CHECK_FILE
    count = json.loads((checkout / "evaluation/table.json").read_bytes())["address"]["alias"]
    try:
        observed = _row_count(check_file)
    except (OSError, ValueError, csv.Error):
        raise ConfigurationError("stage data/address/alias.csv from the official REST archive for the Airbyte check") from None
    if observed != count:
        raise ConfigurationError(f"connector check input address/alias has {observed} rows; expected {count}")

    out.mkdir(mode=0o700)
    for name in RUNTIME_FILES:
        file = out / name
        file.parent.mkdir(parents=True, exist_ok=True)
        if file.suffix == ".sh":
            # A Windows Git worktree can have CRLF where the pinned blob uses LF.
            # Seeders run under Linux Bash, including when staged from Windows.
            file.write_bytes((checkout / name).read_bytes().replace(b"\r\n", b"\n"))
        else:
            shutil.copyfile(checkout / name, file)
    for (group, _), source in source_files.items():
        if group == "flat_files":
            target = out / "flat-files"
        elif group == "custom_api":
            target = out / "elt-docker/rest_api/data/books"
        else:
            target = out / "setup/data/books"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target / source.name)
    check_target = out / "elt-docker/rest_api" / CONNECTOR_CHECK_FILE
    check_target.parent.mkdir(parents=True)
    shutil.copyfile(check_file, check_target)
    (out / "setup/mongo.jsonl").write_text(
        json.dumps({"books": list(expected["mongodb"])}) + "\n", encoding="utf-8")
    shutil.copytree(checkout / TASK, out / "books-template")
    shutil.copytree(checkout / "elt-bench/schemas/books", out / "books-template/schemas")
    return expected


def rest_check(checkout: Path, runtime: Path) -> dict[str, int]:
    from werkzeug.serving import make_server

    _, expected = _expectations(checkout)
    path = (runtime / "elt-docker/rest_api").resolve()
    # Serve the pinned code and staged data over TCP, including the pagination used by Airbyte.
    with chdir(path):
        app = runpy.run_path(str(checkout / "elt-docker/rest_api/app.py"))["app"]
        with make_server("127.0.0.1", 0, app) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                opener = build_opener(ProxyHandler({}))
                check_url = f"http://127.0.0.1:{server.server_port}/address/alias?limit=1&offset=0"
                with opener.open(check_url, timeout=15) as response:
                    check = json.load(response)
                if not isinstance(check, list) or len(check) != 1 or not isinstance(check[0], dict):
                    raise ConfigurationError("the pinned connector check stream did not return a record")
                counts = {}
                for name, expected_count in expected["custom_api"].items():
                    count = 0
                    for offset in range(0, expected_count + 1000, 1000):
                        url = f"http://127.0.0.1:{server.server_port}/books/{name}?limit=1000&offset={offset}"
                        with opener.open(url, timeout=15) as response:
                            page = json.load(response)
                        if (not isinstance(page, list) or len(page) != min(1000, max(0, expected_count - offset))
                                or any(not isinstance(record, dict) for record in page)):
                            raise ConfigurationError(f"unexpected REST response for {name} at offset {offset}")
                        count += len(page)
                    counts[name] = count
                return counts
            finally:
                server.shutdown()
                thread.join()


def bind_airbyte(checkout: Path, credentials: Path, out: Path) -> None:
    import yaml

    try:
        private = json.loads(credentials.read_bytes())
        values = {key: private[field] for key, field in AIRBYTE_FIELDS.items()}
        if not all(isinstance(value, str) and value.strip() and not value.startswith("<")
                   for value in values.values()):
            raise ValueError
        for field in ("workspace_id", "custom_api_definition_id"):
            values[field] = str(uuid.UUID(values[field]))
    except (OSError, KeyError, TypeError, ValueError):
        raise ConfigurationError(
            "run upstream setup_airbyte.py and supply its private credential JSON with workspace and definition UUIDs"
        ) from None

    config = _read_yaml(checkout / TASK / "config.yaml")
    config["Airbyte"]["config"].update(values)
    out.mkdir(mode=0o700)
    file = out / "config.yaml"
    file.touch(mode=0o600, exist_ok=False)
    file.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    subs = parser.add_subparsers(dest="command", required=True)
    staging = subs.add_parser("stage")
    staging.add_argument("--assets", type=Path, required=True)
    staging.add_argument("--out", type=Path, required=True)
    smoke = subs.add_parser("rest-check")
    smoke.add_argument("--runtime", type=Path, required=True)
    bind = subs.add_parser("bind-airbyte")
    bind.add_argument("--credentials", type=Path, required=True)
    bind.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    try:
        check_checkout(checkout, extra_paths=RUNTIME_FILES)
        if args.command == "stage":
            print(json.dumps(stage(checkout, args.assets, args.out), indent=2))
        elif args.command == "rest-check":
            print(json.dumps(rest_check(checkout, args.runtime), indent=2))
        else:
            bind_airbyte(checkout, args.credentials, args.out)
            print("Private books config generated.")
    except ConfigurationError as exc:
        parser.exit(2, f"{exc}\n")
    except FileExistsError:
        parser.exit(2, "Choose a fresh output directory.\n")
    except (OSError, ValueError, ImportError):
        parser.exit(2, "Books runtime operation failed. Check paths and local dependencies (including Flask for rest-check).\n")


if __name__ == "__main__":
    main()
