# ELT-Bench RL environment handoff

## Acceptance status

| Requirement | Executed evidence | Status |
| --- | --- | --- |
| Credential-free, multi-turn ELT | The SQLite trace repaired a failed transform, submitted from a later turn, and earned 1.0 on a fresh replay. The test suite covers faulty input, failed transforms, partial and unsubmitted scores, and cleanup. | Complete |
| Credentialed official task | The November 21 Qwen rollout loaded all 84,337 expected rows into Snowflake. It ended unsubmitted after 24 turns with reward 0. Neither evaluator ran against Snowflake. | Live load verified. Scored agent submission pending. |
| Real Tinker RL update | A previous pilot completed one optimizer step from execution-derived SQLite rewards and verified a changed probe and matching checkpoint metadata. | Complete |
| Submission materials | The repository, reproduction guide, design, and professor summary are ready for review. | Local deliverables complete |

[Latest credentialed rollout](evidence/books-snowflake-final.md) ·
[Current model and submission preflight](evidence/books-model-readiness.md) ·
[Tinker optimizer evidence](evidence/tinker-pilot.md) ·
[Design](DESIGN.md) · [Professor-facing summary](PROFESSOR_SUMMARY.md)

## Final engineering verification

The fresh probe matched 84,337 rows across all 15 pinned tables in local
PostgreSQL. All six Airbyte jobs succeeded on their first attempt and
the probe cleaned up its resources.
[Latest preflight and model evidence](evidence/books-model-readiness.md)

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

## November 21 authorization and checks

- The fresh local Airbyte preflight passed on all six connections. It
  matched all 15 pinned tables and 84,337 rows, with cleanup verified.
  [Readiness evidence](evidence/books-final-audit.md)
- The administrator console confirmed that `ELT_BOOKS_MONITOR` covered
  `ELT_BOOKS_WH`. Before launch it showed 0.46 used credits and an
  immediate suspension threshold of 1.50 credits.
- Authorization covered one sampling-only rollout and its Snowflake
  loading and grading replay, with Airbyte retry limits set to one attempt.

## Final live command

The authoritative model entry point is `elt_rl.run official-rollout`.
The pending candidate is the base `Qwen/Qwen3.5-9B` with its pinned
no-thinking renderer. The runner writes exact prompt token IDs and
sampled actions to an ignored run directory. It permits one group member,
24 turns, 32 tool calls, and one explicit grading replay. Verify model
readiness and warehouse allowance and obtain approval before running this
command. [Official setup](LIVE_SETUP.md#official-snowflake-books)

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
$env:HF_HOME = (Resolve-Path runs/books-offline-model/hf).Path
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); from elt_rl.run import main; raise SystemExit(main())' official-rollout --allow-paid --allow-warehouse --budget-usd 0.15 --model Qwen/Qwen3.5-9B --renderer qwen3_5_disable_thinking --out runs/books-official-qwen9b-001 2>&1 | ForEach-Object ToString | Tee-Object runs/books-official-qwen9b-001-console.txt
```

The runner checks current rates before creating a Tinker session. The
uncached worst-case token bound for Qwen3.5-9B at checked public rates is
**USD 0.124575744**. Previous Snowflake runs used approximately 0.25–0.32
credits to load and execute without grading. Two comparable passes give
**0.50–0.64 credits** as a planning range before headroom for grading and
cleanup. A continuously active standard Gen1 X-Small warehouse uses
1 credit in 60 minutes. The refreshed administrator console confirmed
attachment and approximately 0.79 credits until immediate suspension.
That covers the estimated compute range with limited grading headroom.
It would not cover uninterrupted use for the full timeout.
[Read-only check and administrator SQL](evidence/books-model-readiness.md#read-only-cloud-checks)
[Tinker rate card](https://tinker-docs.thinkingmachines.ai/tinker/models.json) ·
[Snowflake warehouse billing](https://docs.snowflake.com/en/user-guide/warehouses-overview#impact-on-credit-usage-and-billing)

After completion, retain the private manifest, token and tool traces,
candidate file snapshots, submitted-file manifest, official Stage 1 and
Stage 2 artifacts, and namespace cleanup evidence under `runs/`.
Record billed usage from the provider and distinguish it from token-rate
estimates and rounded monitor deltas. Report the actual reward and whether
each stage executed. A missing submit continues to earn zero by design.

The November 21 run exited unsubmitted with reward 0. Its recorded token
usage implies USD 0.020613408 at public rates. The monitor displayed an
approximately 0.25-credit increase. Audit checks confirmed a suspended
warehouse and zero remaining run-owned databases or Airbyte resources.
[Run and billing evidence](evidence/books-snowflake-final.md)

## Repository verification

```powershell
git rev-parse HEAD
git status --porcelain
git check-ignore .env runs/books-reference/sql/authors.sql
```
