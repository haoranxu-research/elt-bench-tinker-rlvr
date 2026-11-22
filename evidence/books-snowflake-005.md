# Official Snowflake Books attempt 005

One authorized Qwen/Qwen3.6-35B-A3B rollout ran on November 22, 2026
from f2febce against Snowflake. The execution used the pinned ELT-Bench
revision 3b068d5f15f64541d05fbc33a817e4b08c6bf173, a fresh SQL workspace,
and a separate native warehouse for grading. The agent generated the
load manifest and each transformation independently.

## Verified result

| Item | Observed |
| --- | --- |
| Native Stage 1 | 1.0, all 15 tables and 84,337 rows |
| Native Stage 2 | 2/3 (0.666667) |
| Accepted submission | publishers.sql, customers.sql, authors.sql, submitted together on turn 34 |
| Correct native outputs | publishers and customers |
| Native mismatch | authors.most_expensive_book, the other six author columns matched |
| Warehouse and trajectory reward | Both 0.7833333333333333 |
| Offline Cookbook audit | Same return, 4 aligned datums, 9,625 sampled action tokens with original log probabilities |
| Cleanup | 0 run-owned Snowflake databases, Airbyte connections, sources, or destinations. Warehouse suspended. |

The initial load completed Airbyte jobs 141–146. The host replay completed
jobs 147–152. All twelve jobs succeeded, with one attempt per job. Both
Google Drive streams loaded in the agent and replay namespaces. The run
started at 03:16:44 UTC, accepted the submission at 03:47:44 UTC, and
exited 0 at 04:05:55 UTC. Replay, grading and cleanup took about 18 minutes.
The provenance audit matched all 40 dispatched tool calls to the model's
34 sampled responses and all 37 eligible tool receipts to the next
prompt. Saved SQL matched the model's writes.

## Failure and offline repair

The final author SQL ranked books by their greatest observed sale price.
Its ranking retained books with no price, using NULLS LAST. An author with
no priced books therefore still received an arbitrary title whenever
that author had any book. The existing public check rejected a dominated
title for an author with priced sales but skipped authors with no priced
sale at all. The model's final execution test returned no warning for
this case.

In developer-only DuckDB diagnostics, the unchanged native SQL snapshot
reproduced Stage 2 = 2/3 with publication_date represented as TEXT. The
private comparison found 3,780 discrepancies, all non-NULL titles for
authors without priced sales. The other output columns matched. Filtering
out unpriced title candidates in a separate diagnostic copy eliminated
all 3,780 differences and gave Stage 2 = 1.0 on DuckDB. The diagnostic
copy was kept outside the model workspace and was never executed on
Snowflake.

The public source-data check now counts non-NULL most-expensive titles
for authors who have no observed sale price. Its advice tells the agent
to keep the author row, rank priced candidates and leave the title NULL
when no priced candidate exists. A synthetic regression covers an author
with a NULL-priced sale, an author without books, and competing priced
titles. The revised check flagged all 3,780 observed rows on the original
snapshot and cleared the diagnostic control. The official evaluator,
reference data and reward formula are unchanged. The full offline suite
passed 125 tests in 44.06 seconds with the pinned renderer and local
Terraform provider enabled. The test transcript is stored at
runs/books-official-qwen35b-005-final-tests.txt.

## Cost and evidence

Before launch, the authorized dedicated monitor update set a 4.00-credit
quota, preserving its 90% immediate suspension threshold. Snowsight
showed 1.78 credits used and approximately 1.82 credits before suspension.
The warehouse was X-Small, auto-resume enabled, auto-suspend 60 seconds.
The credentialed post-run cleanup check confirmed the same setting and
a suspended warehouse. The service role cannot measure monitor usage.
A post-run administrator reading was unavailable.

Tinker recorded 9,625 sampled tokens, 175,360 cached prefill tokens,
24,121 uncached prefill tokens, and zero trained tokens. The rate-based
estimate is USD 0.039486225 for the official run and USD 0.080784195
including the authorized local rehearsal. Provider billing had no
matching session rows at the read-only check.
[Tinker model rates](https://thinkingmachines.ai/tinker/pricing/)

The private run directory runs/books-official-qwen35b-005 contains the
manifest, prompt and action traces, tool receipts, SQL snapshot, native
grader outputs and usage, cleanup and training-return audits. The
local-title-diagnostic subdirectory contains the isolated reproducer.
[Executed native launch command](books-source-recovery.md#execution-gate)

The one authorized native attempt was used. Full correctness on Snowflake
remains unverified, and the changed-input experiment remains deferred.
