# Hosted books submission after context and schema fixes

The first and only newly authorized rehearsal met the local acceptance
target. The base Qwen3.5-9B model independently submitted with
`submit_pipeline(mode="partial")` on turn 24. The submission replayed its
tested `publishers.sql` and `customers.sql` in a new local DuckDB
namespace. Both pinned ELT-Bench evaluators ran. **Stage 1 = 1.0,
Stage 2 = 0.0, execution-derived reward = 0.35.** The process exited 0.
No training, Snowflake compute, or official cloud rollout took place.

## Defects and repairs

- The former context guard charged every rendered prompt a full 2,048
  tokens of generation headroom even when the request could generate
  only 24 more tokens. The Books sampler now clamps every request against
  actual rendered prompt length, the remaining sampled-token allowance,
  its per-turn cap, and a 32-token context margin. When full working
  headroom no longer fits, the host can compact the prompt into
  instructions, loaded columns, pinned source relationships, current
  file and test status, and the latest error. Current SQL remains in the
  workspace and can be read exactly in pages with `read_pipeline_file`.
- The previous agent saw flat column lists and a warehouse receipt of
  row counts. It treated `book_language` as if it contained book rows.
  Books tools now report actual warehouse column names, allow targeted
  table inspection, and surface the join relationships documented by the
  pinned source schemas. The task, evaluator, and rewards are unchanged.
- The previously implemented 54-token submit-only reserve remains in
  place. Compaction keeps the last working state available without using
  the final request until a tested subset can be submitted.

Code commit `8476fd62e821b193e2a2fcb4dd224390a205bace`.
The full offline suite passed **87 tests** in 30.44 seconds with
the real pinned renderer and Terraform schema checks enabled.
The archived response replay reached 21 requests without context
overflow at both 12,288 and 8,192 context tokens, with one and two
compactions respectively. Every replay request fit its context budget.
A separate DuckDB regression reproduced the nonexistent
`book_language.book_id` error, verified that the exact SQL and error were
recoverable, and tested an independently scripted diagnostic correction.
The scripted runs are offline controls.

## Genuine hosted trajectory and evaluation

The rehearsal ran from approximately 04:51:54 to 04:54:09 UTC on
November 21, 2026. It used a 12,288-token context, 24 turns, and 8,192
total sampled tokens with 54 reserved for submission. Before starting,
the USD 0.095084544 worst-case estimate fit the remaining USD 0.30
authorization and the live per-run limit of USD 0.10.

| Turns | Evidence |
| --- | --- |
| 1–6 | Read the task and output specs, saved its own manifest, and loaded all 15 tables with 84,337 rows. |
| 7–10 | The model referenced nonexistent `bl.book_id` in publishers SQL. DuckDB identified the error. The model resaved SQL using `b.book_id`, then materialized and tested 2,264 publisher rows. |
| 11–14 | The static validator flagged disallowed `ARRAY_AGG`. The model rewrote the customers SQL and materialized and tested 2,000 rows. |
| 15–23 | Authored and revised `authors.sql`. Static parsing continued to fail, so the file stayed untested. The working conversation compacted once. |
| 24 | Tinker returned an independent, complete 27-token partial submit call within the 54-token final request. The accepted manifest listed exactly the two tested files. |

The Stage 1 log verified all 15 raw tables. Stage 2 made three model
queries. Publishers matched six columns and missed the expected
`PER_JAPANESE_BOOKS` values. Customers matched six columns and failed the
two percentage columns. Authors had no submitted table. Stage 2 scored
zero fully matching models. The reward is the unchanged weighted
aggregate.

The offline audit decoded all 24 hosted samples, matched their 24 tool
calls with the dispatched calls, matched saved files to model writes,
and verified aligned finite log probabilities and unique sequence IDs.
All 21 eligible tool receipts appeared in the next uncompressed working
prompt. All live requests fit the configured context. The maximum
observed prompt length plus its request cap and margin was 12,177 tokens.
The round-24 action came from the hosted sampler.

| Tinker usage across the new authorization | Total |
| --- | ---: |
| Hosted sessions | 1 |
| Sampled tokens | 6,541 |
| Cached input tokens | 104,064 |
| Uncached input tokens | 13,758 |
| Training tokens | 0 |
| Estimated spend from observed tokens | USD 0.015649827 |
| Remaining under the USD 0.30 authorization on that estimate | USD 0.284350173 |

The read-only billing snapshot at 04:54:50 UTC had no posted row for
the session. Invoiced spend remains unverified. Sampling stopped
after this result.

Private artifacts are under `runs/books-context-loop/attempt-01/` and
include the usage manifest, prompt and action tokens, decoded trajectory,
tool log, candidate SQL, accepted file manifest, both evaluator outputs,
and an independent audit with hashes. The completed load, SQL artifacts,
and evaluator replay remain separate from the credentialed Snowflake
path. Offline replay evidence is in
`runs/books-context-loop/archived-context-replay.json`, and the full test
log is in `runs/books-context-loop/tests-final.log`.

## Official rollout readiness

The read-only Snowflake credential probe, Airbyte workspace probe,
and the exact Qwen3.5-9B official launch preflight passed.
Warehouse metadata showed a suspended Gen1 X-Small with auto-resume
and 60-second auto-suspend. The service role exposed direct CREATE DATABASE
and warehouse USAGE grants in the read-only grant listing.
The prior full local Airbyte sync verified all six connections and all
15 row counts. The current worker configuration still limits each sync
to one attempt. The prepared official output path is unused.

The refreshed administrator monitor view showed 0.72 credits used
against a 1.00-credit nominal quota and immediate suspension at 150%.
The dedicated X-Small warehouse has approximately 0.78 effective credits
remaining. The additional official run is estimated at
**USD 0.124575744** for Tinker under a USD 0.15 cap, and **0.50–0.64**
Snowflake compute credits before grading and cleanup margin. The
40-minute timeout corresponds to approximately 0.667 credits of
continuous Gen1 X-Small compute. The preflight did not create a
namespace or start warehouse compute.
[Tinker rate card](https://tinker-docs.thinkingmachines.ai/tinker/models.json)
[Snowflake warehouse credit rates](https://docs.snowflake.com/en/user-guide/warehouses-overview#impact-on-credit-usage-and-billing)

The [prepared official command](../FINAL_HANDOFF.md#final-live-command)
uses the same model and corrected workflow. One official run now
requires separate authorization for Tinker and Snowflake compute.
