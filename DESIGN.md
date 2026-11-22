# ELT-Bench reinforcement learning with verifiable rewards

## What the model sees and does

The model starts with instructions to read the task and a schema for seven
tools. `read_task` and `read_task_section` expose public source and output
specifications. `list_workspace` lists artifacts, and `write_pipeline_file`
edits only task-approved files. `execute_pipeline` runs extraction/loading
or transformations and returns bounded feedback. `inspect_warehouse`
reports materialized table counts. `submit_pipeline` requests fresh replay
and grading. For `books`, the warehouse tool can also list actual
columns, and `read_pipeline_file` reads saved SQL in pages.

For official `books`, a write receipt names the saved file and the next
execution step. The workspace lists missing, saved, and tested files.
The agent can execute one saved SQL file to isolate an error. Changing a
file invalidates its earlier test. Complete submission requires all
three current files tested on earlier turns. Explicit partial submission
replays just the current tested files. If a Snowflake batch fails after
writing some outputs, the files it completed remain eligible. Each tool
receipt shows the remaining turn, tool-call, and warehouse-attempt
budgets. The last turn and last tool call are reserved for explicit
submission. Hosted books rollouts also reserve sampled tokens for one
submission response and show the remaining sampled budget in feedback.
At the work limit the final prompt lists the tested files and exposes
only the submit tool. Sampling is bounded by the rendered context and
the remaining tokens. Context compaction carries forward the task,
warehouse columns, public relationships, workspace status and recent
error. SQL files stay in the workspace and remain readable. An interrupted
work action does not reach the dispatcher. The official grader gives absent
models zero Stage 2 credit. The run stores the candidate files and a
separate submitted-file manifest.

An episode proceeds from task inspection to source selection and load, then
to transformations. The model can repair an error and rerun the stage.
Editing invalidates earlier execution evidence. Submitting requires a
successful test of the current artifacts in an earlier turn. A rollout ends
on accepted submission, a terminal parse error, or a budget limit. An
action without tools normally ends the episode. The books agent receives
one reminder to use a tool when there is budget for another turn. An
unfinished rollout earns zero.

## Execution and grading

Each episode owns a private artifact directory and a separate warehouse
namespace. Tools run sequentially within that episode. The local backend
loads CSVs into SQLite and materializes two models. The official adapter
uses Airbyte to load selected `books` streams into a transient Snowflake
database and materializes three models using Snowflake SQL. Submission opens
a second fresh namespace and replays the artifacts before reading its
warehouse state. Cleanup is bounded and ambiguous Snowflake resource
creation is reported for operator review.

The official runner accepts an explicit submission by saving an immutable
snapshot of its load manifest and tested SQL while the agent deadline is
still open. The agent terminates at acceptance. The host grades that snapshot
after the sampled transition is recorded, then attaches the result to that
same transition before the Cookbook computes trajectory returns. The default
uses the original shared deadline. An explicit `--grading-seconds` permits a
separately bounded host phase when the protocol allows it. Failed or expired
grading returns zero with a distinct status. Cleanup attempts both Airbyte
and database removal and records failures separately from the grade.

Stage 1 is the fraction of required raw tables with the correct row count.
Only complete Stage 1 success permits Stage 2, which measures matching
transformed models. The terminal training reward weights the stage fractions
35% and 65%. The official adapter executes the pinned evaluator in a private
directory against the replay database. A missing or malformed evaluator
report prevents submission. Stage 2 errors earn no credit for their model.
The local verifier compares full row content by key and checks
duplicates, nulls, and numeric tolerance.

The tool surface has no shell or arbitrary file access. Source IDs and
tables are allowlisted. Local SQL uses a SQLite authorizer. Official SQL is
validated as a single SELECT over approved raw tables. Credentials and
ground truth remain on the host. The private Airbyte bundle binds only the
workspace and custom definition. Routing and the namespace policy come from
the pinned public config. Private reports retain attempted tool calls with
their feedback and record Airbyte jobs separately for each load attempt.

The `books` validator checks each of the three SQL files independently
against its raw inputs and the CTEs visible in that query. When local checks
fail, the transform tool returns a diagnostic per invalid file, with source
line and column when available, before any warehouse statement runs. If
Snowflake rejects a CTAS after local validation passes, feedback identifies
the affected file and labels any location as part of the generated statement.

Artifact, feedback, action, query and
rollout budgets limit work. Changed-input checks can expose some answers
that coincidentally match the original fixture.

## Tinker integration and extension

The pinned Cookbook renders tool messages, runs independent episode groups,
centers execution-derived rewards, and assembles training datums. The
recipe checks sampled token IDs, behavior log probabilities, provenance,
and masks before submitting a rank-16 LoRA update. Constant-reward groups
exit without optimizer calls. The live entry point waits for valid
`forward_backward` results before one `optim_step`, probes post-update action
log probabilities on a training datum, and records the checkpoint and each
status separately.

To add a destination, provide a `TaskDefinition` with public task text,
approved artifacts, a `WarehouseBackend` factory and a host-side verifier.
The episode lifecycle, tool calls and training path stay the same.

The local warehouse path, real Qwen text renderer and Cookbook datum path
have offline evidence. The pinned evaluator used a synthetic warehouse
connector in tests. The production Tinker pilot completed one LoRA optimizer
step using local SQLite rewards, measured a post-update log-probability
change, and verified checkpoint metadata. An earlier November 21 live `books`
attempt observed all 15 expected source tables in Snowflake. The model
used only whole-batch transforms, exhausted its transform attempts and
finished unsubmitted with reward 0.
[Pilot evidence](evidence/tinker-pilot.md) [Earlier credentialed evidence](evidence/books-snowflake-final.md)

For `books`, candidate checks inspect source keys, shipping labels, defined
rates, and whether a proposed title is dominated by another observed sale.
An unsuccessful check provides a repair opportunity within the episode.
The pinned graders still compute the final score. The Qwen3.6-35B-A3B
agent used the workflow to submit three exact outputs with both stages
and reward at 1.0 on DuckDB. [Model-driven evidence](evidence/books-full-baseline.md)

The later Snowflake runs measured both stages on the agent's explicit partial
submissions. The best run matched both submitted tables and returned the same
0.783333 reward from the native grader and the trajectory. The stored native
trajectory also produced aligned offline training datums using its actual
sampled tokens and log probabilities. Full correctness on native Snowflake
remains open. [Native evidence](evidence/books-snowflake-completion.md)

The tool state distinguishes tested, failed and newly saved SQL. Context
compaction carries per-file execution failures and open public checks. The
agent can read the preceding SQL draft explicitly after an overwrite, and
targeted schema inspection returns physical source types. A manifest
save now names any omitted source streams before loading. The hosted
TEXT-date mirror passed both stages. Attempt 004 separately recorded
a source discovery failure and an officially graded partial submission.
[Local rehearsal](evidence/books-hosted-text-validation.md)
[Latest native evidence](evidence/books-snowflake-004.md)
