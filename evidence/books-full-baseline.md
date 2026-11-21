# Model-driven books correctness

Full acceptance requires Stage 1 = 1.0 and Stage 2 = 1.0 for a genuinely
model-authored submission in Snowflake. The experiments below use the pinned
official evaluator logic and all 15 staged tables (84,337 rows) in DuckDB.
Snowflake was outside the authorization for these runs. The prior Tinker
optimization evidence remains in [the training pilot record](tinker-pilot.md).

## Diagnosis

The first hosted submission ran both stages. Its publisher query filtered for a
guessed language code. The actual source labels included `jpn` for Japanese.
Its customer columns had numerical and NULL mismatches from rounding and
defaulting absent rates to zero. The author file was absent from the submitted
subset. A saved draft contained a parser error and later drafts exposed joins
that duplicated book-level measures at sale-line grain.

Changes were limited to public task material and the execution protocol.
The agent sees actual columns and selected source lookup values. Transform
validation checks the public output columns and one row per source entity.
Prompts distinguish entity, book, order, and sale-line grain, preserve precision,
and prioritize testing each required file before reviewing already tested SQL.
The working reasoning renderer retains a separate 54-token no-thinking
submission phase. The read-file tool now accepts the integer offset emitted by
the model and continues to accept archived decimal-string arguments.

Private developer comparisons do not feed into the agent. In rehearsal 03,
both customer rate columns had 303 mismatched NULLs and zero mismatched
non-NULL values. Removing only the two unauthorized zero defaults in a
private comparison removed all those differences. The model independently
authored the fully correct publisher output. It saved an author draft but
never tested it. Its integer pagination arguments were rejected before the
fix, and it reread first pages while using its remaining turns.

## Genuine hosted DuckDB submissions

| Evidence directory | Revision | Tested and submitted files | Exact outputs | Stage 1 | Stage 2 | Reward | Estimated USD from observed tokens |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| `runs/books-context-loop/attempt-01` | `bf6a84f` state | publishers, customers | None | 1 | 0 | 0.35 | 0.015649827 |
| `runs/books-full-baseline/attempt-01` | `a7e6195` | publishers, customers, authors | None | 1 | 0 | 0.35 | 0.010288527 |
| `runs/books-full-baseline/attempt-02` | `fe5e601` | publishers, authors | None | 1 | 0 | 0.35 | 0.023022204 |
| `runs/books-full-baseline/attempt-03` | `25e6283` | publishers, customers | publishers | 1 | 1/3 | 0.566666667 | 0.029919042 |
| `runs/books-full-baseline/attempt-04` | `b54cd9f` | No submission | Ungraded | — | — | — | 0.028499301 |
| `runs/books-full-baseline/attempt-05` | `1dee51c` | publishers, customers | publishers | 1 | 1/3 | 0.566666667 | 0.025740834 |
| `runs/books-full-baseline/attempt-06` | `4742b23` | publishers, customers, authors | publishers | 1 | 1/3 | 0.566666667 | 0.022656924 |
| `runs/books-full-baseline/attempt-07` | `80b1bf0` | publishers, customers, authors | None | 1 | 0 | 0.35 | 0.024535380 |

Attempt 01 produced 17,753 author rows for 9,235 source author IDs. Its global
ranking selected one title for the entire publisher population. Attempt 02
restored all author IDs and used the real Japanese label. The publisher language
percentage still counted distinct languages in its denominator. Two author book
metrics inherited duplication from order lines, and its title selection
mishandled price NULLs or ranking. The customer error feedback suggested a
function outside the accepted SQL subset; it was replaced with deterministic
grouping guidance. Attempt 03 recorded 32 responses, 44 executed tool calls,
41 of 41 eligible tool receipts in the next prompt, and a 27-token explicit
submission. Its 15,506 sampled, 179,200 cached input, and 22,179 uncached input
tokens reconcile to the usage estimate above.

