import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="install the official extra")
pytest.importorskip("sqlglot", reason="install the official extra")

from elt_rl import official
from elt_rl.books_setup import AIRBYTE_FIELDS, RUNTIME_FILES, bind_airbyte, stage
from elt_rl.airbyte import AirbyteRun, select_streams, streams, terraform_plan
from elt_rl.contracts import EpisodeConfig, Grade, PipelineError
from elt_rl.episode import ELTEpisodeState
from elt_rl.official_sql import safe_select


@pytest.mark.parametrize(("error", "message"), [
    (subprocess.TimeoutExpired(["private-secret-marker"], 600), "apply timed out"),
    (subprocess.CalledProcessError(1, ["private-secret-marker"], stderr=b"private-secret-marker"),
     r"apply failed \(exit 1\)"),
    (OSError("private-secret-marker"), "could not launch Terraform apply"),
])
def test_airbyte_terraform_errors_are_actionable_without_secrets(tmp_path, monkeypatch, error, message):
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    runner = AirbyteRun(tmp_path, "terraform", "http://127.0.0.1:8000/api/public/v1", 600)
    with pytest.raises(PipelineError, match=message) as caught:
        runner._tf("apply")
    assert "private-secret-marker" not in str(caught.value)


@pytest.fixture
def checkout():
    default = Path(__file__).resolve().parents[2] / "upstream-elt-bench"
    root = Path(os.environ.get("ELT_BENCH_TEST_CHECKOUT", default))
    if not root.is_dir():
        pytest.skip("pinned public ELT-Bench checkout not found")
    return root.resolve()


def test_official_books_public_task_and_airbyte_plan(checkout, tmp_path, monkeypatch):
    public = yaml.safe_load((checkout / "elt-bench/snowflake/books/config.yaml").read_text())
    public["Airbyte"]["config"].update(username="example", password="host-airbyte-secret${literal}",
                                       workspace_id="workspace", custom_api_definition_id="connector")
    public["postgres"]["config"]["host"] = "untrusted-host"
    public["Airbyte"]["config"]["namespace_definition"] = "source"
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(public))
    cred = {field: f"host-{field}-secret" for field in official.CREDENTIAL_FIELDS}
    (tmp_path / "credentials.json").write_text(json.dumps(cred))
    (tmp_path / "books").mkdir()
    for name in official.MODELS:
        (tmp_path / "books" / f"{name}.csv").touch()
    monkeypatch.setattr(shutil, "which", lambda name: name)
    config = official.OfficialConfig(checkout, tmp_path, tmp_path, tmp_path / "credentials.json",
                                     "http://127.0.0.1:8000/api/public/v1", "terraform", tmp_path / "out")
    with pytest.raises(ValueError, match="approval"):
        official.snowflake_task(config)
    task = official.snowflake_task(config, allow_paid=True)
    assert task.open_backend.keywords["bundle"]["postgres"]["config"]["host"] == "elt-postgres"
    assert task.open_backend.keywords["bundle"]["Airbyte"]["config"]["namespace_definition"] == "destination"
    public_task = task.instructions + "\n".join(task.sections.values())
    assert "host-password-secret" not in public_task and "host-airbyte-secret" not in public_task
    assert len(task.sections) == 8 and task.task_id == "books"
    available = streams(public)
    manifest = json.dumps({"sources": {group: list(tables) for group, tables in available.items()}})
    selected = select_streams(manifest, available)
    plan = terraform_plan(public, selected, "ELT_RL_TEST", cred, config.airbyte_url)
    assert plan["provider"]["airbyte"]["password"] == "host-airbyte-secret$${literal}"
    assert plan["resource"]["airbyte_connection"]["postgres"]["source_id"] == "${airbyte_source_postgres.postgres.source_id}"
    assert len(plan["resource"]["airbyte_connection"]) == 6
    assert all(connection["schedule"] == {"schedule_type": "manual"}
               for connection in plan["resource"]["airbyte_connection"].values())
    modeled = {item["name"] for connection in plan["resource"]["airbyte_connection"].values()
               for item in connection["configurations"]["streams"]}
    assert modeled == {item.lower() for item in json.loads(
        (checkout / "evaluation/table.json").read_text())["books"]}
    assert plan["resource"]["airbyte_destination_snowflake"]["books"]["configuration"]["schema"] == "BOOKS"
    with pytest.raises(PipelineError):
        select_streams('{"sources":{"postgres":["../gold"]}}', available)



