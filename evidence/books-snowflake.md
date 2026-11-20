# Credentialed official `books` rollout

Run date November 20, 2026 UTC. ELT-Bench was pinned at
`3b068d5f15f64541d05fbc33a817e4b08c6bf173`. The run used Airbyte 1.5.1,
a Snowflake trial with a dedicated X-Small Gen1 warehouse, and one
sampling-only session on `Qwen/Qwen3.5-4B`. The operator approved a
1-credit warehouse monitor and a USD 1 estimated sampling limit.

## Executed checks

```powershell
$booksPrivate = Join-Path $env:LOCALAPPDATA 'ELTBenchBooks'
$env:ELT_BOOKS_INPUT_DIR = Join-Path $booksPrivate 'books'
$env:ELT_AIRBYTE_URL = 'http://127.0.0.1:18000/api/public/v1'
$env:ELT_SNOWFLAKE_CREDENTIAL_JSON = Join-Path $booksPrivate 'snowflake.json'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:CHECKPOINT_DISABLE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --snowflake-probe --namespace-probe
$env:ELT_TEST_REAL_RENDERER = '1'
$env:ELT_TEST_TERRAFORM = (Resolve-Path .venv-core/tf-tools/terraform.exe).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/books-official-pinned-tests""]))'
```

The service preflight exited 0. It authenticated with the Snowflake RSA key,
created and dropped one transient database, and checked the Airbyte binding.
The full offline test suite exited 0 with `60 passed in 63.98s`, including
the pinned renderer and Terraform provider checks. A preliminary pytest
invocation using the default Windows temp directory failed with permission
errors. The successful invocation used the repository-local `--basetemp`.

## Live invocation

The first invocation (`runs/books-official-001`) exited 1 before service
client creation. The official pricing URL timed out during TLS negotiation.
No sampling session, Airbyte sync, or warehouse workload was submitted by
that invocation. A separate HTTPS request returned the catalog. The runner
then used a 25-second pricing request timeout and kept the same fail-closed
cost check. The following invocation created the single live sampling session.

```powershell
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_module(""elt_rl.run"", run_name=""__main__"")' official-rollout --allow-paid --allow-warehouse --budget-usd 1 --out runs/books-official-002
```