Attempt 04 received valid integer-offset pages and tested the publisher and
customer files. Its author repairs attempted an unavailable `book.author_id`,
used a text comparison against a date, and referenced a missing CTE column.
For the last saved author draft, SQLGlot warned that it could not preserve a
Snowflake `TO_CHAR` format argument. The PowerShell invocation treated process
stderr as terminating, which prevented submission and evaluator execution.
All 29 traced requests had sampled responses. The trace records 17,063 sampled,
143,616 cached input, and 20,375 uncached input tokens. The next preflight also
reserved USD 0.008220672 for a hypothetical additional maximum-sized call.
The repair reports lossy translations as file-specific errors, exposes actual
date and timestamp types, lists still-untested files, and gives the local
rehearsal ten transform attempts. Snowflake retains its original attempt limit.

Attempt 05 authored and validated a second exact publisher output. It wrote
five customer drafts in sequence without testing them. Its submitted customer
SQL used a zero fallback for both undefined rates. It did not write an author
file. All 32 prompts and responses matched the token audit, 30 of 30 eligible
tool receipts reached the next prompt, and the explicit final submission used
27 of its 54 reserved tokens. Token usage was 14,122 sampled, 144,128 cached
input and 18,989 uncached input. The next revision asks the model to test
each saved draft before writing another, permits writing and testing in one
turn, and issues an advisory for direct zero defaults on percentage measures
whose public task description specifies no missing-value treatment.
This advisory uses the candidate SQL and published task descriptions. It
leaves validation eligibility, evaluator execution and reward unchanged.
Replaying the exact saved customer file produced the advisory and preserved
its tested status. The replay made no model or evaluator calls.

Attempt 06 repaired the missing 110 author IDs and an ambiguous identifier,
then passed all three shape checks. It submitted the complete pipeline on
turn 27 under the regular tool protocol. Stage 2 invoked all three model
queries. The customer query counted distinct constant values in a conditional
count and wrapped percentage expressions in unrequested rounding. The
author SQL summed page counts after a sale-line join and imputed missing
prices as zero. It also ranked unpriced rows. The private comparison found
1,014 differing non-NULL values for the customer book rate, 496 wrong
author page classifications, and 3,780 author book-title NULL mismatches.
The next revision extends candidate-SQL advisories to wrapped defaults,
unrequested percentage rounding, and distinct counts of constant CASE values.
It leaves grading unchanged.

Attempt 07 repaired an invalid author join and a window function in a
`WHERE` clause, then independently submitted all three shape-validated
files on turn 29. The published customer book-rate and author title
columns matched in this run. The publisher language formula inverted its
numerator and denominator, and the customer international rate counted all
orders in both terms despite computing a shipping indicator. The private
comparison found 2,255 wrong NULLs in the publisher rate, 1,557 wrong
non-NULL international rates, and differences in three author metrics.
The tool audit matched
29 prompts and responses, all 35 dispatched calls, and all 32 eligible
feedback receipts in the next prompt. Both evaluator stages ran, issuing 15
source count queries and three output queries. Usage was 13,100 sampled,
124,928 cached input, and 21,560 uncached input tokens. Requests stayed below
the context cap, including the configured margin.

The ignored run directories preserve prompts, sampled tokens and log
probabilities, exact model SQL, tool receipts, and per-model Stage 2 results.
`audit-result.json` records the comparison of sampled tool calls with executed
actions and persisted artifacts. `stage2-isolation.json` and the private
developer diagnostic records are never included in model observations. The
separate `evaluator-control/result.json` verified full, partial, and Stage 1
failure paths with developer-controlled inputs. It is an evaluator test.
The same control was rerun after the final tooling changes and saved under
`evaluator-control-final`.

## Executed regression checks

