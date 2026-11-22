# ELT-Bench environment design

## What the agent does

The agent reads the public task, inspects the source schema, saves a load
manifest, and asks the environment to load it. It then writes SQL, runs
it, and submits the tested files. The tools expose the task and source
types, the working warehouse, and the agent's own files. Only
`write_pipeline_file` changes an artifact. `execute_pipeline` runs saved
artifacts and returns file-specific errors. `submit_pipeline` accepts a
tested version for grading.

Each episode has its own workspace and warehouse. A successful load
enables transformation testing. Editing a SQL file clears its test
status while preserving other tested files. Books supports a complete
submission or an explicit partial submission of tested files. Acceptance
ends model actions. An episode that exhausts its budget without
submitting earns zero.

## Why grading uses a fresh warehouse

The working warehouse can contain output left over from earlier drafts.
The host freezes the accepted manifest and SQL, reloads the sources in a
fresh namespace, and runs exactly those files. This makes the reward
depend on what the submitted pipeline can reproduce. Working state and
grader exports are isolated so they cannot silently supply missing output.

For Books, the pinned ELT-Bench scripts check exact raw table counts
in Stage 1. A full Stage 1 score opens Stage 2, which compares the
transformed tables. The environment combines the executed scores as
`0.35 × Stage 1 + 0.65 × Stage 2`. Source checks can help the agent repair
its SQL during work. Only the official grader computes the two scores.
The verified native profile gives the agent 40 minutes to act and has a
separate 25-minute host grading allowance. The host attaches the completed
reward to the original sampled submission before computing returns.

## How trajectories become training inputs

The Tinker Cookbook renders the conversation as token observations and
records sampled action tokens with their original log probabilities. Given
a group of rollout returns, it computes centered advantages and assembles
training examples that mask prompt tokens out of the loss. The project
checks that each training target and log probability matches its sampled
action. A group with identical returns provides no update signal. The
live LoRA pilot tested this path on SQLite rewards. The Snowflake run
verified grading and reward alignment without training on that rollout.
[Native run](evidence/books-snowflake-007.md) · [LoRA pilot](evidence/tinker-pilot.md)

## What varies across warehouses

The episode owns the tools, artifact state, submission and cleanup
sequence. A task supplies its instructions, allowed files, backend
factory, and verifier. The backend handles loading, query execution, and
warehouse inspection. SQLite supports the self-contained example,
DuckDB mirrors selected source types for rehearsal, and the Snowflake
adapter uses Airbyte and the pinned grader for native verification.

## Integrity and runtime

The agent has no shell or general file access. SQL is restricted to
reading approved raw tables, and benchmark references and credentials
stay on the host. Fresh replay guards against stale outputs, but fixed
inputs still allow a hard-coded pipeline to score well. A separate
synthetic test measures that weakness under controlled input changes.
Airbyte loading in both working and grading warehouses dominated the
native run. File-level testing avoids rebuilding unrelated outputs.
Tool, token, query, and wall-clock limits bound work, and the reserved
submission action leaves the agent a way to hand in tested files.
[Development evidence and limitations](TECHNICAL_REPORT.md)
