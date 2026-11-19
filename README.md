# ELT-Bench × Tinker | Phase 1

Run a multi-turn, credential-free ELT episode that extracts two CSV sources,
loads an isolated SQLite warehouse, materializes two SQL transformations, and
grades a fresh replay of the submitted pipeline. The sample trace consists of
scripted actions, including a failed SQL run and its repair. The project
includes a pinned Cookbook environment adapter and a test that drives it
with scripted token actions.

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

The core install skips the optional Cookbook smoke test. With the pinned full
Cookbook dependency available, install `.[test,cookbook]` and run pytest as
above. The test uses a scripted byte renderer so it can call the real
`Env.initial_observation` and `Env.step` without downloading model weights or
creating a sampling client.

The pinned Cookbook's dependency resolver could not find a compatible
`tml-renderers>=0.4.1` distribution on the tested Windows Python 3.12 host.
For the narrow credential-free environment test on that host, install the
exact checkout with only the exercised runtime dependencies:

```powershell
git clone https://github.com/thinking-machines-lab/tinker-cookbook.git ../upstream-tinker-cookbook
git -C ../upstream-tinker-cookbook checkout --detach 28de41edfcdd07ba3e7980f35d53a586024a2184
.\.venv\Scripts\python.exe -m pip --isolated install --no-deps ../upstream-tinker-cookbook
.\.venv\Scripts\python.exe -m pip --isolated install tinker==0.39.2 chz==0.4.0 numpy==2.5.5 pillow==13.0.0 rich==15.0.0 termcolor==3.3.0
```

The smoke test also needs PyTorch. The executed run appended the base Python
site-packages path to use its existing CPU PyTorch 2.11.0. See the exact
invocation in the evidence log. For a venv with its own CPU PyTorch, run pytest
directly as shown in the local setup.

Use a fresh compatible environment with the full Cookbook package for eventual
model rendering and training. See [executed evidence](evidence/phase1.txt).

## Episode and reward

- `contracts.py` defines the task, limits, backend protocol, and grade.
  `episode.py` implements the six tools and owns the per-rollout state.
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
  and connections. They release them after grading. Default limits are 24
  turns and 24 tool calls. The Cookbook rollout runner can also enforce the
  90-second, 8,192 sampled-token, 2,048 per-turn token and 24,576 context limits.
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

## Upstream audit and later phases

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

### Phase 2 | Official Snowflake rollout, pending authorization

Implement `official.snowflake_task` as a `TaskDefinition` backed by Airbyte and
Snowflake. Follow the pinned benchmark's setup instructions for an isolated
Airbyte/source stack. The adapter must expose sanitized `books` input and dbt
artifacts and inject secrets only in the host runner. The replay needs a fresh
run database with the `books` schema so the official grader can use its task
name and expected rows. Provision and reset only that run's namespace. Obtain
the published Snowflake ground truth in a host-only directory. Run both stages
in a fresh, host-only output folder to avoid stale Stage 2 exports. Proposed
upstream commands, after provisioning and adapter implementation:

```bash
python setup/write_config.py --destination snowflake --credential "$HOST_CREDENTIAL_JSON"
python evaluation/eva.py --folder "$FRESH_RUN_ID" --db-type snowflake --database "$RUN_DATABASE" --only books --credential "$HOST_CREDENTIAL_JSON" --gt-folder "$HOST_GT_SNOWFLAKE"
```

Retain the official `results.log` and `stage2.json`, when produced, along with
the sanitized rollout trace and namespace provenance.

### Phase 3 | Tinker optimization, pending authorization

Add an `RLDataset` / `RLDatasetBuilder` around `ELTGroupBuilder` and reuse
the pinned Cookbook's `train.main` path. Verify available models and spend
limits at run time. Require real, varied within-group rewards and nonempty
training datums after filtering and advantage computation. Record completed
`forward_backward` and `optim_step` results, checkpoint, and spend. The final
Google Doc and shared GitHub delivery follow the later-phase checklist.
