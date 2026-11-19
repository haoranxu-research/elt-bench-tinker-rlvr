# ELT-Bench RLVR implementation design

## Rollout

Each rollout owns an artifact directory and a warehouse namespace. The model
reads the task, selects source streams, runs extraction and loading, writes
transformations, and revises them using execution feedback. Submission
requires an earlier successful run of the current artifacts. The host replays
them into a new warehouse namespace before grading. Tool calls run sequentially
within each rollout and grouped rollouts have independent state.

## Warehouse and reward

The local task loads CSVs into SQLite and materializes two models. The official
`books` adapter translates the model's source selection into Airbyte
connections using the benchmark's pinned Terraform provider, waits for syncs
and materializes three Snowflake models. It runs the pinned evaluator in a
private directory. The model sees public task metadata and bounded execution
feedback. Credentials, hidden references and evaluator artifacts remain on
the host. Official SQL is constrained to raw relations and permitted built-in
functions.

Stage 1 measures the fraction of raw tables with the expected row count.
Only complete Stage 1 success permits Stage 2. Stage 2 measures the fraction
of transformed tables that match. The training reward weights the fractions
35% and 65%, respectively. A rollout without successful submission scores zero.
The official adapter uses the benchmark's comparison results. The optional
local changed-input experiment checks whether a static passing pipeline responds
to new source data.

## Training and evidence

The Cookbook renders tool messages and runs grouped trajectories. The one-step
command uses Cookbook advantage centering and training datum assembly. It
requires varied within-group rewards and nonzero advantages. A budget estimate
uses current prices and defined token limits. The command records sampling,
forward/backward, optimizer completion and checkpoint separately.

Local execution, staged reward, changed-input behavior and the Cookbook
trajectory-to-datum path were tested without credentials. The official provider
configuration was validated against the real Terraform schema. The official
evaluator ran with a synthetic Snowflake connector. The live official rollout
and Tinker update require authorization and the corresponding services and
credentials. [Repository instructions](README.md)
