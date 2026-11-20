# Second authorized official `books` rollout

Run date November 20, 2026 UTC. Runner commit `7bd5382`, upstream ELT-Bench
`3b068d5f15f64541d05fbc33a817e4b08c6bf173`, local Airbyte 1.5.1 and one
sampling-only Tinker rollout on `Qwen/Qwen3.5-4B`.

## Launch checks

- Snowflake rejected `CREDIT_QUOTA = 1.5`. The dedicated warehouse monitor
  retained its 1.00-credit base and was configured to immediately suspend at
  150%, an effective cumulative threshold of 1.50 credits. The updated action
  was read back from `SHOW RESOURCE MONITORS`. It showed 0.13 credits already
  used, leaving approximately 1.37 credits to the revised trigger.
  The trial console displayed `$400 of $400 left` after rounding.
  [Snowflake threshold semantics](https://docs.snowflake.com/en/sql-reference/sql/alter-resource-monitor)
- The five Airbyte job retry limits were set to 1 in the running worker and
  verified from the worker's environment. A local check exercised the deployed
  `RetryManager` class with those limits. It returned
  `complete=false partial=false legacy_max=1` after a first failure of each
  type. The Helm override rendered the same five values for future deployment.
- The official metadata preflight exited 0, including Airbyte workspace and
  Snowflake service login checks. Readback confirmed all six prior local jobs,
  all 15 pinned streams and 84,337 committed records. Both LocalStack objects
  were present. The active custom source manifest and all three evaluation
  reference hashes matched their pinned versions. The run did not repeat the
  local sync preflight.
- The runner retrieved public pricing and recorded a pre-session token cost
  bound of **USD 0.13799424**, below the authorized **USD 0.15**.
  [Tinker prices](https://tinker-docs.thinkingmachines.ai/tinker/models.json)

## Authorized command

```powershell
$booksPrivate = Join-Path $env:LOCALAPPDATA 'ELTBenchBooks'
$env:ELT_BOOKS_INPUT_DIR = Join-Path $booksPrivate 'books'
$env:ELT_AIRBYTE_URL = 'http://127.0.0.1:18000/api/public/v1'
$env:ELT_SNOWFLAKE_CREDENTIAL_JSON = Join-Path $booksPrivate 'snowflake.json'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:CHECKPOINT_DISABLE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_module(""elt_rl.run"", run_name=""__main__"")' official-rollout --allow-paid --allow-warehouse --model Qwen/Qwen3.5-4B --budget-usd 0.15 --out runs/books-official-003 2>&1 |
  ForEach-Object ToString | Tee-Object runs/books-machine/books-official-003-console.log
```

The launcher created a fresh run directory at 05:25:10 UTC. In turn 3 the
agent selected all 15 input streams.

## Executed result

| Airbyte job | Source | Records committed to Snowflake | Attempts |
| --- | --- | ---: | ---: |
| 12 | Original Drive `address_status` | 2 | 1 |
| 13 | Custom API | 19,933 | 1 |
| 14 | MongoDB | 22,362 | 1 |
| 15 | Original Drive `order_status` | 6 | 1 |
| 16 | PostgreSQL | 41,798 | 1 |
| 17 | LocalStack S3 | 236 | 1 |

All six jobs succeeded. The agent's Snowflake inspection showed all 15
tables at their pinned Stage 1 counts, for 84,337 rows. The jobs ran from
05:30:23 to 05:50:19 UTC. The rollout ended at 05:53:34 UTC with exit 2,
`rollout_unsubmitted`, and an episode reward of **0.0**.

No transform reached Snowflake. The saved SQL reproduced the tool failures
offline. The first publisher and author queries referenced undefined tables
or CTEs, including `publisher_book_counts` and
`wrote_fewer_total_pages_than_the_average`. The later publisher SQL passed
validation. The customer SQL retained an invalid `CAST` expression at
line 67, and the author reference remained unresolved. The tool reported
validation failures without identifying the file, and the agent spent its
remaining turns changing the publisher query. The host never replayed a
submission. Both official evaluator outputs are absent from this run.

The raw connector logs and API job receipts are in the private local
`%LOCALAPPDATA%/ELTBenchBooks/airbyte-official-003/` directory. The run
directory `runs/books-official-003/` holds the manifest, all sampled token
IDs and log probabilities, the tool and SQL trace, the Airbyte audit and
`sql-validation-audit.json`. Airbyte's read-only cleanup check found zero
run-owned sources, connections or destinations.

## Usage and cleanup

- The Tinker trace contains 24 responses with unique sequence IDs and finite
  log probabilities aligned to all sampled tokens. An independent token audit
  matched both the rollout transcript and manifest. It counted **7,739 sampled
  tokens**, **128,384 cached prefill tokens** and **11,390 uncached prefill
  tokens**. The published-rate estimate for this observed usage is **USD
  0.020009739**. The read-only billing endpoint returned zero posted rows at
  05:54:11 UTC. Final Tinker billing remains pending.
- The warehouse monitor reported **0.13 credits** used before the run and
  **0.45 credits** used at 05:56:50 UTC. The rounded monitor delta is
  **approximately 0.32 Snowflake credits**. The values are the monitor's
  readings and may differ from final billed credits.
- The service-role cleanup check found zero remaining run databases. The
  dedicated warehouse was `SUSPENDED`, with 60-second auto-suspend. Both the
  service account and the dedicated monitor remained configured.

Manifest SHA-256:
`d90bdea0d2d7102d4a5750413934e38a3ec8a5b0496db8743fc5ab9b1cff5bc9`.
Sample trace SHA-256:
`45a2cae4be467089a697e0a58baf940cae143afe5401b24528b208e4f5021f75`.
The private run directory includes `audit-result.json`,
`airbyte-audit.json`, and `snowflake-cleanup-verification.json`.
