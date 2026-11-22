# Official Snowflake Books attempt 006

On November 22, 2026 the authorized model rollout executed from d08dd32
with pinned ELT-Bench revision
3b068d5f15f64541d05fbc33a817e4b08c6bf173. It began with an empty SQL
workspace and independently generated a new submission. The launch
command and the preceding local validation are recorded separately.
[Command and local evidence](books-author-title-verification.md)

| Item | Verified result |
| --- | --- |
| Stage 1 | 1.0, all 15 tables and 84,337 rows |
| Stage 2 | 2/3, all author and customer columns matched |
| Sole mismatch | publishers.num_books_pages_greater_than_70_per_of_avg |
| Submission | All three SQL files, explicitly accepted on turn 30 |
| Warehouse and trajectory reward | Both 0.7833333333333333 |
| Offline Cookbook audit | Same reward in four aligned datums with 9,436 original action tokens |
| Cleanup | Zero run-owned Snowflake databases and Airbyte resources, warehouse suspended |

Initial Airbyte jobs 153–158 and replay jobs 159–164 all succeeded with
one attempt each. The run started at 04:49:29 UTC, the host accepted
submission at 05:22:53 UTC, and the process exited 0 at 05:45:07 UTC.
Replay, grading, and cleanup took about 22 minutes 14 seconds after
acceptance. The provenance audit matched all 48 dispatched tool calls
to genuine model responses and all saved SQL to those model writes.

## Author semantics

The native author model passed all seven columns, including
most_expensive_book. A host-only execution of the first and last model
drafts on staged data retained all 9,235 author rows and returned NULL
for all 3,890 authors without priced sales. Authors with priced sales
all received titles. The targeted unpriced-title warning did not fire
because the first draft handled the case. The agent repaired a different
public warning about the page average during the episode. No reference
SQL, expected output, or diagnostic control was supplied to the model.

## Publisher result and offline follow-up

The submitted SQL compared pages with seventy times the average.
The public requirement uses seventy percent of the global book-page
average. On the TEXT-date mirror, the unmodified submission reproduced
the 2/3 result and gave zero instead of a positive count for 1,545
publishers. Changing the multiplier in an isolated developer control
eliminated all mismatches and produced 1.0 on DuckDB. That control was
kept outside the agent workspace and was never run on Snowflake.

A source-data feedback check now finds publishers reporting zero
despite having a book above the published threshold. It uses observable
source pages and reports an aggregate mismatch count. It does not
supply per-publisher answers. The check detected all 1,545 original
errors and cleared the corrected control. The regression covers
an exact-threshold tie, missing page data, and a publisher without rows.
The full offline suite passed 126 tests in 45.61 seconds.
The grader, reference data, and reward formula are unchanged.

## Costs and artifacts

The user set the dedicated monitor quota to 5.00 credits after
Snowsight's form rejected a fractional quota. Administrator preflight
confirmed 2.52 credits used, the ELT_BOOKS_WH attachment, and 90%
immediate suspension. Effective pre-run headroom was 1.98 credits.
The warehouse retained its 60-second auto-suspend. Its read-only
post-run metadata confirmed suspension. A refreshed post-run
administrator credit reading was unavailable.

Tinker metered 9,436 sampled tokens, 161,408 cached prompt tokens and
22,057 uncached prompt tokens. The published-rate estimate was
USD 0.03704943 for the native run, or USD 0.071219175 including the
authorized local rehearsal. The native session invoice had not posted
at the read-only billing check. No optimizer call was made.

Private evidence under runs/books-official-qwen35b-006 contains the
official grading outputs, prompts, model actions and log probabilities,
tool receipts, SQL snapshots, cleanup and usage audits, and the isolated
publisher diagnostic. The authorized official attempt was used once.
A native 1.0 result has not been observed.
