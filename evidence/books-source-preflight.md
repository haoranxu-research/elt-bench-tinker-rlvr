# Complete official `books` source preflight

ELT-Bench revision `3b068d5f15f64541d05fbc33a817e4b08c6bf173`. The local
source probe exercises the live loader's pinned provider and connection
builder with a disposable PostgreSQL destination. Its expected inventory and
counts come from the pinned Stage 1 manifest. Snowflake and Tinker are
excluded from this preflight invocation.

## Failure analysis

The first credentialed rollout synced `address` successfully in Airbyte job
`2`. The model then requested the complete stream set. Terraform was
creating the six connections and running Airbyte source schema discovery.
The second load queued no Airbyte sync jobs.

| Time (UTC), 2026-11-20 | Failing operation | Exact observed symptom |
| --- | --- | --- |
| 03:29:34 | File 0.5.23 schema discovery for `order_status` | HTTPS connection to `drive.google.com:443` failed with `[Errno 101] Network is unreachable`. |
| 03:32:37 | S3 4.12.2 schema discovery for the S3 group | `The bucket books-bucket does not exist.` |

The File error was in the connector workload. The pinned Drive URLs
subsequently synchronized from Airbyte as documented in the first attempt's
recovery. The original logs establish the network error at that time and
leave the underlying route failure unspecified. The S3 bucket was absent
after LocalStack restarted. Reseeding restored both objects byte for byte.
[Previous rollout and recovery evidence](books-snowflake.md)

This work keeps the original source definitions and URLs. The probe checks
the bound custom API connector's active published manifest against upstream,
runs the six actual connections, and checks every destination row count. A
Terraform apply failure can now identify the failing source or connection
resource address while keeping raw diagnostics in the private Airbyte logs.

## Invocation

```powershell
$booksPrivate = Join-Path $env:LOCALAPPDATA 'ELTBenchBooks'
$env:ELT_BOOKS_INPUT_DIR = Join-Path $booksPrivate 'books'
$env:ELT_AIRBYTE_URL = 'http://127.0.0.1:18000/api/public/v1'
$env:ELT_SNOWFLAKE_CREDENTIAL_JSON = Join-Path $booksPrivate 'snowflake.json'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:CHECKPOINT_DISABLE = '1'
$docker = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --source-probe --docker $docker --docker-context desktop-linux |
  Tee-Object runs/books-machine/full-source-preflight.json
```

The separate manifest comparison passed against the same loopback Airbyte
workspace and source binding. The manifest comparison was integrated after
the full sync invocation had started. The full sync and the additional
comparison therefore have separate execution artifacts.

## Executed results

The local preflight exited 0 and reported `source_sync: pass`. Airbyte 1.5.1
ran all six jobs through the pinned Terraform provider 0.6.5. Each job
succeeded on attempt 0. The separate API readback confirmed the committed
counts below. Each of the **15 destination tables** matched the pinned Stage 1
count, for **84,337 rows** total.

| Job | Source connector | PostgreSQL counts | Committed |
| --- | --- | --- | ---: |
| 6 | File 0.5.23 | `address_status=2` | 2 |
| 7 | Declarative manifest 4.3.0 | `book_author=17642`, `book_language=27`, `publisher=2264` | 19,933 |
| 8 | MongoDB v2 1.5.14 | `author=9235`, `book=11127`, `customer=2000` | 22,362 |
| 9 | File 0.5.23 | `order_status=6` | 6 |
| 10 | PostgreSQL 3.6.29 | `address=1000`, `cust_order=7550`, `customer_address=3350`, `order_history=22348`, `order_line=7550` | 41,798 |
| 11 | S3 4.12.2 | `country=232`, `shipping_method=4` | 236 |

The jobs ran from 03:58:56 to 04:11:50 UTC, or 13m 15s combined. The
complete probe including setup, counts and cleanup took approximately 17
minutes. Independent checks found zero probe-owned Airbyte connections,
sources, and destinations, and zero remaining probe databases.

The report, audit script and audit output are in `runs/books-machine/` as
`full-source-preflight.json`, `audit-full-books-sources.py`, and
`full-source-preflight-audit.json`. The published manifest check is recorded
in `full-source-manifest-check.txt`. Raw Airbyte workload logs and job detail
are private in `%LOCALAPPDATA%/ELTBenchBooks/source-preflight-full/`.

The complete offline suite exited 0 with `66 passed in 60.97s`. It includes
the real pinned renderer and Terraform provider checks, plus regression
coverage for mismatched row counts, a mismatched published manifest, and
sanitized Terraform failure diagnostics.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:ELT_TEST_REAL_RENDERER = '1'
$env:ELT_TEST_TERRAFORM = (Resolve-Path .venv-core/tf-tools/terraform.exe).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/full-books-source-final-tests""]))'
```

Transcript: `runs/books-machine/full-books-source-final-tests.txt`. The
local run produced no new Snowflake or Tinker usage. Snowflake application
of the whole load, the official evaluator results, and the resulting live
reward remain unobserved.

## Prepared live run

The proposed command below is for a new authorization. It will use a fresh
run directory and the existing monitored X-Small Gen1 warehouse. Confirm the
monitor attachment and remaining credits in the raw administrator `SHOW`
results before starting.

```powershell
# Execute only after new authorization.
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_module(""elt_rl.run"", run_name=""__main__"")' official-rollout --allow-paid --allow-warehouse --model Qwen/Qwen3.5-4B --budget-usd 0.15 --out runs/books-official-003 2>&1 |
  ForEach-Object ToString | Tee-Object runs/books-machine/books-official-003-console.log
```

At published rates, 24 turns with up to 16,384 uncached prefill tokens per
turn and 8,192 total sampled tokens give a conservative estimate of **USD
0.13799424**. The runner refreshes pricing before it creates a Tinker session
and checks it against the proposed **USD 0.15** limit.
[Tinker public rates](https://tinker-docs.thinkingmachines.ai/tinker/models.json)

Snowflake X-Small Gen1 consumes one compute credit per active hour, with a
60-second minimum when it resumes. The existing warehouse monitor is
configured for 1.00 cumulative credits. Its last recorded display was
0.87 credits remaining. A clean submission loads the inputs twice, once
for the agent and again for independent grading. Allow roughly 35–50 minutes
based on the local load and replay path. That would use about 0.58–0.83
warehouse compute credits if active continuously. Auto-suspend, connector
timing, and cloud-services usage will affect the actual result. Preserve both Airbyte job
sets, the Tinker usage and session billing, official Stage 1 and Stage 2
results, the resulting reward, and post-run cleanup checks. Record separate
Snowflake meter readings before and after the run.
[Snowflake warehouse billing](https://docs.snowflake.com/en/user-guide/warehouses-considerations)
