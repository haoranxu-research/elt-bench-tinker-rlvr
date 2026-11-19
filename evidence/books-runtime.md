# Official books runtime audit

Executed on 2026-11-19 from the Windows project checkout, based on `c365e5b`.
The upstream checkout was clean at
`3b068d5f15f64541d05fbc33a817e4b08c6bf173`. No credentialed official rollout
was performed, and no live evaluator, execution-derived reward, or Snowflake
receipt exists for this task.

## Host and source execution

`Get-Command` found no Docker, abctl, Podman or kubectl in PATH. Docker
Desktop was absent at its default installation path, and the Docker engine
named pipe was absent. `wsl --status` exited 50 and `wsl --list --verbose`
exited 1. The host reported 18 logical processors, 31.6 GiB total RAM,
7.3 GiB free RAM during inspection, 50.7 GiB free on C: and 557.8 GiB free on
S:. Virtualization firmware and SLAT were reported enabled. No operating
system virtualization features were installed or enabled. A portable
Compose build passed configuration validation and confirmed the daemon was
unavailable.

```powershell
& ./runs/books-native/docker-compose.exe version
& ./runs/books-native/docker-compose.exe -p elt-docker -f runs/books-runtime-verified/elt-docker/docker-compose.yml config --quiet
& ./runs/books-native/docker-compose.exe ls
```

Compose v2.35.1 returned 0 for config validation and warned that the pinned
file uses an obsolete `version` attribute. `ls` exited 1 with
`open //./pipe/docker_engine: The system cannot find the file specified`.
The legacy Airbyte chart index contains chart 1.5.1 with app version 1.5.1.
LocalStack and the Airbyte cluster require a usable Linux Docker engine.

```powershell
.\.venv-core\Scripts\python.exe -m elt_rl.books_setup --checkout ../upstream-elt-bench stage --assets runs/books-assets --out runs/books-runtime-verified
$env:PYTHONPATH=(Resolve-Path src).Path
python -m elt_rl.books_setup --checkout ../upstream-elt-bench rest-check --runtime runs/books-runtime-verified
python runs/books-native/check.py postgres
$env:PYTHONPATH=(Resolve-Path src).Path+';'+(Resolve-Path runs/books-native/python).Path
python runs/books-native/check.py mongodb
```

All four commands exited 0. Staging parsed each input and checked its count
against the official `evaluation/table.json`. The runtime directory contains
the pinned source setup and the public `books-template`. PostgreSQL 16.16
and MongoDB 8.0.21 ran as temporary loopback processes from vendor archives,
without a system install. The PostgreSQL harness executed the pinned
`postgres.sh` with Git Bash and verified using SQL counts. The MongoDB harness
created a single-node `rs0` replica set, ran the pinned `mongo.py` with the
staged books-only manifest, and verified using collection counts. Both
servers were stopped. No listeners remained on 5433, 27017, 5005, 4566,
or 8000. The real HTTP smoke test used the pinned Flask app on an ephemeral
loopback port and checked page lengths, counts, and end-of-stream responses.
All 25 requests returned 200. The local Anaconda environment emitted an
optional pandas/numexpr version warning, and all responses matched.

| Source | Staged row counts | Runtime evidence |
|---|---|---|
| PostgreSQL | address 1,000; cust_order 7,550; customer_address 3,350; order_history 22,348; order_line 7,550 | All five counts confirmed with `psql` on a native PostgreSQL server |
| MongoDB | author 9,235; book 11,127; customer 2,000 | All three counts confirmed against a native MongoDB replica set |
| REST | book_author 17,642; book_language 27; publisher 2,264 | All three confirmed over paginated HTTP |
| LocalStack S3 | country 232; shipping_method 4 | CSV files parsed and counted. Bucket sync pending. |
| Public flat files | address_status 2; order_status 6 | Downloaded JSONL and CSV parsed and counted. Airbyte sync pending. |

