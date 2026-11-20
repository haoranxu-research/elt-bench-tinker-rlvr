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

The production Tinker pilot completed one optimizer step. Three live
rollouts earned 1.0, 0.0 and 1.0 and yielded six aligned training datums.
The post-update forward probe measured a change in action log probabilities,
and checkpoint metadata matched the base model and LoRA rank. This
establishes the update on local SQLite rewards.

For the official `books` task, all 15 staged inputs match the pinned Stage 1
row counts. In a credentialed attempt, Tinker sampled an agent trajectory and
Airbyte wrote the official `address` stream to Snowflake. The agent observed
1,000 rows. Discovery of the remaining sources failed on an absent LocalStack
bucket and a Google Drive connection error. The episode ended without a
submission and earned 0. Neither official evaluation stage ran.
[Design](DESIGN.md) [Credentialed attempt evidence](evidence/books-snowflake.md)
[Setup and handoff](LIVE_SETUP.md)