def test_books_staging_rejects_bad_counts_before_creating_runtime(tmp_path):
    checkout = tmp_path / "checkout"
    book_dir = checkout / "elt-bench/snowflake/books"
    book_dir.mkdir(parents=True)
    (checkout / "elt-bench/schemas/books").mkdir(parents=True)
    (checkout / "evaluation").mkdir()
    public = {group: {"config": {"tables": [group], "sync_mode": "full_refresh_append"}}
              for group in ("postgres", "mongodb", "custom_api")}
    public.update(aws_s3={"data": []}, flat_files=[])
    (book_dir / "config.yaml").write_text(yaml.safe_dump(public), encoding="utf-8")
    (checkout / "evaluation/table.json").write_text(json.dumps({
        "books": {name: 1 for name in public if name not in {"aws_s3", "flat_files"}},
        "address": {"alias": 1},
    }), encoding="utf-8")
    for name in RUNTIME_FILES:
        file = checkout / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"pinned\r\n")
    assets = tmp_path / "assets"
    db = assets / "data-db/data/books"
    api = assets / "data-api/data/books"
    for folder in (db, api):
        folder.mkdir(parents=True)
    (db / "postgres.csv").write_text("id\n1\n", encoding="utf-8")
    (db / "mongodb.csv").write_text("id\n1\n", encoding="utf-8")
    input_file = api / "custom_api.csv"
    input_file.write_text("id\n1\n2\n", encoding="utf-8")
    out = tmp_path / "runtime"
    with pytest.raises(ValueError, match="Stage 1 expects 1"):
        stage(checkout, assets, out)
    assert not out.exists()
    input_file.write_text("id\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="data/address/alias.csv"):
        stage(checkout, assets, out)
    assert not out.exists()
    alias = assets / "data-api/data/address/alias.csv"
    alias.parent.mkdir()
    alias.write_text("id\n1\n", encoding="utf-8")
    assert stage(checkout, assets, out)["custom_api"] == {"custom_api": 1}
    assert json.loads((out / "setup/mongo.jsonl").read_bytes()) == {"books": ["mongodb"]}
    assert (out / "books-template/config.yaml").read_bytes() == (book_dir / "config.yaml").read_bytes()
    assert (out / "setup/sources/books/data.sh").read_bytes() == b"pinned\n"
    assert (out / "elt-docker/rest_api/data/address/alias.csv").read_bytes() == alias.read_bytes()


def test_books_binding_needs_published_ids_and_excludes_unrelated_secrets(checkout, tmp_path):
    import uuid

    credential = tmp_path / "airbyte.json"
    out = tmp_path / "books"
    values = {field: "example" for field in AIRBYTE_FIELDS.values()}
    credential.write_text(json.dumps(values), encoding="utf-8")
    with pytest.raises(ValueError, match="definition UUIDs"):
        bind_airbyte(checkout, credential, out)
    assert not out.exists()
    values.update(workspace_id=str(uuid.uuid4()), api_definition_id=str(uuid.uuid4()), extra="omit-this")
    credential.write_text(json.dumps(values), encoding="utf-8")
    bind_airbyte(checkout, credential, out)
    bound = official.read_bundle(out)
    assert bound["Airbyte"]["config"]["custom_api_definition_id"] == values["api_definition_id"]
    assert "omit-this" not in (out / "config.yaml").read_text()


def test_failed_stage2_models_cannot_receive_full_credit():
    results = {name: {"status": "ok", "match": True} for name in official.MODELS}
    results["authors"]["status"] = "error"
    grade = official._pack_grade("Success: books schema and tables verified.", {"books": results}, frozenset())
    assert grade.stage1 == 1 and grade.stage2 == pytest.approx(2 / 3)


@pytest.mark.parametrize("query", [
    "SELECT * FROM OTHER.BOOKS.author",
    "SELECT * FROM BOOKS.author",
    "SELECT * FROM @private_stage",
    "SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))",
    "SELECT SYSTEM$GET_AWS_SNS_IAM_POLICY('example') FROM author",
    "SELECT other_schema.external_udf(author_id) FROM author",
    "SELECT $SECRET FROM author",
    "SELECT * FROM publishers",
    "SELECT * FROM author; DROP TABLE author",
    "WITH x AS (SELECT * FROM publishers) SELECT * FROM x",
    "SELECT 1",
])
def test_snowflake_sql_boundary(query):
    with pytest.raises(PipelineError):
        safe_select(query, frozenset({"author", "book_author"}))


def test_snowflake_sql_accepts_join_aggregation_and_windows():
    sql = safe_select(
        "WITH joined AS (SELECT a.author_id, COUNT(*) AS n "
        "FROM author a JOIN book_author b ON a.author_id=b.author_id GROUP BY 1) "
        "SELECT *, ROW_NUMBER() OVER(ORDER BY n DESC) AS rank FROM joined",
        frozenset({"author", "book_author"}),
    )
    assert "ROW_NUMBER()" in sql


def test_official_stage_gate_uses_fresh_pinned_evaluator(checkout, tmp_path, monkeypatch):
    real_run = subprocess.run
    raw = frozenset({"author", "book"})
    (tmp_path / "books").mkdir()
    for name in official.MODELS:
        (tmp_path / "books" / f"{name}.csv").write_text("id,value\n1,good\n", encoding="utf-8")
    calls = []
    mode = {"complete": True}

    def launch(command, **kwargs):
        assert "--only" in command and "--db-type" in command
        cwd = kwargs["cwd"]
        assert not (cwd / "agent_results").exists()
        calls.append(cwd)
        (cwd / "table.json").write_text('{"books":{"author":5,"book":3}}', encoding="utf-8")
        (cwd / "db_connectors.py").write_text(
            "import pandas as pd\n"
            "class Connector:\n"
            " def close(self): pass\n"
            " def verify_schema(self, database, schema): return True\n"
            " def _norm(self, table): return table.lower()\n"
            " def list_tables(self, database, schema): return ['author','book']\n"
            f" def table_size(self, database, schema, table): return {{'author':5,'book':{3 if mode['complete'] else 2}}}[table]\n"
            " def query_evaluation_sql(self, query, database):\n"
            "  value = 'wrong' if 'authors' in query else 'good'\n"
            "  return pd.DataFrame({'id':[1],'value':[value]})\n"
            "def get_connector(*args): return Connector()\n",
            encoding="utf-8",
        )
        return real_run(command, **kwargs)

    monkeypatch.setattr(official.subprocess, "run", launch)
    config = official.OfficialConfig(checkout, tmp_path, tmp_path, tmp_path / "no-credentials",
                                     "http://localhost/api/public/v1", "terraform", tmp_path / "reports")
    for complete in (True, False):
        mode["complete"] = complete
        workspace = tmp_path / str(complete)
        workspace.mkdir()
        backend = official.SnowflakeBooksBackend(
            workspace, EpisodeConfig(tmp_path), config, {},
            {field: "dummy" for field in official.CREDENTIAL_FIELDS}, raw,
        )
        grade = backend.evaluate()
        assert (backend.report / "results.log").exists()
        assert (backend.report / "stage2.json").exists() == complete
        assert not (workspace / "official-evaluation/credential.json").exists()
        if complete:
            assert grade == Grade(1, 2 / 3, True, True)
        else:
            assert grade == Grade(0.5, 0, False, True)
    assert len(set(calls)) == 2


def test_airbyte_job_poll_and_cancel_use_owned_job(tmp_path, monkeypatch):
    run = AirbyteRun(tmp_path, "terraform", "http://localhost/api/public/v1", 1)
    calls = []

    def request(method, path, body=None):
        calls.append((method, path, body))
        return {"jobId": 42} if method == "POST" else {"status": "succeeded"}

    monkeypatch.setattr(run, "_request", request)
    run._sync("source", "owned-connection")
    report, = run.jobs
    assert (report["stream_group"], report["job_id"], report["status"]) == ("source", "42", "succeeded")
    assert report["started_utc"] <= report["finished_utc"]
    assert calls[0] == ("POST", "/jobs", {"jobType": "sync", "connectionId": "owned-connection"})
    run.active_job = "17"
    run.cleanup()
    assert calls[-1][:2] == ("DELETE", "/jobs/17")


def test_airbyte_invalid_terraform_output_is_repairable_and_cleans_up(tmp_path, monkeypatch):
    run = AirbyteRun(tmp_path / "airbyte", "terraform", "http://localhost/api/public/v1", 1)
    main = tmp_path / "main.tf"
    main.touch()
    calls = []
    def terraform(command, *args):
        calls.append(command)
        return b'{"expected":false}'
    monkeypatch.setattr(run, "_tf", terraform)
    with pytest.raises(PipelineError, match="identifiers"):
        run.provision(main, {"output": {"connections": {"value": {"expected": "ref"}}}}, "dummy", "dummy")
    run.cleanup()
    assert calls == ["init", "apply", "output", "destroy"]


def test_official_success_requires_all_stage2_reports():
    with pytest.raises(ValueError, match="omitted"):
        official._pack_grade(
            "Success: books schema and tables verified.",
            {"books": {"authors": {"match": True}}},
            frozenset({"author"}),
        )


def test_snowflake_service_key_reaches_connector_and_airbyte(checkout, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from elt_rl.settings import ConfigurationError

    password = "synthetic-key-passphrase"
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password.encode()),
    )
    (tmp_path / "service.p8").write_bytes(pem)
    path = tmp_path / "credentials.json"
    base = dict.fromkeys(official.CONNECTION_FIELDS, "dummy")
    base.update(private_key_file="service.p8", private_key_file_pwd=password, password="unused")
    path.write_text(json.dumps(base), encoding="utf-8")
    parsed = official.read_credentials(path)
    options = official.snowflake_connect_options(parsed)
    assert options["authenticator"] == "SNOWFLAKE_JWT"
    assert options["private_key_file"] == str(tmp_path / "service.p8")
    assert "password" not in options
    bundle = yaml.safe_load((checkout / "elt-bench/snowflake/books/config.yaml").read_text())
    bundle["Airbyte"]["config"].update(workspace_id="dummy", username="dummy", password="dummy")
    plan = terraform_plan(bundle, {"postgres": ["address"]}, "ELT_RL_TEST", parsed,
                          "http://127.0.0.1:1/api/public/v1/")
    auth = plan["resource"]["airbyte_destination_snowflake"]["books"]["configuration"]["credentials"]
    assert auth == {"key_pair_authentication": {"private_key": pem.decode(), "private_key_password": password}}
    base["private_key_file_pwd"] = "wrong"
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="correct passphrase"):
        official.read_credentials(path)


