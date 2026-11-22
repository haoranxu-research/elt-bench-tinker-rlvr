# ELT-Bench × Tinker

This project gives an agent a warehouse, a small set of tools, and a reward
computed by executing its submitted ELT pipeline. It includes a
credential-free SQLite example, a DuckDB rehearsal, and an official Books
adapter for Airbyte and Snowflake. [Design](DESIGN.md) ·
[Technical report](TECHNICAL_REPORT.md) · [Professor summary](PROFESSOR_SUMMARY.md)

## Verified results

| Experiment | Result |
| --- | --- |
| Official Books on Snowflake | Qwen3.6-35B-A3B independently wrote, tested, and submitted all three SQL files. Airbyte loaded 15 tables and 84,337 rows. Both official stages, the warehouse reward, and the trajectory reward were **1.0**. [Native evidence](evidence/books-snowflake-007.md) |
| Separate live Tinker pilot | One rank-16 LoRA optimizer step completed on SQLite rewards, with a post-update probe and checkpoint verification. [Training evidence](evidence/tinker-pilot.md) |
| Synthetic changed-input replay | The data-derived pipeline stayed at **1.0**. A hard-coded pipeline fell from **1.0 to 0.35**. [Experiment results](evidence/changed-input-final.md) |

The final full offline suite passed **130 tests** with the optional renderer
and Terraform checks enabled. Evidence files from earlier attempts record
their own test counts and readiness status. Use the handoff for final
verification and the exact native launch. [Final handoff](FINAL_HANDOFF.md)

## Run locally

From the repository root in PowerShell, with Python 3.12 installed:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip --isolated install -e '.[test]'
.\.venv\Scripts\python.exe -m elt_rl.cli examples/customer_orders.jsonl
.\.venv\Scripts\python.exe -m pytest -q --basetemp .venv/pytest-run
```

On macOS or Linux, use `python3 -m venv .venv` and
`.venv/bin/python`. The SQLite example is scripted. It reports an error
in `order_totals.sql`, then runs the corrected pipeline in a fresh
database and returns:

```json
{"reward": 1.0, "stage1": 1.0, "stage2": 1.0, "stage2_ran": 1, "submitted": 1}
```

The core example uses no credentials, model, or external warehouse.
Optional tests skip when their dependencies or fixtures are absent.
[Recorded scripted trace](evidence/audit-local.txt)

## Optional integration tests

Where the pinned Cookbook resolves, install with
`python -m pip install -e '.[test,official,cookbook]' duckdb` and run
pytest as above. A scripted-token test exercises rollout grouping and
training example assembly. The optional Qwen test uses the real tokenizer
and renderer. Both tests work without model weights or a sampling client.

The pinned Cookbook's dependency resolver could not find a compatible
`tml-renderers>=0.4.1` distribution on the tested Windows Python 3.12 host.
For the narrow credential-free environment test on that host, install the
exact checkout with only the exercised runtime dependencies:

```powershell
git clone https://github.com/thinking-machines-lab/tinker-cookbook.git ../upstream-tinker-cookbook
git -C ../upstream-tinker-cookbook checkout --detach 28de41edfcdd07ba3e7980f35d53a586024a2184
.\.venv\Scripts\python.exe -m pip --isolated install --no-deps ../upstream-tinker-cookbook
.\.venv\Scripts\python.exe -m pip --isolated install tinker==0.39.2 chz==0.4.0 numpy==2.5.5 pillow==13.0.0 rich==15.0.0 termcolor==3.3.0 blobfile==3.3.0 cloudpickle==3.1.3 datasets==4.4.1
.\.venv\Scripts\python.exe -m pip --isolated install -e '.[test,official]' duckdb
```

The smoke test also needs PyTorch. The executed run appended the base Python
site-packages path to use its existing CPU PyTorch 2.11.0. For a venv
with its own CPU PyTorch, run pytest directly as shown above.
[Historical Windows setup and test log](evidence/integrations.txt)

The audited default Qwen text path uses the pinned Cookbook renderer directly
and works with the focused Windows environment. Other model/renderer choices
should use a compatible full Cookbook install and pass preflight.

Cache only the public tokenizer files for the default model, then use
`ELT_TEST_REAL_RENDERER=1` to require the real-renderer test. This download
does not use a Tinker credential or download model weights.

```powershell
@'
from huggingface_hub import snapshot_download
from elt_rl.rendering import QWEN_TOKENIZER_REVISION
snapshot_download(
    "Qwen/Qwen3.5-4B", revision=QWEN_TOKENIZER_REVISION, token=False,
    allow_patterns=["tokenizer.json", "tokenizer_config.json", "config.json", "chat_template.jinja"],
)
'@ | .\.venv\Scripts\python.exe -
$env:HF_HUB_OFFLINE='1'
$env:ELT_TEST_REAL_RENDERER='1'
.\.venv\Scripts\python.exe -m pytest -q --basetemp .venv/pytest-run
```

To run the official adapter's offline tests, install `.[test,official]` and
`duckdb`. Put the pinned benchmark checkout at `../upstream-elt-bench` or set
`ELT_BENCH_TEST_CHECKOUT`. The evaluator tests execute the pinned scripts
with a synthetic warehouse connector. Set `ELT_TEST_TERRAFORM` to a Terraform
executable for the provider-schema test. It runs `init -backend=false` and
`validate` against a loopback placeholder, which does not call Airbyte.
Use a local provider mirror via `TF_CLI_CONFIG_FILE` if the Terraform
download endpoint is unavailable.

## Run the official Books or Tinker workflows

- **Books:** Use the [Snowflake setup guide](LIVE_SETUP.md#official-snowflake-books)
  to stage assets, bind Airbyte, and configure a dedicated warehouse. Use the
  [native launch and preflight commands](FINAL_HANDOFF.md#final-live-command)
  for the verified profile. The source probe runs the six Airbyte connections
  against disposable local PostgreSQL before the credentialed rollout.
- **Tinker LoRA pilot:** Use the [pilot setup and command](LIVE_SETUP.md#tinker-pilot)
  to reproduce the optimizer experiment with SQLite. Its reported update is
  separate from native Books grading.

Both live workflows require explicitly authorized resources. Keep private
configuration and raw artifacts outside Git. Use `.env.example` for variable
names. The sanitized evidence reports results and resource estimates.

## Optional changed-input check

```powershell
.\.venv\Scripts\python.exe -m elt_rl.robustness examples/customer_orders.jsonl
.\.venv\Scripts\python.exe -m elt_rl.robustness examples/static_answer.jsonl
.\.venv\Scripts\python.exe -m elt_rl.robustness --suite --repetitions 3
```

The second command exits 2 because the hard-coded pipeline fails the changed
fixture. The suite reports scores and measured extra local time. It operates
only on the synthetic SQLite example and leaves the official score intact.
[Interventions and limitations](evidence/changed-input-final.md)

## Upstream pins

- [ELT-Bench `3b068d5f15f64541d05fbc33a817e4b08c6bf173`](https://github.com/uiuc-kang-lab/ELT-Bench/tree/3b068d5f15f64541d05fbc33a817e4b08c6bf173)
- [Tinker Cookbook `28de41edfcdd07ba3e7980f35d53a586024a2184`](https://github.com/thinking-machines-lab/tinker-cookbook/tree/28de41edfcdd07ba3e7980f35d53a586024a2184)
