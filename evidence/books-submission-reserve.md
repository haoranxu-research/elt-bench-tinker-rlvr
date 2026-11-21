# Books sampled-token reserve

## Accounting and behavior

The pinned Cookbook runner totals returned action tokens, including
tokens from interrupted responses. The per-turn request is capped by
the remaining sampled tokens, context room, and per-turn limit. The
previous hosted rehearsal had used 6,120 of 6,144 tokens before turn 19.
It gave an unfinished transform call 24 tokens and stopped on length.
The working tool receipts exposed the turn and call counts without
showing this sampled-token limit.

The host now measures the final action using the production renderer's
serialized assistant output, including its stop token. Both
`submit_pipeline(mode="complete")` and
`submit_pipeline(mode="partial")` measured 27 tokens with the pinned
Qwen3.5-9B tokenizer. The host reserves twice that size, 54 tokens.
The reserve is part of the original total. Each working request is
capped before sampling. A truncated working response is counted and
never dispatched. The host also reserves a final turn and tool slot,
including when a working response packs multiple calls or uses an
unknown tool name. The final prompt lists the tested files and exposes
only `submit_pipeline`. A refusal, invalid call, or interruption in
that final response ends without a submission. Rewards, replay isolation,
and evaluator code are unchanged.

## Executed verification

| Check | Result |
| --- | --- |
| Full offline suite with the real pinned renderer and Terraform schema checks enabled | 87 passed in 33.27 s. Regression variants cover interrupted working and final responses, last-turn and last-tool availability, unknown tools, invalid submissions, attempted edits, and refusals. |
| Archived Tinker outputs with the original 6,144-token policy | Reproduced the 24-token interrupted request on turn 19, no submission, no evaluators, reward 0. |
| Same archived trajectory with the reserve and a scripted final action | Turn 18 was capped at 964 tokens and its interrupted author write was discarded. Turn 19 offered 54 tokens in a 367-token submit-only prompt. The scripted 27-token partial action submitted `publishers.sql` and `customers.sql` at 6,117 total sampled tokens. The pinned evaluators over DuckDB returned Stage 1 = 1, Stage 2 = 0, reward = 0.35. |
| Revised hosted read-only preflight | Passed with 54 reserved and 6,090 working tokens. Estimated upper bound USD 0.078686208. Tinker session creation was recorded as `not_started`. |

The replay validates the workflow and execution-derived reward. Its
final action was scripted. A model-chosen final submission has yet to
run with the reserve.

Full test command from the repository root:

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:CHECKPOINT_DISABLE = '1'
$env:ELT_TEST_REAL_RENDERER = '1'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:ELT_TEST_TERRAFORM = (Resolve-Path .venv-core/tf-tools/terraform.exe).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/books-token-reserve-verified""]))'
```

Private evidence is under `runs/books-9b-reserve-replay/`, with
`tests-final.log`, the replay script `audit.py`, and
`final/result.json`. The hosted preflight manifest is under
`runs/books-9b-reserved-preflight/`.

## Next authorized verification

Run the [prepared hosted 9B command](../FINAL_HANDOFF.md#hosted-9b-rehearsal)
once after separate authorization. It uses the same staged DuckDB inputs,
20 total turns, 32 tool calls, a 12,288-token context, and a 2,048-token
working per-turn limit. The 6,144 sampled tokens are split into up to
6,090 for work and 54 for the final request. The cap is USD 0.08.
The official configuration retains its 8,192 total sampled tokens,
including the same 54-token reserve.

Verify a genuine sampled `submit_pipeline` action, its accepted
tested-file manifest, both pinned evaluator outputs, the resulting
reward, and the token ledger. A refusal or incomplete final call is
an unsubmitted outcome. No paid sampling, Snowflake compute, or
training took place during this fix.
