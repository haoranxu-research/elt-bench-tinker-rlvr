# ELT-Bench × Tinker

Run a multi-turn, credential-free ELT episode that extracts two CSV sources,
loads an isolated SQLite warehouse, materializes two SQL transformations, and
grades a fresh replay of the submitted pipeline. The sample trace consists of
scripted actions, including a failed SQL run and its repair. The project
includes a pinned Cookbook environment adapter and a test that drives it
with scripted token actions. The same episode interface supports an official
Snowflake `books` rollout and a one-step Tinker LoRA command.

The hosted Qwen3.6-35B-A3B agent authored and submitted all three `books`
transformations on DuckDB. The pinned evaluators returned Stage 1 = 1.0,
Stage 2 = 1.0 and reward = 1.0. The best credentialed Snowflake run
graded a partial submission at Stage 1 = 1.0 and Stage 2 = 2/3.
Its warehouse grade and trajectory reward agreed at 0.783333. Full native
correctness remains open.
[Local scoring evidence](evidence/books-full-baseline.md)
[Native grading and diagnosis](evidence/books-snowflake-completion.md)
[Latest native attempt and connector failure](evidence/books-snowflake-004.md)
[Latest hosted TEXT-date full-score rehearsal](evidence/books-hosted-text-validation.md)

[Implementation design](DESIGN.md) · [Phase 1 evidence](evidence/phase1.txt) ·
[Integration evidence](evidence/integrations.txt) · [Final handoff](FINAL_HANDOFF.md) · [Live Tinker pilot](evidence/tinker-pilot.md)

## Run locally

