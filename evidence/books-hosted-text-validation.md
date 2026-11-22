# Hosted 35B Books validation with TEXT publication dates

The November 22, 2026 rehearsal was one genuine Tinker-hosted
Qwen/Qwen3.6-35B-A3B rollout on the official Books inputs in local DuckDB.
The book publication date used the TEXT-compatible DuckDB representation.
The agent started from an empty SQL workspace. The pinned official
ELT-Bench evaluators at 3b068d5f15f64541d05fbc33a817e4b08c6bf173 ran on
the replayed submission through the DuckDB transport.

| Result | Observed |
| --- | --- |
| Source load | 15 tables, 84,337 rows |
| Submitted files | publishers.sql, customers.sql, authors.sql |
| Submission | Explicit complete submit_pipeline call on turn 20 |
| Stage 1 | 1.0, all 15 source counts matched |
| Stage 2 | 1.0, all three output comparisons matched |
| Evaluator and recorded trajectory rewards | 1.0 and 1.0 |

The two previous native failures exhausted turns. One used ten consecutive
turns reviewing material and saved authors too late to execute. The other
replaced an author draft after a grouping error and left a diagnosed customer
percentage issue unrepaired. See the [native timing and diagnosis](books-offline-readiness.md).
Commit 73f7b64 made the Books observation prioritize current schema and the
next pending file, including actionable checks on files that already executed.
The profile reserved submission capacity and used 40 model turns and 60
tool calls. The agent used 20 turns and 30 calls. It saved and tested all
three files, responded to a public check on 110 authors without books,
revised authors.sql, re-tested it, and submitted before entering finalization.
The receipts span 81.04 seconds from the first tool to submission, with
95.61 seconds of aggregate sampling across all model requests including
the first. Local loading took 0.562 seconds and individual transform tests
took 0.141–0.171 seconds. These timings measure DuckDB and hosted sampling.
Native loading also requires Airbyte and warehouse operations.

The provenance audit matched 30 dispatched calls to decoded model actions,
28 eligible observations to subsequent prompts, and the saved SQL bytes to
model writes. It confirmed one context compaction and a maximum of 11,803
tokens per request including generation allowance and margin, within 12,288.
An offline audit aligned 5,513 sampled action tokens and their log
probabilities with Cookbook training input. It verified the recorded 1.0
return against a 0.0 control and made no optimizer call. Reference outputs
were available to the host grader only.

## Commands and usage

PowerShell from the repository root, with the cached renderer and staged
input bundle used by the earlier Books runs.

~~~powershell
$env:TEMP = (Resolve-Path runs/books-full-baseline/tmp).Path
$env:TMP = $env:TEMP
$env:HF_HOME = (Resolve-Path runs/books-offline-model/hf).Path
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:CHECKPOINT_DISABLE = '1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); sys.path.insert(0,""scripts""); runpy.run_path(""scripts/books_model_rehearsal.py"",run_name=""__main__"")' --checkout ../upstream-elt-bench --assets runs/books-assets --book-publication-date-text --hosted --books-35b-profile --model Qwen/Qwen3.6-35B-A3B --budget-usd 0.25 --allow-paid --out runs/books-offline-readiness/qwen35b-validation
~~~

The command exited 0. The full offline suite independently passed 120 tests
in 104.66 seconds, with the real renderer and local Terraform provider
enabled. Use the [offline test recipe](books-offline-readiness.md) with
the pytest basetemp set to .venv/books-35b-before-validation.

| Usage | Observed |
| --- | --- |
| Estimated uncached bound before launch | USD 0.23758848 |
| Metered uncached prompt tokens | 14,720 |
| Metered cached prompt tokens | 90,624 |
| Metered sampled tokens | 5,513 |
| Trained tokens | 0 |
| Usage priced at published rates | USD 0.022140015 |
| Provider invoice | Session charge unavailable at the read-only check |
| Snowflake compute for this rehearsal | 0 |

Rates use the [Tinker model pricing](https://thinkingmachines.ai/tinker/pricing/).
Private evidence lives under runs/books-offline-readiness/qwen35b-validation
and includes the manifest, prompts, samples, tool calls, submitted SQL,
evaluator logs, provenance audit, and training-return audit.

## Native validation gate

The native metadata preflight verified Airbyte workspace and connector
visibility, pinned evaluator assets, RSA sign-in, and warehouse visibility.
Snowflake SHOW metadata confirmed direct database-creation and warehouse-use
grants, an X-Small suspended warehouse, auto-resume, and 60-second
auto-suspend. Historical native runs verified cleanup. A new database
creation and drop was deferred during this read-only Snowflake check.
Airbyte's worker has one sync attempt per job.

The Snowflake and Airbyte metadata command was
`.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --snowflake-probe`.
The local restart had emptied the LocalStack bucket. The two staged CSV
inputs were restored and their object keys verified. The full connector
check uses a disposable local PostgreSQL destination with
`.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --source-probe --docker (Get-Command docker).Source --docker-context desktop-linux`.
All six local jobs (121–126) succeeded on their first attempt. The
published custom connector matched the pinned manifest, all 15 matched
counts totaled 84,337 rows, and cleanup completed. The six jobs took 8
minutes 47 seconds from the first start to the last finish. Evidence is
in runs/books-offline-readiness/final-native-local-source.json. The
[setup guide](../LIVE_SETUP.md) defines the private environment variables.

The native Tinker preflight passed at an estimated uncached bound of
USD 0.23758848. For Snowflake, plan for 0.75–1.10 compute credits and
verify at least 1.30 credits before immediate suspension. The last known
dedicated quota was 3.00 credits with immediate suspension at 90%, giving
an effective threshold of 2.70 credits. Current usage, monitor attachment,
and trial balance require an administrator check. The service role could
authenticate but could not see the monitor. If the threshold is unchanged,
used credits must be at most 1.40, and the active trial must have sufficient
remaining balance.

From the administrator's worksheet, leave the warehouse unselected and run
these metadata commands. Read the current trial balance in Snowsight
Admin → Cost Management.

~~~sql
SHOW RESOURCE MONITORS LIKE 'ELT_BOOKS_COMPLETION_MONITOR';
SHOW WAREHOUSES LIKE 'ELT_BOOKS_WH';
~~~

After the administrator check and separate authorization, use the
[final live command](../FINAL_HANDOFF.md#final-live-command) in a new run
directory. The native agent generates its own SQL. Keep the recorded local
SQL and grading assets outside the native model workspace.