def test_ambiguous_snowflake_create_does_not_drop_an_unconfirmed_database(tmp_path, monkeypatch):
    config = official.OfficialConfig(tmp_path, tmp_path, tmp_path, tmp_path / "c",
                                     "http://localhost/api/public/v1", "terraform", tmp_path / "reports")
    backend = official.SnowflakeBooksBackend(
        tmp_path, EpisodeConfig(tmp_path), config, {}, {}, frozenset({"author"}),
    )
    monkeypatch.setattr(official, "terraform_plan", lambda *args: {})
    calls = []
    def broken_sql(statements):
        calls.extend(statements)
        raise PipelineError("connection dropped after request")
    monkeypatch.setattr(backend, "_run_sql", broken_sql)
    with pytest.raises(PipelineError, match="connection dropped"):
        backend._load({"mongodb": ["author"]})
    with pytest.raises(PipelineError, match="outcome is uncertain"):
        backend._load({"mongodb": ["author"]})
    with pytest.raises(PipelineError, match="cleanup requires"):
        backend.close()
    assert len(calls) == 1 and calls[0].startswith("CREATE TRANSIENT DATABASE")
    assert backend.database in (backend.report / "cleanup-required.txt").read_text()


def test_namespace_probe_cleans_up_when_schema_creation_fails(monkeypatch):
    import snowflake.connector
    from elt_rl.preflight import _snowflake_probe
    from elt_rl.settings import ConfigurationError

    statements = []
    class Cursor:
        description = [("name",)]

        def cursor(self):
            return self

        def close(self):
            pass

        def __iter__(self):
            return iter([("DEDICATED",)])

        def execute(self, sql, **kwargs):
            statements.append(sql)
            if sql.startswith("CREATE SCHEMA"):
                raise RuntimeError("synthetic permission denial")

    monkeypatch.setattr(snowflake.connector, "connect", lambda **kwargs: Cursor())
    creds = {**dict.fromkeys(official.CREDENTIAL_FIELDS, "dummy"), "warehouse": "DEDICATED"}
    assert "unverified" in _snowflake_probe(creds, False)
    assert statements == ["SHOW WAREHOUSES"]
    with pytest.raises(ConfigurationError, match="namespace check failed"):
        _snowflake_probe(creds, True)
    created = statements[-3].split()[-1]
    assert statements[-1] == f"DROP DATABASE {created}"


