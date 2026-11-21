# Books grading deadline and Snowflake readiness

## Native evidence and cause

The archived native run `runs/books-official-qwen35b-001` used the official
checkout at `3b068d5f15f64541d05fbc33a817e4b08c6bf173`. The model explicitly
submitted `publishers.sql` and `customers.sql` on turn 27. The grader returned
Stage 1 = **1.0**, Stage 2 = **1/3**, reward **0.56666666666667**. The former
Cookbook runner returned `rollout_timeout`, with trajectory reward **0.0**.
Its 40-minute deadline cancelled the await on the synchronous grading thread.
That thread later finished and saved the warehouse grade. The two results
were captured separately in the original archive. [Native run details](books-snowflake-35b.md)

| Archived interval, UTC | Elapsed | Evidence |
| --- | ---: | --- |
| Initial six Airbyte syncs, 09:07:34–09:24:19 | 16m 45s | Working database `airbyte-jobs-1.json` |
| Fresh replay's six syncs, 09:38:58–09:55:31 | 16m 33s | Grading database `airbyte-jobs-1.json` |
| Last replay sync to native `grade.json`, 09:55:31–09:56:59 | about 1m 28s | Evaluator files and receipt timestamps |
| Start at 09:03:17 to run end at 09:57:35 | 54m 18s | Private run manifest |

The two sync passes alone took 33m 18s. The evaluator was not the main
source of latency. The replay still reloads the selected streams into its own
namespace. Successful Snowflake transforms now omit the redundant inventory
round trip after each CTAS bundle. Explicit schema inspection, output validation,
and the official row-count checks still run. No live latency improvement has
been measured.

## Acceptance and grading boundaries

Commit `e1ffd72` implements the repair. The official runner snapshots the
tested artifacts at acceptance and records the
model's genuine terminal action before starting host grading. Passing the
verifier attaches `Grade.reward` and the stage metrics to that action before
the Cookbook computes returns. The run also checks the retained grade receipt
against the returned reward. Timed-out or failed grading remains zero, and
cleanup status is tracked independently. Cleanup attempts both the Airbyte
resources and the transient database even when one side fails.

The default shares one wall-clock deadline between agent and replay. The
prepared command explicitly requests 2,400 seconds for agent actions and
1,500 seconds for host grading, followed by bounded cleanup. The pinned
ELT-Bench README runs `evaluation/eva.py` separately from agent execution.
The upstream agent implementations have their own configurable timeouts. The
40-minute value was set by this repository for the archived run. For an
external protocol with a shared overall limit, omit `--grading-seconds`.

## Source-type and semantic checks

The archive's live schema has `BOOK.PUBLICATION_DATE` as Snowflake `TEXT`.
The staged CSV contains 11,127 non-null dates and all parse in the local
date conversion control. With local DATE inference, the archived turn-22
author draft runs. With raw VARCHAR ingestion, it fails at `DATE_PART`.
An isolated conversion control runs against the same text and returns 9,235
author rows. The unedited full-score DuckDB SQL also fails on that column
with VARCHAR ingestion. The developer-side date-only control on those same
archived three files scored Stage 1 = 1.0, Stage 2 = 1.0, and reward = 1.0
using the pinned evaluator with DuckDB transport. It performed 15 row-count
queries and three model queries. The Snowflake adapter surfaces the actual type and
provides a file-specific date conversion hint. A local rehearsal can mirror
this field with `--book-publication-date-text`. That option mirrors one
observed source type and does not certify other Snowflake dialect behavior.

The submitted customer transform returns zero for each of two percentages on
303 customers without orders. The two pinned typed comparisons both fail.
The isolated NULL control matches both columns and removes all 303 null-mask
differences per column. The public data check independently flags a defined
percentage when its denominator is zero. The controls use neither a model
call nor a native Snowflake execution and remain outside the next model's
workspace and prompt.

Run the private diagnostic commands from the repository root.

```powershell
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); runpy.run_path(""runs/books-next-deadline-metadata/check-author-date-mirror.py"",run_name=""__main__"")'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); runpy.run_path(""runs/books-official-qwen35b-001/check-customer-null.py"",run_name=""__main__"")'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); runpy.run_path(""runs/books-next-deadline-metadata/check-full-date-mirror.py"",run_name=""__main__"")'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); runpy.run_path(""runs/books-next-deadline-metadata/check-full-date-mirror.py"",run_name=""__main__"")' --private-date-control
```

## Executed regression checks

