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
uncached bound of USD 0.26327040. This model requires separate authorization.
The proposed next run is one local rehearsal with a USD 0.27 cap.
Snowflake grading remains gated on a genuine local score of 1.0 at both stages.
The preflight ran the following command in the configured project environment.

```powershell
./.venv/Scripts/python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); sys.path.insert(0,""scripts""); runpy.run_path(""scripts/books_model_rehearsal.py"",run_name=""__main__"")' --hosted --preflight-only --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5 --budget-usd 0.27 --checkout ../upstream-elt-bench --assets runs/books-assets --out runs/books-full-baseline/stronger-preflight-current
```