def test_terraform_provider_schema(checkout, tmp_path):
    executable = os.environ.get("ELT_TEST_TERRAFORM")
    if not executable:
        pytest.skip("set ELT_TEST_TERRAFORM to validate with the real provider")
    bundle = yaml.safe_load((checkout / "elt-bench/snowflake/books/config.yaml").read_text())
    bundle["Airbyte"]["config"].update(username="unused", password="unused",
                                       workspace_id="c60fc810-15b3-4e38-a752-5c13830f09b4",
                                       custom_api_definition_id="22cdc343-ac41-4030-ab23-862b759116ff")
    plan = terraform_plan(bundle, {group: list(tables) for group, tables in streams(bundle).items()},
                          "ELT_RL_TEST", {field: "unused" for field in official.CREDENTIAL_FIELDS},
                          "http://127.0.0.1:1/api/public/v1/")
    shutil.copyfile(checkout / "setup/main.tf", tmp_path / "versions.tf")
    (tmp_path / "pipeline.tf.json").write_text(json.dumps(plan), encoding="utf-8")
    for options in (["init", "-backend=false", "-input=false", "-no-color"], ["validate", "-no-color"]):
        result = subprocess.run([executable, *options], cwd=tmp_path, text=True, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
    destination = plan["resource"]["airbyte_destination_snowflake"]["books"]["configuration"]
    destination["credentials"] = {"key_pair_authentication": {"private_key": "schema-test"}}
    (tmp_path / "pipeline.tf.json").write_text(json.dumps(plan), encoding="utf-8")
    result = subprocess.run([executable, "validate", "-no-color"], cwd=tmp_path,
                            text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_official_episode_calls_two_isolated_warehouse_replays(checkout, tmp_path, monkeypatch):
    import snowflake.connector

    bundle = yaml.safe_load((checkout / "elt-bench/snowflake/books/config.yaml").read_text())
    bundle["Airbyte"]["config"].update(username="example", password="dummy", workspace_id="workspace",
                                       custom_api_definition_id="connector")
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(bundle))
    (tmp_path / "credentials.json").write_text(json.dumps({key: "dummy" for key in official.CREDENTIAL_FIELDS}))
    (tmp_path / "books").mkdir()
    for name in official.MODELS:
        (tmp_path / "books" / f"{name}.csv").touch()
    monkeypatch.setattr(shutil, "which", lambda name: name)
    config = official.OfficialConfig(checkout, tmp_path, tmp_path, tmp_path / "credentials.json",
                                     "http://localhost/api/public/v1", "terraform", tmp_path / "reports")
    databases = set()
    statements = []
    airbyte_databases = []
    cleanups = []

    class FakeSnowflake:
        def cursor(self):
            return self

        def close(self):
            pass

        def execute(self, sql, *, timeout, num_statements):
            assert timeout == 60 and num_statements == 1
            statements.append(sql)
            if sql.startswith("CREATE TRANSIENT DATABASE"):
                databases.add(sql.split()[-1])
            if sql.startswith("DROP DATABASE"):
                databases.remove(sql.split()[-1])

        def fetchall(self):
            return [("AUTHOR", 7)]

    def provision(run, main_tf, plan, username, password):
        assert main_tf == checkout / "setup/main.tf"
        assert (username, password) == ("example", "dummy")
        options = plan["resource"]["airbyte_destination_snowflake"]["books"]["configuration"]
        airbyte_databases.append(options["database"])

    monkeypatch.setattr(snowflake.connector, "connect", lambda **kwargs: FakeSnowflake())
    monkeypatch.setattr(AirbyteRun, "provision", provision)
    monkeypatch.setattr(AirbyteRun, "cleanup", lambda run: cleanups.append(run))
    monkeypatch.setattr(official.SnowflakeBooksBackend, "evaluate", lambda backend: Grade(1, 1, True, True))
    task = official.snowflake_task(config, allow_paid=True)
    with ELTEpisodeState(task, EpisodeConfig(tmp_path / "work", execution_seconds=60)) as episode:
        def call(name, turn, **arguments):
            return episode.dispatch(name, arguments, turn=turn)

        assert "Official ELT-Bench" in call("read_task", 1).text
        assert "author(" in call("read_task_section", 2, section="mongodb").text
        call("write_pipeline_file", 3, path="load.json", content='{"sources":{"mongodb":["author"]}}')
        assert "author=7" in call("execute_pipeline", 4, stage="load").text
        for turn, name in enumerate(official.MODELS, start=5):
            call("write_pipeline_file", turn, path=f"{name}.sql", content="SELECT * FROM author")
        assert "Snowflake transform finished" in call("execute_pipeline", 8, stage="transform").text
        assert call("submit_pipeline", 9).submitted
        assert episode.grade().reward == 1
        assert len(databases) == 1
    assert len(cleanups) == 2 and not databases
    assert len(set(airbyte_databases)) == 2
    assert sum(sql.startswith("CREATE OR REPLACE TABLE") for sql in statements) == 6
