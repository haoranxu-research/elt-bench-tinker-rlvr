# ELT-Bench RL environment handoff

## Acceptance status

| Requirement | Executed evidence | Status |
| --- | --- | --- |
| Credential-free, multi-turn ELT | The SQLite trace repaired a failed transform, submitted from a later turn, and earned 1.0 on a fresh replay. The test suite covers faulty input, failed transforms, partial and unsubmitted scores, and cleanup. | Complete |
| Hosted agent submission with pinned books grading | Qwen3.6-35B-A3B independently wrote, executed, and submitted all three outputs on DuckDB. All 15 tables and 84,337 rows were present. Stage 1 = 1.0, Stage 2 = 1.0, reward = 1.0. | Local target complete |
| Credentialed official task | Qwen3.6-35B-A3B loaded all 84,337 rows and submitted two tested models. The best native result was Stage 1 = 1.0, Stage 2 = 2/3. The native grader and trajectory both returned 0.783333. An offline audit used the recorded return and sampled actions to verify training datums. | Full native correctness pending. |
| Real Tinker RL update | A previous pilot completed one optimizer step from execution-derived SQLite rewards and verified a changed probe and matching checkpoint metadata. | Complete |
| Submission materials | The repository records the current results and reproduction commands. | Final baseline handoff pending |

[Earlier credentialed rollout](evidence/books-snowflake-final.md) ·
[35B native grading and diagnosis](evidence/books-snowflake-35b.md) ·
[Latest authorized Snowflake rollouts](evidence/books-snowflake-completion.md) ·
[Offline readiness and proposed local validation](evidence/books-offline-readiness.md) ·
[Hosted model correctness and diagnostics](evidence/books-full-baseline.md) ·
[Hosted submission and official preflight](evidence/books-context-completion.md) ·
[Tinker optimizer evidence](evidence/tinker-pilot.md) ·
[Design](DESIGN.md) · [Professor-facing summary](PROFESSOR_SUMMARY.md)

## Final engineering verification

The fresh probe matched 84,337 rows across all 15 pinned tables in local
PostgreSQL. All six Airbyte jobs succeeded on their first attempt and
the probe cleaned up its resources.
[Latest preflight and reward regression evidence](evidence/books-snowflake-deadlines.md)

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

## Earlier November 21 authorization and checks

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

The next validation gate is one hosted local run using the native profile
and the TEXT date mirror. It requires a new Tinker authorization and uses
no Snowflake compute. [Prepared local command and launch gate](evidence/books-offline-readiness.md#next-validation-and-spending-gate)

The commands below reproduce the two authorized 35B Snowflake rollouts.
Use a fresh output directory and obtain separate authorization before
launching any additional official run.

The authoritative model entry point is `elt_rl.run official-rollout`.
The candidate is `Qwen/Qwen3.6-35B-A3B` with its pinned no-thinking
renderer. The runner records prompt and action token IDs in an ignored
run directory. It permits one agent, 32 turns, 48 tool calls, ten
transform attempts, and one fresh grading replay. The prepared command
uses 40 minutes for agent actions and up to 25 minutes for host grading,
then bounded cleanup. An accepted submission retains its sampled action
and receives its completed grade before the reward reaches the caller.
The Tinker profile uses 12,288 context tokens, 12,288 total sampled tokens,
and at most 2,048 sampled tokens per turn.
[Deadline repair and readiness evidence](evidence/books-snowflake-deadlines.md)

The refreshed Airbyte probe completed six local syncs (jobs 91–96) and
matched all 15 counts, totaling 84,337 rows. Probe cleanup completed. The
worker has one sync attempt per job. [Preflight evidence](evidence/books-snowflake-deadlines.md#next-run-gates)

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
./.venv/Scripts/python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); from elt_rl.run import main; raise SystemExit(main())' official-rollout --books-35b-profile --allow-paid --allow-warehouse --rollout-seconds 2400 --grading-seconds 1500 --budget-usd 0.20 --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5_disable_thinking --out runs/books-official-qwen35b-002 2>&1 | ForEach-Object ToString | Tee-Object runs/books-official-qwen35b-002-console.txt
./.venv/Scripts/python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); from elt_rl.run import main; raise SystemExit(main())' official-rollout --books-35b-profile --books-max-turns 40 --allow-paid --allow-warehouse --rollout-seconds 2400 --grading-seconds 1500 --budget-usd 0.25 --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5_disable_thinking --out runs/books-official-qwen35b-003 2>&1 | ForEach-Object ToString | Tee-Object runs/books-official-qwen35b-003-console.txt
```

The runner checks current rates before creating a Tinker session. The
uncached token bounds were **USD 0.19335168** and **USD 0.23758848**.
The retry raised the turn and tool-call caps to 40 and 60 while keeping
the model, token count limits, and wall-clock deadlines. The dedicated
monitor had a 3-credit quota and an immediate suspension trigger at 2.70
credits, with no reset schedule. The host checked the remaining allowance
before the retry. [Run and spending evidence](evidence/books-snowflake-completion.md)
[Tinker rate card](https://tinker-docs.thinkingmachines.ai/tinker/models.json) ·
[Snowflake warehouse billing](https://docs.snowflake.com/en/user-guide/warehouses-overview#impact-on-credit-usage-and-billing)

After completion, retain the private manifest, token and tool traces,
candidate file snapshots, submitted-file manifest, official Stage 1 and
Stage 2 artifacts, and namespace cleanup evidence under `runs/`.
Record billed usage from the provider and distinguish it from token-rate
estimates and rounded monitor deltas. Report the actual reward and whether
each stage executed. A missing submit continues to earn zero by design.

An earlier November 21 run exited unsubmitted with reward 0. Its recorded token
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
