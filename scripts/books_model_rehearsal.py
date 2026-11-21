"""Model-authored books rollout using the production token protocol and local warehouse I/O."""

import argparse
import asyncio
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.request import Request, urlopen

import duckdb
from sqlglot import transpile
from sqlglot.errors import ErrorLevel, SqlglotError, UnsupportedError

from books_evaluator_smoke import REFERENCE_HASHES, evaluate_local, load_local_inputs, result_fields, save_result, sha256
from elt_rl.airbyte import streams
from elt_rl.contracts import EpisodeConfig, PartialTransformError, TokenBudget
from elt_rl.cookbook import ELTGroupBuilder
from elt_rl.episode import BOOKS_INSTRUCTION, BOOKS_REQUEST
from elt_rl.official import SnowflakeBooksBackend, _read_yaml, books_task_definition, check_checkout
from elt_rl.rendering import make_renderer
from elt_rl.settings import DEFAULT_RENDERER, ConfigurationError, read_settings


HOSTED_BUDGET = TokenBudget(context=16_384, sampled=12_288)
HOSTED_REASONING_BUDGET = TokenBudget(context=16_384, sampled=20_480, per_turn=4_096)
HOSTED_TURNS = 32


class LocalBooksBackend(SnowflakeBooksBackend):
    """Reuse the official stage and SQL checks while substituting DuckDB for transport."""

    transform_attempt_limit = 10

    def __init__(self, bundle, assets):
        self.bundle = bundle
        self.assets = assets
        self.raw_tables = frozenset(name for group in streams(bundle).values() for name in group)
        self.database = "memory"
        self.connection = duckdb.connect()
        self.load_attempts = 0
        self.transform_attempts = 0

    def _load(self, selected):
        self.connection.execute("SET schema = 'main'")
        self.connection.execute("DROP SCHEMA IF EXISTS books CASCADE")
        load_local_inputs(self.connection, self.assets, (name for group in selected.values() for name in group))

    def execute(self, stage, artifacts):
        result = super().execute(stage, artifacts)
        return result.replace("Airbyte load finished.", "Local input load finished.", 1).replace(
            "Snowflake transform finished.", "DuckDB transform finished.", 1,
        )

    def _run_sql(self, statements, *, artifact_names=None):
        tested = []
        for index, statement in enumerate(statements[2:], start=2):
            name = artifact_names[index]
            try:
                query, = transpile(statement, read="snowflake", write="duckdb",
                                   unsupported_level=ErrorLevel.RAISE)
                self.connection.execute(query)
            except (SqlglotError, duckdb.Error) as error:
                message = str(error)
                if isinstance(error, UnsupportedError):
                    message = "unsupported Snowflake-to-DuckDB translation: " + message
                if "must appear in the GROUP BY clause" in message:
                    message = message.split("\nEither ", 1)[0]
                    message += "\nUse a deterministic aggregate or compute the measure in a separate grouped CTE."
                if "'~~(DATE, " in message or "'~~(TIMESTAMP, " in message or "expression 'ToChar'" in message:
                    message += "\nFor a year comparison, use EXTRACT(YEAR FROM date_column) with a numeric year."
                detail = f"{name}: local SQL error: {message}"
                raise PartialTransformError(detail, tuple(tested)) from None
            tested.append(name)

    def inspect(self):
        names = self.connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE lower(table_schema) = 'books' ORDER BY table_name",
        ).fetchall()
        return ", ".join(f"{name}={count}" for name, in names
                         for count, in self.connection.execute(f"SELECT COUNT(*) FROM books.{name}").fetchall())

    def columns(self):
        return self._column_catalog(self.connection.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE lower(table_schema) = 'books' ORDER BY table_name, ordinal_position",
        ).fetchall())

    def _lookup_rows(self, query: str):
        return self.connection.execute(query).fetchall()

    def close(self):
        self.connection.close()


def local_request(args, endpoint, payload):
    request = Request(f"http://127.0.0.1:{args.port}/api/{endpoint}", method="POST",
                      headers={"Content-Type": "application/json"}, data=json.dumps(payload).encode())
    with urlopen(request, timeout=300) as response:
        return json.load(response)


def append_sample(args, entry):
    with (args.out / "samples.jsonl").open("a", encoding="utf-8") as trace:
        trace.write(json.dumps(entry) + "\n")