Run the full suite with the pinned renderer and cached Terraform provider.

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:CHECKPOINT_DISABLE='1'
$env:ELT_TEST_REAL_RENDERER='1'
$env:ELT_TEST_TERRAFORM=(Resolve-Path .venv-core/tf-tools/terraform.exe).Path
$env:TF_CLI_CONFIG_FILE=(Resolve-Path .venv-core/tf-tools/terraform.rc).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' -q --tb=short --basetemp .venv/books-next-deadline-suite
.\.venv-core\Scripts\python.exe -m elt_rl.cli examples/customer_orders.jsonl
```

The suite exited 0 with **113 passed in 43.56 seconds**. The SQLite trace
exited 0 after repairing its deliberate SQL error and returned Stage 1 = 1.0,
Stage 2 = 1.0, and reward = 1.0. The new tests cover a grade that exceeds
the original runner deadline, shared and separate grading expiry, rejection
at the action deadline, evaluator failure, cleanup, and application of the
reconciled reward to training advantages with unchanged action tokens,
sequence IDs, and log probabilities.

## Next-run gates

Snowsight was refreshed with `ACCOUNTADMIN` on November 21. The trial display
showed **USD 398 of 400**. The attached dedicated monitor
`ELT_BOOKS_MONITOR` showed **1.46 used credits**, nominal quota **1.00**,
**150% immediate suspension** and frequency **Never**. Effective headroom
is about **0.04 credits**. Even an effective trigger of 2.00 on this same
monitor would leave 0.54 credits, below the prior run's observed 0.73-credit
delta immediately after cleanup. Read-only RSA authentication, warehouse
visibility, direct warehouse `USAGE` and account `CREATE DATABASE` grants,
Airbyte workspace access, and pinned evaluator assets passed. The warehouse
was suspended, X-Small, with 60-second auto-suspend and auto-resume enabled.
No previous run-owned database remained visible. The worker deployment
reported `SYNC_JOB_MAX_ATTEMPTS=1`.

The fresh local probe exited 0. Jobs 91 through 96 each completed their
first replication attempt against local PostgreSQL. All six connections
matched the complete pinned inventory and all 15 table counts, totaling
84,337 rows. Cleanup completed. The job 96 S3 discovery helper pod did log
an NLTK resource download error followed by an XML parse error. The S3
replication completed and its observed table counts matched. Preserve the
private helper log when investigating connector startup on another machine.

```powershell
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --source-probe --docker-context desktop-linux --snowflake-probe
.\.venv-core\Scripts\python.exe runs/books-next-deadline-metadata/snowflake-readonly.py
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); from elt_rl.run import main; raise SystemExit(main())' official-rollout --books-35b-profile --preflight-only --rollout-seconds 2400 --grading-seconds 1500 --budget-usd 0.20 --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5_disable_thinking --out runs/books-next-deadline-metadata/tinker-metadata
```

Set the same environment variables as the handoff command. The private
directory `runs/books-next-deadline-metadata/` holds `official-preflight.txt`,
`snowflake-warehouse-readonly.json`, `tinker-metadata/manifest.json`,
`pytest-final.txt`, `sqlite.txt`, and the local dialect diagnostics.

Plan for **0.75–1.10 credits** and require at least **1.30 credits of
verified headroom**. Continuous Gen1 X-Small compute for 65 minutes would be
about 1.083 credits before cleanup and cloud-services metering. The previous
run's observed Tinker tokens imply USD 0.03342849 at published rates. The
read-only capability and pricing check confirmed the next command's
uncached bound of **USD 0.19335168** under the USD 0.20 proposed cap. No Tinker
session or Snowflake compute started during this follow-up.
[Tinker pricing](https://tinker-docs.thinkingmachines.ai/tinker/models/)
[Snowflake warehouse billing](https://docs.snowflake.com/en/user-guide/warehouses-considerations)

If authorized, an administrator can attach a fresh monitor on the existing
trial warehouse with an effective 1.35-credit trigger. This is a proposed
new run allowance and requires fresh authorization. Keep any account-level
monitor in force. Re-verify that it leaves enough headroom as well. Snowflake
can take time to enforce suspension, so the trigger is below the nominal
quota. [Resource monitor behavior](https://docs.snowflake.com/en/user-guide/resource-monitors)

```sql
-- Read-only checks, run as ACCOUNTADMIN.
SHOW WAREHOUSES LIKE 'ELT_BOOKS_WH';
SHOW RESOURCE MONITORS;

-- Proposed setup. Run only after fresh authorization and confirm that
-- ELT_BOOKS_NEXT_MONITOR is a new, unused name.
CREATE RESOURCE MONITOR ELT_BOOKS_NEXT_MONITOR
  WITH CREDIT_QUOTA = 1.50 FREQUENCY = NEVER START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 90 PERCENT DO SUSPEND_IMMEDIATE;
ALTER WAREHOUSE ELT_BOOKS_WH SET RESOURCE_MONITOR = ELT_BOOKS_NEXT_MONITOR;
SHOW RESOURCE MONITORS LIKE 'ELT_BOOKS_NEXT_MONITOR';
SHOW WAREHOUSES LIKE 'ELT_BOOKS_WH';
```

Confirm the dedicated warehouse is suspended, uses X-Small with `AUTO_RESUME`
enabled and `AUTO_SUSPEND=60`, and is the only warehouse attached to the monitor.
After replenishing the verified allowance and obtaining approval, use the
[prepared launch command](../FINAL_HANDOFF.md#final-live-command) once. A new
native run is still required to establish full SQL correctness and agreement
between the native grade, trajectory return, and manifest.

After the authorized run, verify that both run databases, the run's Airbyte
resources, and any cleanup notices are resolved. Verify warehouse suspension
via `SHOW WAREHOUSES LIKE 'ELT_BOOKS_WH';` and use the administrator's
`ALTER WAREHOUSE ELT_BOOKS_WH SUSPEND;` if it remains active. Preserve the
end-of-run monitor reading and delayed provider billing separately.
