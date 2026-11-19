# ELT-Bench RLVR starter implementation

The recipe gives a model a stateful ELT task. It chooses sources, loads a
warehouse, writes transformations, observes errors, repairs the pipeline
and submits it. A fresh replay produces the warehouse state used for the
reward. The shared episode runs against local SQLite and has an Airbyte and
Snowflake adapter for the official `books` task.

The credential-free example loaded both source tables, recovered from a SQL
error, and earned a reward of 1.0. Offline tests exercised the pinned
Cookbook with the public Qwen tokenizer and renderer. Scripted warehouse
outcomes of 0.175 and 1.0 produced 20 aligned training datums. The pinned
Airbyte provider validated the generated configuration, and the pinned
official evaluator enforced its Stage 1 gate with a synthetic connector.

A controlled change to the source data kept the data-derived pipeline at
1.0 and reduced a hard-coded pipeline from 1.0 to 0.35. The local experiment
also checks particular row, null, ordering and repeat-execution behaviors.

Read-only Tinker checks accepted the supplied credential and showed that
the organization can sample and train the selected model. The remaining
grading evidence is a credentialed official `books` rollout and one live
Tinker optimizer step with post-update verification. The
[design](DESIGN.md) and [handoff](FINAL_HANDOFF.md) document reproduction,
limitations, and the live commands.