def sample(args, tokenizer, observation, stop, max_tokens):
    prompt_ids = observation.to_ints()
    prompt = tokenizer.decode(prompt_ids, skip_special_tokens=False, clean_up_tokenization_spaces=False)
    stop_text = [tokenizer.decode([value]) if isinstance(value, int) else value for value in stop]
    result = local_request(args, "generate", {
        "model": args.local_model, "prompt": prompt, "raw": True, "stream": False,
        "options": {"num_ctx": TokenBudget().context, "num_predict": max_tokens,
                    "temperature": 0.8, "seed": 21, "stop": stop_text},
    })
    action = tokenizer.encode(result["response"], add_special_tokens=False)
    if result["done_reason"] == "stop" and stop and isinstance(stop[0], int):
        action.append(stop[0])  # Ollama omits the matched stop delimiter from its returned text.
    append_sample(args, {"prompt_tokens": prompt_ids, "action_tokens": action, "response": result})
    return action, result["done_reason"]


async def run_native_tools(args, episode, budget, pipelines):
    messages = [{"role": "system", "content": BOOKS_INSTRUCTION},
                {"role": "user", "content": BOOKS_REQUEST}]
    tools = [{"type": "function", "function": {"name": name, "description": tool.description,
                                               "parameters": episode.tool_schema(name)}}
             for name, tool in episode.tools.items()]
    sampled = 0
    calls = 0
    recovered = False
    for turn in range(1, episode.config.max_turns + 1):
        result = await asyncio.to_thread(local_request, args, "chat", {
            "model": args.local_model, "messages": messages, "tools": tools, "stream": False,
            "options": {"num_ctx": budget.context, "num_predict": min(budget.sampled - sampled, budget.per_turn),
                        "temperature": 0.8, "seed": 21},
        })
        append_sample(args, {"messages": messages, "response": result})
        sampled += result["eval_count"]
        message = result["message"]
        messages.append(message)
        if result["done_reason"] == "length":
            return turn, sampled, "sample_truncated"
        if not message.get("tool_calls"):
            hint = episode.continuation_hint(turn)
            if recovered or hint is None or sampled >= budget.sampled:
                return turn, sampled, "no_tool_call"
            recovered = True
            messages.append({"role": "user", "content": hint})
            print(f"turn={turn} text recovery", flush=True)
            continue
        for tool_call in message["tool_calls"]:
            name = tool_call["function"]["name"]
            arguments = tool_call["function"]["arguments"]
            feedback = episode.dispatch(name, arguments, turn=turn)
            calls += 1
            with (pipelines / "local-native.tools.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"turn": turn, "tool": name, "arguments": arguments,
                                         "feedback": feedback.text, "submitted": feedback.submitted}) + "\n")
            print(f"turn={turn} tool={name} submitted={feedback.submitted}", flush=True)
            messages.append({"role": "tool", "tool_name": name, "content": feedback.text})
            if feedback.submitted:
                return turn, sampled, "tool_stopped"
            if calls >= episode.config.max_tool_calls:
                return turn, sampled, "max_tool_calls"
        if sampled >= budget.sampled:
            return turn, sampled, "token_budget"
    return turn, sampled, "max_turns"


async def run_cookbook_tokens(args, env, renderer, budget, config):
    observation, stop = await env.initial_observation()
    sampled = 0
    for turn in range(1, config.max_turns + 1):
        max_tokens = min(budget.sampled - sampled, budget.per_turn, budget.context - observation.length)
        if max_tokens <= 0:
            return turn - 1, sampled, "token_budget"
        action, stop_reason = await asyncio.to_thread(sample, args, renderer.tokenizer, observation, stop, max_tokens)
        sampled += len(action)
        if stop_reason == "length":
            return turn, sampled, "sample_truncated"
        result = await env.step(action)
        print(f"turn={turn} tokens={len(action)} terminal={result.episode_done}", flush=True)
        if result.episode_done:
            return turn, sampled, next((key.removeprefix("stop/") for key in result.metrics if key.startswith("stop/")),
                                      "completed")
        observation, stop = result.next_observation, result.next_stop_condition
    return turn, sampled, "max_turns"


