# Books submission workflow and model readiness

This is the record of the local-model investigation. The next rehearsal
uses hosted sampling. [Updated launch evidence](books-hosted-readiness.md)

## Scope and outcome

The November 21 credentialed attempt used genuine Tinker samples and loaded
84,337 rows into Snowflake. At turn 21 Snowflake materialized
`publishers.sql` and `customers.sql`, then rejected `authors.sql` with
SQLSTATE `42601`. The tool returned the failure and withheld the successful
files from submission eligibility. The agent attempted another full batch
at turn 24 and hit the four-attempt cap without calling submit. The
warehouse diagnostics already reached the agent. Repeated batch execution,
SQL errors, missing per-file state, and the execution cap all contributed.
The recorded identifier, static syntax and qualification failures establish
concrete model errors. One trajectory cannot isolate the effect of model
capacity. [Original credentialed trace summary](books-snowflake-final.md)

The revised workflow lists approved bare filenames in tool schemas, gives
repair instructions for malformed load JSON, and treats `file=load.json`
as an explicit way to load the saved manifest. It retains successful files
from a partially failed Snowflake batch, shows the budget and current
tested files on each observation, and raises the transform cap from four
to seven. The final turn and final tool call are reserved for explicit
submission. An early response without tools receives one reminder. The
agent still has to write and test its own files and explicitly submit on
a later turn. The fresh replay, pinned evaluator, and reward formula are
unchanged. Implementation commit `10c477c`.

## Verification and its limits

