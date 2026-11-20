# Official `books` SQL validation and feedback

The second credentialed rollout loaded all 15 streams into Snowflake and
ended before submission. The saved trace shows that the validator stopped at
the first failing file and omitted its name. Once the publisher file cleared
the first check, the customer's SQL parse error hid the author's undefined
CTE. The model repeatedly edited `publishers.sql` after that file stopped
producing a diagnostic. [Full failure reconstruction](../FAILURE_ANALYSIS.md)

## Implementation

- `src/elt_rl/official.py` validates every required model file before sending
  warehouse statements. It returns one actionable diagnostic per invalid
  file in the same tool response. Valid siblings are omitted. After local
  validation succeeds, only the first failed warehouse statement is reported,
  with the relevant file and any safe compiler details Snowflake supplies.
- `src/elt_rl/official_sql.py` reports parser locations and resolves CTE scope
  within each file using Snowflake identifier casing. The three task outputs
  depend on raw inputs and their own CTEs. Output files do not supply tables
  to one another. The SQL safety checks, task specification, submission
  gate, pinned grader and reward weights are unchanged.
- `tests/test_official.py` covers the archived error patterns, mixed-case and
  quoted CTE resolution, the exclusion of a repaired sibling, and attribution
  of a simulated Snowflake compiler error with credentials omitted.

## Offline evidence

Executed from the repository root on November 20, 2026. The existing Windows
virtual environment uses the base Python installation for `pytest`. The pinned
renderer and Terraform checks were enabled.

```powershell
$env:CHECKPOINT_DISABLE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:ELT_TEST_REAL_RENDERER = '1'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:ELT_TEST_TERRAFORM = (Resolve-Path .venv-core/tf-tools/terraform.exe).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/books-feedback-tests-final""]))' 2>&1 | ForEach-Object ToString | Tee-Object runs/books-machine/books-feedback-tests-final.txt
```

The suite exited 0 with **69 passed in 38.05 seconds**. It includes the pinned
official evaluator integration with a synthetic Snowflake connector.

The archived replay used the saved token IDs, the pinned Qwen renderer and
the real episode loop and SQL validator. Source loading reused the original
receipt without contacting Airbyte or Snowflake. The harness compared the
new tool events to the archived calls and decoded the next prompt to verify
delivery of every diagnostic. No warehouse statement or evaluator was
called. The replay matched **24 responses and 30 tool calls**.

| Turns | Diagnostics present in the next rendered observation |
| --- | --- |
| 10 | `publishers.sql` line 11 column 35, unresolved `PUBLISHER_BOOK_COUNTS` relation. `customers.sql` line 93 column 47, expected `)`. `authors.sql` line 79 column 50, unresolved `WROTE_FEWER_TOTAL_PAGES_THAN_THE_AVERAGE` relation. |
| 14, 17, 19, 21, 23 | `customers.sql` line 67 column 105, malformed `CAST` missing `AS` and a target type. `authors.sql` line 76 column 50, the same unresolved relation. No publisher diagnostic. |

The replay uses fixed historical actions, so it remained unsubmitted with
reward 0. It establishes delivery and attribution. The independent local
smoke used fresh adaptive generation from the preinstalled `llama3.2:latest`
in Ollama with a small credential-free SQLite fixture and the real validator.
It ran eight unchanged transform attempts and two premature submission attempts
across 10 turns, ending unsubmitted with reward 0. The model and data differ
from the official run, so this does not measure Qwen's response to the fix.

```powershell
$env:TINKER_TELEMETRY = '0'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import runpy,sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_path(""runs/books-official-003/failure-replay/replay-fixed.py"", run_name=""__main__"")'
.\.venv-core\Scripts\python.exe -u runs/books-official-003/failure-replay/local-model-smoke.py
```

Replay scripts and output are under the ignored `runs/books-official-003/failure-replay/`
directory on the run host. Relevant files are `replay-fixed.py`,
`replay-fixed-output.txt`, `fixed-tools.jsonl` and `local-model-smoke.json`.
The live trajectory and source data stay outside Git.

## Next rollout readiness