`pytest -q --tb=short --basetemp .venv/books-stage2-count-review-full`
ran from the Cookbook environment, with the real renderer and the local
Terraform provider enabled. Result was 92 passed in 26.35 seconds. The
pagination check uses the observed integer offset 1250, and the translation
check runs the observed Snowflake date expression against a typed DuckDB
column. The advisory regression distinguishes outer zero defaults from a
valid zero contribution inside the numerator and from explicit task
instructions to fill a NULL. It also distinguishes a constant conditional
count from one counting actual entity keys. An earlier invocation pointed
the 4B renderer at the isolated 9B cache
and failed to find the cached tokenizer. Using the existing default 4B tokenizer
cache and enabling the local provider resolved it. The logs are in
`runs/books-full-baseline`.

The reasoning runs used 32 model turns, 48 tool calls, a 16,384-token context
limit, a 20,480-token sampled budget, and 4,096 sampled tokens per working
turn. Their read-only preflight returned USD 0.17381376 as the uncached
maximum. The sixth run capped context at 14,336 tokens for an upper bound of
USD 0.15415296. Run 07 capped it at 12,288 tokens and preflight quoted
USD 0.13449216 against a remaining conservative allowance of USD 0.136002669.
The separate finalization prompt limits sampling to 54 tokens.
Each maximum was checked against the remaining cumulative authorization
before launch. Token totals come from sampled responses. USD figures are
usage-based estimates at the checked rates, pending posted billing records.
The seven new sessions used USD 0.164662212 by this estimate, including the
recorded tokens for the interrupted session. The earlier USD 0.015649827
run was part of the same USD 0.30 authorization. The combined estimate is
USD 0.180312039. After retaining the interrupted-session buffer, the
available allowance is USD 0.111467289. It is below the USD 0.13449216 upper
bound of the last profile to produce a complete submission. The most recent audit found no posted
usage rows for the seventh session. The interrupted run and all Snowflake
grading remain distinct from the hosted DuckDB results above.

## Stronger-model preflight

A read-only Tinker preflight for `Qwen/Qwen3.6-35B-A3B` passed with the pinned
Qwen reasoning tokenizer and renderer. Account metadata showed sampling
support and a maximum context of 65,536 tokens. The same local 32-turn profile
with the default 16,384-token cap and 20,480 sampled tokens has a conservative
uncached bound of USD 0.26327040. One local rehearsal was authorized and
launched with a USD 0.27 cap.
Snowflake grading remains gated on a genuine local score of 1.0 at both stages.
The preflight ran the following command in the configured project environment.

```powershell
./.venv/Scripts/python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); sys.path.insert(0,""scripts""); runpy.run_path(""scripts/books_model_rehearsal.py"",run_name=""__main__"")' --hosted --preflight-only --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5 --budget-usd 0.27 --checkout ../upstream-elt-bench --assets runs/books-assets --out runs/books-full-baseline/stronger-preflight-current
```

## Authorized 35B rehearsal

Run `runs/books-full-baseline/stronger-01` used revision `34fbf96`. The launch
used the preflight command above with `--allow-paid` in place of
`--preflight-only` and `stronger-01` as the fresh output directory.
The model independently wrote a valid manifest and loaded all 15 DuckDB
tables (84,337 rows). It never saved a transformation or submitted. Neither
evaluator ran, and the unsubmitted environment reward was exactly 0.

Turns 6, 11, 16, and 21 each reached the per-turn cap of 4,096 output tokens.
The turn 6 sample began serializing a publisher SQL write but lacked a
closing tool-call marker. Turn 11 used its allowance reasoning about multiple
models and never began a tool call. The recovery observation preserved the
loaded state but also repeated the original instruction to begin with
`read_task`. Each recovery loop reread the task, saved the same manifest,
and requested a load that the host correctly treated as already complete.
The final working turn hit the remaining 803-token cap. With no successfully
tested SQL files, the episode ended unsubmitted.

The run consumed 20,426 sampled, 76,672 cached input, and 17,821 uncached input
tokens. The usage-based estimate is USD 0.04218864. The audit matched
26 responses to 26 prompts, verified behavior log probabilities and all 35
dispatched calls, and found no posted billing rows for the run. There was
one hosted session, with no retries, Snowflake compute, or training.

