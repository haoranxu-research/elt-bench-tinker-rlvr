# Read-only live acceptance checks

Checks on 2026-11-19 UTC from the local project. The credential was read
from the ignored environment file. No principal identity, billing rows,
or credential value was retained.

## Tinker

The installed SDK points at
`https://tinker.thinkingmachines.dev/services/tinker-prod`. The key
endpoint was called with the SDK's documented CLI authentication header,
an explicit production hostname, TLS, and redirects disabled. Capabilities
and a single completed UTC-hour billing query used the installed 0.39.2 SDK.

```text
GET /api/v1/auth/apikey/me -> HTTP 200
key_validated = true
RestClient.get_server_capabilities() -> Qwen/Qwen3.5-4B
max_context_length = 65536
sampleable = true
trainable = true
explicit_project_configured = false
AdminClient.get_billing_usage(...) -> allowed
```

The API reports model capabilities for the authenticated organization.
The Default project will be used because the project ID is unset. The
checks leave project session creation and remaining balance unverified.
The billing check verified usage read access. It did not retain any
organization-wide usage or claim an invoice amount.

`fetch_model_pricing("Qwen/Qwen3.5-4B", timeout=15)` returned the following
USD per million tokens. [Published price table](https://tinker-docs.thinkingmachines.ai/tinker/models/models_and_pricing/)

| Uncached prefill | Cached prefill | Sampling | Training |
|---:|---:|---:|---:|
| 0.33 | 0.066 | 1.005 | 0.737 |

The three-member pilot estimates USD 0.4904 for tokens at these rates,
including its single verification forward pass. The actual bill depends
on usage. No Tinker session, model sampling, training, optimizer or
checkpoint request has been made. The Cookbook tests checked concrete
sampled target IDs and behavior log probabilities with scripted actions
and real SQLite rewards. The optimizer and checkpoint metadata tests use
test doubles. [Pilot command and reconciliation steps](../LIVE_SETUP.md#tinker-pilot)

## Official Snowflake books

Read only the three published references from the pinned dataset into
ignored `runs/books-assets/gt_snowflake/books/`. [Dataset revision](https://huggingface.co/datasets/tttjjj/elt_bench/tree/1ed5861e60b00a67746e02541139af50c903df6b/gt_snowflake/books)

| File | SHA-256 |
|---|---|
| authors.csv | `1221bea8c2d1d7d4b129c032ed7f18970b6a0dae878033fdc595611f9e53aef9` |
| customers.csv | `4042eeb5b38df4e93dfc93c0ff203e2a79f7aa586d649b378b4535e1fec39f71` |
| publishers.csv | `a9b2d1ace59c594f7696d66f23f2eecb02b8eccd71f4e7eebc50ee839296f906` |

Local `.env` now points at the pinned benchmark checkout, locally installed
Terraform, and the downloaded references. The following command verified
the checkout, Terraform and all three CSVs. It exited 2 because the generated
private input bundle, Airbyte URL and Snowflake credential JSON are missing.
Service probes were omitted.

```powershell
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official
```

The official source archives exposed ZIP entries through HTTP Range.
The selected `books` inputs are staged under ignored
`runs/books-assets/data-db/data/books/` and
`runs/books-assets/data-api/data/books/`, with the original flat-file
downloads in `runs/books-assets/flat-files/`. A local count comparison
matched all **15** inputs to the pinned Stage 1 table expectations.
The upstream Flask app responded through its in-process test client.

```text
book_author 200 17642 records
book_language 200 27 records
publisher 200 2264 records
address_status jsonl 2 rows
order_status csv 6 rows
15 local source streams match pinned books Stage 1 row counts
books-only Mongo seed manifest prepared
```

These checks cover source assets and the pinned REST implementation.
They leave actual connector synchronization and warehouse materialization
unverified.

The adapter and preflight now support a Snowflake RSA service key, and the
Airbyte configuration uses the pinned provider’s key-pair credential block.
A synthetic encrypted PKCS#8 key and negative passphrase case covered that
path offline. The provider’s schema check used an inert key value and a
loopback placeholder. The official evaluator was exercised in tests with
a synthetic connector. No account or Snowflake workload was provisioned.
[Credentials, deployment, qualifying trial and costs](../LIVE_SETUP.md#official-snowflake-books)

## Final offline test run

```powershell
Get-Content .env.example | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.TrimEnd('=')) -ErrorAction SilentlyContinue }
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:TINKER_TELEMETRY='0'
$env:CHECKPOINT_DISABLE='1'
$env:ELT_TEST_TERRAFORM=(Resolve-Path .venv-core/tf-tools/terraform.exe).Path
$env:TF_CLI_CONFIG_FILE=(Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:ELT_TEST_REAL_RENDERER='1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/live-readiness""]))'
```

`55 passed in 36.38s`. This includes the downloaded public tokenizer,
synthetic checkpoint verification, and the pinned Terraform provider's
validation of password and key-pair resource schemas.
