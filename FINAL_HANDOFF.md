# ELT-Bench RL environment handoff

## Acceptance

| Deliverable | Verified result |
| --- | --- |
| Credential-free local integration | SQLite loaded both sources, reported a file-specific SQL error, accepted the corrected submission and returned 1.0. |
| Hosted Books rehearsal | Qwen3.6-35B-A3B independently submitted all three transformations on the DuckDB TEXT-date mirror. Both pinned stages and the trajectory reward were 1.0. |
| Official native Books | Snowflake attempt 007 loaded all 15 tables and 84,337 rows, accepted all three independent SQL files, and returned **Stage 1 = 1.0, Stage 2 = 1.0, warehouse reward = 1.0, trajectory reward = 1.0**. |
| Reward provenance | All 43 dispatched native calls matched sampled calls. The original 9,334 action tokens and log probabilities aligned with four offline Cookbook datums derived from the recorded reward. |
| Native cleanup | Both transient databases and all run-owned Airbyte resources were gone. The dedicated X-Small warehouse was suspended. |
| Genuine RL update | The separate SQLite pilot completed one live Tinker LoRA optimization step with post-update and checkpoint verification. |
| Optional robustness | Three repetitions of an eight-case SQLite changed-input check verified detection of specific fixed-fixture faults. |

[Native grading evidence](evidence/books-snowflake-007.md) ·
[Tinker optimizer evidence](evidence/tinker-pilot.md) ·
[Implementation design](DESIGN.md) · [Technical report](TECHNICAL_REPORT.md) ·
[Professor-facing summary](PROFESSOR_SUMMARY.md)

## Reproduce local verification

Install the credential-free or full optional test environment as described
in [README.md](README.md). From the repository root:

```powershell
.\.venv\Scripts\python.exe -m elt_rl.cli examples/customer_orders.jsonl
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m elt_rl.robustness --suite --repetitions 3
```

The final full offline suite passed **130 tests in 53.95 seconds** with the
pinned Cookbook and provider, cached public Qwen tokenizer, and optional
real renderer and local Terraform checks enabled. Set
`ELT_TEST_REAL_RENDERER=1` and `ELT_TEST_TERRAFORM` to the local Terraform
executable to include those checks. The executed logs are in
`runs/books-offline-readiness/goal-final-tests.txt` and
`goal-final-sqlite.txt` in the same folder.
[Optional experiment timings and limitations](evidence/changed-input-final.md)

## Final live command

Native attempt 007 ran from implementation commit `073d737`. The native
implementation is unchanged in the final documentation revision. Start
with the [live setup guide](LIVE_SETUP.md) and an existing funded Tinker
project and Snowflake trial. Confirm that Airbyte's six job connections
have one attempt each and that the isolated project warehouse is X-Small,
has a 60-second auto-suspend, and is attached to the dedicated monitor.
Verify at least 1.30 credits before immediate suspension and verify trial
balance. The exact funded checks for the completed run are recorded in
[the native evidence](evidence/books-snowflake-007.md).

On the verified Windows host, the pinned optional Python dependencies
span the virtual environment and base site-packages. The following
preflight and launch reflect that layout. The private configuration and
tokenizer must already be in place.

```powershell
$private = Join-Path $env:LOCALAPPDATA 'ELTBenchBooks'
$env:ELT_BOOKS_INPUT_DIR = Join-Path $private 'books'
$env:ELT_SNOWFLAKE_CREDENTIAL_JSON = Join-Path $private 'snowflake.json'
$env:ELT_AIRBYTE_URL = 'http://127.0.0.1:18000/api/public/v1'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:CHECKPOINT_DISABLE = '1'
$env:HF_HOME = (Resolve-Path runs/books-offline-model/hf).Path
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$tmp = (New-Item -ItemType Directory -Force runs/books-final-tmp).FullName
$env:TEMP = $tmp
$env:TMP = $tmp

.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); from elt_rl.preflight import main; raise SystemExit(main())' official --source-probe --airbyte-probe --snowflake-probe

# Use a new output path for each separate, authorized run.
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); from elt_rl.run import main; raise SystemExit(main())' official-rollout --books-35b-profile --books-max-turns 40 --rollout-seconds 2400 --grading-seconds 1500 --budget-usd 0.25 --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5_disable_thinking --allow-paid --allow-warehouse --out runs/books-official-qwen35b-reproduction
```

The native token estimate bound was **$0.23758848**. The successful run
used **$0.03823716** at published rates on metered tokens. An invoice
entry had yet to post. The Snowflake preflight estimate was **0.75–1.10
credits**. Numeric post-run credit use was not collected. Both the grading
and run-scoped cleanup audits completed.
[Native cost and resource record](evidence/books-snowflake-007.md)

## Submission package

- [README.md](README.md) and [LIVE_SETUP.md](LIVE_SETUP.md) cover local and
  live reproduction, with the pinned upstream revisions.
- [DESIGN.md](DESIGN.md) is the copy-ready implementation design for Google Docs.
- [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md), [FAILURE_ANALYSIS.md](FAILURE_ANALYSIS.md)
  and [the evidence index in README](README.md) document the findings and
  limits of the experiments.
- [PROFESSOR_SUMMARY.md](PROFESSOR_SUMMARY.md) is the concise submission summary.

The official evaluator, expected outputs, and reward formula remain intact.
Raw provider receipts, sampled prompts, credentials, source staging, and
evaluation assets are stored privately or regenerated from pinned upstream
assets. The repository can be shared independently of the private runs.
Use `git log -1 --oneline` and `git status --porcelain` to identify
the submission revision and verify its working tree.