The offline repair removes the new-episode user instruction from compacted
prompts. After a truncated action it provides one explicit next step based on
the preserved file and load state, and uses the same Qwen tool format with
thinking disabled for that recovery turn. Normal working turns retain the
selected renderer. A replay of the first six archived 35B responses against
the actual DuckDB data regenerated a 3,224-token recovery prompt. It directed
the model to write one file, retained the warehouse schema and loaded state,
and confirmed the truncated SQL was never saved. The replay issued no model
or evaluator requests. Evidence is in `stronger-01/offline-recovery-check.json`.
The full suite ran as
`pytest -q --tb=short --basetemp .venv/books-interrupted-35b` with the real
renderer and the local Terraform provider enabled. Result was 93 passed
in 33.18 seconds. The fix has not been verified in another hosted session.

The follow-up read-only preflight for the corrected code passed with the
same reasoning profile and a 14,336-token context cap. The uncached upper
bound is USD 0.23377920. The command adds `--context-cap 14336`, sets
`--budget-usd 0.24`, and writes to
`runs/books-full-baseline/stronger-recovery-preflight`. No follow-up sampling
session was launched.

## Second authorized 35B rehearsal

Run `runs/books-full-baseline/stronger-02` used revision `52438cf`, with
`--hosted --allow-paid --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5
--context-cap 14336 --budget-usd 0.24` and the same checkout and assets.
The model loaded all 15 tables and 84,337 rows, wrote and tested
`publishers.sql` and `customers.sql`, and called `submit_pipeline` itself
on turn 16. Stage 1 was 1.0. Stage 2 matched publishers and customers
exactly and could not find an authors output. Stage 2 was 2/3 and the
environment reward was 0.7833333333333333.

Turns 9, 11, and 13 hit 4,096 sampled tokens without completing an author
write. The recovery prompts prevented the restart loop from the prior run.
The model used the recovery turns to read the public author description or
request the still-missing file. The next prompt restored thinking even though
the author write remained pending. Turn 15 exhausted the last 953 working
tokens. The model then used 27 of the reserved 54 tokens to submit both
tested files. The audit matched 16 prompts and responses, all 20 dispatched
tool calls, all 19 eligible receipts, and the persisted SQL. It verified
20,453 sampled, 44,800 cached input, and 13,081 uncached input tokens.
The usage estimate is USD 0.037223205. No billing rows were posted when
checked. No Snowflake compute, training, or second paid session ran.

The offline follow-up keeps thinking disabled across read-only turns until
the pending recovery action changes. An offline replay of the first ten
actual model responses confirmed that the original next prompt restored
thinking and the revised prompt keeps recovery mode active. It retained
both tested files and the author write as the pending action. The replay
used local DuckDB and issued no sampling or evaluator requests. The full
suite ran with `pytest -q --tb=short --basetemp .venv/books-persistent-recovery`
using the real renderer and the local Terraform provider. Result was
93 passed in 35.12 seconds. The revised recovery mode still needs hosted
verification. The fresh read-only preflight in
`stronger-persistent-preflight` passed at the same USD 0.23377920 upper bound.

## Third authorized 35B rehearsal

Run `runs/books-full-baseline/stronger-03` used revision `ad4cff6` and the
same sampling flags, assets, and context cap as `stronger-02`. After one
4,096-token interruption on turn 5, the model recovered without exhausting
the working budget. It loaded all 15 source tables (84,337 rows), wrote and
executed all three files, and submitted the complete set itself on turn 19.
Stage 1 was 1.0. Stage 2 certified publishers and customers as exact matches.
Five of the seven author columns matched. Stage 2 was 2/3, giving a reward
of 0.7833333333333333.

The author query derived publication counts and page totals from the same
rows as sale prices. The source has 7,550 order lines for 5,466 distinct
ordered books. Joining at this grain repeats book-level page counts and
dates. The submitted year-rate column differed for 97 authors and the page
classification differed for 836. The query also used only authors with books
when averaging, though the public description specifies all authors. The
offline SQL advisory now flags this join pattern and prompts a check of
the population used in the average. Its inputs are the candidate SQL and
public source relationships. It leaves the file eligible for submission and
does not affect the evaluator or reward.