async def run_hosted(args, task, bundle, assets, expected, evaluator_calls):
    from elt_rl.training import run_remote

    settings = read_settings(args.env_file)
    if not settings["TINKER_API_KEY"]:
        raise ConfigurationError("set TINKER_API_KEY in the environment or local .env")
    for name, digest in REFERENCE_HASHES.items():
        if sha256(assets / "gt_snowflake" / "books" / f"{name}.csv") != digest:
            raise ConfigurationError("local rehearsal reference does not match the pinned dataset")
    with LocalBooksBackend(bundle, assets).connection as connection:
        load_local_inputs(connection, assets, expected)
        for table, count in expected.items():
            if connection.execute(f'SELECT COUNT(*) FROM books."{table}"').fetchone()[0] != count:
                raise ConfigurationError(f"staged rehearsal row count does not match for {table}")

    manifest = {"mode": "books-rehearsal", "warehouse": "duckdb_transport", "staged_rows": sum(expected.values())}

    def record(**updates):
        manifest.update(updates, updated_utc=datetime.now(timezone.utc).isoformat())
        temp = args.out / "manifest.tmp"
        temp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temp.replace(args.out / "manifest.json")

    reasoning = args.renderer == "qwen3_5"
    config = EpisodeConfig(args.out / "work", max_turns=HOSTED_TURNS, max_tool_calls=48 if reasoning else 32,
                           rollout_seconds=600, max_submissions=1)
    try:
        result = await run_remote(
            "books-rehearsal", task, config, args.out, args.model, args.renderer, 1, args.budget_usd, record,
            api_key=settings["TINKER_API_KEY"], project_id=settings["TINKER_PROJECT_ID"] or None,
            token_budget=HOSTED_REASONING_BUDGET if reasoning else HOSTED_BUDGET, preflight_only=args.preflight_only,
        )
        record(evaluator_queries=evaluator_calls)
        return result
    except (Exception, KeyboardInterrupt) as error:
        record(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed", error_type=type(error).__name__)
        raise


async def run(args):
    checkout = args.checkout.resolve()
    assets = args.assets.resolve()
    args.out = args.out.resolve()
    check_checkout(checkout)
    bundle = _read_yaml(checkout / "elt-bench/snowflake/books/config.yaml")
    expected = json.loads((checkout / "evaluation/table.json").read_bytes())["books"]
    evaluator_calls = []

    def verify(backend):
        grade, counts = evaluate_local(
            backend.connection, checkout, assets / "gt_snowflake", args.out, "grading", expected,
        )
        evaluator_calls.append(counts)
        return grade

    def open_backend(_path, _config):
        return LocalBooksBackend(bundle, assets)

    args.out.mkdir(parents=True)
    pipelines = args.out / "pipelines"
    pipelines.mkdir()
    task = books_task_definition(checkout, bundle, open_backend, verify)
    if args.hosted:
        return await run_hosted(args, task, bundle, assets, expected, evaluator_calls)
    renderer = make_renderer(args.model, args.renderer, offline=True)
    budget = TokenBudget()
    config = EpisodeConfig(args.out / "work", max_turns=24, max_tool_calls=32, max_submissions=1)
    builder = ELTGroupBuilder(config, renderer, 1, task_factory=lambda: task, budget=budget, evidence_dir=pipelines)
    env, = await builder.make_envs()
    episode, = builder.episodes
    started = monotonic()
    try:
        if args.native_tools:
            turns, sampled, reason = await run_native_tools(args, episode, budget, pipelines)
        else:
            turns, sampled, reason = await run_cookbook_tokens(args, env, renderer, budget, config)
        grade = episode.grade()
        save_result(args.out, {
            "kind": "model_authored_local_rehearsal", "local_model": args.local_model,
            "protocol": "ollama_native_tools" if args.native_tools else "pinned_cookbook_tokens",
            "renderer_model": None if args.native_tools else args.model,
            "warehouse": "duckdb_transport", "turns": turns, "sampled_tokens": sampled, "stop_reason": reason,
            "elapsed_seconds": round(monotonic() - started, 2), "submitted": grade.submitted,
            "submitted_files": episode.submitted_files, "evaluator_calls": evaluator_calls, **result_fields(grade),
        })
        return 0 if grade.submitted else 2
    finally:
        await builder.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--renderer", choices=(DEFAULT_RENDERER, "qwen3_5"), default=DEFAULT_RENDERER)
    parser.add_argument("--local-model", default="qwen3.5:9b")
    parser.add_argument("--native-tools", action="store_true", help="Use Ollama tool rendering with the same dispatcher")
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--hosted", action="store_true", help="Use Tinker sampling and local DuckDB")
    parser.add_argument("--preflight-only", action="store_true", help="Check hosted prerequisites without creating a session")
    parser.add_argument("--allow-paid", action="store_true", help="Confirm authorization for one hosted rehearsal")
    parser.add_argument("--budget-usd", type=float, default=0.17)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    if args.hosted:
        if args.native_tools or not (args.preflight_only or args.allow_paid):
            parser.error("--hosted requires --preflight-only or explicit --allow-paid and uses the pinned tool protocol")
        if not math.isfinite(args.budget_usd) or args.budget_usd <= 0:
            parser.error("--budget-usd must be finite and positive")
    elif args.preflight_only or args.allow_paid:
        parser.error("hosted flags require --hosted")
    try:
        raise SystemExit(asyncio.run(run(args)))
    except (Exception, KeyboardInterrupt) as error:
        detail = str(error) if isinstance(error, ConfigurationError) else type(error).__name__
        parser.exit(1, f"Rehearsal stopped ({detail}). See the private output directory.\n")
