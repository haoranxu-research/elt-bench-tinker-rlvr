import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="install the official extra")
pytest.importorskip("sqlglot", reason="install the official extra")

from elt_rl import official
from elt_rl.airbyte import AirbyteRun, select_streams, streams, terraform_plan
from elt_rl.contracts import EpisodeConfig, Grade, PipelineError
from elt_rl.episode import ELTEpisodeState
from elt_rl.official_sql import safe_select


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