A developer-only comparison deduplicated book-grain inputs and isolated the
average population and the missing-author page totals one at a time. It
eliminated all 97 year-rate differences and all 836 page-classification
differences. That diagnostic is saved in
`runs/books-full-baseline/stronger-03-grain-isolation.json` and was never
part of a model prompt or submission. No additional hosted run tested the
advisory.

The audit matched all 19 responses to prompts, all 25 dispatched calls to
samples, and all 24 eligible tool receipts to the next prompt. It matched
the final files to model writes and verified that all requests fit within
the context limit. Token use was 8,544 sampled, 77,696 cached input, and
11,894 uncached input. Estimated cost is USD 0.02375118, with no posted
billing rows at the time of the audit. No other paid session, training,
or Snowflake compute ran.

The revised SQL advisory passed the full test suite using
`pytest -q --tb=short --basetemp .venv/books-join-grain-final` with the real
renderer and the local Terraform provider enabled. Result was 94 passed
in 34.47 seconds.

## Fourth 35B rehearsal

Run `runs/books-full-baseline/stronger-04` used revision `d101a0e`,
32 turns, a 12,288-token context cap, and the same 20,480-token sampled
budget. The worst-case quote was USD 0.204288 against the remaining
USD 0.21624882 from the current USD 0.24 authorization. The model loaded
all data, wrote three SQL files, and submitted the complete pipeline on
turn 29. Stage 1 was 1.0, Stage 2 was 2/3, and reward was
0.7833333333333333. Publishers and customers matched exactly. The 1992
publication rate now matched. The only remaining Stage 2 discrepancy
was the author page classification, which differed for 169 authors.

The submitted average excluded authors without book rows, and their NULL
page totals were never classified as below average. A developer-only
control including all authors eliminated all 169 differences. The revised
advisory now checks this requirement independently of the sales-join
warning. It uses only the public task description and the candidate SQL.
The actual saved query produced the advisory in an offline check.
Compacted observations also identify the next pending file. The full test
suite passed 95 tests in 36.91 seconds with
`pytest -q --tb=short --basetemp .venv/books-author-average`.

The audit verified all 29 prompts and responses, 42 dispatched calls,
41 eligible tool receipts, and the saved SQL. Token use was 17,703
sampled, 108,672 cached input, and 19,146 uncached input. The estimated
Tinker cost was USD 0.042029685. Billing had not posted for the run.

## Fifth 35B rehearsal

Run `runs/books-full-baseline/stronger-05` used revision `d4c75cf`,
26 turns and a 12,288-token context cap. The read-only quote was
USD 0.17111040 against USD 0.174219135 remaining. The model submitted all
three files on turn 24. Stage 1 was 1.0, Stage 2 was 2/3, and reward was
0.7833333333333333. Publishers and customers again matched exactly, and
both previously incorrect author metrics matched in this run. The only
remaining discrepancy was the author average-price flag, for 127 authors.

The SQL averaged each book's maximum price for the average-sale-price
measure. A private control computed that measure from sale lines and
removed all 127 differences. The change to the execution advisory detects
candidate SQL that averages a price column derived from MAX. It relies
only on the candidate SQL and the public model description. An offline
check verified it recognizes the actual saved author SQL.

The audit verified 24 prompt and response pairs, 30 dispatched tools,
28 eligible receipts, and that the saved files came from model writes.
Recorded usage was 17,963 sampled, 83,072 cached input, and 16,623 uncached
input tokens. Estimated cost was USD 0.038937435. Billing had not posted
when checked. The full suite ran with
`pytest -q --tb=short --basetemp .venv/books-sale-price` and passed 96 tests
in 36.43 seconds.

## Sixth 35B rehearsal

