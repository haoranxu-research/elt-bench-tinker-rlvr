# Hosted Qwen3.5-9B readiness

## Manifest failure and repair

In `runs/books-offline-model/llama-native-v5/pipelines/local-native.tools.jsonl`,
the model sent `write_pipeline_file(path="load.json", content="{}")` on
turn 3. The file was saved and the following load rejected it. The raw
tool-call receipt already contained the empty JSON object. The
diagnostic did not show the required shape or identify how to correct
it. Later tools could not proceed without a successful load.

The shared `books` prompt now asks for the source manifest as an object
and for a successful save receipt before execution. The tool schema
declares an object with a required `sources` field and stream arrays.
The write path rejects malformed manifests before saving and reports
the expected shape, allowed groups, or allowed streams. It preserves
the previous valid file on a rejected write. The source validation
rules still allow a partial manifest. The pinned evaluator decides
whether it qualifies for Stage 2.

## Executed checks

| Evidence | Actual result |
| --- | --- |
| Targeted Cookbook, runner and official adapter tests | 22 passed. The new regression initially failed because its warehouse test fixture lacked `inspect`. After that fixture was fixed, the new regression passed independently in 0.40 s. |
| Rehearsal `--preflight-only` | Exit 0. The pinned staged reference hashes and all 15 DuckDB counts matched, totaling 84,337 rows. Tinker metadata reported Qwen3.5-9B sampleable with 65,536 tokens of context. The pinned tokenizer loaded. `session_creation=not_started`. |
| Official `--preflight-only` with `--rollout-seconds 2400` | Exit 0. The pinned official configuration, tokenizer, model metadata, and budget check passed. `session_creation=not_started`. |
| Authorization checks | Hosted launch without `--allow-paid` and official launch with only `--allow-paid` each exited 2 before creating an output directory. |
| Snowflake and Airbyte metadata | RSA login and warehouse visibility passed, as did Airbyte workspace and custom-source visibility. Reused the six successful source syncs from the preceding verification. |
| Snowsight administrator read | `ELT_BOOKS_MONITOR` still covers `ELT_BOOKS_WH`. Used 0.72 credits of the 1.00 nominal quota, with 0.28 nominal remaining and immediate suspension at 150%. About 0.78 credits until suspension. No changes made. |

The rehearsal and official dry-run manifests are
`runs/books-9b-rehearsal-preflight/manifest.json` and
`runs/books-9b-official-preflight/manifest.json`. The combined targeted
test log and the corrected regression log are
`runs/books-offline-model/hosted-protocol-tests.log` and
`runs/books-offline-model/hosted-manifest-regression.log`.
The latest source syncs and credentials-free evaluator results remain
in the [local readiness record](books-model-readiness.md).

## Remaining paid actions

1. Authorize one hosted rehearsal using the command in the
   [handoff](../FINAL_HANDOFF.md#hosted-9b-rehearsal). One base-model
   sampling session, 20 turns maximum, local DuckDB execution, and
   pinned grading of the model's explicit submission. Check actual
   file writes, SQL execution feedback and terminal submission.
   Uncached token estimate **USD 0.078686208**, cap **USD 0.08**.
2. After reviewing the rehearsal, separately authorize one
   [official rollout](../FINAL_HANDOFF.md#final-live-command). It uses
   the unchanged official Airbyte-to-Snowflake path and evaluator.
   Allow one model rollout and at most one fresh grading replay, with
   both sampling and Airbyte configured for single attempts per request.
   Uncached token estimate **USD 0.124575744**, cap **USD 0.15**.

Total estimated Tinker token spend at checked rates is **USD 0.203261952**,
with a combined **USD 0.23** cap. Snowflake projects **0.50–0.64 compute
credits** based on previous runs, plus grading and cleanup margin,
against the existing trial allowance. The 40-minute rollout deadline
equates to about **0.667 credits** at continuous Gen1 X-Small usage.
The monitor limits further usage if in-flight operations or metering
raise the total. An account-specific dollar conversion was not verified.
[Tinker prices](https://tinker-docs.thinkingmachines.ai/tinker/models.json)
[Snowflake compute billing](https://docs.snowflake.com/en/user-guide/warehouses-overview#impact-on-credit-usage-and-billing)

No model weights were downloaded in this phase. No Tinker sampling
session, optimization, or Snowflake compute was started. A genuine
hosted submission and official Snowflake grading are still pending.
