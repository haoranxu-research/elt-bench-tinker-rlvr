# Hosted Qwen3.5-9B books rehearsal

One authorized Tinker session ran on November 21, 2026 between approximately
02:43:14 and 02:45:30 UTC from commit
`7924ddaa1e1137c019eed4b913ffb73330068626`. The model was the base
`Qwen/Qwen3.5-9B` with the pinned no-thinking Cookbook renderer.
DuckDB executed the staged books inputs. No Snowflake compute, training,
or second run was started. The SDK submission retry limit was one attempt.

**Outcome:** exit 2, `rollout_unsubmitted`, reward **0.0**. No grading
replay ran. Stage 1 and Stage 2 results are unavailable for this trajectory.

## Model actions

| Turn | Observed behavior |
| ---: | --- |
| 1–3 | Read the task and the public source and output schemas. |
| 4–5 | Authored a valid manifest and loaded all 15 tables, totaling 84,337 rows. |
| 6–9 | Saved `publishers.sql`. Static checking flagged a qualified raw table on line 17. The model resaved the file and materialized 2,264 publisher rows. |
| 10–17 | Saved four versions of `customers.sql`. DuckDB reported missing `country_id` on aliases `sm` and `ca1`, then an ungrouped `customer_id`. The last version executed and materialized 1,697 rows. Execution did not establish correctness. |
| 18 | Saved `authors.sql`. Two tested files were available for explicit partial submission. |
| 19 | Started a transform call and exhausted the sampled-token budget inside the tool-call text. No complete tool call was dispatched on this turn. |

The tool advised partial submission after turns 17 and 18. The model
used turn 18 to write `authors.sql`. At the start of turn 19 it had
used 6,120 of 6,144 sampled tokens. The final request allowed 24 tokens
and returned `stop_reason=length` with a truncated call beginning
`execute_pipeline`. Its prompt was 10,198 tokens within the 12,288
context cap, with eight tool-call slots left. The terminal condition
was sampled-token exhaustion. Two files had tested successfully,
but the model never invoked `submit_pipeline`. Zero is the defined
reward for an unsubmitted episode.

## Independent audit

The audit decoded the 19 returned samples with the pinned tokenizer.
All 24 decoded tool calls matched the dispatched names, turns, and
arguments. All 24 receipts appeared in the model's next prompt.
The four retained files matched the model's final successful writes
byte for byte. Prompt lengths, unique sampler sequence identifiers,
finite token-aligned log probabilities, and token accounting matched.

| Usage | Count |
| --- | ---: |
| Sampled tokens | 6,144 |
| Cached input tokens | 87,552 |
| Uncached input tokens | 11,108 |
| Training tokens | 0 |

Observed token usage at checked Tinker rates gives **USD 0.013543728
estimated**. The read-only billing query at 02:45:54 UTC returned
no posted rows for the session. Invoiced spend is unverified.
[Tinker rate card](https://tinker-docs.thinkingmachines.ai/tinker/models.json)

Private evidence under `runs/books-9b-rehearsal-live/` includes
`manifest.json`, `prompt-inputs.jsonl`, `sampled-actions.jsonl`,
`decoded-actions.jsonl`, the three SQL files and manifest in
`pipelines/`, the tool trace, the unsubmitted manifest, and
`audit-result.json` with hashes and the billing snapshot. The executed
[hosted command](../FINAL_HANDOFF.md#hosted-9b-rehearsal) used exactly
one authorized run and returned exit code 2.

## Official rollout decision

The rehearsal confirmed independent loading, persistence, SQL testing,
and repair. It did not establish successful submission or grading.
The official run's 8,192-sampled-token limit is higher. The feedback
reported turns, tool calls, and warehouse attempts. It never reported
how few sampled tokens remained. A sampled-token-aware submission
warning and reserve would address the observed budget failure while
keeping submission an explicit model action. The official rollout has
no authorization from this run.
