# ELT-Bench reinforcement learning with verifiable rewards

## Agent interface

The agent observes the public ELT task, permitted sources and output files,
actual warehouse schema and types, and execution feedback. It can read the
task and inspect the workspace or warehouse. It writes the load manifest
and SQL using `write_pipeline_file`, runs a load or transformation with
`execute_pipeline`, and submits tested files with `submit_pipeline`.
The official Books tools can read saved SQL in pages and show observed
values for selected source columns.

Only a successful write changes a file. Editing invalidates that file's
test. Single-file execution exposes the relevant SQL error and preserves
other tested files. Incomplete load manifests leave the previously valid
manifest intact. Public data checks report observed anomalies such as an
undefined rate with a nonempty denominator. They run on source or candidate
data and use no hidden expected outputs.

## Episode lifecycle and limits

An episode loads the declared sources, tests current SQL, and accepts an
explicit submission. Complete submission requires all current SQL files
to have been tested. Partial submission can use the tested subset and
missing models earn no Stage 2 credit. An unsubmitted trajectory earns zero.

Context compaction preserves source schema, artifact status and recent
errors. The tested SQL stays on disk. The runner accounts for actual
rendered prompt length and bounds output per request. It reserves a final
turn, tool slot and measured token allowance for an explicit submission.
An interrupted or malformed work action can receive bounded recovery.
The action still counts against its original budget.

## Warehouse and evaluation

Each episode owns its workspace and warehouse namespace. The local
example uses SQLite. The Books rehearsal uses staged official inputs on
DuckDB. The live official adapter loads through six Airbyte connections
into Snowflake, validates single SELECT statements over approved raw
tables, and materializes the three requested models. It keeps credentials
and evaluator assets outside model-accessible paths.

A submission freezes the current manifest and SQL. The host replays them
in a new namespace and invokes the pinned official grader. Stage 1 checks
all required raw tables and counts. Only Stage 1 = 1.0 permits Stage 2,
which compares transformed outputs by the official rules. The reward
weights Stage 1 by 35% and Stage 2 by 65%. Host-only checks and optional
changed-input experiments have no effect on this score.

The model stops acting when a submission is accepted. The native profile
uses a 40-minute action deadline and a separately bounded 25-minute host
grading phase. A grading timeout records zero. A completed grade attaches
to the original sampled submission transition before returns are computed.
Cleanup covers both warehouse namespaces and their Airbyte resources.
Query, tool, token and time limits bound each run, with a dedicated
Snowflake monitor as an external backstop.

## Tinker and new destinations

The pinned Cookbook renderer converts tool interactions to token
observations and actions. The recipe pairs sampled action tokens with
their original behavior log probabilities and masks, then assigns
advantages from grouped execution returns. A constant-return group
produces no update. The rank-16 pilot made one `forward_backward` and
one `optim_step` call, then checked the updated state and checkpoint.

To add a destination, implement the warehouse backend and host verifier,
then register them with a `TaskDefinition` describing public instructions
and allowed artifacts. The episode, scoring interface and Tinker adapter
can be reused.

## Verified result

Independent Qwen3.6-35B-A3B SQL achieved Stage 1, Stage 2, and returned
reward of 1.0 on the official Snowflake Books task. The offline audit
matched the native grade to sampled actions and training datums. The
separate live Tinker update used SQLite rewards. These experiments
demonstrate end-to-end execution and a genuine optimizer update on their
respective runs. [Native evidence](evidence/books-snowflake-007.md) ·
[Optimizer evidence](evidence/tinker-pilot.md) ·
[Technical report](TECHNICAL_REPORT.md)
