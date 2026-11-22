# Books percentage feedback and tested-file preservation

## Changes and failure evidence

[Native attempt 006](books-snowflake-006.md) loaded all 15 tables and 84,337
rows. The agent submitted all three files after 30 turns and 48 tool calls.
Stage 1 was 1.0. Stage 2 was 2/3, with full matches for `authors` and
`customers`. Warehouse and trajectory rewards were 0.783333. The submitted
publisher cutoff multiplied the global page average by 70. This produced
1,545 incorrect zero counts.

The publisher check reports the aggregate number of false zeros observed
in the episode warehouse. The diagnostic now translates the public 70%
threshold into a 0.70 multiplier on the average across all books. It
provides no row IDs, expected output rows, or reference SQL. The customer
check now detects when a customer whose orders were all shipped
internationally has a rate expressed as a fraction such as 1 in place of
100 percentage points. The existing checks also cover zero denominators,
out-of-range percentages, and unexpected shipping labels. The existing
author advisory covers per-title aggregation of maximum printed pages
and the grain of priced sales. Official grading and reward code are
unchanged.

## Executed verification

| Check | Actual result |
| --- | --- |
| Complete offline pytest suite, including the cached real renderer and local Terraform checks | 126 passed in 47.21 s. |
| Focused genuine local Ollama `llama3.2:latest` sampling | The model used the public rule to produce `70 * average_pages / 100`. In a separate repair prompt with the archived 70× expression and the database feedback, it returned `0.7 * average_pages`. Both expressions matched independently calculated public-rule counts on two fixtures. This check evaluated only the threshold. |
| Fresh full local Ollama `llama3.2:latest`, native tools, DuckDB TEXT-date mirror | Five turns, 259 emitted tokens, 77.83 s. The model tried malformed `load.json` payloads and ended with a tool-like JSON string in the text response. No valid load, SQL submission, or evaluator calls occurred. Episode reward was 0.0. |
| Replay of the earlier genuine Qwen full-score trajectory against the current TEXT-date mirror | The archived actions passed both pinned evaluators and returned 1.0. All three submitted SQL files were byte-identical to the original snapshot. The replay used 29 turns and 8,257 archived sampled tokens. The largest prompt plus generation allocation was 12,035 tokens against a 12,288 limit. |
| File-level regression | Repairing and retesting one file preserved the other two tested artifacts and the actionable advisory through compaction. Reserved finalization accepted the explicit three-file submission with the expected contents. |

The focused model inputs were the public rule, a column name, and, in the
repair case, the archived wrong expression and live local diagnostic.
The host used independent rational arithmetic for the fixture expectations.
The archived action replay sampled zero new tokens. No paid sampling or
Snowflake compute ran in this verification.

The ignored local evidence is under `runs/`:

- `books-publisher-007-targeted/result.json` has both raw model responses and fixture results.
- `books-publisher-007-local-full/samples.jsonl` and `result.json` have the fresh full attempt.
- `books-offline-readiness/native-007-archived-replay/archive-text/summary.json` has the replay grades and token checks.
- `books-offline-readiness/native-007-offline-tests.txt` has the pytest output.
- `books-publisher-007-hosted-preflight/manifest.json` records the local-only hosted candidate configuration and budget.

## Authorized hosted validation

The prepared command ran once from commit `7365284`. Tinker returned
six responses. The first five dispatched read-only task calls. On turn
six, the model asked for the MongoDB task section but closed the function
tag with `</function</arg>`. The pinned renderer recognized the end of
the message and rejected the malformed XML. The environment then ended
the episode with `parse_error`. The model never saved a load manifest
or wrote SQL. Neither evaluation stage ran, and the trajectory reward
was **0.0**.

| Usage | Observed |
| --- | ---: |
| Sampled tokens | 152 |
| Cached prefill tokens | 11,648 |
| Uncached prefill tokens | 3,581 |
| Published-rate estimate from the metered tokens | $0.00286269 |
| Snowflake compute | 0 |

The billing lookup had no session rows posted at the time of the check.
The provenance audit verified all five dispatched calls against the
sampled tokens and found aligned sampled tokens and log probabilities.
Original prompts, actions, tool receipts, and audits are under
`runs/books-publisher-007-hosted-validation/`.

## Offline repair and verification

The Books working phase now allows one recovery from a completely
malformed tool call when the message boundary is intact and working
budget remains. It rebuilds the prompt from the actual episode state and
requests one correctly formatted next action. The bad call has no side
effects. Its sampled tokens and turn still count. A repeated malformed
call terminates, and when the working budget ends with tested files the
final turn remains available for an explicit submission.

Replaying all six exact hosted token receipts with the pinned 35B
renderer produced a 2,968-token recovery prompt pointing to the next
step, writing the load manifest. The replay wrote no files, retained
the 54-token submission reserve, and terminated when the bad action
was repeated. Regression tests also exercised a valid continuation
and a successful explicit submission after a malformed last working
action. No new model sampling was used for the repair verification.
The full offline suite passed 129 tests. The earlier full-score Qwen
action trace also replayed through the repaired workflow with Stage 1,
Stage 2, and reward all at 1.0. Logs are in
`runs/books-offline-readiness/native-007-recovery-final-tests.txt` and
`runs/books-offline-readiness/native-007-post-recovery-replay/`.

## Next bounded validation

The prepared run is one Tinker-hosted `Qwen/Qwen3.6-35B-A3B` rehearsal
against the DuckDB TEXT-date mirror. Its read-only preflight verified
the 84,337 staged rows, pinned renderer, a 40-turn and 60-tool profile,
12,288 sampled tokens and a 54-token submission reserve. The upper
estimate is **$0.23758848** at uncached prefill rates with a configured
**$0.25** estimate limit. There is no Snowflake workload in this command.
[Tinker pricing](https://thinkingmachines.ai/tinker/pricing/)

The first rehearsal authorization was used. Run this command only
under fresh authorization, with the existing Tinker credentials and
cached tokenizer available:

```powershell
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.insert(0,""scripts""); sys.path.append("".venv-core/Lib/site-packages""); runpy.run_path(""scripts/books_model_rehearsal.py"",run_name=""__main__"")' --hosted --books-35b-profile --model Qwen/Qwen3.6-35B-A3B --book-publication-date-text --checkout ../upstream-elt-bench --assets runs/books-assets --budget-usd 0.25 --allow-paid --out runs/books-publisher-007-hosted-recovery
```

A later native rollout requires a fresh model-driven local score of 1.0
in both stages plus an explicit submission of all three models.
The prior estimated Snowflake use was 0.75–1.10 compute credits, with
a gate of at least 1.30 verified credits before immediate suspension.
The dedicated 5.00-credit quota at 90% gave 1.98 credits before attempt
006. Current headroom has yet to be verified after that run.