From the repository root in PowerShell, with Python 3.12 installed:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip --isolated install -e '.[test]'
.\.venv\Scripts\python.exe -m elt_rl.cli examples/customer_orders.jsonl
.\.venv\Scripts\python.exe -m pytest -q --basetemp .venv/pytest-run
```

On macOS or Linux, use `python3 -m venv .venv` and replace
`.\.venv\Scripts\python.exe` with `.venv/bin/python`. The core CLI uses
Python's standard library. Installation may fetch public packages. The CLI
and tests use local files and create no external service clients. Leave
`.env.example` unpopulated for Phase 1.

Omit the trace path to read one JSON object per line from stdin. Each object
takes the form `{"tool":"read_task","arguments":{}}`. Each line consumes
one turn. The final JSON contains host-side metrics, and the CLI exits
with status 1 if the episode ended without submission.

### Observed demo trace

```text
01 read_task: # Local customer orders
03 execute_pipeline: load finished. raw_customers=4, raw_orders=4
06 execute_pipeline: ERROR: order_totals.sql: no such column: wrong_amount
07 write_pipeline_file: saved order_totals.sql
08 execute_pipeline: transform finished. customer_totals=4, order_totals=1, raw_customers=4, raw_orders=4
10 submit_pipeline: pipeline submitted and graded
{"reward": 1.0, "stage1": 1.0, "stage2": 1.0, "stage2_ran": 1, "submitted": 1}
```

### Cookbook offline check

The core install skips the optional Cookbook smoke tests. With the pinned full
Cookbook dependency available, install `.[test,official,cookbook]` and run
pytest as above. A scripted-token test runs the real group builder and
training datum assembly. The optional Qwen test uses the real tokenizer,
Cookbook renderer and tool calls through `Env.step`. Both tests work without
model weights or a sampling client.

The pinned Cookbook's dependency resolver could not find a compatible
`tml-renderers>=0.4.1` distribution on the tested Windows Python 3.12 host.
For the narrow credential-free environment test on that host, install the
exact checkout with only the exercised runtime dependencies:

```powershell
git clone https://github.com/thinking-machines-lab/tinker-cookbook.git ../upstream-tinker-cookbook
git -C ../upstream-tinker-cookbook checkout --detach 28de41edfcdd07ba3e7980f35d53a586024a2184
.\.venv\Scripts\python.exe -m pip --isolated install --no-deps ../upstream-tinker-cookbook
.\.venv\Scripts\python.exe -m pip --isolated install tinker==0.39.2 chz==0.4.0 numpy==2.5.5 pillow==13.0.0 rich==15.0.0 termcolor==3.3.0 blobfile==3.3.0 cloudpickle==3.1.3 datasets==4.4.1
.\.venv\Scripts\python.exe -m pip --isolated install -e '.[test,official]'
```

The smoke test also needs PyTorch. The executed run appended the base Python
site-packages path to use its existing CPU PyTorch 2.11.0. See the exact
invocation in the integration evidence log. For a venv with its own CPU PyTorch, run pytest
directly as shown in the local setup.

The audited default Qwen text path uses the pinned Cookbook renderer directly
and works with the focused Windows environment. Other model/renderer choices
should use a compatible full Cookbook install and pass preflight.

Cache only the public tokenizer files for the default model, then use
`ELT_TEST_REAL_RENDERER=1` to require the real-renderer test. This download
does not use a Tinker credential or download model weights.

```powershell
@'
from huggingface_hub import snapshot_download
from elt_rl.rendering import QWEN_TOKENIZER_REVISION
snapshot_download(
    "Qwen/Qwen3.5-4B", revision=QWEN_TOKENIZER_REVISION, token=False,
    allow_patterns=["tokenizer.json", "tokenizer_config.json", "config.json", "chat_template.jinja"],
)
'@ | .\.venv\Scripts\python.exe -
$env:HF_HUB_OFFLINE='1'
$env:ELT_TEST_REAL_RENDERER='1'
.\.venv\Scripts\python.exe -m pytest -q --basetemp .venv/pytest-run
```

To run the official adapter's offline tests, install `.[test,official]` and
put the pinned benchmark checkout at `../upstream-elt-bench` or set
`ELT_BENCH_TEST_CHECKOUT`. The evaluator tests execute the pinned scripts
with a synthetic warehouse connector. Set `ELT_TEST_TERRAFORM` to a Terraform
executable for the provider-schema test. It runs `init -backend=false` and
`validate` against a loopback placeholder, which does not call Airbyte.
Use a local provider mirror via `TF_CLI_CONFIG_FILE` if the Terraform
download endpoint is unavailable.

## Episode and reward

- `contracts.py` defines the task, limits, backend protocol, and grade.
  `episode.py` implements the tools and owns the per-rollout state.
  `local.py` owns source extraction and SQLite materialization.
  `verifier.py` reads the hidden fixture targets.
- A rollout creates its own temporary workspace and DB. Reading the task is
  required before tool use. The agent writes a source manifest, runs load,
  writes SQL and runs transform. A successful transform must precede
  submission by at least one turn. Any write or reload invalidates the
  previous successful execution. Submission replays the artifacts in a
  second fresh DB and takes the terminal grade from that DB.
- The Cookbook adapter uses `AgentToolMessageEnv` and
  `EnvFromMessageEnv` with sequential tool dispatch. The subclass tracks which
  turn received execution feedback. Group members have separate workspaces
  and connections. They release them after grading. Local defaults are 24
  turns and 24 tool calls. The Cookbook runner enforces a 16,384 context cap,
  at most 8,192 sampled tokens and at most 2,048 tokens per turn. Remote runs
  allow 32 tool calls and use mode-specific time limits.
- Stage 1 is the fraction of required raw tables with exact row counts. Stage 2
  runs only after every Stage 1 check passes. It compares the full contents
  of each materialized model by unique key with exact null and integer handling
  and floating-point tolerances (`rel_tol=1e-6`, `abs_tol=1e-8`).
  The local terminal reward is `0.35 × stage1 + 0.65 × stage2`. An unsubmitted or
  failed replay scores zero. The stage fractions and gate status are available
  as host metrics. This local shaping and comparison rule are project choices.
- Only approved filenames and source IDs resolve to paths. There is no shell,
  general file read, arbitrary path, or SQL write tool. A SQLite authorizer
  allows model SQL to read approved raw tables and call a small function
  allowlist. Host code materializes checked results. Artifacts are limited to
  8 KiB each, tool feedback to 2,048 characters, and SELECTs to 256 output rows
  and roughly one second or 500,000 VM instructions each. SQLite also enforces
  page, value, expression, and compound-query limits. The hidden references
  stay outside the rollout workspace and model transcript. The fixture
  assumes a trusted host Python process. It does not measure generalization or
  deter an agent that was given the static fixture answers out of band.

## Upstream audit

- [ELT-Bench `elt_bench++` at `3b068d5f15f64541d05fbc33a817e4b08c6bf173`](https://github.com/uiuc-kang-lab/ELT-Bench/tree/3b068d5f15f64541d05fbc33a817e4b08c6bf173).
  Inspected `agents/README.md`, `agents/run.py`, `agents/codex_agent/run.py`,
  `agents/common/warehouse.py`, `setup/write_config.py`, `setup/setup_airbyte.py`,
  the `setup/sources/books` scripts, the Snowflake `books` config and data model,
  and `evaluation/eva.py`, `eva_stage1.py` and `eva_stage2.py`.
  The `books` task uses PostgreSQL, MongoDB, S3, flat files and a custom API.
  Its output models are publishers, customers and authors. Input generation
  injects warehouse and Airbyte credentials into generated config files.
  Stage 1 verifies raw table counts and Stage 2 reads only Stage 1-success
  schemas. Stage 2 can reuse export CSVs from its results folder.
- [Tinker Cookbook `v0.7.0` at `28de41edfcdd07ba3e7980f35d53a586024a2184`](https://github.com/thinking-machines-lab/tinker-cookbook/tree/28de41edfcdd07ba3e7980f35d53a586024a2184).
  Inspected `rl/types.py`, `rl/message_env.py`, `rl/rollout_limits.py`,
  `tool_use/agent_tool_message_env.py`, `tool_use/tools.py`,
  `recipes/search_tool/search_env.py`, `recipes/search_tool/train.py` and
  the relevant training paths in `rl/train.py`. The Cookbook groups
  trajectories for advantage computation and filters constant-reward
  groups on its training path. [RL docs](https://tinker-docs.thinkingmachines.ai/cookbook/rl/)
  and [Custom environment tutorial](https://tinker-docs.thinkingmachines.ai/tutorials/cookbook-abstractions/custom-environment/).

## Official Snowflake rollout

The implementation uses the official `books` task, source groups and Airbyte
Terraform provider. The agent selects streams in `load.json` and writes one
Snowflake SELECT for each of the three official models. The host creates the
model tables directly with CTAS. Input task sections come from the pinned public
configuration, schema CSVs and model YAML. Airbyte credentials, Snowflake
credentials and grader files stay in the host process and private files.

One approved rollout uses one Snowflake database for work and a separate
database for replay. Both have the `BOOKS` schema. All resources are run-owned,
Airbyte schedules are manual, and the host polls only the syncs it creates.
The official CLI runs in a private copy of the evaluator with a fresh results
folder. The output includes sanitized tabular grading evidence, a private
tool trace, submitted artifacts and per-attempt sync provenance. A cleanup failure leaves a
`cleanup-required.txt` file and may retain credential-bearing Terraform state
in `private-recovery`. Keep the entire run directory private and review cleanup
notices before using the result.

An earlier November 21 live `books` attempt loaded all 15 streams and 84,337 rows
through Airbyte into Snowflake. The model repaired the publisher SQL, then
hit an author SQL error and the transformation attempt limit. It ended
unsubmitted after 24 turns with reward 0. Neither official grading stage
ran in that attempt. [Earlier unsubmitted run](evidence/books-snowflake-final.md)

The validator now reports the first actionable error in each invalid SQL file
in the same tool observation. The saved 24-turn trajectory confirms delivery
of the corrected feedback. [Failure analysis](FAILURE_ANALYSIS.md) ·
[Fix and verification evidence](evidence/books-feedback-fix.md)

A separate host reference passed both pinned evaluator stages offline.
It used the staged `books` inputs and a local SQL transport.
[Smoke results and one-load Snowflake procedure](evidence/books-evaluator-smoke.md)

See the [recorded launch procedure](FINAL_HANDOFF.md#final-live-command).
The official tools support testing a single saved SQL file and explicitly
submitting the files that passed. Each observation shows the remaining
budget and current tested files. Grading uses a fresh warehouse and the
official Stage 1 gate. [Model and protocol evidence](evidence/books-model-readiness.md)

Follow the [official setup and cost guide](LIVE_SETUP.md#official-snowflake-books)
to stage the assets, start the source services, publish the Airbyte connector,
and create the private `books/config.yaml` using `elt_rl.books_setup bind-airbyte`.
The Airbyte binding is separate from the Snowflake RSA service credential.
Keep both under an ignored private directory or outside the checkout.

```bash
python -m elt_rl.preflight official
```

With authorized service access, use `--airbyte-probe` for workspace and
custom-source visibility and `--snowflake-probe` for login and warehouse
visibility. The separately authorized `--namespace-probe` exercises create/drop.
Use `--source-probe` before authorizing the rollout to run all six pinned
source connections and compare all 15 table counts in a disposable local
PostgreSQL database. See the [Windows invocation](LIVE_SETUP.md#4-execute-and-clean-up-one-official-rollout).
Snowflake loading and grading happen during the authorized rollout.
[Executed full-source preflight](evidence/books-source-preflight.md)

```bash
python -m pip install -e '.[official,cookbook]'
```

Set `ELT_SNOWFLAKE_CREDENTIAL_JSON` and `TINKER_API_KEY` through the private
environment or ignored local `.env`. One backend permits two load attempts
and seven warehouse transform attempts. Submission allows one separate replay.
The runner checks the Tinker token estimate. The Snowflake warehouse has a
separate budget and resource monitor.

## One Tinker LoRA update

The authorized live pilot completed one optimizer step and verified the
checkpoint. It used three live rollouts on the local SQLite fixture.
[Executed pilot evidence](evidence/tinker-pilot.md)

The pilot trains on the local fixture. It uses the hosted `Qwen/Qwen3.5-4B`
model by default and only needs a local copy of its public tokenizer. Set
`TINKER_API_KEY` in the environment or ignored local `.env`.
`TINKER_PROJECT_ID` is optional. The dry-run never constructs a Tinker client
and reports whether the selected renderer and tokenizer work offline.
The read-only production check accepted the configured key, reported the
default model as sampleable and trainable, and permitted reading billing
metadata. Creating a training session and its project-level write
permissions remain unverified. [Read-only evidence](evidence/live-readiness.md)

```bash
python -m elt_rl.preflight tinker --budget-usd 0.60 --group-size 3
# Only after approval
python -m elt_rl.run train-one --allow-paid --budget-usd 0.60 --group-size 3 --out runs/tinker-001
```

The command checks live public prices and server capabilities for
`Qwen/Qwen3.5-4B` by default, samples one group from rank-16 LoRA weights and
passes genuine rewards to the Cookbook's advantage and datum assembly. The
pilot allows 18 turns, an 8,192-token context, 4,096 sampled tokens and up to
1,024 tokens per turn. The offline reference estimate was about USD 0.49
for three rollouts, including one verification forward pass. The live
command recalculates the estimate using published prices.
If all rewards are identical or there are no usable datums, it exits with
status 2 before optimizer calls. With nonempty training data, it queues
`forward_backward`, checks its result, then submits `optim_step`. It compares
action log probabilities from a training datum before and after the update,
then saves one checkpoint with a 24-hour TTL. A completed optimizer with
inconclusive state verification is recorded separately and exits 2.
Use the Tinker
session link to reconcile actual billing. The local manifest records a
token-based estimate and marks actual expenditure and credit balances as
unavailable. [Tinker models and pricing](https://tinker-docs.thinkingmachines.ai/tinker/models/models_and_pricing/)

## Optional changed-input check

```powershell
.\.venv\Scripts\python.exe -m elt_rl.robustness examples/customer_orders.jsonl
.\.venv\Scripts\python.exe -m elt_rl.robustness examples/static_answer.jsonl
.\.venv\Scripts\python.exe -m elt_rl.robustness --suite --repetitions 3
```

Both traces score 1.0 on the original fixture. On the changed input, the
data-derived pipeline scores 1.0 and the hard-coded pipeline scores 0.35
with correct Stage 1 counts and both Stage 2 models wrong. The second CLI
invocation exits 2. The suite adds single-value, added-row, duplicate-key,
null, ordering, and same-warehouse repeat checks and reports the measured
extra runtime per case. See the [results and limitations](FINAL_HANDOFF.md#e-scientific-observations).
