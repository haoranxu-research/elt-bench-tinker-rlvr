# Engineering an execution-graded ELT environment

A useful reward had to answer two questions: could the submitted SQL rebuild
the required warehouse tables from source, and did the resulting score reach
the sampled trajectory? The project verified both in official Snowflake
attempt 007. The separate live Tinker optimizer pilot used SQLite. The
examples and evidence below distinguish scripted tests, archived replays,
host-written controls, and fresh model rollouts. For the final test count
and reproducible launch, see the [handoff](FINAL_HANDOFF.md).

## 1. Making the local loop testable

The first question was whether a failed SQL run could lead to a repair and a
reward from the corrected submission. The scripted SQLite trace deliberately
queried a nonexistent column. The runner reported the error against
`order_totals.sql`, accepted a replacement, then replayed the two SQL files
in a fresh database. Both stages and the reward were **1.0**. This was a
controlled test of the tool and grading loop. Fresh model behavior and
native Snowflake semantics required separate checks.
[Recorded trace](evidence/audit-local.txt) · [SQLite example](examples/customer_orders.jsonl)

## 2. Making the source load reproducible

In native attempt 004, Airbyte hit an unexpected TLS EOF while discovering
one Google Drive stream. The next model manifest dropped both flat files.
Stage 1 fell to **13/15**, and Stage 2 skipped. The connector logs identified
the failing request. They could not locate the network fault. The manifest
validator was changed to preserve the last valid file when a required stream
is omitted. Discovery can retry within bounds before a sync exists. For
opaque errors the runner first checks whether a connection was already
created, and a read-only status retry polls the original job.

Controlled loopback failures tested those recovery rules. A separate local
preflight exercised the actual six Airbyte connections, matched all **15
tables and 84,337 rows** in disposable PostgreSQL, and verified cleanup.
The fault tests support the retry behavior and the live preflight supports
the tested source configuration. Neither measures resilience to a longer outage.
[Attempt 004](evidence/books-snowflake-004.md) · [Source recovery](evidence/books-source-recovery.md)

## 3. Making failures actionable for the model

An early 24-turn native run exhausted its transformation attempts after SQL
errors. It ended unsubmitted with zero reward. The saved trace separated two
problems: the model produced invalid SQL, and batch feedback concealed which
files had already succeeded. The workflow was changed to report errors by
file, preserve tested artifacts across partial failures, allow single-file
retests, and reserve a final action for submission. Replaying the 24 archived
responses and 30 tool calls verified improved feedback delivery. The
unchanged actions still did not submit.

A later hosted model stopped before load after closing a tool-call XML tag
incorrectly. The working phase now offers one recovery from a completely
malformed call with intact framing, within the original budget. Replaying
those exact sampled tokens verified that the next prompt points the model
back to the load manifest, leaves artifacts untouched, and retains the
submission reserve. These replays test the protocol. Fresh runs were
needed to measure whether a model would use the revised feedback.
[Failure analysis](FAILURE_ANALYSIS.md) · [Feedback replay](evidence/books-feedback-fix.md) ·
[Malformed-call recovery](evidence/books-publisher-stability.md)

## 4. Returning the warehouse grade to the trajectory

An earlier native run submitted two files. The warehouse recorded
**Stage 1 = 1.0, Stage 2 = 1/3, reward = 0.566667**, while the rollout returned
**0.0**. The timeline showed that the 40-minute runner deadline cancelled
the wait on grading. The grading thread went on to save the real result.
The two Airbyte sync passes alone took 33 minutes 18 seconds.

The runner now captures the sampled submission before grading. The host
can use a separately bounded grading window, then attach the completed
grade to the original transition before computing the return. Regression
tests covered grading after the action deadline, rejection of late
submissions, and grading expiry. A later native attempt verified agreement
at **0.783333** for both the warehouse and the trajectory. The deadline fix
preserved the grade of the submitted pipeline. SQL correctness still
depended on what the agent wrote.
[Deadline diagnosis](evidence/books-snowflake-deadlines.md) ·
[Native reward reconciliation](evidence/books-snowflake-completion.md)

