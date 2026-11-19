# Live acceptance setup

## Tinker pilot

Production read-only checks accepted the saved credential, reported
`Qwen/Qwen3.5-4B` as sampleable and trainable with 65,536 context tokens, and
permitted reading billing usage. The project ID is unset, so `ServiceClient`
will use the organization’s Default project. A read-only Default project can
still reject session creation. Confirm the organization has spendable credit
before the authorized run. The usage API response verifies access to usage
metadata. [Tinker project and organization permissions](https://tinker-docs.thinkingmachines.ai/tinker/data-model/)

The pilot uses rank 16, three rollouts, one `forward_backward`, one
`optim_step` and one post-update verification forward pass. If all rewards
are equal or no usable actions remain, it exits before optimizing. The
reference token estimate is USD 0.4904. The run manifest records the rates
used for the final estimate. Checkpoint storage and finalized billing are separate.
[Published rates](https://tinker-docs.thinkingmachines.ai/tinker/models/models_and_pricing/)

After explicit approval, run this once from the project root on the tested
Windows environment. The launcher uses the existing base Python CPU PyTorch.

```powershell
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_module(""elt_rl.run"", run_name=""__main__"")' train-one --allow-paid --budget-usd 0.60 --group-size 3 --out runs/tinker-001
```

The manifest captures sampling token counts, actual rewards, aligned action
count and target fingerprint, forward/backward input token count, optimizer
status, post-update probe, checkpoint path and metadata readback. Preserve the private manifest
and pipeline artifacts. After usage appears in billing, use the recorded
session to reconcile its usage and gross cost in the console. The SDK billing
API exposes hourly session-attributed usage, typically with a delay. Its cost
estimates and the local token estimate are separate from invoice totals or
remaining credit. Do not infer an update from a submitted request or rerun
automatically on a timeout.

## Official Snowflake books

Snowflake is the shortest path for this repository because the official
adapter already implements that destination. Its supported inputs are the
pinned ELT-Bench checkout, the generated private `books/config.yaml`, and the
three official Snowflake reference CSVs. The references were downloaded and
validated locally. [Asset provenance](evidence/live-readiness.md)

| Required item | Setup |
|---|---|
| Local host | Use a Linux lab machine, or Linux under WSL with Docker. Install Docker with Compose, `abctl`, Terraform with the pinned Airbyte 0.6.5 provider, Python, `gdown`, AWS CLI, `psql`, and `unzip`. This Windows host has no usable Docker or installed WSL distribution. |
| Source inputs | The selected files are already staged in `runs/books-assets/data-api/data/books` and `runs/books-assets/data-db/data/books`. The upstream `data_api.zip` and `data_db.zip` are the alternative for another host. The REST application code is in the pinned checkout. |
| Source services | Start the pinned Compose stack for PostgreSQL, MongoDB replica set, LocalStack S3, and the custom Python API. Connect the Airbyte control-plane container to the Compose network as in the upstream setup script. Two additional official flat-file streams are served from Google Drive. |
| Airbyte | Use a self-hosted workspace with a reachable public API and workspace username, password and ID. Publish the pinned `setup/elt_snowflake.yaml` connector and capture its definition ID using `setup/setup_airbyte.py`. Confirm the deployed Airbyte runtime supports that manifest’s CDK version and the pinned provider API. |
| Snowflake | Use a supported account, preferably an existing lab account or an eligible trial. Admin provisions a dedicated role, a `TYPE=SERVICE` user with an RSA public key, and an X-Small Gen1 warehouse with auto-suspend and a dedicated resource monitor. Grant the role warehouse `USAGE` and account `CREATE DATABASE`. The role owns each database it creates and uses that ownership for schema creation, loading, transformation, grading and cleanup. Apply organizational network or authentication policies to this service user and both connector hosts. |
| Credential files | Keep the RSA PKCS#8 PEM and optional passphrase private. For the adapter JSON, provide `account`, `host`, `user`, `role`, `warehouse`, `private_key_file` and optionally `private_key_file_pwd`. Key paths can be relative to the JSON. The upstream generator only needs a separate legacy input JSON with `account`, `user` and an inert `password` placeholder. The adapter uses its service key JSON directly. |

The upstream `elt_setup.sh` is the reference for download, unpacking and
network topology. When using the staged files, copy the respective `data/books`
trees into `elt-docker/rest_api/data/books` and `setup/data/books` of the
disposable setup checkout. Copy the prepared `mongo-books/mongo.jsonl` to its
own temporary directory. To reduce seeding, run the pinned `setup/sources/books/data.sh`
from its own directory with the absolute `setup` directory as its argument.
It seeds the five PostgreSQL tables and two LocalStack objects. For MongoDB,
run the pinned `setup/mongo.py` with that same absolute `--path`, from a
temporary directory containing a copy of `mongo.jsonl` filtered to its
`books` entry. Leave upstream files intact. Start the custom service with its
published application directory mounted as upstream prescribes. This
books-only sequence was reviewed against the pinned scripts. It has not run
on a live source stack. [Pinned setup script](https://github.com/uiuc-kang-lab/ELT-Bench/blob/3b068d5f15f64541d05fbc33a817e4b08c6bf173/setup/elt_setup.sh)

Older Airbyte charts can need the documented MinIO repository override.
Preserve the image tag when applying it. [Airbyte deployment](https://docs.airbyte.com/platform/deploying-airbyte/abctl)

Set `ELT_BENCH_ROOT`, `ELT_BOOKS_INPUT_DIR`, `ELT_GT_SNOWFLAKE`,
`ELT_SNOWFLAKE_CREDENTIAL_JSON`, and `ELT_AIRBYTE_URL`. After service usage
approval, run the probes, then one official rollout. Retain the manifest,
the Airbyte jobs, both grading stages when the gate passes, and any cleanup
notice.

```bash
python -m elt_rl.preflight official --airbyte-probe --snowflake-probe --namespace-probe
python -m elt_rl.run official-rollout --allow-paid --allow-warehouse --budget-usd 1 --out runs/books-001
```

## Warehouse cost

Snowflake advertises an eligible trial with USD 400 in usage credits. The
trial lasts up to 30 days or until the credit balance is exhausted, and
does not require a payment method. Leave the account on trial terms if using
trial credits. The locally hosted Airbyte and source containers incur no
cloud service subscription if run on a machine already available to the
project. [Trial offer](https://www.snowflake.com/en/snowflake-trial/) · [Trial terms](https://docs.snowflake.com/en/user-guide/admin-trial-account)

For context, AWS US East Standard on-demand is USD 2 per platform credit,
and an X-Small Gen1 warehouse uses one credit per hour. Fifteen to sixty
billed compute minutes would therefore be USD 0.50 to USD 2.00 for compute
alone. That is a cost illustration. No run time or actual Snowflake charge
was measured. Resumes have a 60-second minimum, and storage, transfer and
other charges can add to the total. Use short auto-suspend and a monitored
dedicated warehouse. [Credit prices](https://www.snowflake.com/legal/creditconsumptiontable/) ·
[Warehouse rates](https://docs.snowflake.com/en/user-guide/performance-query-warehouse-size) ·
[Compute billing](https://docs.snowflake.com/en/user-guide/cost-understanding-compute)
