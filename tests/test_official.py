import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="install the official extra")
pytest.importorskip("sqlglot", reason="install the official extra")

from elt_rl import official
from elt_rl import source_probe
from elt_rl.books_setup import AIRBYTE_FIELDS, RUNTIME_FILES, bind_airbyte, stage
from elt_rl.airbyte import AirbyteRun, select_streams, streams, terraform_plan
from elt_rl.contracts import EpisodeConfig, Grade, PipelineError
from elt_rl.episode import ELTEpisodeState
from elt_rl.official_sql import public_sql_review, safe_select


@pytest.mark.parametrize(("error", "message"), [
    (subprocess.TimeoutExpired(["private-secret-marker"], 600), "apply timed out"),
    (subprocess.CalledProcessError(1, ["private-secret-marker"],
                                  stderr=b"private-secret-marker\n  with airbyte_connection.s3,"),
     r"apply failed \(exit 1\) for airbyte_connection\.s3"),
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
    assert "book.language_id -> book_language.language_id" in task.sections["mongodb"]
    assert "book_author.book_id -> book.book_id" in task.sections["custom_api"]
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
    local = terraform_plan(task.open_backend.keywords["bundle"], selected, "ELT_RL_TEST", None, config.airbyte_url)
    snowflake = terraform_plan(task.open_backend.keywords["bundle"], selected, "ELT_RL_TEST", cred, config.airbyte_url)
    assert {k: v for k, v in local["resource"].items() if k.startswith("airbyte_source_")} == {
        k: v for k, v in snowflake["resource"].items() if k.startswith("airbyte_source_")
    }
    assert set(local["output"]["connections"]["value"]) == set(snowflake["output"]["connections"]["value"])
    assert all(connection["destination_id"] == "${airbyte_destination_postgres.books.destination_id}"
               for connection in local["resource"]["airbyte_connection"].values())
    assert "airbyte_destination_snowflake" not in local["resource"]
    with pytest.raises(PipelineError):
        select_streams('{"sources":{"postgres":["../gold"]}}', available)


def test_books_malformed_model_manifest_does_not_replace_saved_sources(checkout, tmp_path):
    bundle = official._read_yaml(checkout / "elt-bench/snowflake/books/config.yaml")
    loaded = []

    class NoWarehouse:
        def execute(self, stage, artifacts):
            assert stage == "load"
            loaded.append(select_streams(artifacts["load.json"], streams(bundle)))
            return "loaded"

        def inspect(self):
            return ""

        def close(self):
            pass

    task = official.books_task_definition(checkout, bundle, lambda *_: NoWarehouse(), lambda _: Grade())
    with ELTEpisodeState(task, EpisodeConfig(tmp_path)) as episode:
        episode.dispatch("read_task", {}, turn=1)
        schema = episode.tool_schema("write_pipeline_file")["properties"]["content"]
        assert schema["anyOf"][1]["required"] == ["sources"]
        malformed = {"path": "load.json", "content": "{}"}
        result = episode.dispatch("write_pipeline_file", malformed, turn=2)
        assert 'Example shape: {"sources":' in result.text and "was not changed" in result.text
        assert not (episode.artifact_dir / "load.json").exists()
        assert "write missing files" in episode.dispatch("execute_pipeline", {"stage": "load"}, turn=3).text
        invalid = {"path": "load.json", "content": {"sources": {"postgres": "address"}}}
        assert "For postgres, use a nonempty array" in episode.dispatch("write_pipeline_file", invalid, turn=4).text
        sources = {group: list(tables) for group, tables in streams(bundle).items()}
        corrected = {"path": "load.json", "content": {"sources": sources}}
        assert "saved load.json" in episode.dispatch("write_pipeline_file", corrected, turn=5).text
        assert "was not changed" in episode.dispatch("write_pipeline_file", malformed, turn=6).text
        assert not loaded
        assert "loaded" in episode.dispatch("execute_pipeline", {"stage": "load"}, turn=7).text
        assert loaded == [sources]

        sql = "SELECT " + "x" * 1243 + "tail"
        episode.dispatch("write_pipeline_file", {"path": "publishers.sql", "content": sql}, turn=8)
        first_page = episode.dispatch("read_pipeline_file", {"path": "publishers.sql"}, turn=9)
        assert "Next offset: 1250" in first_page.text
        assert episode.tool_schema("read_pipeline_file")["properties"]["offset"]["type"] == "integer"
        for offset in (1250, "1250"):
            second_page = episode.dispatch("read_pipeline_file", {"path": "publishers.sql", "offset": offset}, turn=10)
            assert "\ntail\n" in second_page.text
        invalid_offset = episode.dispatch("read_pipeline_file", {"path": "publishers.sql", "offset": True}, turn=11)
        assert "offset must be a nonnegative character index" in invalid_offset.text


@pytest.mark.parametrize("bad_count", [False, True])
def test_books_source_probe_checks_every_row_count_and_cleans_up(checkout, tmp_path, monkeypatch, bad_count):
    config, groups = source_probe._expectations(checkout)
    config["Airbyte"]["config"].update(username="private-user", password="private-password",
                                       workspace_id="workspace", custom_api_definition_id="connector")
    expected = {name: count for tables in groups.values() for name, count in tables.items()}
    monkeypatch.setattr(source_probe, "pinned_books_bundle", lambda *_args: config)
    monkeypatch.setattr(source_probe, "check_published_manifest", lambda *_args: None)
    monkeypatch.setattr(source_probe.shutil, "which", lambda name: name)
    workspace = tmp_path / "probe"
    workspace.mkdir()
    monkeypatch.setattr(source_probe, "mkdtemp", lambda **_kwargs: str(workspace))
    statements = []
    cleaned = []

    def psql(command, **_kwargs):
        statement = command[-1]
        statements.append(statement)
        if statement.startswith("SELECT tablename"):
            return "\n".join(expected)
        if statement.startswith("SELECT count"):
            name = statement.split('"')[1]
            return str(expected[name] - (bad_count and name == "country"))
        return ""

    def provision(self, main_tf, plan, username, password):
        assert main_tf == checkout / "setup/main.tf"
        assert set(plan["output"]["connections"]["value"]) == {
            "address_status", "order_status", "custom_api", "mongodb", "postgres", "s3",
        }
        assert (username, password) == ("private-user", "private-password")
        self.jobs.append({"job_id": "1"})

    monkeypatch.setattr(source_probe.subprocess, "check_output", psql)
    monkeypatch.setattr(AirbyteRun, "provision", provision)
    monkeypatch.setattr(AirbyteRun, "cleanup", lambda self: cleaned.append(self))
    evidence = {}

    def run_probe():
        return source_probe.books_source_probe(checkout, tmp_path, "http://127.0.0.1:18000/api/public/v1",
                                              "terraform", "docker", None, evidence)

    if bad_count:
        with pytest.raises(ValueError, match="country: 231 vs 232"):
            run_probe()
    else:
        assert run_probe().startswith("15 pinned streams matched")
        assert evidence["rows"] == expected
    assert len(evidence["rows"]) == len(expected) == 15
    assert evidence["cleanup"] == "complete" and len(cleaned) == 1
    assert statements[-1] == "DROP DATABASE " + evidence["database"]
    assert not workspace.exists()


def test_source_probe_rejects_a_different_published_manifest(checkout, monkeypatch):
    calls = []

    def request(self, method, route, body):
        calls.append((method, route, body))
        if route.endswith("/list"):
            return {"projects": [{"sourceDefinitionId": "definition", "builderProjectId": "project",
                                  "activeDeclarativeManifestVersion": 2}]}
        return {"declarativeManifest": {"manifest": {"type": "DeclarativeSource"}}}

    monkeypatch.setattr(AirbyteRun, "_request", request)
    with pytest.raises(ValueError, match="differs from the pinned"):
        source_probe.check_published_manifest(checkout, "http://127.0.0.1:18000/api/public/v1", {
            "username": "private", "password": "private", "workspace_id": "workspace",
            "custom_api_definition_id": "definition",
        })
    assert calls[-1][2] == {"workspaceId": "workspace", "builderProjectId": "project", "version": 2}



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


def test_snowflake_rejects_correlated_limit_but_accepts_independent_limit():
    tables = frozenset({"book", "publisher"})
    with pytest.raises(PipelineError, match="LIMIT in a correlated subquery"):
        safe_select("SELECT p.publisher_id, (SELECT b.title FROM book b "
                    "WHERE b.publisher_id = p.publisher_id ORDER BY b.title LIMIT 1) "
                    "FROM publisher p", tables)
    assert "LIMIT 1" in safe_select("SELECT (SELECT title FROM book ORDER BY title LIMIT 1) FROM publisher", tables)


def test_lookup_values_are_scoped_and_escape_the_filter():
    backend = object.__new__(official.SnowflakeBooksBackend)
    backend.database = "ELT_SESSION"
    queries = []
    backend._lookup_rows = lambda query: queries.append(query) or [("observed",)]
    assert backend.lookup_values("book_language", "language_name", "x' OR") == ["observed"]
    assert "ELT_SESSION.BOOKS.book_language" in queries[0]
    assert "'%x'' or%'" in queries[0] and queries[0].endswith("LIMIT 30")
    with pytest.raises(PipelineError, match="use a column"):
        backend.lookup_values("customer", "email", "")
    with pytest.raises(PipelineError, match="use up to"):
        backend.lookup_values("country", "country_name", "%;")
    assert len(queries) == 1


def test_public_review_flags_undefined_rate_defaults_but_preserves_zero_numerator():
    query = """
        SELECT CASE WHEN total_books > 0 THEN 100.0 * eligible / total_books ELSE 0.0 END AS books_pct,
               ROUND(COALESCE(100.0 * matched / total_orders, 0), 4) AS order_pct,
               SUM(CASE WHEN eligible > 0 THEN eligible ELSE 0 END) AS contributions,
               COALESCE(publisher_rate, 0) AS publisher_pct,
               COUNT(DISTINCT CASE WHEN eligible > 0 THEN 1 END) AS existence
        FROM orders
    """
    public_definitions = (
        "books_pct: Percentage of books above the cutoff.\n"
        "order_pct: The percentage of international orders.\n"
        "contributions: The percentage of filtered contributions.\n"
        "publisher_pct: Percentage of eligible publishers, replace NULL values with 0.\n"
    )
    defaults, rounding, counting = public_sql_review(query, public_definitions)
    assert "books_pct, order_pct" in defaults and "publisher_pct" not in defaults
    assert "order_pct" in rounding and "books_pct" not in rounding
    assert "cannot count qualifying rows" in counting
    independent_count = "SELECT COUNT(DISTINCT CASE WHEN eligible > 0 THEN order_id END) FROM orders"
    assert not public_sql_review(independent_count, public_definitions)


def test_public_review_flags_book_attributes_at_sale_line_grain():
    combined = """
        WITH author_books AS (
            SELECT ba.author_id, b.publication_date, b.num_pages, ol.price
            FROM book_author ba JOIN book b ON ba.book_id = b.book_id
            LEFT JOIN order_line ol ON b.book_id = ol.book_id
        )
        SELECT author_id, SUM(num_pages), AVG(price) FROM author_books GROUP BY author_id
    """
    independent = """
        WITH pages AS (SELECT book_id, num_pages FROM book),
             sales AS (
                 SELECT b.book_id, AVG(ol.price) FROM book b
                 LEFT JOIN order_line ol ON b.book_id = ol.book_id GROUP BY b.book_id
             )
        SELECT pages.num_pages FROM pages JOIN sales ON pages.book_id = sales.book_id
    """
    assert "Several order lines can refer to one book" in public_sql_review(combined, "")[0]
    assert not public_sql_review(independent, "")


def test_public_review_reminds_author_average_population_without_sale_join():
    sql = """
        WITH per_author AS (
            SELECT ba.author_id, SUM(b.num_pages) AS total_pages
            FROM book_author ba JOIN book b ON ba.book_id = b.book_id
            GROUP BY ba.author_id
        )
        SELECT AVG(total_pages) FROM per_author
    """
    requirement = "below_average: Flag if the author wrote fewer pages than the average total pages of all authors."
    assert "includes authors with no related book rows" in public_sql_review(sql, requirement)[0]
    assert not public_sql_review(sql, "average_pages: Average over authors with books.")


def test_public_review_flags_nullable_author_identifier_after_left_join():
    sql = ("SELECT ba.author_id, b.num_pages FROM author a "
           "LEFT JOIN book_author ba ON a.author_id = ba.author_id "
           "LEFT JOIN book b ON ba.book_id = b.book_id")
    assert "nullable side of the left join (ba.author_id)" in public_sql_review(sql, "")[0]
    assert not public_sql_review(sql.replace("SELECT ba.author_id", "SELECT a.author_id"), "")
    assert not public_sql_review(sql.replace("LEFT JOIN book_author", "JOIN book_author"), "")


def test_public_review_separates_average_sale_price_from_maximum_price():
    sql = """WITH expensive AS (
        SELECT book_id, MAX(price) AS highest_price FROM order_line GROUP BY book_id
    ) SELECT AVG(highest_price) FROM expensive"""
    requirement = "Set to 1 if the average sale price of the books written by the author is over $19."
    assert "computed with MAX(price)" in public_sql_review(sql, requirement)[0]
    assert not public_sql_review("SELECT MAX(price), AVG(price) FROM order_line", requirement)


def test_local_books_date_format_translation_reports_the_file(monkeypatch):
    duckdb = pytest.importorskip("duckdb")
    pytest.importorskip("pandas")
    pytest.importorskip("tinker_cookbook")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from books_model_rehearsal import LocalBooksBackend
    from elt_rl.contracts import PartialTransformError

    backend = LocalBooksBackend.__new__(LocalBooksBackend)
    with duckdb.connect() as connection:
        backend.connection = connection
        connection.execute("CREATE TABLE source_book(publication_date DATE)")
        with pytest.raises(PartialTransformError, match=r"authors.sql: .*unsupported Snowflake-to-DuckDB") as error:
            backend._run_sql(["USE DATABASE memory", "USE SCHEMA books",
                              "SELECT TO_CHAR(publication_date, 'YYYY') FROM source_book"],
                             artifact_names=[None, None, "authors.sql"])
        assert "EXTRACT(YEAR FROM date_column)" in str(error.value)
        assert connection.execute("SELECT EXTRACT(YEAR FROM DATE '1992-01-01')").fetchone() == (1992,)


def test_books_output_shape_checks_public_columns_and_source_ids():
    backend = object.__new__(official.SnowflakeBooksBackend)
    backend.database = "ELT_SESSION"
    backend.columns = lambda: {"authors": ["author_id", "author_name"], "author": ["author_id"]}
    backend._lookup_rows = lambda query: [(17753, 9235, 9235, 0)]
    assert "17753 rows and 9235 distinct IDs" in backend.output_shape("authors", ("author_id", "author_name"))
    assert "missing ['first_book']" in backend.output_shape("authors", ("author_id", "author_name", "first_book"))
    backend._lookup_rows = lambda query: [(9235, 9235, 9235, 0)]
    assert backend.output_shape("authors", ("author_id", "author_name")) is None


def test_books_accepts_boolean_join_and_filter_conditions():
    sql = safe_select(
        "SELECT c.id FROM customer c LEFT JOIN address a ON c.id = a.id AND a.active = 1 "
        "WHERE c.enabled = 1 OR a.id IS NULL",
        frozenset({"customer", "address"}),
    )
    assert " AND " in sql and " OR " in sql
    assert "EXISTS" in safe_select(
        "SELECT c.id FROM customer c WHERE EXISTS (SELECT 1 FROM address a WHERE a.id = c.id)",
        frozenset({"customer", "address"}),
    )


@pytest.mark.parametrize("mode", ["complete", "partial"])
def test_books_write_repair_submit_and_fresh_replay(tmp_path, monkeypatch, mode):
    from elt_rl.contracts import TaskDefinition
    from elt_rl.episode import ELTEpisodeState
    import snowflake.connector

    records = {}
    opened = []

    class Cursor:
        def execute(self, statement, **_kwargs):
            if statement.startswith("CREATE OR REPLACE"):
                warehouse = statement.split()[4].split(".")[0]
                if "BAD_COLUMN" in statement:
                    raise snowflake.connector.errors.ProgrammingError(
                        msg="line 1 at position 63 invalid identifier 'BAD_COLUMN'", sqlstate="42000",
                    )
                records[warehouse].append(statement.split()[4].split(".")[-1])

        def fetchall(self):
            return []

        def cursor(self):
            return self

        def close(self):
            pass

    monkeypatch.setattr(snowflake.connector, "connect", lambda **_kwargs: Cursor())

    def open_backend(path, _config):
        backend = object.__new__(official.SnowflakeBooksBackend)
        backend.database = f"TEST{len(opened)}"
        backend.query_timeout = 1
        backend.raw_tables = frozenset({"author"})
        backend.transform_attempts = 0
        backend._connection_options = dict
        backend.inspect = lambda: "author=1"
        backend.close = lambda: None
        execute = backend.execute
        backend.execute = lambda stage, files: "load finished" if stage == "load" else execute(stage, files)
        records[backend.database] = []
        opened.append(path)
        return backend

    def verify(backend):
        return Grade(1, len(records[backend.database]) / 3, True, True)

    files = tuple(f"{name}.sql" for name in official.MODELS)
    task = TaskDefinition("books", "three files", ("load.json",), files,
                          open_backend, verify, partial_transforms=True)
    last_turn = 8 if mode == "complete" else 5
    with ELTEpisodeState(task, EpisodeConfig(tmp_path, max_turns=last_turn)) as episode:
        def call(tool, turn, **args):
            return episode.dispatch(tool, args, turn=turn)

        call("read_task", 1)
        assert episode.tool_schema("write_pipeline_file")["properties"]["path"]["enum"] == ["load.json", *files]
        assert "one bare filename: load.json" in call(
            "write_pipeline_file", 1, path="./data/load.json", content="{}",
        ).text
        assert "write_pipeline_file" in call("execute_pipeline", 1, stage="load", sql="SELECT 1").text
        assert "missing" in call("list_workspace", 1).text
        assert "execute_pipeline with stage=load" in call("write_pipeline_file", 2, path="load.json", content="{}").text
        assert "for stage=load" in call("execute_pipeline", 2, stage="load", file="authors.sql").text
        assert "load finished" in call("execute_pipeline", 2, stage="load", file="load.json").text
        assert "already loaded" in call("execute_pipeline", 2, stage="load").text
        for name in files:
            call("write_pipeline_file", 3, path=name,
                 content="SELECT BAD_COLUMN FROM author" if name == "customers.sql" else "SELECT * FROM author")
        failure = call("execute_pipeline", 4, stage="transform").text
        assert "customers.sql: Snowflake query failed" in failure
        assert "Current tested files: publishers.sql" in failure
        assert "later turn" in call("submit_pipeline", 4, mode="partial").text
        assert "publishers.sql: tested" in call("list_workspace", 4).text
        assert episode.grade() == Grade() and len(opened) == 1
        if mode == "complete":
            assert "Tested: publishers.sql" in call(
                "execute_pipeline", 5, stage="transform", file="publishers.sql",
            ).text
            assert "already contains" in call(
                "write_pipeline_file", 5, path="publishers.sql", content="SELECT * FROM author",
            ).text
            assert "later turn" in call("submit_pipeline", 5, mode="partial").text
            assert "authors.sql" in call("submit_pipeline", 6).text
            call("write_pipeline_file", 6, path="customers.sql", content="SELECT * FROM author")
            assert "customers.sql: saved, needs execution" in call("list_workspace", 6).text
            assert "Tested:" in call("execute_pipeline", 7, stage="transform").text
            assert "reserved for submit_pipeline" in call(
                "write_pipeline_file", 8, path="authors.sql", content="SELECT BAD_COLUMN FROM author",
            ).text
        else:
            assert "Use the next turn to call submit_pipeline" in failure
            assert "Warehouse transform attempts left: 6" in failure
        result = call("submit_pipeline", last_turn, mode=mode)
        assert result.submitted and "Stage 1: 1" in result.text
        assert "Reward: " in result.text
        assert len(opened) == 2 and opened[0] != opened[1]
        assert records["TEST1"] == (list(official.MODELS) if mode == "complete" else ["publishers"])
        assert episode.submitted_files == (files if mode == "complete" else ("publishers.sql",))
        assert episode.grade().reward == pytest.approx(1.0 if mode == "complete" else (35 + 65 / 3) / 100)


def test_books_reports_independent_sql_failures_in_one_pass():
    backend = object.__new__(official.SnowflakeBooksBackend)
    backend.raw_tables = frozenset({"publisher", "customer", "author"})
    backend.transform_attempts = 0
    backend._run_sql = lambda *_args, **_kwargs: pytest.fail("invalid batch reached Snowflake")
    files = {
        "publishers.sql": "WITH publisher_book_counts AS (\n"
                          " SELECT * FROM publisher JOIN publisher_book_counts USING (publisher_id)\n"
                          ") SELECT * FROM publisher_book_counts",
        "customers.sql": "SELECT customer_id,\n ROUND(CAST(COUNT(*), 2) AS FLOAT) AS n\n"
                         "FROM customer GROUP BY customer_id",
        "authors.sql": "WITH wrote_fewer_total_pages AS (SELECT * FROM author)\n"
                       "SELECT * FROM author\n"
                       "JOIN wrote_fewer_total_pages_than_the_average USING (author_id)",
    }
    with pytest.raises(PipelineError) as captured:
        backend.execute("transform", files)
    feedback = str(captured.value)
    assert "publishers.sql: line 2" in feedback and "relation PUBLISHER_BOOK_COUNTS" in feedback
    assert "customers.sql: line 2" in feedback and "CAST requires" in feedback
    assert "authors.sql: line 3" in feedback and "relation WROTE_FEWER_TOTAL_PAGES_THAN_THE_AVERAGE" in feedback

    files["publishers.sql"] = "WITH publisher_book_counts AS (SELECT * FROM publisher) SELECT * FROM PUBLISHER_BOOK_COUNTS"
    files["customers.sql"] = "SELECT customer_id,\n ROUND(COUNT(*) AS n) FROM customer GROUP BY customer_id"
    with pytest.raises(PipelineError) as captured:
        backend.execute("transform", files)
    assert "publishers.sql" not in str(captured.value)
    assert "customers.sql: line 2" in str(captured.value) and "authors.sql: line 3" in str(captured.value)
    assert backend.transform_attempts == 0


def test_books_quoted_cte_name_keeps_snowflake_case_sensitivity():
    with pytest.raises(PipelineError, match="relation AUTHORS is neither"):
        safe_select('WITH "authors" AS (SELECT * FROM author) SELECT * FROM AUTHORS', frozenset({"author"}))


def test_books_warehouse_error_names_only_the_failing_artifact(monkeypatch):
    import snowflake.connector

    class Warehouse:
        def cursor(self):
            return self

        def close(self):
            pass

        def execute(self, statement, **_kwargs):
            if statement.startswith("CREATE OR REPLACE TABLE PROBE.BOOKS.customers"):
                raise snowflake.connector.errors.ProgrammingError(
                    msg="line 1 at position 90 invalid identifier 'CA.COUNTRY_ID' private-credential-marker",
                    sqlstate="42000",
                )

    monkeypatch.setattr(snowflake.connector, "connect", lambda **_kwargs: Warehouse())
    backend = object.__new__(official.SnowflakeBooksBackend)
    backend.database = "PROBE"
    backend.query_timeout = 60
    backend._connection_options = dict
    backend.raw_tables = frozenset({"author"})
    backend.transform_attempts = 0
    files = {f"{name}.sql": "SELECT * FROM author" for name in official.MODELS}
    with pytest.raises(PipelineError) as captured:
        backend.execute("transform", files)
    assert str(captured.value) == (
        "customers.sql: Snowflake query failed (SQLSTATE 42000): "
        "invalid identifier 'CA.COUNTRY_ID' (generated statement, line 1 at position 90)"
    )
    assert backend.transform_attempts == 1


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
            if ".INFORMATION_SCHEMA.COLUMNS " in statements[-1]:
                return [("AUTHOR", "AUTHOR_ID", "NUMBER"), ("AUTHOR", "AUTHOR_NAME", "TEXT"),
                        ("BOOK", "PUBLICATION_DATE", "DATE"), ("PRIVATE_TABLE", "SECRET", "TIMESTAMP_NTZ"),
                        *((filename.removesuffix(".sql").upper(), col.upper(), "TEXT")
                          for filename, cols in task.output_columns.items() for col in cols)]
            if statements[-1].startswith("SELECT COUNT(*), COUNT(DISTINCT"):
                return [(7, 7, 7, 0)]
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
        loaded = call("execute_pipeline", 4, stage="load").text
        assert "author=7" in loaded and "author(author_id, author_name)" in loaded
        assert "book(publication_date DATE)" in loaded
        assert "Still need successful tests: publishers.sql, customers.sql, authors.sql." in loaded
        assert "SECRET" not in loaded
        assert "author(author_id, author_name)" in call("inspect_warehouse", 4, table="author").text
        for turn, name in enumerate(official.MODELS, start=5):
            call("write_pipeline_file", turn, path=f"{name}.sql", content="SELECT * FROM author")
        assert "Snowflake transform finished" in call("execute_pipeline", 8, stage="transform").text
        assert call("submit_pipeline", 9).submitted
        assert episode.grade().reward == 1
        assert len(databases) == 1
    assert len(cleanups) == 2 and not databases
    assert len(set(airbyte_databases)) == 2
    assert sum(sql.startswith("CREATE OR REPLACE TABLE") for sql in statements) == 6