## 5. Separating dialect errors from incorrect results

The same author query ran on locally inferred DATE input and failed on the
native `BOOK.PUBLICATION_DATE` TEXT column. Replaying it with VARCHAR
ingestion reproduced the failure at `DATE_PART`. The adapter now exposes
the observed physical type, and the DuckDB rehearsal can mirror that one
column as text. An isolated developer conversion control passed both pinned
stages on DuckDB. Full dialect compatibility still required a native run.

Several other queries executed successfully but computed the wrong
numbers. Attempt 006 used a multiplier of 70 where the publisher rule
specified 70%, leaving Stage 2 at **2/3**. A later fresh local model corrected
the cutoff but returned NULL for **2,255** publishers with books and no
Japanese titles. The source-based check distinguishes a zero numerator
from an absent denominator. The archived action replay reproduced the
warning, and the next fresh TEXT-date model run submitted all three files
and scored **1.0** on both stages. The diagnostic controls and expected
answers stayed out of model workspaces. The result shows that the
configuration can work on this task.
[Type and NULL diagnostics](evidence/books-snowflake-deadlines.md#source-type-and-semantic-checks) ·
[Attempt 006](evidence/books-snowflake-006.md) · [Publisher follow-up](evidence/books-publisher-stability.md)

## 6. Verifying the full native result and the training interface

In attempt 007, Qwen3.6-35B-A3B started with an empty SQL workspace and
independently wrote, tested, and submitted all three models. Six Airbyte
jobs succeeded on the first attempt in the working warehouse and six more
in the grading replay. The pinned evaluators returned **Stage 1 = 1.0,
Stage 2 = 1.0**. Warehouse and trajectory rewards were both **1.0**.
The provenance audit matched 43 dispatched calls to sampled actions and
checked the submitted file bytes. It verified 9,334 sampled action tokens
and their log probabilities. Both transient databases and their Airbyte
objects were removed, and the warehouse was suspended.

The run lasted approximately **51 minutes 39 seconds** from manifest start
to terminal status. The initial load tool took **1,062.953 seconds**.
Grading replay and cleanup took **1,201.375 seconds** after acceptance.
Measured Tinker usage was 9,334 sampled tokens, 164,608 cached prefill
tokens, and 24,359 uncached prefill tokens. Published rates imply
**$0.03823716**. No invoice entry had posted at the check. Snowflake's
**0.75–1.10 compute credits** was a preflight estimate. The post-run monitor
delta was unavailable. [Native scores, timestamps and audit receipts](evidence/books-snowflake-007.md)

An offline audit paired the Snowflake trajectory with an empty zero-return
control and produced four aligned training examples. The separate live
rank-16 LoRA pilot used three SQLite rollouts with rewards **[1.0, 0.0, 1.0]**.
It completed one optimizer step, verified a change in action log probabilities
on a training datum, and confirmed checkpoint metadata. The native run
establishes full correctness for one independent rollout. The pilot
establishes that the update executed. There was no downstream evaluation
of learning or estimate of success rates across seeds.
[Tinker pilot evidence](evidence/tinker-pilot.md)

## 7. Testing whether fixed-fixture reward survives input changes

A warehouse replay checks reproducibility on the supplied data. A fixed
fixture can still reward a query that outputs memorized values. To isolate
that weakness, the optional SQLite experiment held each submitted pipeline
fixed and changed order-to-customer assignments and amounts, using the
corresponding independently specified fixture targets. Both pipelines
scored **1.0** on the original input. The data-derived pipeline stayed at
**1.0**. The hard-coded pipeline fell to **0.35**, keeping Stage 1 credit
and losing both Stage 2 outputs.

The median additional local replay for the hard-coded case was **63.54 ms**
across three repetitions. The eight-case suite also exposed a cutoff,
missing rows, duplicate keys, and incorrect NULL assumptions. The
experiment is a synthetic check of selected failure modes, with no hosted
sampling or Snowflake compute. It does not change the official score or
reward formula, train a model, or estimate general resistance to reward
hacking. [Interventions, scores and timings](evidence/changed-input-final.md)
