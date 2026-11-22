# Technical report

The project delivers a reproducible ELT execution environment and a reward
pipeline for Tinker. Its completion run used an independently sampled
Qwen3.6-35B-A3B trajectory on the official ELT-Bench Books Snowflake task.
Airbyte loaded 15 tables and 84,337 rows. The model wrote, tested and submitted
all three outputs. Native Stage 1, Stage 2 and both recorded rewards were 1.0.
[Official run and audits](evidence/books-snowflake-007.md)

## Development findings

1. **Make tool state observable.** Initial runs lost clear attribution when a
   later transformation failed. Per-file validation, preserved successful
   files, and distinct write, execute and submit actions let agents repair
   the affected file. The budget display and reserved submission action make
   the tested subset available at the end of the working phase.
   [Failure reconstruction](FAILURE_ANALYSIS.md)
2. **Separate working limits from evaluation.** An earlier native grade
   completed after the agent action deadline while the trajectory recorded
   zero. The host now preserves an accepted sampled submission and attaches
   its completed grading result to that action before creating returns,
   with a separately bounded grading allowance when configured.
   [Deadline evidence](evidence/books-snowflake-deadlines.md)
3. **Use observed source semantics to support repair.** The TEXT-date mirror
   reproduced Snowflake date handling. File feedback used source-based checks
   for undefined ratios, population boundaries and price observations. In
   attempt 006 the publisher page cutoff used 70 rather than 0.70. The
   subsequent 35B local run fixed that column but omitted publishers from
   the Japanese numerator cohort. Source-based denominator feedback
   addressed that distinct case in the workflow.
   [Publisher run sequence](evidence/books-publisher-stability.md)
4. **Preserve genuine training evidence separately.** The earlier SQLite
   pilot completed one actual rank-16 Tinker LoRA update. Offline native
   auditing separately verified token/log-probability alignment and reward
   propagation on the stored trajectory. [Tinker optimization](evidence/tinker-pilot.md)

## Limits of the evidence

A full Snowflake result establishes feasibility for this task and configuration.
Repeated partial results show that a single full-score outcome cannot estimate
reliability across model seeds, backends or tasks. The optimizer probe verifies
an update and checkpoint. It does not estimate capability improvement.
The optional changed-input experiment detects specific fixed-fixture failures
on SQLite and leaves the official score unchanged.
[Controlled replay results](evidence/changed-input-final.md)

[Implementation design](DESIGN.md) · [Reproduction handoff](FINAL_HANDOFF.md) ·
[Professor-facing summary](PROFESSOR_SUMMARY.md)