Run `runs/books-full-baseline/stronger-06` used revision `c8d72a9`,
the no-thinking renderer, 25 turns, and a 10,240-token context cap. Its
USD 0.13160448 quote fit the USD 0.13528170 remaining. The model again
produced exact publisher and customer outputs. Its first author draft
failed with a missing `book_id` in a CTE. It saved a repaired file on
turn 19, then submitted only the two tested files on turn 20 with five
turns left. The 32-call limit reserved the final call for submission,
so there was no tool capacity to try the saved repair. Both evaluation
stages ran. Stage 1 was 1.0, Stage 2 was
2/3, and the reward was 0.7833333333333333.

The no-thinking rehearsal now uses the same 48-call ceiling as reasoning
mode. The token spending bound depends on the number of sampled turns and
tokens, so the tool ceiling does not increase that bound. The new protocol
asks the model to test a freshly saved draft before an
early partial submission when it still has time, tool calls, working
tokens, and warehouse attempts. It permits explicit partial submission
after that test fails and in the reserved submission phase. Token use
was 6,014 sampled, 82,176 cached input, and 15,098 uncached input.
The estimate was USD 0.02221863.

## Seventh 35B rehearsal

Run `runs/books-full-baseline/stronger-07` used revision `30957bb`,
23 model turns, 48 tool calls, and a 9,216-token context cap. The
USD 0.11179008 quote fit USD 0.11306307 remaining. All 15 tables loaded
and the model wrote, executed, and independently submitted all three
files on turn 19. Stage 1 was 1.0, Stage 2 was 2/3, and the reward was
0.7833333333333333. The customer and publisher models matched. Six of
seven author columns matched, including the average-sale-price flag.
The page classification remained incorrect for 169 authors. The query
used a left join but projected the nullable relationship-table author
ID. This collapsed unmatched authors into a single NULL group.

A private comparison preserved the source author's identifier and
eliminated all 169 differences. The candidate-SQL advisory now recognizes
this exact public-schema mistake and points out the nullable identifier in
the receipt. This diagnostic does not reveal expected output or change
grading. The audited hosted run used 4,630 sampled, 75,520 cached input,
and 13,578 uncached input tokens, estimated at USD 0.01908795. All 28
executed tools, 26 eligible receipts and the saved SQL matched the trace.
The full suite after the follow-up passed 98 tests in 35.18 seconds with
`pytest -q --tb=short --basetemp .venv/books-author-key`.

## Eighth 35B rehearsal and authorization limit

Run `runs/books-full-baseline/stronger-08` used revision `f904e7b`,
20 model turns, 48 tool calls, the no-thinking renderer, and an
8,192-token context cap. The read-only quote was USD 0.09013248
against USD 0.09397512 remaining. The model loaded all 15 tables.
It validated the publisher output, hit a grouping error in its customer
draft, and saved a repair without testing it before the turn deadline.
It submitted only the tested publisher file on turn 20. Stage 1 was 1.0,
Stage 2 was 1/3, and the reward was 0.5666666666666667. The model did not
write an author file in this run, so the author-key repair has offline
evidence only. The audit matched all 20 responses, 28 tool calls, and
23 eligible receipts to the trace. The maximum context consumption
including the margin was 8,191. Recorded usage was 4,044 sampled,
64,000 cached input, and 14,409 uncached input tokens, estimated at
USD 0.01764279. No billing rows had posted.

The best model-driven outcome remains Stage 1 = 1.0 and Stage 2 = 2/3.
Several genuine complete submissions matched six of the seven author
columns. The missing column varies across runs. The developer-only
controls that isolate individual discrepancies do not count toward the
model-driven acceptance target.

The six 35B rehearsals from `stronger-03` through `stronger-08` used
an estimated USD 0.16366767 in total. Runs 04 through 08 used an
estimated USD 0.13991649 after the disconnect. Each session's quote
was checked against the cumulative USD 0.24 authorization before
launch. USD 0.07633233 remains, below the USD 0.09013248 bound of the
smallest tested profile. Shortening that last profile had already
left the agent without time to test its customer repair or write the
author file. No further hosted run or Snowflake workload started.
