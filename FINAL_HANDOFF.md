# ELT-Bench RLVR audit and handoff

Project at `S:\STARTER\elt-tinker-phase1`. The implementation and submission
materials are local. The [live-readiness update](evidence/live-readiness.md)
records subsequent read-only production Tinker checks and staged official
assets. This document retains the audit execution history.

## A. Completed implementations

| Area | Implementation and audit findings |
|---|---|
| Episode lifecycle | `src/elt_rl/episode.py` accepts JSON objects for `load.json` from the real Qwen XML parser. The failing renderer trace reproduced the old string-only contract. Submission publishes a grade after replay and cleanup, and an unsuccessful replay consumes an attempt. `cookbook.py` rejects further message steps after termination. |
| Official warehouse | `official.py`, `airbyte.py` and `official_sql.py` implement source selection, Terraform setup and sync, bounded transformations, private official evaluation, and owned-namespace cleanup. The audit added pinned-asset integrity checks, malformed provider-output handling, required Stage 2 reports, and recovery notices for ambiguous creation or failed cleanup. |
| Official preflight | `preflight.py official` inspects assets and local configuration. Authorized options inspect Airbyte workspace and source inventory, Snowflake login and warehouse visibility, and create/drop capability in a transient namespace. Inventory checks leave actual stream sync unverified. |
| Tinker path | `rendering.py` exercises the actual pinned Qwen tokenizer and Cookbook renderer. `training.py` uses the Cookbook's group rewards and datums and verifies sampled target IDs, behavior log probabilities, masks, and provenance. It skips constant or empty groups, waits for successful backward results before requesting one optimizer step, then probes action log probabilities and saves a checkpoint. `preflight.py tinker` runs the local renderer and budget checks without constructing Tinker clients. |
| Credentials | `settings.py` reads recognized options from the environment and ignored `.env`. CLI errors sanitize foreign exceptions. A regression test supplies a synthetic key to the client boundary and checks both the error output and manifest. The provisioned key was excluded from Git and all recorded evidence. |
| Robustness and delivery | `robustness.py --suite` executes eight local checks. [README](README.md), [DESIGN](DESIGN.md), and the [professor-facing summary](PROFESSOR_SUMMARY.md) are ready for review and transfer. |

## B. Executed evidence

