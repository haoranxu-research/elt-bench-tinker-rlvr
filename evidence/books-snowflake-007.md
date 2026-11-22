# Official Snowflake Books attempt 007

On November 22, 2026, the hosted Qwen3.6-35B-A3B agent ran from implementation
commit `073d737` with an empty SQL workspace. The official ELT-Bench
checkpoint was `3b068d5f15f64541d05fbc33a817e4b08c6bf173`.
The pinned Cookbook was `28de41edfcdd07ba3e7980f35d53a586024a2184`.

| Requirement | Verified result |
| --- | --- |
| Actual source load and grading replay | All six Airbyte connections succeeded on the first attempt in each phase. All 15 required tables and 84,337 rows matched. |
| Independent model submission | The agent wrote and tested three transformations, then called `submit_pipeline` in complete mode on turn 32. All 43 dispatched calls matched sampled calls. Saved artifacts matched model writes byte for byte. |
| Official Stage 1 | **1.0**, 15 of 15 raw counts |
| Official Stage 2 | **1.0**, all columns in `publishers`, `customers`, and `authors` matched |
| Warehouse and trajectory reward | **1.0** each |
| Offline training interface audit | Cookbook returns `[1.0, 0.0]` with an empty zero-return control, yielding four datums and 9,334 aligned sampled action tokens. All sampled log probabilities were finite and aligned. |
| Cleanup | Both transient Snowflake databases and their Airbyte resources were removed. `ELT_BOOKS_WH` was suspended with a 60-second auto-suspend setting. |

## Timeline and reproducibility

- The fresh local Airbyte preflight checked six connections, the pinned
  connector manifest, all 15 counts, and cleanup. The independent hosted
  TEXT-date rehearsal returned both full scores, with 37 model-authored tool
  calls and all three files. [Publisher validation and diagnosis](books-publisher-stability.md)
- Native manifest start was 06:46:18 UTC. The model-directed load returned at
  07:05:00 UTC after 1,062.953 seconds. Initial Airbyte jobs were 171–176.
- The accepted submission was recorded at 07:17:40 UTC. Replay jobs 177–182
  succeeded. Grading and replay cleanup took another 1,201.375 seconds.
  The runner recorded its final status at 07:37:57 UTC and exited 0.
- Two context compactions preserved the working state. The largest requested
  context including margin was 11,749 of 12,288 tokens.
- A separate host-only replay of those same 32 archived token actions also
  scored 1.0 on the TEXT-date mirror. Native acceptance relies on the
  independent Snowflake receipts above.

The agent received the public task, observed source schemas and data checks,
and its own saved SQL. Its new workspace did not contain previous submissions
or hidden evaluation assets. Pinned Stage 1 gates Stage 2, and the reward
formula remains `0.35 × Stage 1 + 0.65 × Stage 2`.

## Resource verification

| Resource | Recorded usage or limit |
| --- | --- |
| Native Tinker tokens | 9,334 sampled, 164,608 cached prefill, 24,359 uncached prefill |
| Native Tinker cost estimate | **$0.03823716** calculated from token receipts. Session-level billing had no posted rows when checked. |
| This continuation's two hosted local rehearsals plus native run | **$0.10438464** using published token rates across the three runs |
| Snowflake trial guard | 6.00 dedicated monitor credits with 90% immediate suspension; 3.29 used before launch left about 2.11 credits of effective headroom. The trial showed about $392 available. |
| Snowflake per-run estimate | **0.75–1.10 compute credits** before launch. The post-run numeric monitor delta was not collected. |

Existing funded and free-trial resources were used. The Tinker console showed
$8.99 prepaid and auto-reload disabled. No additional training or account
upgrade was performed. [Tinker rate card](https://thinkingmachines.ai/tinker/pricing/)

## Private evidence and launch

The exact native launch flags and setup are in the [handoff](../FINAL_HANDOFF.md#final-live-command).
The run is stored in `runs/books-official-qwen35b-007/`. Its ignored artifacts include:

- `manifest.json`, `prompt-inputs.jsonl`, `sampled-actions.jsonl`, and
  `pipelines/` with tool receipts, submitted SQL and the acceptance manifest.
- `official/` with native grade, Stage 2 comparison, job records and evaluator
  logs from the run.
- `provenance-audit.json` and `training-return-audit.json` with artifact
  hashes and matching sampled actions, log probabilities, and returns.
- `airbyte-audit.json`, `airbyte-job-receipts/`, `snowflake-cleanup-verification.json`,
  and `audit-status.json` with zero exit codes for all four audits.

The public repository records results and reproduction instructions. Raw
prompt receipts, assets, and cloud credentials remain private.
