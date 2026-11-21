# Hosted Qwen3.5-9B rehearsal with a submission reserve

One authorized sampling-only Tinker session used the committed model
workflow at `7cdc30d5114154c29d0604d3ec7da11d4c0cce91`. The DuckDB
run was recorded from approximately 04:18:41 to 04:20:27 UTC on
November 21, 2026. The price gate passed at USD 0.078686208 under the
USD 0.08 limit. Operation submission was set to one attempt. No training
or Snowflake compute ran.

**Result:** exit 2, `rollout_unsubmitted`, reward **0.0**. The model
made no `submit_pipeline` call. No file passed SQL execution, and
neither Stage 1 nor Stage 2 ran. The reserve stayed intact. This run
does not establish readiness for the official Snowflake rollout.

## What failed

The model independently saved a valid load manifest and loaded all
15 tables with 84,337 rows. It saved five distinct versions of
`publishers.sql` and reused unchanged bytes once. Only that SQL file
was attempted. It did not write `customers.sql` or `authors.sql`.

| Turn | Actual DuckDB feedback |
| ---: | --- |
| 6 | The initial SQL used `DESC` in a tuple predicate. Its translated SQL failed to parse near `AS`. |
| 10 | `book.pages` did not exist. The pinned column is `num_pages`. |
| 14 | The alias for `book_author` did not have `publisher_id`. |
| 17 | The alias for `book_language` did not have `language`. |
| 19 | The final query counted nonexistent `book_language.book_id`. The saved query also joined a book ID to a language ID. |

The final turn's transform action was complete and was dispatched. After
the binder error, 78 sampled tokens remained. Of those, 54 were reserved
and 24 were available for work. There were no tested files to enter
submission-only finalization. The terminal reason was **context overflow**.
An offline replay reproduced all 19 request prompts and caps. It measured
the next rendered prompt at 10,347 tokens. The pinned wrapper checked it
against the full 2,048-token per-turn generation allowance, and
10,347 + 2,048 exceeded the 12,288-token context. The primary obstacle to a
valid submission was that the working SQL never passed execution.

## Audit and usage

The audit decoded all 19 recorded samples, matched all 21 tool calls in
order, and confirmed all 20 receipts with a following request appeared
in the next prompt. The saved files matched the model's writes. The
sampler sequence IDs were unique and log probabilities aligned with
the returned tokens.

| Usage | Count |
| --- | ---: |
| Sampled tokens | 6,066 |
| Cached input tokens | 94,464 |
| Uncached input tokens | 11,281 |
| Training tokens | 0 |

Usage-based estimated spend was **USD 0.013947402**. The read-only
billing check at 04:21:01 UTC returned zero posted rows for the session.
Invoiced spend remains unverified.
[Tinker rate card](https://tinker-docs.thinkingmachines.ai/tinker/models.json)

Private evidence is under `runs/books-9b-rehearsal-reserved-live/`.
It includes `manifest.json`, `prompt-inputs.jsonl`,
`sampled-actions.jsonl`, `decoded-actions.jsonl`, saved artifacts and
tool receipts in `pipelines/`, the unsubmitted manifest,
`audit-result.json`, and the offline `context-diagnostic.json`.
No further paid attempt was launched.