Windows PowerShell, Python 3.12.6, SQLite 3.45.3, Terraform 1.13.5 with
Airbyte provider 0.6.5, and Tinker SDK 0.39.2. Both upstream working trees
were clean. The exact pins were [ELT-Bench `3b068d5f15f64541d05fbc33a817e4b08c6bf173`](https://github.com/uiuc-kang-lab/ELT-Bench/tree/3b068d5f15f64541d05fbc33a817e4b08c6bf173)
and [Cookbook `28de41edfcdd07ba3e7980f35d53a586024a2184`](https://github.com/thinking-machines-lab/tinker-cookbook/tree/28de41edfcdd07ba3e7980f35d53a586024a2184).

The baseline at `c7998ed31a56b88584a073183ad043f1805188f7` independently
reported **45 passed in 24.97s**. The audited implementation reported
**54 passed in 32.49s**, including provider validation, the real Qwen
renderer, the pinned official evaluator with synthetic warehouse responses,
cleanup regressions, and scripted Cookbook rollouts. The optimizer tests
used a fake SDK client. The group with local warehouse rewards
`[0.175, 1.0]` produced 20 aligned datums. The equal-reward case produced none.
[Final pytest output](evidence/audit-final-tests.txt)

The preflight and test commands were run from the project root. The
Windows launcher appends the existing base Python CPU PyTorch path to the
focused Cookbook environment. The provider used the checksum-verified
local mirror from the earlier [integration evidence](evidence/integrations.txt).

```powershell
Get-Content .env.example | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.TrimEnd('=')) -ErrorAction SilentlyContinue }
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:TINKER_TELEMETRY='0'
$env:CHECKPOINT_DISABLE='1'
$env:ELT_TEST_TERRAFORM=(Resolve-Path .venv-core/tf-tools/terraform.exe).Path
$env:TF_CLI_CONFIG_FILE=(Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:ELT_TEST_REAL_RENDERER='1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""--basetemp"", "".venv/audit-final-pass""]))' | Tee-Object -FilePath evidence/audit-final-tests.txt
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); import pytest; raise SystemExit(pytest.main([""-q"", ""-s"", ""-k"", ""cookbook_rollouts_produce_real_advantages_and_datums"", ""--basetemp"", "".venv/audit-datums""]))'

.\.venv-core\Scripts\python.exe -m elt_rl.cli examples/customer_orders.jsonl
.\.venv-core\Scripts\python.exe -m elt_rl.robustness examples/customer_orders.jsonl
.\.venv-core\Scripts\python.exe -m elt_rl.robustness examples/static_answer.jsonl
.\.venv-core\Scripts\python.exe -m elt_rl.robustness --suite --repetitions 3

$env:ELT_TERRAFORM=(Resolve-Path .venv-core/tf-tools/terraform.exe).Path
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); from elt_rl.preflight import main; raise SystemExit(main([""tinker"", ""--budget-usd"", ""0.60""]))'
```

- **SQLite demo, exit 0.** Loaded two four-row sources, surfaced the
  `wrong_amount` SQL error, accepted the repair and graded fresh replay
  at Stage 1 **1.0**, Stage 2 **1.0**, reward **1.0**. [Trace](evidence/audit-local.txt)
- **Robustness.** Data-derived comparison exited 0, hard-coded comparison
  exited 2 as intended, and the full suite exited 0.
  [Experiment JSON](evidence/audit-robustness.json)
- **Official preflight, exit 2.** The adjacent pinned assets and Terraform
  passed. Required live configuration was absent, so connectivity, stream
  health and Snowflake permissions were left unverified.
  [Official preflight output](evidence/audit-official-preflight.json)
- **Tinker preflight, exit 0.** Key presence, the actual cached Qwen tokenizer
  and renderer, and the reference budget passed. Project access and key
  validity remain unverified. The estimate was **USD 0.4904** for three
  members, including the verification forward pass. [Tinker preflight output](evidence/audit-tinker-preflight.json)

The targeted Cookbook check printed `Scripted warehouse rewards [0.175, 1.0], 20 training datums`
and reported **1 passed, 53 deselected in 12.11s**.

The public Qwen tokenizer was cached without downloading weights or using
credentials. The pinned revision is `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`.
The official evaluator checks ran the pinned evaluator scripts with a
synthetic connector. The Terraform test ran provider initialization and
schema validation only. No Snowflake session, Airbyte sync, live Tinker
sampling, backward pass, optimizer call or checkpoint creation was executed.

## C. Remaining blockers

- **Official `books`.** The checkout, Terraform and reference CSVs are
  configured. The generated Airbyte `books` input bundle, reachable self-hosted
  workspace and source services, Snowflake credential JSON and warehouse
  still require setup.
  Actual source sync, dedicated warehouse visibility, and role privileges
  to create, transform, grade and clean up the run-owned databases remain
  unverified.
- **Tinker.** The default renderer works offline on this Windows host.
  Authentication, billing usage read access, model capabilities and
  published prices passed read-only production checks. An authorized run
  must confirm actual session creation. Genuine reward variation is required.
  Equal rewards cause the run to exit before optimizer calls. A live
  checkpoint and measurement of post-update state remain unexecuted.
- **Submission.** The native Google Doc, GitHub publication, and contact with
  the professor remain pending authorization.

## D. Live execution checklist

1. After warehouse approval, use the pinned benchmark setup in the
   [README](README.md#official-snowflake-rollout). Set the official environment
   entries, use a dedicated Snowflake role and monitored warehouse, and keep
   the run output private. Probe Airbyte inventory, Snowflake login, and
   transient namespace cleanup. The source sync itself is exercised by the
   official rollout.
2. After usage approval, run one bounded official rollout. Retain its
   manifest, Airbyte job log, Stage 1 results and, if the gate passes, Stage 2
   output. Inspect the run for `cleanup-required.txt`.
3. After Tinker usage approval, run the local SQLite training pilot. Retain the
   manifest, actual sampling rewards, datum count, confirmed forward/backward
   and optimizer results, post-update probe, and checkpoint. Compare billing
   against the recorded session. There is no automatic paid retry.

```bash
python -m elt_rl.preflight official --airbyte-probe --snowflake-probe --namespace-probe
python -m elt_rl.run official-rollout --allow-paid --allow-warehouse --budget-usd 1 --out runs/books-001

python -m elt_rl.preflight tinker --budget-usd 0.60 --group-size 3
python -m elt_rl.run train-one --allow-paid --budget-usd 0.60 --group-size 3 --out runs/tinker-001
```

The budgets estimate token costs using the public rate card. The official
warehouse uses its own limit and the trainer's state probe does not measure
downstream improvement. [Tinker pricing](https://tinker-docs.thinkingmachines.ai/tinker/models/models_and_pricing/)

## E. Scientific observations

Scores are from actual SQLite execution. Each case ran three times. Extra
milliseconds are the median duration of the additional check on this host,
measured separately from the baseline.

| Case | Intervention | Original | Robust | Detected behavior | Extra ms |
|---|---|---:|---:|---|---:|
| Data-derived control | Change order assignments and amounts | 1.0 | 1.0 | Correct SQL follows the data | 66.77 |
| Hard-coded aggregates | Same changed orders | 1.0 | 0.35 | Both materialized outputs are wrong despite complete loading | 68.43 |
| Amount cutoff | Change one amount from 12.75 to 22.75 | 1.0 | 0.675 | A legitimate order is excluded by an unjustified cutoff | 78.17 |
| Missing row | Add a customer with no orders | 1.0 | 0.675 | Required customer is absent | 84.33 |
| Duplicate key | Add a customer with an existing name | 1.0 | 0.675 | Corrupted customer identifier duplicates another key | 84.24 |
| Null assumption | Change one additional name to NULL | 1.0 | 0.675 | A missing name is incorrectly filled | 68.64 |
| Order invariance | Reverse source order and output descending keys | 1.0 | 1.0 | Ordering alone does not change the grade | 66.71 |
| Repeat execution | Load and transform twice in the same database | 1.0 | 1.0 | Local replace semantics preserve table contents | 33.48 |

The new expected outputs were specified independently of the candidate SQL.
The repeat case tests the local fixture's full refresh and replace behavior.
These controlled examples do not establish model generalization, resistance
to arbitrary reward hacking, or Snowflake costs.

## F. Git status

The audited implementation commit is
`8afaeaa3f0c318e8032d0d253e6c9bbc9784654a`. The succeeding handoff commit
contains the documentation and transcripts. To resolve its exact hash and
recheck the local working tree:

```powershell
git log -1 --format=%H -- FINAL_HANDOFF.md
git status --porcelain
git ls-files .env
git check-ignore .env
```

The expected porcelain output and tracked-file lookup are empty. The ignored
file check reports `.env` without reading it.
