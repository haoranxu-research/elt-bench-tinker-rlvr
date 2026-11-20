# Official `books` evaluator smoke and terminal-state audit

## Why the archived local rollout did not submit

The Ollama harness gave every action a `path` and `sql` field, including
actions that do not write artifacts. The model put the intended SELECTs
in transform and submit actions and never selected `write_pipeline_file`.
All eight transforms therefore used the unchanged invalid files. Both
submit attempts hit the earlier-turn execution gate. The harness stopped
after its 10-action loop, before the underlying episode's 14-turn limit.

The archived replay matched all 10 receipts, ignoring identifier case,
and ended with zero reward and no grading replay. A scripted control on
the same fixture explicitly wrote each file, transformed successfully,
and submitted on a later turn. Fresh replay earned reward 1. These are
offline controls. [Prior local model run](books-feedback-fix.md)

The archived 24-turn Qwen trace also replayed offline. It matched all 30
tool calls, confirmed attributed feedback on six turns, executed no
warehouse SQL and earned zero on the unchanged actions. The replay log
is at `runs/books-reference/replay-archived-qwen.txt`.

Two independent defects were reproduced and fixed.

- SQLGlot classifies `AND` and `OR` as function nodes. The validator rejected
  these Boolean operators, including a valid join in the reference SQL.
  The validator now treats them as operators. The ordinary function and
  table allowlists still apply.
- After the Cookbook token layer returned a terminal `length` result, a
  direct caller could step again and submit a previously tested pipeline.
  The rollout runner already stopped at that signal. The ELT token wrapper
  now rejects further steps after a terminal result or initial context
  overflow. Regression tests confirm zero reward, no verifier call and
  no submission directory after length or turn exhaustion. A valid
  submission on the last turn retains its reward and invokes the verifier
  once. Cleanup removes the episode workspace.

Neither defect explains the archived model's missing write action. The
official task, graders and 35%/65% reward weights are unchanged.

## Offline reference results

The host derived three SELECTs from the staged raw inputs and checked
the full outputs against the pinned published references. The queries
only read raw tables. The reference SQL and raw data remain in ignored
`runs/` directories. The smoke command never creates an agent or
includes reference material in a model observation.

The smoke ran unmodified upstream `eva.py`, `eva_stage1.py`,
`eva_stage2.py` and `db_connectors.py` at revision
`3b068d5f15f64541d05fbc33a817e4b08c6bf173`. DuckDB executed the
materialization and grader queries. The local transport replaced the
Snowflake SDK connection and adapted its metadata lookup syntax. The
normal Stage 2 comparator read the published CSVs and actual query
outputs. Snowflake execution remains to be verified.

| Host reference case | Stage 1 | Stage 2 | Evaluator score |
| --- | --- | --- | ---: |
| All staged inputs | 15 of 15 tables, 84,337 rows | 3 of 3 models, 22 columns matched | 1.0 |
| One `address_status` row removed | 14 of 15 tables | Skipped, zero model queries | 0.3266666667 |

The partial score comes from grading a host reference. An unsubmitted
agent episode receives zero. This verification started no Snowflake
compute or model sampling.

Executed from the repository root.

```powershell
.\.venv-core\Scripts\python.exe -m pip install --disable-pip-version-check duckdb==1.4.4
.\.venv-core\Scripts\python.exe scripts/books_evaluator_smoke.py offline --checkout ../upstream-elt-bench --assets runs/books-assets --sql-dir runs/books-reference/sql --out runs/books-reference/evaluator-offline-003
.\.venv-core\Scripts\python.exe runs/books-reference/replay-local-model.py
```

The offline evaluator exited 0. Its output includes `result.json` with the
benchmark revision, SQL and reference hashes, plus both upstream output
directories with `results.log` and the completed `stage2.json`. The CLI
refused Snowflake mode without authorization and created no output for
that attempt.

The full suite passed **74 tests in 53.18 seconds**, with the pinned Qwen
renderer and Terraform tests enabled. The length regression reproduced
the old behavior with the original Cookbook wrapper. The Boolean
regression reproduced the operator rejection before the validator fix.

```powershell
$env:CHECKPOINT_DISABLE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:ELT_TEST_REAL_RENDERER = '1'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:ELT_TEST_TERRAFORM = (Resolve-Path .venv-core/tf-tools/terraform.exe).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/books-evaluator-tests-final""]))' 2>&1 | ForEach-Object ToString | Tee-Object runs/books-reference/tests-final.txt
```

## Minimum credentialed evaluator check

Confirm the six source connections are reachable and the Snowflake
warehouse is suspended. An administrator must inspect the raw
`SHOW WAREHOUSES` and `SHOW RESOURCE MONITORS` results to verify the
monitor assignment and current credit headroom. The service account
cannot see that balance. Use the existing Airbyte single-attempt
settings. [Prior readiness checks](books-feedback-fix.md#next-rollout-readiness)

After separate approval for one Snowflake run, use the configured
official environment and the command below. It verifies the SQL and
reference hashes against the successful offline receipt, then uses one
fresh namespace, one six-connection Airbyte load, one materialization of
the three models and one invocation of the production evaluator. Stage 1
gates Stage 2. The command cleans up the namespace. This host check
requires neither a submission replay nor a Tinker call.

```powershell
.\.venv-core\Scripts\python.exe scripts/books_evaluator_smoke.py snowflake --sql-dir runs/books-reference/sql --verification runs/books-reference/evaluator-offline-003/result.json --out runs/books-reference/evaluator-snowflake-001 --allow-warehouse
```

Keep `result.json`, the warehouse report's `results.log`, `stage2.json`,
`airbyte-jobs-1.json` and any cleanup marker private. Read back namespace
deletion and the before/after monitor values. A passing live reference
verifies the evaluator independently. A live agent submission needs its
own rollout.
