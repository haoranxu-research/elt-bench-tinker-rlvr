# ELT-Bench RLVR starter implementation

The project provides a stateful reinforcement learning environment for
extraction, loading, and transformation. A model reads the public task,
selects sources, writes SQL, executes and repairs it, and explicitly
submits tested files. Host-side evaluation computes reward by replaying
the submitted pipeline in a clean warehouse. The same episode interface
supports credential-free SQLite, a DuckDB rehearsal, and official
Airbyte-to-Snowflake execution.

**The official Books task achieved full correctness on Snowflake.**
Qwen3.6-35B-A3B independently generated and submitted
`publishers.sql`, `customers.sql`, and `authors.sql`. Airbyte loaded
15 tables and 84,337 rows through six connections. The pinned evaluators
returned Stage 1 = 1.0 and Stage 2 = 1.0. The warehouse and trajectory both
returned 1.0. An offline audit matched 9,334 original sampled action tokens
and their log probabilities to four training datums. Both transient
databases and their Airbyte resources were removed, and the warehouse
was suspended. [Official run and independent audits](evidence/books-snowflake-007.md)

**The separate Tinker pilot completed one real LoRA optimizer update.**
Three SQLite rollouts earned 1.0, 0.0, and 1.0. The pilot verified a
post-update change in action log probabilities and matching checkpoint
metadata. The evidence verifies an update on execution-derived rewards.
It provides no estimate of model performance improvement.
[Optimizer evidence](evidence/tinker-pilot.md)

**An optional changed-input check exposed fixed-fixture failures.**
The data-derived SQLite pipeline retained a reward of 1.0. A pipeline
with fixed answers fell from 1.0 to 0.35 under controlled input changes.
The extra replay took about 64 milliseconds for that case. These are
synthetic, host-only results separate from the official score.
[Robustness results](evidence/changed-input-final.md)

[Implementation design](DESIGN.md) · [Technical report](TECHNICAL_REPORT.md) ·
[Reproduction and handoff](FINAL_HANDOFF.md)
