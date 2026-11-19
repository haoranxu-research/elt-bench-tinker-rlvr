# Authorized Tinker pilot

On 2026-11-19 UTC, one training session on `Qwen/Qwen3.5-4B` completed a real
rank-16 LoRA optimizer step. The pilot used the local SQLite ELT fixture and
three live sampled rollouts. It used no Snowflake connection or other paid
infrastructure.

The live rate check gave a projected token bound of **USD 0.4903936**
against the approved **USD 0.60** before creating the session. The pinned
SDK's request submission retries and sampler backpressure resubmission
were disabled. Future result polling continued for the original requests.
There was no second training session or paid operation retry.

## Observed result

| Check | Result |
|---|---|
| Local run start and finish UTC | 09:53:23.520793 to 09:57:38.004616 |
| Rollout rewards | `[1.0, 0.0, 1.0]` |
| Rollout termination | Successful submission, turn limit, successful submission |
| Sampling provenance | 42 responses with unique sequence IDs. All 3,125 tokens had finite matching behavior log probabilities. Recorded prompt, cached, and sampled token counts matched the rollout transcript. |
| Training inputs | Six datums, 3,125 aligned action targets, 10,209 input tokens |
| `forward_backward` | Completed, returned six results. `loss:sum=485.333438873291` and `clock_cycle:unique=7519520.0`. |
| `optim_step` | Completed as one real service operation |
| Post-update check | Maximum absolute action log-probability delta **0.5459532737731934** across 1,169 action tokens. The probe used 2,781 input tokens. |
| Checkpoint | Saved with a 24-hour TTL. Independent metadata readback confirmed the exact base model and LoRA rank 16. |
| Exit and terminal status | `pilot_exit=0`, `checkpoint_saved` |

The post-update check tests parameter-update behavior on one training datum.
No downstream model evaluation was run.

## Token usage and billing

The sampler recorded **54,528 cached prefill**, **7,249 uncached prefill**
and **3,125 sampled** tokens. The completed training requests carried **10,209**
backward-pass input tokens and **2,781** verification forward-pass input
tokens. The published-rate estimate is **USD 0.018705273** for those measured
token counts, including **USD 0.009131643** for sampling. This is a usage-based
estimate excluding storage and any billing adjustments.
[Published rates](https://tinker-docs.thinkingmachines.ai/tinker/models/models_and_pricing/)

At 09:58:03 UTC the read-only billing API returned zero rows for this session
in the 09:00–10:00 UTC window. A second read at 10:00:12 UTC also returned zero
rows in the 09:00–11:00 UTC window. Final billed cost remained pending.

## Reproduction and preserved artifacts

The approved command was executed once from the repository root.

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:TINKER_TELEMETRY='0'
foreach ($name in 'TINKER_API_KEY','TINKER_PROJECT_ID','TINKER_CREDENTIAL_CMD') { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_module(""elt_rl.run"", run_name=""__main__"")' train-one --allow-paid --budget-usd 0.60 --group-size 3 --model Qwen/Qwen3.5-4B --renderer qwen3_5_disable_thinking --out runs/tinker-001 2>&1 | Tee-Object -FilePath runs/tinker-001-console.txt
```

The private files remain outside version control under `runs/tinker-001/`.

| Artifact | Contents |
|---|---|
| `manifest.json` | Session URL, checkpoint path and metadata, rates, receipt statuses, rollouts and aligned-target fingerprint |
| `sampled-actions.jsonl` | Returned token IDs, log probabilities, sequence IDs and usage for each response |
| `pipelines/` | The two submitted pipeline artifact trees |
| `audit_result.py`, `audit-result-initial.json`, `audit-result.json` | Independent token and transcript consistency checks and both read-only billing observations |

SHA-256 of `manifest.json` is
`cf2e20fd630e6df4986e0c3b691c10d5c20c651fed36f3287fdc75646fc7549b`.
SHA-256 of `sampled-actions.jsonl` is
`a1958966dcd4873f07dc112210ebe2091bfff85f31b6299d7c4378ec19da7c14`.
The aligned training target digest is
`f2d251f6592241751a3d23e5342316a2d8daa627e2afb978611ed41225028587`.

The full offline regression suite on the pilot code reported
`56 passed in 39.25s`, including the SDK no-resubmission test.
