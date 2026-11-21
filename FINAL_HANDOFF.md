# ELT-Bench RL environment handoff

## Acceptance status

| Requirement | Executed evidence | Status |
| --- | --- | --- |
| Credential-free, multi-turn ELT | The SQLite trace repaired a failed transform, submitted from a later turn, and earned 1.0 on a fresh replay. The test suite covers faulty input, failed transforms, partial and unsubmitted scores, and cleanup. | Complete |
| Hosted agent submission with pinned books grading | Qwen3.6-35B-A3B independently wrote, executed, and submitted all three outputs on DuckDB. All 15 tables and 84,337 rows were present. Stage 1 = 1.0, Stage 2 = 1.0, reward = 1.0. | Local target complete |
| Credentialed official task | The November 21 Qwen rollout loaded all 84,337 expected rows into Snowflake. It ended unsubmitted after 24 turns with reward 0. Neither evaluator ran against Snowflake. | Live load verified. Scored agent submission pending. |
| Real Tinker RL update | A previous pilot completed one optimizer step from execution-derived SQLite rewards and verified a changed probe and matching checkpoint metadata. | Complete |
| Submission materials | The repository records the current results and reproduction commands. | Final baseline handoff pending |

[Latest credentialed rollout](evidence/books-snowflake-final.md) ·
[Hosted model correctness and diagnostics](evidence/books-full-baseline.md) ·
[Hosted submission and official preflight](evidence/books-context-completion.md) ·
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

## Hosted 9B rehearsal

With context compaction and live column inspection, the hosted
`Qwen/Qwen3.5-9B` rehearsal independently repaired and submitted its
tested publisher and customer SQL files. Both pinned evaluators ran
through DuckDB. Stage 1 was 1.0, Stage 2 was 0.0, and the reward was
0.35. The model spent 27 of the 54 reserved tokens on its final
tool call. That rehearsal verified submission and grading. The three output
models still had to pass the same evaluator.
[Trajectory, evaluators, and usage](evidence/books-context-completion.md)

Executed command for the local hosted run:

```powershell
$env:HF_HOME = (Resolve-Path runs/books-offline-model/hf).Path
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.insert(0,""scripts""); sys.path.append("".venv-core/Lib/site-packages""); runpy.run_path(""scripts/books_model_rehearsal.py"",run_name=""__main__"")' --hosted --allow-paid --budget-usd 0.10 --checkout ../upstream-elt-bench --assets runs/books-assets --out runs/books-context-loop/attempt-01
```

The uncached bound was **USD 0.095084544** for 24 turns, 12,288 context
tokens, and 8,192 sampled tokens. Measured usage implies **USD
0.015649827**. The DuckDB rehearsal used no Snowflake compute.

## Final live command

The local score requirement passed in `stronger-13`. The command below
matches that run's model, renderer, and limits. The official rollout still
requires separate authorization for Snowflake and Tinker.

The authoritative model entry point is `elt_rl.run official-rollout`.
The candidate is `Qwen/Qwen3.6-35B-A3B` with its pinned no-thinking
renderer. The runner records prompt and action token IDs in an ignored
run directory. It permits one agent, 32 turns, 48 tool calls, ten
transform attempts, one grading replay and a 40-minute rollout timeout.
The Tinker profile uses 12,288 context tokens, 12,288 total sampled tokens,
and at most 2,048 sampled tokens per turn. Snowflake authentication,
warehouse visibility, grants, and monitor attachment passed read-only
checks.
[Official setup](LIVE_SETUP.md#official-snowflake-books)

The refreshed Airbyte probe completed six local syncs and matched all
15 counts, totaling 84,337 rows. Probe cleanup completed. The worker
has one sync attempt per job. [Preflight evidence](evidence/books-full-baseline.md#full-score-hosted-submission)

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
./.venv/Scripts/python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); from elt_rl.run import main; raise SystemExit(main())' official-rollout --books-35b-profile --allow-paid --allow-warehouse --rollout-seconds 2400 --budget-usd 0.20 --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5_disable_thinking --out runs/books-official-qwen35b-001 2>&1 | ForEach-Object ToString | Tee-Object runs/books-official-qwen35b-001-console.txt
```

The runner checks current rates before creating a Tinker session. The
uncached token bound for this Qwen3.6-35B profile is **USD 0.19335168**.
The full-score local run used an estimated USD 0.03314277. Previous
Snowflake runs used approximately 0.25–0.32
credits to load and execute without grading. Two comparable passes give
**0.50–0.64 credits** as a planning range before headroom for grading and
cleanup. A continuously active standard Gen1 X-Small warehouse uses
1 credit in 60 minutes. The refreshed administrator console confirmed
attachment and approximately 0.78 credits until immediate suspension.
Forty minutes of continuous Gen1 X-Small compute is 0.667 credits.
The monitor remains the backstop for in-flight work, resume minimums,
other metered usage, and cleanup.
[Latest checks and commands](evidence/books-context-completion.md#official-rollout-readiness)
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