| Run | Actual result |
| --- | --- |
| Full offline suite with the real pinned renderer and Terraform schema tests enabled | 78 passed in 43.44 s, exit 0. Tests include split batch success, later-turn partial submission in a fresh replay, final-turn protection, and bounded text recovery with unsubmitted reward zero. |
| Archived official tool trajectory against current workspace rules and DuckDB execution | 31 tool calls across 24 turns replayed. No submit, no evaluator replay, reward 0. The DuckDB errors are local results. Original Snowflake feedback is preserved alongside them. |
| Genuine local Llama 3.2 run with native Ollama tool calls and the same episode dispatcher and schemas | The final run used 19 turns and 32 tool calls, including an actual early `submit_pipeline` attempt. The load manifest lacked a valid `sources` object and no transformation was tested. The host rejected submission. Reward 0, evaluator unexecuted, exit 2. The native chat format differs from the pinned Qwen token format. |
| Host-provided reference SQL with pinned evaluators over DuckDB transport | Full reference Stage 1 and Stage 2 both 1, reward 1. With one model absent, Stage 2 was 2/3 and reward 0.7833333. With one wrong raw count, Stage 1 was 14/15 and Stage 2 skipped, reward 0.3266667. This is the separate evaluator control. |
| Qwen3.5-9B tokenizer and renderer preflight | Exact tokenizer revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a` cached and tested offline. The pinned renderer built a prompt, then decoded all 24 archived 4B actions into the same sequence of 31 tool calls. No new model samples were used in this check. |

The earlier local Llama attempts exposed a skipped task read, invalid path
prefixes, and tool calls written as chat text. The corresponding changes
were tried in fresh runs. The final run advanced to a real submit action
but did not load or pass grading. Ollama blob transfers stalled and the
pinned public GGUF download failed with repeated HTTP transfer timeouts.
No local Qwen3.5-9B weights became available on S. The strongest achieved
model rehearsal remains ungraded.

### Reproduce the local checks

From the repository root in the existing Windows workspace:

```powershell
$env:CHECKPOINT_DISABLE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:ELT_TEST_REAL_RENDERER = '1'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:ELT_TEST_TERRAFORM = (Resolve-Path .venv-core/tf-tools/terraform.exe).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/books-submit-verified-test""]))'
.\.venv-core\Scripts\python.exe scripts/books_evaluator_smoke.py offline --checkout ../upstream-elt-bench --assets runs/books-assets --sql-dir runs/books-reference/sql --out runs/books-reference/evaluator-submit-audit
$env:HF_HOME = (Resolve-Path runs/books-offline-model/hf).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.insert(0,""scripts""); sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); runpy.run_path(""scripts/books_model_rehearsal.py"",run_name=""__main__"")' --checkout ../upstream-elt-bench --assets runs/books-assets --port 11434 --local-model llama3.2:latest --native-tools --out runs/books-offline-model/llama-native-v5
```

Choose a new output directory on reruns. A unified Python environment
needs the repository's official and Cookbook extras and DuckDB 1.4.4
for the local scripts. For Qwen, install the public
`qwen3.5:9b` weights in a loopback Ollama instance with model storage and
temporary files on S. Use the same rehearsal command with
`--port 11435 --local-model qwen3.5:9b --model Qwen/Qwen3.5-9B` and omit
`--native-tools`. This mode renders and parses through the production
Cookbook and uses the same episode and pinned evaluator. Ollama samples a
quantized model locally. DuckDB executes the staged public inputs with
Snowflake-to-DuckDB SQL translation. Full rehearsal therefore checks the
tool loop and grading flow, while Snowflake compiler behavior and hosted
sampling require a credentialed run. [Ollama model](https://ollama.com/library/qwen3.5)

Raw model and tool traces, candidate files, the archive replay, and the
test log are under private ignored directory `runs/books-offline-model/`.
The archive replay command was `runs/books-offline-model/archive-replay.py`
with the same Python import path for Torch and DuckDB.

The optional reference-only Snowflake smoke is independently gated and
still unexecuted. It uses the just-verified SQL and the same official
evaluator, with one Airbyte load and no sampling. The live agent command
and this smoke both exited 2 before creating an output directory when
invoked without their paid-execution flags. The Snowflake reference CSVs
configured in `.env` matched all three pinned hashes.

## Read-only cloud checks

The Tinker capabilities endpoint returned all four models below as
sampleable with the saved key. Prices are USD per million tokens. The
per-rollout uncached bounds use 24 turns, a 16,384-token context, and
8,192 sampled tokens. They do not include Snowflake.

| Model | Context | Input / cached input / output | Uncached bound |
| --- | ---: | ---: | ---: |
| Qwen/Qwen3.5-4B | 65,536 | $0.33 / $0.066 / $1.005 | $0.13799424 |
| Qwen/Qwen3.5-9B | 65,536 | $0.30 / $0.06 / $0.807 | $0.124575744 |
| Qwen/Qwen3.6-35B-A3B | 65,536 | $0.45 / $0.09 / $1.335 | $0.18788352 |
| openai/gpt-oss-120b | 32,768 | $0.33 / $0.066 / $0.84 | $0.13664256 |

The 9B variant is the preferred candidate because it has the same
no-thinking tool format, has passed the pinned tokenizer/renderer check,
and has the lowest bound among these candidates. This choice is a
compatibility and cost judgment. Its ability to solve the benchmark is
unverified. GPT-OSS is within the cap and would need separate protocol
verification. The checked 35B MoE exceeds the cap using the same limits.
[Tinker rate card](https://tinker-docs.thinkingmachines.ai/tinker/models.json)
[Tinker renderer documentation](https://tinker-docs.thinkingmachines.ai/tutorials/core-concepts/rendering/)
[Qwen3.5-9B tokenizer source](https://huggingface.co/Qwen/Qwen3.5-9B/tree/c202236235762e1c871ad0ccb60c8ee5ba337b9a)

The current read-only official preflight passed pinned assets, the private
input binding, warehouse login and visibility, and Airbyte workspace and
custom-connector visibility. It used:

```powershell
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --snowflake-probe
```

The fresh local source probe also passed. All six Airbyte jobs (67–72)
completed on attempt 0. The disposable PostgreSQL destination matched
all 15 pinned table counts, totaling 84,337 rows. Sync time was 8 minutes
36 seconds across the six jobs. Cleanup completed and removed the probe
workspace. The command and resulting private receipt were:

```powershell
$docker = (Get-Command docker.exe).Source
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --source-probe --docker $docker --docker-context desktop-linux
```

Receipt `runs/books-offline-model/source-probe.json`, SHA-256
`d7d28d91dc14ea2f51fbffc17f09fcbcd27588b052d2bcf7cbe2b5d6035b2b39`.

`SHOW WAREHOUSES` returned `ELT_BOOKS_WH` suspended, Gen1 standard X-Small,
with auto-resume and 60-second auto-suspend. The service role did not
expose the resource monitor. A fresh read-only Snowsight view under
`ACCOUNTADMIN` confirmed `ELT_BOOKS_MONITOR` attached to
`ELT_BOOKS_WH`, 0.71 credits used, 0.29 left against the 1.00 nominal quota,
and immediate suspension at 150% of quota. That is about 0.79 credits
of effective headroom. The account UI showed about USD 398 in trial
credits remaining. To repeat the metadata check for a later launch:

```sql
SHOW WAREHOUSES LIKE 'ELT_BOOKS_WH';
SHOW RESOURCE MONITORS LIKE 'ELT_BOOKS_MONITOR';
```

At one compute credit per continuously active hour, 0.79 credits covers
about 47 minutes of active compute before minute floors and ancillary
charges. Projected usage is 0.50–0.64 compute credits before grading
margin. A full hour of uninterrupted warehouse use would exceed the
current allowance. The live Airbyte worker deployment confirmed
`SYNC_JOB_MAX_ATTEMPTS=1`. The previous credentialed run's successful
cleanup is in the live run record.
[Snowflake monitor documentation](https://docs.snowflake.com/en/user-guide/resource-monitors)

No new paid Tinker sampling, training, Snowflake workload, or monitor
change occurred. The next accepted result requires an independently
model-authored submission graded against Snowflake in the pinned
evaluator. The [prepared live command](../FINAL_HANDOFF.md#final-live-command)
requires separate authorization. The previous SQLite LoRA update remains
independent evidence.
