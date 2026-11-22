# Verification gate for the Books author title

The pinned public field asks for the most expensive book title and
descending title order on a price tie. Attempt 005 chose a title for
3,780 authors without an observed sale price. Its two other outputs and
six other author columns matched on Snowflake.
[Native grading and diagnosis](books-snowflake-005.md)

## Executed checks

- Three focused author tests passed. The checks cover no linked books,
  NULL-priced sales, competing priced titles, page totals and TEXT dates.
- The offline diagnostic on the actual attempt 005 SQL reproduced its
  2/3 Stage 2 score. The source-data warning flagged all 3,780 cases.
  The separate privately corrected control scored 1.0 on DuckDB and
  produced no warning. The control did not reach a model or a live run.
- Fresh credential-free Ollama sampling used a public field description,
  source schemas and observed database errors. The original schema, a
  reduced raw-sales view, and a single-author semantic fixture were
  tried with locally installed models. Llama 3.2 and DeepSeek R1 1.5B
  did not produce a passing SQL query. They hit name-resolution,
  aliasing or result-cardinality errors before demonstrating the title
  rule. The model requests contained no reference SQL, expected outputs
  or prior benchmark solutions. These are targeted fixture runs, not
  complete Books rollouts.

Private requests, model responses, and fixtures are retained under
runs/books-author-title-model-check. The fresh tests establish the
diagnostic behavior. Model-driven repair of this exact case with the
production 35B model remains unverified.

## One conditional authorization proposal

Run one fresh hosted Qwen3.6-35B-A3B rehearsal against the local TEXT-date
mirror. The agent starts from an empty workspace and sees the public
execution checks. Before proceeding to Snowflake, verify that it
generated and submitted all three transformations and that Stage 1,
Stage 2 and trajectory reward are each 1.0. Inspect the saved author
SQL and execution trace for the unpriced case. If the new public check
does not fire because the first draft is correct, record that as correct
first-pass behavior.

Only after that success, use the same committed workflow for one fresh
official Snowflake rollout. Before that launch, confirm at least 1.30
credits before the dedicated monitor's immediate suspension threshold,
the trial balance and the original Airbyte sources. The 4.00-credit
quota and 90% threshold were verified before attempt 005. The monitor's
current usage was not verified after 005.

The read-only Tinker preflight returned an uncached bound of
USD 0.23758848 per run. Launch with USD 0.25 per run and a USD 0.50
combined authorization. The last native rollout used USD 0.039486225
at published token rates, and the last hosted local rehearsal used USD
0.04129797. Expected Snowflake use is 0.75–1.10 existing trial compute
credits. API estimates do not guarantee final billing. No retry,
training, account upgrade or quota change is included. RSA and Airbyte
metadata and the pinned evaluator assets passed a read-only preflight.
No sampling or warehouse compute was started for this proposal.
[Tinker rates](https://thinkingmachines.ai/tinker/pricing/)

~~~powershell
# Set the private environment and offline cache as in FINAL_HANDOFF.md.
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); sys.path.insert(0,""scripts""); runpy.run_path(""scripts/books_model_rehearsal.py"",run_name=""__main__"")' --checkout ../upstream-elt-bench --assets runs/books-assets --book-publication-date-text --hosted --books-35b-profile --model Qwen/Qwen3.6-35B-A3B --budget-usd 0.25 --allow-paid --out runs/books-author-title-hosted-validation

# Run only after the full local scores and Snowflake resource gates pass.
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); from elt_rl.run import main; raise SystemExit(main())' official-rollout --books-35b-profile --books-max-turns 40 --allow-paid --allow-warehouse --rollout-seconds 2400 --grading-seconds 1500 --budget-usd 0.25 --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5_disable_thinking --out runs/books-official-qwen35b-006
~~~

## Authorized 35B rehearsal result

The hosted command above completed from commit 79b592a using the local
DuckDB TEXT-date representation. The model loaded the complete source
set, independently wrote three SQL files, and explicitly submitted all
three on turn 29. Both pinned stages, the grade, and the trajectory
reward were 1.0. All 38 dispatched calls and saved file bytes matched
the sampled tool calls, and the offline Cookbook audit verified the
trajectory reward against the original sampled tokens and log probabilities.

The targeted host-only audit executed both the first and submitted
author drafts. Both retained all 9,235 author rows and returned NULL
for all 3,890 authors with no priced sale. Neither omitted an author
nor returned NULL for an author with a priced sale. The new warning was
never needed for this field. The model fixed a different public warning
on the 1992 percentage. No diagnostic SQL, reference SQL or expected
output was supplied to the model. The evidence demonstrates correct
first-pass title handling on this local run.

The run used 8,257 sampled tokens, 151,040 cached prefill tokens and
21,229 uncached prefill tokens. The published-rate estimate is
USD 0.034169745. No provider session rows had posted when checked. The
private manifests, prompts, SQL and audits are in
runs/books-author-title-hosted-validation.

The official authorization remains unused. A fresh Snowsight
administrator reading showed the active trial, the dedicated warehouse
attachment, 2.52 used credits, a 4.00-credit quota, and immediate suspension
at 90%. Effective headroom is 1.08 credits, below the 1.30-credit gate.
The warehouse metadata verified X-Small, suspended, and 60-second
auto-suspend. The native run was not started. A dedicated quota of 4.30
credits would leave about 1.35 credits at the same usage and threshold.
