# Credentialed Snowflake Books rollout

The authorized run uses revision `c0ad13f`, Qwen3.6-35B-A3B, and the
no-thinking profile verified by the local full-score rehearsal. The fresh
workspace starts without SQL files. The agent receives public task material
and tool observations. The pinned Stage 1 and Stage 2 evaluators receive
the submission only after the explicit submit tool call.

## Launch checks

- Local run `stronger-13` scored 1.0 at both stages and earned 1.0.
  The audit matched the submitted bytes to model writes, and the
  launch check independently verified the archived artifact hashes.
- The latest Airbyte source probe passed all six connections and matched
  all 15 counts, totaling 84,337 rows, on local PostgreSQL. The active
  worker reported `SYNC_JOB_MAX_ATTEMPTS=1`. The launch-time metadata probe
  verified the scoped Airbyte workspace and custom source.
- The launch-time Snowflake probe authenticated with RSA and found the
  existing warehouse. The prior read-only grant check confirmed
  `CREATE DATABASE` and warehouse `USAGE` for the service role.
  The warehouse was Gen1 X-Small with a 60-second auto-suspend.
- The refreshed administrator console displayed USD 398 of USD 400 in
  trial credit and confirmed the monitor's warehouse attachment. Its
  nominal quota was 1.00 credit, utilization 0.72 credits, and immediate
  suspension 150%, leaving 0.78 credits until suspension.
- Tinker quoted USD 0.19335168, below the USD 0.20 cap. The projected
  Snowflake interval was 0.50 to 0.64 compute credits before grading
  and cleanup, within the available headroom. The monitor stayed at its
  existing settings.

The launch used the [official 35B command](../FINAL_HANDOFF.md#final-live-command)
with `runs/books-official-qwen35b-001` as its evidence root.

## Official outcome

The run started at 09:03:17 UTC on November 21, 2026 and the process
exited at about 09:57:35 UTC. Both the working namespace and the grading
namespace received all 15 tables and 84,337 rows. Airbyte jobs 79 through
90 each succeeded in one attempt. The six grading syncs belonged to the
one explicit submission's fresh replay.

The agent wrote its own manifest and three SQL files. It tested the
publisher and customer files, then sampled a partial submission on
turn 27 after the author file failed. Both pinned native Snowflake
evaluators ran. Stage 1 was **1.0**. Stage 2 was **1/3** because
publishers matched, two customer rates differed, and the author output
was absent from the submitted subset. The verifier wrote
**0.5666666666666667** to `grade.json`.

The 40-minute Cookbook timeout cancelled the rollout's await on the
submission tool. The already dispatched synchronous grading worker
completed at about 09:56:59 UTC. Consequently the terminal trajectory
recorded `rollout_timeout`, reward **0.0**, and no completed submission
transition. This is distinct from the persisted warehouse grade and
host submission manifest. The rollout did not reproduce the local
full score.

## Usage and cleanup

- All 27 returned samples contained 7,814 sampled, 139,520 cached input,
  and 23,200 uncached input tokens. The token-rate estimate is
  **USD 0.03342849**. The original manifest's USD 0.033227295 omits
  the last request because its tool transition did not return before the
  timeout. Tinker had no posted session billing rows when checked.
- The refreshed administrator monitor increased from 0.72 to 1.45
  credits used, an observed rounded delta of **0.73 credits**.
  The immediate suspension trigger remained at 1.50 credits.
  The monitor displayed 0.05 credits of headroom to that trigger.
  The trial console showed USD 398 remaining. No account upgrade ran.
- Cleanup audits found zero run-owned Snowflake databases, zero Airbyte
  connections, sources and destinations, and a suspended warehouse
  with 60-second auto-suspend.

The private run root contains the complete prompt and sampled-token
receipts, tool receipts through the last completed transition, decoded
submission, all model SQL snapshots, official results and grading logs,
Airbyte job receipts, and the monitor and cleanup verification records.
No additional paid rollout or training ran.

## Offline diagnosis

The run captured Snowflake metadata with `SHOW COLUMNS`. The native
`BOOK.PUBLICATION_DATE` was TEXT, while local CSV inference gave DATE.
The author SQL attempted to extract the year directly. Turn 19 failed
with SQLSTATE 22000, turn 21 failed with invalid identifier `BMP.PRICE`,
and turn 23 failed again with 22000. Running the turn-22 author's saved
SQL offline succeeded with DATE and failed at the date-part function
against a TEXT reproduction. The original tool trace retained SQLSTATE
for the two type-related failures and no native diagnostic text.

The customer SQL defaulted both rates to zero when the customer had no
orders. The offline follow-up adds a raw-relationship check that reports
those undefined rates without consulting ground truth. Source schema
feedback now includes the actual types of date-named columns and is
cached for immutable source-table inspection. The feedback sanitizer
recognizes date conversion failures without exposing source values.
The private replay found 303 NULL mismatches in each rate. In isolation,
removing only the default values eliminated all 606 differences and
both columns passed the pinned comparator. This was a developer-side
diagnostic and did not affect the official score.

The reporting repair keeps each tool receipt with its worker, preserves
a completed warehouse grade separately when it arrives outside the
trajectory, and calculates sampling usage from returned samples even
when a tool transition is missing. The official evaluator and reward
formula are unchanged. The repairs were tested offline only.
The full suite passed 105 tests in 37.73 seconds with the real Cookbook
renderer and the offline Terraform provider enabled. The log is
`offline-verified-suite-final.log` in the private run root.

The observed rollout required about 54 minutes including cleanup. A
future launch needs a wall-clock plan that budgets for the isolated
grading load and a fresh warehouse allowance check. The currently
observed 0.05-credit headroom is insufficient for another run.
