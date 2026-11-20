# ELT-Bench RL environment handoff

## Acceptance status

| Requirement | Executed evidence | Status |
| --- | --- | --- |
| Credential-free, multi-turn ELT | The SQLite trace repaired a failed transform, submitted from a later turn, and earned 1.0 on a fresh replay. The test suite covers faulty input, failed transforms, partial and unsubmitted scores, and cleanup. | Complete |
| Credentialed official task | The second real Qwen rollout loaded all 84,337 expected rows into Snowflake. It ended unsubmitted with reward 0. Neither evaluator ran against Snowflake. | Final scored agent rollout pending |
| Real Tinker RL update | A previous pilot completed one optimizer step from execution-derived SQLite rewards and verified a changed probe and matching checkpoint metadata. | Complete |
| Submission materials | The repository, reproduction guide, design, and professor summary are ready for review. | Local deliverables complete |

[Prior credentialed rollout](evidence/books-snowflake-second.md) ·
[Tinker optimizer evidence](evidence/tinker-pilot.md) ·
[Design](DESIGN.md) · [Professor-facing summary](PROFESSOR_SUMMARY.md)

## Final engineering verification

The host persists model-authored SQL, returns file-level validation and
warehouse errors, and allows an individual saved file to be tested.
An explicit partial submission replays only successfully tested current
files. The grader uses the same Stage 1 gate and Stage 2 comparator.
Changing any file invalidates its previous test. Repeating an unchanged
successful load has no warehouse effect.

The final audit includes an archived sampled-token replay, a scripted
interaction regression with simulated compiler responses, and the actual
pinned evaluators over DuckDB. Those are separate from genuine model
execution. The host evaluator smoke passed all 15 raw tables and all three
model outputs. With one model absent, Stage 2 awarded two of three and the
environment formula returned 0.7833333. With an incorrect raw count, Stage 2
skipped all model queries. [Commands and evidence](evidence/books-final-audit.md)

## Before approval

- The fresh local Airbyte preflight passed on all six connections. It
  matched all 15 pinned tables and 84,337 rows, with cleanup verified.
  [Readiness evidence](evidence/books-final-audit.md)
- In Snowflake, inspect the raw `SHOW WAREHOUSES LIKE 'ELT_BOOKS_WH'`
  and `SHOW RESOURCE MONITORS LIKE 'ELT_BOOKS_MONITOR'` results as an
  administrator. Confirm the actual monitor attachment, remaining headroom,
  and suspension trigger. The service account can log in and has the
  required grants, but cannot read that allowance.
- Authorize one Tinker sampling-only rollout and one Snowflake rollout,
  including its fresh grading replay. Leave Airbyte automatic retries off.

## Final live command

The authoritative model entry point is `elt_rl.run official-rollout`.
Run the following only after approval and the administrator check. It uses
the baseline Qwen3.5-4B with the pinned renderer, one group member, at most
24 turns and 32 tool calls, and one explicit submission replay. Use a new
private output path on S. [Official setup](LIVE_SETUP.md#official-snowflake-books)

```powershell
$private = Join-Path $env:LOCALAPPDATA 'ELTBenchBooks'
$env:ELT_BOOKS_INPUT_DIR = Join-Path $private 'books'
$env:ELT_SNOWFLAKE_CREDENTIAL_JSON = Join-Path $private 'snowflake.json'
$env:ELT_AIRBYTE_URL = 'http://127.0.0.1:18000/api/public/v1'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$tmp = (New-Item -ItemType Directory -Force runs/books-final-tmp).FullName
$env:TEMP = $tmp
$env:TMP = $tmp
$env:CHECKPOINT_DISABLE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_module(""elt_rl.run"", run_name=""__main__"")' official-rollout --allow-paid --allow-warehouse --budget-usd 0.15 --model Qwen/Qwen3.5-4B --renderer qwen3_5_disable_thinking --out runs/books-official-final 2>&1 | ForEach-Object ToString | Tee-Object runs/books-official-final-console.txt
```

The runner checks current rates before creating a Tinker session. The
uncached worst-case token bound at checked public rates is **USD 0.13799424**.
The prior Snowflake attempt used approximately **0.32 credits** through load
and agent execution. Two comparable passes would use about **0.64 credits**;
a continuously active standard Gen1 X-Small warehouse for 60 minutes uses
1 credit. Allow for resumed periods, grading, and cleanup. These are planning
estimates. The account's actual dollar rate and new usage are unverified.
[Tinker rate card](https://tinker-docs.thinkingmachines.ai/tinker/models.json) ·
[Snowflake warehouse billing](https://docs.snowflake.com/en/user-guide/warehouses-overview#impact-on-credit-usage-and-billing)

After completion, retain the private manifest, token and tool traces,
candidate file snapshots, submitted-file manifest, official Stage 1 and
Stage 2 artifacts, and namespace cleanup evidence under `runs/`.
Record billed usage from the provider and distinguish it from token-rate
estimates and rounded monitor deltas. Report the actual reward and whether
each stage executed. A missing submit continues to earn zero by design.

The audit launched no paid workload. The historical zero-reward rollout is
still the latest genuine agent result for the official task. No new charge,
reward, or live grade was generated.

## Repository verification

```powershell
git rev-parse HEAD
git status --porcelain
git check-ignore .env runs/books-reference/sql/authors.sql
```
