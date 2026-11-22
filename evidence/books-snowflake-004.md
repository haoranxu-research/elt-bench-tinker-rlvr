# Official Snowflake Books attempt 004

One authorized, independent Qwen/Qwen3.6-35B-A3B rollout ran on
November 22, 2026, from commit 18cc3e1 and pinned ELT-Bench revision
3b068d5f15f64541d05fbc33a817e4b08c6bf173. The SQL workspace started
empty. The full-score DuckDB rehearsal is separate evidence.

## Result

| Item | Observed |
| --- | --- |
| Native Stage 1 | 13/15 (0.866667). All present tables matched their expected counts, totaling 84,329 of 84,337 rows. |
| Native Stage 2 | Skipped by the pinned Stage 1 gate. The receipt encodes stage2=0 and stage2_ran=0. |
| Accepted submission | publishers.sql, explicit partial submission on turn 40 |
| Warehouse reward | 0.30333333333333334 |
| Recorded trajectory reward | 0.30333333333333334 |
| Offline Cookbook training audit | Same return, 5 aligned datums, 6,891 action tokens with log probabilities |
| Cleanup checks | 0 run-owned Snowflake databases, Airbyte connections, sources, and destinations. Warehouse suspended. |

The run started at 01:54:13 UTC, accepted submission at 02:21:24 UTC,
and exited 0 at 02:31:59 UTC. Host replay, grading, and cleanup took
about 10 minutes 35 seconds after acceptance.

## Failure and correction

1. On turn 11 the model saved a complete manifest containing all 15
   streams. On turn 12 Airbyte Terraform apply failed at
   airbyte_connection.address_status before any sync jobs were queued.
   The Airbyte file connector ended with requests.exceptions.SSLError.
   Its connection to drive.google.com returned
   UNEXPECTED_EOF_WHILE_READING, and its HTTP retries were exhausted.
   The preceding six-connection PostgreSQL preflight had passed.
2. On turn 14 the model dropped the flat_files group, omitting both
   address_status and order_status. Turn 15 loaded the other 13
   tables. Airbyte jobs 127–130 succeeded in one attempt each. The
   second manifest was a model action in the same rollout.
3. publishers.sql passed a Snowflake execution test on turn 26.
   customers.sql initially failed twice with invalid identifiers
   HOME_COUNTRY_ID and METHOD_NAME. Its next version executed on turn
   37 but failed public shipping-label and zero-denominator checks.
   The model rewrote it on turn 39 without another execution test.
   The overwrite invalidated the previous test as designed.
   The model never wrote authors.sql. The reserved final turn accepted
   the model's partial submission of the remaining tested file.
4. Fresh replay jobs 131–134 succeeded in one attempt each. The official
   Stage 1 report lists both omitted tables as missing and no incorrect
   row counts for the other 13. The host recorded the completed grade
   on the accepted sampled transition. Stage 2 supplied no evidence
   about the semantic correctness of publishers.sql.

The follow-up adds a targeted warning to the save receipt for a
valid but incomplete Books manifest. It names the missing public
streams and explains that Stage 2 requires them. The regression
saves all 15 streams, then drops the exact two observed in the run.
It exercises the ordinary execution and submission path on a
synthetic warehouse. The warning preserves the model's manifest
and leaves evaluator and reward semantics unchanged. It does not
repair intermittent Google Drive connectivity. The full offline suite
passed 120 tests in 39.05 seconds with the real renderer and offline
Terraform provider enabled. The private test log is
runs/books-official-qwen35b-004-final-tests.txt.

## Verification and costs

The Snowsight administrator preflight showed approximately USD 394 in
trial balance, with 29 days left. ELT_BOOKS_COMPLETION_MONITOR was
attached to ELT_BOOKS_WH. With 1.33 of 3.00 credits used and immediate
suspension at 90%, the verified headroom was approximately 1.37 credits.
No monitor or warehouse settings changed. The current post-run credit
usage is unavailable to the service role and was not measured.

The Tinker preflight estimated an uncached upper bound of USD 0.23758848.
The sampled run recorded 18,124 uncached prefill tokens, 188,160 cached
prefill tokens, 6,891 sampled tokens and zero trained tokens. Published
rates imply USD 0.034289685. No billing rows had posted when queried.
[Tinker pricing](https://thinkingmachines.ai/tinker/pricing/)

The provenance audit verified 40 prompts and samples, exact correspondence
of all 39 dispatched tools to sampled calls, saved SQL byte equality,
and all 36 eligible observations in the next prompt. The action/sample
and training-return audits passed. The Cookbook audit paired the
authentic trajectory with an empty zero-return control, with no
optimizer call. An administrator can separately reconcile warehouse
usage using the run's UTC window and the dedicated monitor.

The run and its receipts are private under runs/books-official-qwen35b-004.
They include the manifest, tool transcript, sampled token IDs and log
probabilities, SQL snapshots, accepted submission, native evaluator
output, connector failure log, audits and cleanup reports.
[Archived launch command](../FINAL_HANDOFF.md#final-live-command)

Full correctness remains open. A future authorized launch needs a
reliable route to both pinned flat-file sources from Airbyte workers,
fresh verification of both connector jobs, and a new trial and monitor
headroom check. The optional changed-input evaluation remains deferred.
