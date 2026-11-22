# Official Books on-policy Tinker update

On November 22, 2026, `train-official-one` completed one genuine
Tinker optimizer step using the reward from a new official Snowflake
Books rollout. The earlier full-score native evaluation and the
SQLite optimizer pilot were separate runs.

| Item | Verified result |
| --- | --- |
| Implementation | `3f79707dae499337b454d2ce40e9fe025ef0396b` |
| Official benchmark | Books at ELT-Bench `3b068d5f15f64541d05fbc33a817e4b08c6bf173` |
| Behavior policy | Pre-update snapshot of the same Qwen/Qwen3.6-35B-A3B rank-16 LoRA trainer, sampled at temperature 1.0 |
| Airbyte | Jobs 189–194 loaded the working warehouse. Jobs 195–200 reloaded the grading warehouse. Each succeeded on its first attempt. |
| Submission | The model wrote, tested and explicitly submitted all three SQL files in complete mode on turn 40. All 51 dispatched tool calls and submitted file bytes matched sampled actions. |
| Native grades | Stage 1 **1.0** across 15 tables and 84,337 rows. Stage 2 **1.0**, with all publisher, customer and author columns matching. |
| Training return | Warehouse reward and trajectory reward both **1.0**. Fixed baseline **0.0** gave action advantage **+1.0**. |
| Training data | Five datums and **12,261** aligned action targets and finite original log probabilities. The independently rebuilt alignment hash matched the live manifest. |
| Tinker update | One completed `forward_backward` with five outputs and loss sum −12,261.0, followed by one completed `optim_step`. |
| Post-update check | Maximum absolute action log-probability difference **3.00096786** over **4,509** probe tokens. Tinker saved a checkpoint with a 24-hour TTL and confirmed the base model and LoRA rank. |
| Cleanup | Both isolated databases removed. Zero remaining run-owned Airbyte sources, destinations or connections. X-Small warehouse suspended with 60-second auto-suspend. |

The native run started at 09:00:16 UTC, accepted submission at 09:35:05,
and recorded the verified checkpoint at 09:54:20. Grading replay and its
cleanup took 1,114.781 seconds after acceptance. The model had a
54-token final submission reserve and used 27 tokens for the explicit call.

## Objective and comparison

The experiment samples once from the trainer's initial LoRA snapshot.
For a verified terminal return `R`, each eligible sampled token receives
advantage `A = R − 0`. Prompt positions receive zero advantage. Tinker's
token-level `importance_sampling` objective weights each action's
advantage by `exp(log p_train − log p_behavior)`, with the denominator
taken from its own original sampling receipt. The training policy
starts from the snapshot used for sampling. No model update intervenes.
This is a single-trajectory policy-gradient step. The SQLite pilot
centered advantages against the mean of three sampled returns.
No additional trajectory or fabricated reward was used here. Zero
signal, invalid receipts, failed grading, and missing submissions
block optimization. The official grading and reward formula are unchanged.
[Tinker loss documentation](https://tinker-docs.thinkingmachines.ai/tinker/losses/)

Offline reconstruction from native attempts
[006](books-snowflake-006.md) and [007](books-snowflake-007.md)
verified four datums each, with 9,436 and 9,334 original targets and
advantages 0.783333 and 1.0, respectively. Those reconstructions used no
new samples or optimization calls. The test suite passed **134** offline
tests, including the reward, timeout, masking, checkpoint and cleanup checks.

## Resource use

| Resource | Observed quantity or estimate |
| --- | --- |
| Tinker sampling | 12,261 sampled, 213,888 cached prefill, 28,135 uncached prefill tokens |
| Tinker training and verification | 33,105 forward/backward input tokens and 10,687 verification forward input tokens |
| Tinker charge estimate | **$0.099822289** at published token rates from measured usage. Preflight upper estimate **$0.830570496**, under the configured **$0.90** gate. Session billing had no posted rows at the check. |
| Snowflake | Dedicated monitor's rounded used-credit reading rose from **4.03 to 4.74**, a **0.71-credit** delta. The delta is a monitor observation, which can include cloud services. It does not isolate compute or represent an invoice. |

The run used existing prepaid and trial resources. The Snowflake dedicated
quota remained 6 credits, with 90% immediate suspension. Tinker auto-reload
remained off. The update probe verified a changed training state. This run
included no post-update benchmark or measurement of generalization.
[Tinker rate card](https://thinkingmachines.ai/tinker/pricing/)

## Reproduction and private receipts

Use the existing [Snowflake setup and environment](../FINAL_HANDOFF.md#final-live-command).
With approved Tinker and Snowflake resources, an installed pinned runtime,
and cached public tokenizer, the native training command is:

```powershell
.\.venv\Scripts\python.exe -m elt_rl.run train-official-one --budget-usd 0.90 --allow-paid --allow-warehouse --out runs/books-official-training-reproduction
```

The verified Windows host used the base-site-packages launcher shown
in the handoff. The mode defaults to the 40-turn, 60-tool, 12,288-token Books
profile and the 2,400-second action and 1,500-second grading deadlines.
Use a new private output path. The same command with `--preflight-only`
in place of the two authorization flags checks pricing and model support
without creating a session.

Private receipts in `runs/books-official-training-001/` include
`manifest.json`, `prompt-inputs.jsonl`, `sampled-actions.jsonl`, `pipelines/`,
`official/`, `fixed-baseline-audit.json`, `provenance-audit.json`,
`airbyte-audit.json`, and `snowflake-cleanup-verification.json`.
The checkpoint path, model outputs, benchmark references and credentials
remain private.
