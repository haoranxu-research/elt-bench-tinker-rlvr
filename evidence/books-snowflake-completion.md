# Official Books completion runs

The model was `Qwen/Qwen3.6-35B-A3B` with the pinned no-thinking renderer.
Both executions used the official Snowflake task, the pinned ELT-Bench
checkout at `3b068d5f15f64541d05fbc33a817e4b08c6bf173`, and the same 40-minute
agent and 25-minute host grading deadlines. Each attempt started with an
empty model workspace and its own transient warehouse namespace. The CLI
launch details are recorded in the [handoff](../FINAL_HANDOFF.md#final-live-command).

## First authorized attempt

Run `runs/books-official-qwen35b-002` used commit `1fe4937`. The six working
Airbyte jobs 97–102 and the six fresh grading jobs 103–108 each passed on
their first replication attempt. Each load committed 84,337 rows across
all 15 pinned tables. The native grader matched publishers and customers.
The agent saved `authors.sql` on turn 31 and did not test it. It explicitly
submitted the two successfully tested files on turn 32.

| Evidence | Result |
| --- | --- |
| Native Stage 1 | 1.0 |
| Native Stage 2 | 2/3 |
| Native reward and recorded trajectory reward | 0.7833333333333333 |
| CLI start and submission receipt, UTC | 11:39:22 and 12:06:49 |
| Native grade and final manifest, UTC | 12:26:30 and 12:27:12 |
| Token receipts | 7,667 sampled, 166,784 cached prefill, 20,120 uncached prefill |
| Published-rate token estimate | USD 0.034300005 |
| Snowflake dedicated monitor at post-run refresh | 0.59 credits used, rounded |
| Cleanup | Zero run-owned Snowflake databases, Airbyte connections, sources, or destinations. Warehouse suspended. |

Grading completed almost 47 minutes after CLI start, about 19 minutes 41
seconds after acceptance. The native grade, terminal receipt and trajectory
agree. The audit paired the genuine stored trajectory with an empty zero-return
control and assembled four aligned offline Cookbook datums containing its 7,667
sampled actions and behavior log probabilities. It submitted no optimizer request.

## Failure replay and changes for the second attempt

- The validator rejected `TRY_TO_DATE` and `TO_DATE` on turns 11 and 13
  because SQLGlot normalized both to `TsOrDsToDate`. The fixed validator
  accepted both exact archived drafts. The new SQLSTATE diagnostic also
  reports an ambiguous column and requests a source qualifier.
- The 2,048-character load response was filled with Airbyte-managed column
  names and cut off later schemas and observed labels. The revised response
  omits connector metadata and includes three real publication-date samples.
  The full local source replay verified that it exposed all 15 table schemas,
  the date type and examples, and the budget information.
- The first customer transform assigned defined rates to 303 customers with
  no orders. The model repaired that issue in the actual native run and the
  pinned grader matched the customer model.
- The private DuckDB diagnostic exposed an ambiguous identifier in the
  untested author draft. Correcting only that ambiguity left the 1992 rate
  column unmatched. Its parser format covered a year, while the observed
  source strings included month and day. A developer-only qualification and
  date-format control earned 1.0 in both pinned local stages. This diagnostic
  never entered either model's prompt or workspace. The revised environment
  reports an aggregate public-data warning if an author with a source book
  published in 1992 receives a zero or undefined rate.

The retry kept the model, sampling token limit, official grader, reward,
and deadlines unchanged. It raised the model cap from 32 to 40 turns and
from 48 to 60 tool calls, and delayed the final partial-submission reminder
until the last turn or tool call. Those changes and the validator repairs
were tested in the **118-test** offline suite. The retry used commit `772c011`.

## Second authorized attempt

Run `runs/books-official-qwen35b-003` used commit `772c011`. The six working
Airbyte jobs 109–114 and grading jobs 115–120 each passed on their first
replication attempt. Both loads committed 84,337 rows across the 15 pinned
tables. The agent explicitly submitted publishers and customers on turn 40.
The pinned graders matched publishers and reported only the two percentage
columns as mismatched for customers. The submitted pipeline omitted authors.

| Evidence | Result |
| --- | --- |
| Native Stage 1 | 1.0 |
| Native Stage 2 | 1/3 |
| Native reward and recorded trajectory reward | 0.5666666666666667 |
| CLI start and submission receipt, UTC | 12:28:39 and 12:58:03 |
| Native grade and final manifest, UTC | 13:20:27 and 13:21:06 |
| Token receipts | 6,025 sampled, 207,872 cached prefill, 24,350 uncached prefill |
| Published-rate token estimate | USD 0.037709355 |
| Training-interface audit | Seven offline datums, 6,025 aligned action tokens |
| Cleanup | Zero run-owned Snowflake databases, Airbyte connections, sources, or destinations. Warehouse suspended. |

Native grading completed about 22 minutes 24 seconds after acceptance.
Both runs accepted before the action deadline and graded after the original
40-minute overall window. The audits matched all 47 and 55 dispatched calls,
respectively, to decoded sampled outputs in order. Saved file bytes matched
the model's successful writes. All 44 and 51 eligible tool receipts appeared
in the next model prompt. The raw and recorded rewards agreed in both runs.

## Retry diagnosis

The retry reached Snowflake with `TRY_TO_DATE` accepted by the application
validator. The model independently requested and received actual ISO date
strings. Its full author draft on turn 31 failed execution on turn 32 with
Snowflake SQLSTATE `42601`, generated statement line 1 at position 116.
Reconstructing that statement placed the error at `ba.author_id`. The
unchanged archived SQL also failed binding in DuckDB because two CTEs selected
the joined key while grouping by the preserved table's key. The model
replaced the draft with a small date-test query, which ran but failed the
required author output shape. It explicitly submitted the two tested files on
turn 40. The watch did not change any model-generated SQL.

The customer validation message on turn 16 identified 303 customers with
two defined rates despite having no orders. The model retained the zero
defaults through submission. In the developer-side DuckDB control, fixing
just the author grouping error kept the author's total-page flag and most
expensive title columns unmatched. The environment's public checks flagged
110 no-book authors and 1,747 inappropriate price-ranked titles. Correcting
the two customer defaults, including zero-page authors in the page comparison,
and restricting the title ranking to priced sales reproduced the desired
result in the pinned evaluator over DuckDB. All three models and their columns
then matched, with Stage 1 = 1.0, Stage 2 = 1.0 and reward = 1.0. The
developer control is private and never became a model submission.

The follow-up adds a sanitized grouping-error explanation and keeps open
public data checks visible in the budget summary across turns. The **119-test**
offline suite passed with the follow-up. The model
instructions point to source inspection for format questions so the SQL
draft remains available for repair.

## Allowance and evidence files

The fresh dedicated trial monitor `ELT_BOOKS_COMPLETION_MONITOR` was verified
in Snowsight with the existing `ELT_BOOKS_WH` as its only attachment, a quota
of 3.00 credits, no reset, and immediate suspension at 90% or 2.70 credits.
The initial reading was 0.00 and the pre-retry reading was 0.59, leaving
2.11 credits before the trigger. The conservative Tinker estimates were
USD 0.19335168 and USD 0.23758848, totaling USD 0.43094016 under the authorized
USD 0.45 ceiling. Provider-billed values are tracked separately from the
published-rate token estimates and rounded monitor readings.

The two observed token receipts imply USD 0.07200936 combined at published
rates. Both billing lookups returned zero posted session rows. The last verified
administrator monitor reading, before the retry, was 0.59 credits used. The
second post-run monitor total remains unverified. The service role's read-only
monitor query returned no rows and browser automation stopped after it could
not verify the active Windows browser URL. An administrator can retrieve the
final rounded usage with `SHOW RESOURCE MONITORS LIKE 'ELT_BOOKS_COMPLETION_MONITOR';`.
Both authorized attempts are exhausted. A further native run requires fresh
authorization, a verified trial allowance, and its own output directory.

The ignored run directories contain native `results.log`, `stage2.json`,
`grade.json`, saved model SQL, prompt/action receipts, tool traces, and
manifest files. `runs/books-native-completion/` retains local diagnostics,
test logs, monitor observations, and the preflight records. The Tinker
optimization pilot remains separate. [Tinker pilot evidence](tinker-pilot.md)

To reproduce the offline training-data audit, use the same cached tokenizer
and virtual environment as the [official entry point](../FINAL_HANDOFF.md#final-live-command).

```powershell
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); runpy.run_path(""scripts/audit_books_training_return.py"",run_name=""__main__"")' runs/books-official-qwen35b-002
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); runpy.run_path(""scripts/audit_books_training_return.py"",run_name=""__main__"")' runs/books-official-qwen35b-003
```