The official rate table yielded an upper bound of **USD 0.13799424** before
session creation. This estimate assumed uncached prefill for all 24 turns at
the 16,384-token context limit and up to 8,192 sampled tokens.
[Official rate table](https://tinker-docs.thinkingmachines.ai/tinker/models.json)

After the model first selected only the `address` stream, Airbyte job `2`
loaded it into Snowflake. The agent observed `address=1000` and revised its
configuration to include all 15 required streams in turn 14.

## Result and cleanup

| Check | Observed result |
| --- | --- |
| Manifest start and terminal update, UTC | 03:19:36 to 03:35:25 |
| First load | Airbyte job `2` succeeded from 03:22:03 to 03:25:14 UTC. Airbyte reported 1,000 records emitted and committed. The agent's independent warehouse inspection returned `address=1000`. |
| Full load | Terraform apply stopped during Airbyte discovery, before it queued a sync. The S3 connector reported that `books-bucket` did not exist. The `order_status` file connector reported a network-unreachable error reaching `drive.google.com:443`. |
| Terminal result | Exit `2`, `rollout_unsubmitted`, stop reason `max_turns`, environment reward `0.0`. The final submit call failed because the current artifacts had no successful transform. |
| Official evaluation | No Stage 1 or Stage 2 output. The zero reward comes from the unsubmitted episode rule. |
| Cleanup | API and metadata checks found zero run-owned Airbyte connections, sources, and destinations, and zero remaining run-owned Snowflake databases. The warehouse auto-suspended. |

The sampled trace contains 24 responses with unique sequence IDs and one
finite behavior log probability per token. Prompt and sample lengths match
the rollout transcript. It recorded 5,893 sampled, 62,720 cached prefill,
and 8,964 uncached prefill tokens. There were no training calls.

## Costs

- Tinker sampling cost at the published rates was **USD 0.013020105** for the
  observed tokens. The read-only billing API returned zero posted rows for
  this session at 03:35:58 and 03:46:49 UTC. The estimate is separate from the
  eventual bill.
- At 03:44:03 UTC the dedicated Snowflake warehouse monitor showed **0.13
  credits used** and **0.87 credits remaining** on its **1.00-credit quota**.
  The `ACCOUNTADMIN` result confirmed the monitor was attached to the
  `ELT_BOOKS_WH` warehouse. The service role's result hid the monitor name.
  This is the monitor's rounded cumulative usage. During the audit the
  `SHOW WAREHOUSES … ->> SELECT …` projection briefly resumed the warehouse.
  `ALTER WAREHOUSE ELT_BOOKS_WH SUSPEND` succeeded before the monitor reading.
  The monitor count can include that audit query and does not isolate
  rollout-only usage or final billed credits.
  [Snowflake monitor reference](https://docs.snowflake.com/en/sql-reference/sql/show-resource-monitors)

## Preserved evidence

The private artifacts are under `runs/books-official-001`,
`runs/books-official-002`, and `runs/books-machine`. Raw job logs and job
detail remain under `%LOCALAPPDATA%/ELTBenchBooks/airbyte-official-002`.
The second directory contains `manifest.json`, `sampled-actions.jsonl`,
`pipelines/*.tools.jsonl`, `official/*/airbyte-jobs-*.json`, `audit-result.json`,
`airbyte-audit.json` and `snowflake-cleanup-verification.json`. Its run
manifest SHA-256 is `a033020f3d7161c158325136b4decb1d80becaafb592d9e1fb5d0b897cdd1025`.
The sampled trace SHA-256 is
`05f33b75dc8adc6136f6d9214f3adb9e4f22c405c442e2007132743655c54e61`.

## Local recovery

The LocalStack container was healthy but `awslocal s3 ls` showed no buckets
after the restart. Reseeding restored the original `country.csv` and
`shipping_method.csv`. Downloads from the bucket were byte-identical to the
staged inputs, with 232 and 4 rows respectively. The runbook now reseeds
and verifies the bucket before the rollout.

An HTTP-only mirror experiment failed in local Airbyte discovery because the
pinned File connector upgrades the URLs to HTTPS. That configuration was
discarded. The local follow-up used the original Google Drive URLs again.

The actual Airbyte jobs below used the pinned File and S3 connectors with a
fresh disposable PostgreSQL destination. Each warehouse count matched pinned
Stage 1's input count. The command exited 0. Separate API and PostgreSQL
metadata checks found no remaining resources from the local smoke runs.

| Airbyte job | Source | Records committed | Destination count | Duration |
| --- | --- | ---: | --- | ---: |
| `3` | Original Google Drive `address_status` | 2 | 2 | 120 s |
| `4` | Original Google Drive `order_status` | 6 | 6 | 110 s |
| `5` | Reseeded LocalStack bucket | 236 | `country=232`, `shipping_method=4` | 176 s |

```powershell
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:CHECKPOINT_DISABLE = '1'
.\.venv-core\Scripts\python.exe -u runs/books-machine/smoke-books-original-connectors.py
```

The exact local script, transcript, and job summary are preserved in
`runs/books-machine/` as `smoke-books-original-connectors.py`,
`smoke-books-original-connectors.log`, and `books-connector-upstream-smoke.json`.
The raw job responses are `local-job-{3,4,5}.json` in the private log directory.
The repair used local PostgreSQL only. A fresh credentialed attempt would
still need to complete the full Snowflake transfer and both official stages.

The runner now spells out the full stream-selection rule without the partial
one-stream example. Terraform timeout, process failure, and executable errors
have separate sanitized feedback. The regression test covers all three
failure paths and checks that raw errors cannot echo a secret marker.

With the test environment above and `--basetemp .venv/books-connector-final-tests`,
the final offline suite exited 0 with `63 passed in 58.20s`.
The transcript is `runs/books-machine/offline-tests-connector-final.txt`.