The three local reference SHA-256 digests matched the
[recorded reference hashes](live-readiness.md#official-snowflake-books).
The machine-specific harness and logs are in ignored `runs/books-native/`
and `runs/books-runtime/`. The source asset archives and credentials are
outside version control.

## Official preflight and access

```powershell
.\.venv-core\Scripts\python.exe -m elt_rl.books_setup --checkout ../upstream-elt-bench bind-airbyte --credentials runs/books-runtime/setup/airbyte/airbyte_credential.json --out runs/books-private/books
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --snowflake-probe
```

Both commands exited 2. The local environment lacks the published
Airbyte workspace/definition credential JSON, `ELT_AIRBYTE_URL`,
`ELT_BOOKS_INPUT_DIR`, and `ELT_SNOWFLAKE_CREDENTIAL_JSON`. The binder created no
private config. The preflight passed the checkout, dependency, Terraform and
reference checks and avoided both service requests. Warehouse visibility,
role privileges, actual source transfers, and isolated namespace cleanup
remain unverified live. No Snowflake account, trial, warehouse, or schema
was created. The [operator runbook](../LIVE_SETUP.md#official-snowflake-books)
has the exact setup, RSA binding, grant, probe, rollout, and cleanup commands.

## Correctness and regression evidence

The runtime now derives routing, built-in connector definitions and namespace
policy from the verified public checkout. The private binding contributes
four fields for Airbyte authentication, the workspace and the published
custom definition. Snowflake credentials use a separate host-side JSON and
remain outside model tools. The evaluator is invoked against the second,
fresh Snowflake database created by submission. Stage 1 gates Stage 2.
A missing or malformed result cannot become an accepted grade, and the
adapter counts a Stage 2 match only when the upstream verdict has status
`ok`. Cleanup is required before assigning the replay grade. Per-attempt
Airbyte jobs, decoded tool arguments and feedback, and sampled token IDs
support investigation of failed runs.

```powershell
Get-Content .env.example | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.TrimEnd('=')) -ErrorAction SilentlyContinue }
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:TINKER_TELEMETRY='0'
$env:CHECKPOINT_DISABLE='1'
$env:ELT_TEST_TERRAFORM=(Resolve-Path .venv-core/tf-tools/terraform.exe).Path
$env:TF_CLI_CONFIG_FILE=(Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:ELT_TEST_REAL_RENDERER='1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/books-runtime-tests""]))'
```

```text
............................................................             [100%]
60 passed in 36.59s
```

The tests exercise the pinned upstream evaluator with a synthetic warehouse
connector and run Terraform provider-schema validation offline. Those checks
do not establish Snowflake integration. The preflight JSON and full local
test and service logs are retained in ignored `runs/books-runtime/`.

## Remaining actions and costs

1. Enable WSL2 and Docker Desktop with administrator approval or provide an
   existing isolated Linux Docker host. Deploy Airbyte and the remaining
   source services, publish the custom connector, and bind the private config.
2. Have the Snowflake administrator provision or designate an authorized
   account, service user, role and monitored warehouse. Register the RSA
   public key. Store the private credential JSON locally, then run the
   connectivity and separately approved namespace probes.
3. Authorize the Snowflake usage and model sampling for one official rollout.
   Tinker sampling for this rollout is separate from the completed pilot.
   Retain the agent trace and grader evidence, then confirm cleanup.

New paid service charges for this audit were USD 0. The illustrative Snowflake
compute estimate is USD 0.50 to 2.00 for 15 to 60 billed minutes at USD 2 per
credit and one credit per hour. Warehouse time and actual costs remain
unmeasured. At the [previously observed Tinker rate card](live-readiness.md#tinker),
one official rollout has a token estimate of USD 0.1380 using at most
393,216 uncached prefill tokens and 8,192 sampled tokens. The runner refreshes
the prices before sampling. [Warehouse cost and trial terms](../LIVE_SETUP.md#warehouse-cost)

To resolve the commit recording this audit, run
`git log -1 --format=%H -- evidence/books-runtime.md`. To check the current
working tree, run `git status --porcelain`.
