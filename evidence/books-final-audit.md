# Final official books workflow audit

## Scope and findings

The audit reviewed the original starter specification and acceptance
checklist, the pinned ELT-Bench and Cookbook entry points, the model
renderer, the episode and verifier, the Airbyte and Snowflake adapters,
and the archived live and local traces. The authoritative live path is
`elt_rl.run official-rollout`. [Command and acceptance status](../FINAL_HANDOFF.md)

| Finding | Resolution or observed limit |
| --- | --- |
| Actual Qwen rollout wrote three files. Missing file attribution sent later repairs to the wrong model. | Diagnostics aggregate static failures across saved files and attribute an actual warehouse error to its active SQL file. Archived action replay still terminates unsubmitted. |
| The later Ollama smoke included SQL in execute and submit actions. No file-writing action was emitted. | The official tool descriptions, schemas and write receipts make the persistence boundary explicit. Extra execute or submit arguments return a corrective hint and leave files unchanged. |
| The full transform path blocked independent progress when another model failed validation. | The official transform tool accepts one approved filename. Workspace feedback tracks missing, saved and tested files. |
| A previously tested file could not be replayed independently if any sibling was unfinished. | Explicit partial submission replays a nonempty subset of successfully tested current files. The same pinned Stage 2 comparator handles absent outputs. |
| Repeating successful load could recreate paid resources with unchanged input. | A successful unchanged load returns its existing state, and rewriting identical bytes preserves test evidence. |
| The archived agent tried a normal `EXISTS` predicate. | The SQLGlot allowlist recognizes the native predicate. Its child queries still undergo table, scope and function validation. |
| Unsubmitted files were retained in the tool trace only. | Run cleanup retains official candidate files and a separate manifest that names the exact graded subset, or records that no submission took place. |

Fresh replay, verified earlier-turn execution, bounded tools and
turns, the approved SQL paths, the pinned evaluator, and the 35%/65%
weights remain the acceptance boundary. The original model is unchanged.
The workflow never supplies reference SQL to the agent.

## Offline execution evidence

- The final full suite exited 0 with **77 tests passed in 73.88 seconds**.
  The official CLI rejected an invocation without its two explicit
  approval flags before creating an output directory.
- The archived Qwen token stream replayed all **24 responses and 30
  calls** with the final official schema. The next observation contained
  the expected diagnostics for all six failing transform calls. There
  was no warehouse SQL, official grade or new model sampling. Reward 0
  followed from the unchanged actions.
- The official interaction regression used the actual host dispatcher and
  SQL validator with a simulated Snowflake connection. It verified invalid
  arguments, persistent writes, a file-specific SQLSTATE 42000, re-execution,
  same-turn submission rejection, and complete and partial grading replay
  in a fresh namespace. A separate terminal test verified zero reward and
  no graded files after exhaustion.
- The SQLite trace executed against real local tables and earned 1.0 after
  an error, repair and later submission.
- The existing eight-case SQLite robustness suite ran three repetitions.
  The changed-input control retained 1.0 and the hard-coded output fell
  from 1.0 to 0.35. See `runs/books-reference/final-robustness.txt`.
- The independent host reference executed unmodified pinned `eva.py`,
  Stage 1 and Stage 2 with a DuckDB transport. All 15 counts and all three
  model results passed, with score 1.0. With one model absent, Stage 1 was
  1.0, Stage 2 was 2/3 and the score was 0.7833333. Removing a required raw
  row yielded Stage 1 at 14/15 and zero Stage 2 queries. These are host
  evaluator checks. [Transport and input provenance](books-evaluator-smoke.md)

```powershell
$env:CHECKPOINT_DISABLE='1'
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:ELT_TEST_REAL_RENDERER='1'
$env:TF_CLI_CONFIG_FILE=(Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:ELT_TEST_TERRAFORM=(Resolve-Path .venv-core/tf-tools/terraform.exe).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/books-final-suite-verified""]))' 2>&1 | ForEach-Object ToString | Tee-Object runs/books-reference/final-suite-verified.txt
.\.venv-core\Scripts\python.exe -m elt_rl.cli examples/customer_orders.jsonl
.\.venv-core\Scripts\python.exe -m elt_rl.robustness --suite --repetitions 3
.\.venv-core\Scripts\python.exe scripts/books_evaluator_smoke.py offline --checkout ../upstream-elt-bench --assets runs/books-assets --sql-dir runs/books-reference/sql --out runs/books-reference/evaluator-final-offline
```

Private audit logs are under `runs/books-reference/`. The archived
Qwen replay log is `final-archived-qwen-replay.txt`. The SQLite receipt
is `final-local-trace.txt`. The staged reference SQL and evaluator CSVs
stay outside Git.

## Read-only Snowflake and Tinker checks

Snowflake RSA authentication passed. Warehouse metadata reported
`SUSPENDED`, `X-Small`, `STANDARD`, auto-resume enabled and a 60-second
auto-suspend. The service role had `CREATE DATABASE` on the account
and `USAGE` on the warehouse. It saw zero remaining `ELT_RL_`
namespaces. The service role returned no monitor row, so the current quota
and monitor attachment must be refreshed by an administrator. The prior
administrator reading was 0.45 credits used toward a 1.50-credit suspension
trigger. A fresh Snowflake create/drop test remains unexecuted.

A read-only Tinker capability request reported `Qwen/Qwen3.5-4B` as
sampleable with a 65,536-token service context. There was no new Tinker
session, optimizer step, Snowflake workload, reward or billed usage.
The prior live run's zero reward and absent official grades remain
the current genuine agent result. [Historical metering](books-snowflake-second.md)

## Local Airbyte prerequisites

The standard preflight verifies ELT-Bench revision
`3b068d5f15f64541d05fbc33a817e4b08c6bf173` and pinned grader files.
The offline reference check verified all three published CSV SHA-256
values. The Cookbook pin remains
`28de41edfcdd07ba3e7980f35d53a586024a2184`.
The active Airbyte worker reported `1` for all five job retry limits.

```powershell
$private = Join-Path $env:LOCALAPPDATA 'ELTBenchBooks'
$env:ELT_BOOKS_INPUT_DIR = Join-Path $private 'books'
$env:ELT_SNOWFLAKE_CREDENTIAL_JSON = Join-Path $private 'snowflake.json'
$env:ELT_AIRBYTE_URL = 'http://127.0.0.1:18000/api/public/v1'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:CHECKPOINT_DISABLE = '1'
$env:TEMP = (New-Item -ItemType Directory -Force runs/books-final-tmp).FullName
$env:TMP = $env:TEMP
$docker = (Get-Command docker).Source
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --snowflake-probe --source-probe --docker $docker --docker-context desktop-linux | Tee-Object runs/books-machine/books-final-preflight.json
```

The fresh source probe exited 0. All **15 destination tables** matched
the official Stage 1 row counts, for **84,337 rows** in local PostgreSQL.
The bound custom connector manifest matched upstream.

| Source | Airbyte job | Committed rows |
| --- | ---: | ---: |
| `address_status` | 55 | 2 |
| Custom API | 56 | 19,933 |
| MongoDB | 57 | 22,362 |
| `order_status` | 58 | 6 |
| PostgreSQL | 59 | 41,798 |
| LocalStack S3 | 60 | 236 |

Each job succeeded on one attempt. Independent readback of the Airbyte
job receipts and PostgreSQL inventory verified cleanup of the temporary
connections, sources, destination, and database. The private clean-up
report is `runs/books-machine/books-final-source-audit.json`.
