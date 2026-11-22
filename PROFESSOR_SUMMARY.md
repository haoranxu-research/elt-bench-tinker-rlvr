# ELT-Bench RLVR starter project

I built an environment in which a model loads source data, writes and
tests SQL, and submits the resulting pipeline for execution-based grading.
The most important design choice was to grade the submitted files in a
fresh warehouse. During repair, the working warehouse can contain output
from an earlier draft. Starting clean tests whether the accepted files
alone can reproduce the result. [Implementation design](DESIGN.md)

On the official ELT-Bench Books task, Qwen3.6-35B-A3B independently
generated and submitted all three transformations. Airbyte loaded
15 tables and 84,337 rows into Snowflake. Both pinned evaluation stages
scored **1.0**, and the trajectory received the same **1.0** reward as the
warehouse. The audit matched the submitted files to the model's sampled
actions, then verified reward propagation into offline Tinker training
examples. [Native run and audit](evidence/books-snowflake-007.md)

I also ran a separate on-policy training experiment on Books. A fresh rollout
from a Qwen3.6-35B-A3B LoRA snapshot earned **1.0** on Snowflake. The verified
reward drove one real Tinker optimizer step, with a post-update probe and
checkpoint metadata confirming the update. The earlier SQLite pilot used
group-relative rewards. These experiments verify the training loop and
leave downstream performance unevaluated.
[Official training evidence](evidence/books-official-training.md) ·
[SQLite pilot](evidence/tinker-pilot.md)

I also tested a small limitation of fixed-fixture grading. Changing
synthetic order assignments and amounts left the data-derived pipeline
at **1.0** and reduced a hard-coded pipeline from **1.0 to 0.35**. That
experiment ran separately from the official benchmark.
[Technical report](TECHNICAL_REPORT.md) · [Reproduction guide](README.md)