The metadata preflight exited 0 after Docker Desktop and the local sources
were restarted. It found the Airbyte workspace and published custom source,
verified the pinned checkout and evaluator assets at
`3b068d5f15f64541d05fbc33a817e4b08c6bf173`, and authenticated with the Snowflake
service RSA key. A separate check confirmed the active published Airbyte
manifest matched upstream. All three local reference CSV hashes matched the
recorded hashes. [Reference hashes](live-readiness.md#official-snowflake-books)

```powershell
$privateDir = Join-Path $env:LOCALAPPDATA 'ELTBenchBooks'
$env:ELT_BOOKS_INPUT_DIR = Join-Path $privateDir 'books'
$env:ELT_SNOWFLAKE_CREDENTIAL_JSON = Join-Path $privateDir 'snowflake.json'
$env:ELT_AIRBYTE_URL = 'http://127.0.0.1:18000/api/public/v1'
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --snowflake-probe |
  Tee-Object runs/books-machine/books-feedback-metadata-preflight.json
```

Read-only `SHOW DATABASES` found no remaining database from the second
official run. `SHOW WAREHOUSES` reported `ELT_BOOKS_WH` suspended, `X-Small`,
60-second auto-suspend and auto-resume enabled. The service role sees no
resource monitor rows. The last administrator reading was **0.45 credits
used**, against a **1.50-credit cumulative suspension trigger**. An
administrator must refresh the monitor assignment, current usage and
remaining headroom before launch. The read-only checks did not test creating
or dropping a fresh Snowflake namespace. [Last administrator reading](books-snowflake-second.md)

The restarted Airbyte worker reported `1` for all five retry limits. After
the LocalStack restart, `seed-compose.py s3` restored the two pinned S3 files
with 232 and 4 rows. On the first full local source probe, the File 0.5.23
check for `address_status` (job 18) could not reach `drive.google.com:443`
and failed with `[Errno 101] Network is unreachable`. Airbyte made one attempt,
and an independent cleanup check found no remaining probe connection, source,
destination or PostgreSQL database. Both pinned HTTPS URLs subsequently
returned HTTP 200 from the Airbyte worker. The pinned paths were used
throughout.

The full local preflight ran in the same private environment as the
metadata check.

```powershell
$docker = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --source-probe --docker $docker --docker-context desktop-linux |
  Tee-Object runs/books-machine/books-feedback-source-probe.json
```

The second invocation targeted `books-feedback-source-probe-recheck.json`.
Docker stopped before that process finished, so the file was never written.
After restart, Airbyte job history confirmed success for `address_status`,
`custom_api`, and `mongodb`. The recovery command uses the original local
Terraform state, skips completed jobs, checks the PostgreSQL counts, and
cleans up that probe's resources.

```powershell
.\.venv-core\Scripts\python.exe -u runs/books-machine/recover-books-feedback-sources.py 2>&1 |
  ForEach-Object ToString | Tee-Object runs/books-machine/books-feedback-source-recovery.txt
```

The recovery exited 0. Airbyte reported one successful attempt per connection,
and PostgreSQL matched all 15 pinned Stage 1 input counts, **84,337 rows** in
total. The script verified zero remaining probe connections, sources,
destinations and databases. Full counts and receipts are recorded in the
ignored `runs/books-machine/books-feedback-source-recovery.json`.

| Source group | Airbyte job | Committed records |
| --- | ---: | ---: |
| `address_status` | 19 | 2 |
| `custom_api` | 20 | 19,933 |
| `mongodb` | 21 | 22,362 |
| `order_status` | 52 | 6 |
| `postgres` | 53 | 41,798 |
| `s3` | 54 | 236 |

The comparison should use the base `Qwen/Qwen3.5-4B` and the same `books`
task, disabled thinking renderer and 35%/65% reward weights as the second
run. At 24 turns, 32 tool calls, a 16,384-token context, 2,048 sampled tokens
per turn and 8,192 sampled tokens total, the public rates checked November
20 still bound sampling at **USD 0.13799424**. This estimate charges every
prefill token at the uncached rate. Confirm Snowflake headroom for Airbyte
loading, transform execution, fresh grading replay and both official stages
before a separately authorized launch. This verification started no Tinker
sampling, training or Snowflake warehouse compute. Both live evaluation
stages remain pending.
[Tinker public rates](https://tinker-docs.thinkingmachines.ai/tinker/models.json)
