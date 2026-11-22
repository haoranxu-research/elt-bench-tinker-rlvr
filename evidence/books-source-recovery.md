# Books source recovery and rollout readiness

Native attempt 004 started with all 15 official streams. Airbyte
discovery for address_status then encountered an unexpected TLS EOF
from the Google Drive endpoint. The archived connector logs identify
the failing request but cannot locate the interruption within the
network path. The next model action dropped both flat files, resulting
in Stage 1 = 13/15 and a skipped Stage 2.
[Native result and evidence](books-snowflake-004.md)

## Changes

- Manifest validation checks every required group and stream against
  the pinned public task. An incomplete write names the missing
  streams and preserves the previous valid file. The execution
  backend applies the same validator before provisioning.
- An explicit Airbyte catalog discovery error at a connection can
  trigger one Terraform reapply, with the same plan and state, before
  sync jobs are queued. The server wrapped attempt 004's catalog
  failure in an opaque UnexpectedProblem. For that response, the
  runner checks the workspace connection inventory and retries only
  when it confirms none of the failed connection names exists.
  Authentication errors and unresolved mutations are excluded.
  A read-only job status request can also retry
  once after a recognized transport or gateway failure. Sync job
  creation remains single-attempt.
- The agent action deadline bounds Airbyte work, and replay retains
  the separate host-grading deadline. Cleanup remains independently
  bounded. The agent sees the next pending file on SQL errors.
  Untested drafts and missing files take priority over repeated
  repair of an already attempted file. Tested files stay eligible
  for submission until their content changes.

Tests dropped a real loopback TCP connection during a TLS handshake
and injected the corresponding discovery diagnostic at the Terraform
boundary. One case recovered and queued exactly one sync, and the
persistent case stopped after two attempts and queued none. Opaque errors
retry only when an inventory response confirms absence. The inventory
read also passed against the running local Airbyte. A separate
local HTTP endpoint dropped the first job-status connection. The runner
continued polling the original job without a second job creation.
The episode regression also verified that an attempted deletion of
both flat files after a load failure leaves the 15-stream manifest in
place and that the saved complete manifest can be executed again.
These tests use fixture endpoints and do not claim Google Drive or
Snowflake fault injection.

## Local evidence

Fresh local Airbyte jobs 135 through 140 loaded all 15 tables and
84,337 rows into a disposable PostgreSQL database and completed cleanup.
Both original Google Drive files were included. The probe matched the
published custom connector to the pinned manifest. The Airbyte worker
remains configured for one sync attempt per job. This probe measured
real connectivity after the incident. The controlled interruption
tests separately exercised retry and duplicate-avoidance behavior.

~~~powershell
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --source-probe --docker (Get-Command docker).Source --docker-context desktop-linux
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --snowflake-probe
~~~

The archived Qwen3.6-35B-A3B sampled actions still produced all three
files, an accepted submission, Stage 1 = 1.0, Stage 2 = 1.0, and reward
= 1.0 on the TEXT-date DuckDB mirror. The pinned grader ran all 15 raw
counts and three output comparisons. The saved actions were replayed
without new sampling.

The separately executed local Llama 3.2 rehearsal started with an empty
workspace using Ollama and the TEXT-date mirror. It failed to write a
valid manifest, ended unsubmitted after eight turns, and never invoked
either official evaluator. This result does not validate full correctness
for the corrected protocol. The validated 35B model is hosted, so a fresh
35B local-destination rehearsal requires sampling authorization.

The final offline suite passed 125 tests in 46.79 seconds with the real
Cookbook renderer and offline Terraform provider enabled. The retained
log is post-004-recovery-verified-suite.txt. Archived replay evidence
is in post-004-final-replay/archive-text/summary.json. The native Tinker
preflight returned the listed bound without creating a sampling session.

## Execution gate

RSA metadata and direct warehouse-use and database-creation grants
were verified. The X-Small warehouse was suspended with auto-resume
and 60-second auto-suspend. The checkout and evaluator assets were
verified. The service role cannot read the dedicated monitor. The
administrator's 1.37-credit headroom reading predates attempt 004 and
cannot be reused. An administrator must confirm an active trial, the
dedicated monitor's attachment and immediate suspension threshold, and
at least 1.30 credits before suspension.

Proposed authorization covers one hosted TEXT-date rehearsal and, only
if it reaches 1.0 in both stages and reward, one native Snowflake rollout
after the credit check. Each has an estimated uncached Tinker bound of
USD 0.23758848 and a launch limit of USD 0.25. The two-run estimated
bound is USD 0.47517696 with combined authorization capped at USD 0.50.
The native run is expected to use 0.75–1.10 trial compute credits. These
are estimates, and a longer outage can still exhaust the retry or time
budgets. No paid run was started during this follow-up.
[Model rates](https://thinkingmachines.ai/tinker/pricing/)

~~~powershell
# Set the private Snowflake/Airbyte paths and offline caches as in FINAL_HANDOFF.md.
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); sys.path.insert(0,""scripts""); runpy.run_path(""scripts/books_model_rehearsal.py"",run_name=""__main__"")' --checkout ../upstream-elt-bench --assets runs/books-assets --book-publication-date-text --hosted --books-35b-profile --model Qwen/Qwen3.6-35B-A3B --budget-usd 0.25 --allow-paid --out runs/books-post004-hosted-validation

# Run only after the fresh rehearsal passes and the resource monitor is verified.
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); from elt_rl.run import main; raise SystemExit(main())' official-rollout --books-35b-profile --books-max-turns 40 --allow-paid --allow-warehouse --rollout-seconds 2400 --grading-seconds 1500 --budget-usd 0.25 --model Qwen/Qwen3.6-35B-A3B --renderer qwen3_5_disable_thinking --out runs/books-official-qwen35b-005
~~~

Private artifacts for this follow-up are under runs/books-offline-readiness/
with the post-004 prefix. The official evaluator and reward formula are
unchanged. The full native milestone remains open.

## Authorized hosted 35B validation result

The hosted command above completed on November 22, 2026 using commit
ce6f45b and the TEXT-date DuckDB mirror. It loaded all 15 tables and
84,337 rows, independently wrote and executed all three SQL files,
and repaired an authors.sql binder error. The model explicitly
submitted publishers.sql, customers.sql, and authors.sql on turn 33.
The pinned grader confirmed all three outputs. Stage 1, Stage 2,
the evaluation reward, and the terminal trajectory reward were 1.0.

A provenance audit matched all 39 dispatched tool calls to generated
calls and all saved files to model writes. All 36 eligible tool
receipts appeared in the following prompt. The offline Cookbook
audit propagated 1.0 into 3 aligned datums with 11,464 action tokens
and their original log probabilities. No optimization ran.

The session used 24,765 uncached prefill tokens, 164,992 cached
prefill tokens, and 11,464 sampled tokens. The rate-based estimate
is USD 0.04129797. Provider billing showed no session rows at the
read-only check. The manifest, native-format grader output on DuckDB,
traces, and audits are preserved privately under
runs/books-post004-hosted-validation.

The local launch gate passed. The authorized native attempt waits on
current administrator evidence of an active trial and at least
1.30 credits before immediate warehouse suspension.
