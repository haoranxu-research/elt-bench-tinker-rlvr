# Books offline readiness after two native rollouts

## What stopped the two agents

| Run | Author transformation | Customer transformation | Binding limit |
| --- | --- | --- | --- |
| `books-official-qwen35b-002` | Saved on turn 31 and never executed. Turns 11 and 13 rejected valid publisher date conversions in the application validator. Turns 16–25 reviewed or inspected existing material. | Turn 27 flagged defined rates for 303 customers without orders. The agent rewrote customers on turn 28, tested the revision on turn 29, and the native grader matched the output. | 32 of 32 turns and 47 of 48 tool calls. |
| `books-official-qwen35b-003` | Turn 31 saved a full draft. Turn 32 failed with SQLSTATE `42601` at the first `ba.author_id` projection. The SQL selected the joined key and grouped by the preserved key. The agent sampled actual ISO date strings, then replaced its full draft with a date probe. The probe failed the output-shape check on turn 35. The agent ended without a repaired author draft. | Turn 16 flagged the same 303 rows and named both percentage fields. The agent never revised customers. Native Stage 2 confirmed those two mismatches. | 40 of 40 turns and 55 of 60 tool calls. |

The retry used 14 consecutive turns for review or inspection between its first
customer test and its first author write. These included five pages of SQL
from already-executed files and four named schema inspections. The sampled
prompts and tool receipts show that the customer warning reached the agent.
The retry also observed actual `book.publication_date` values and the TEXT type.
The archives support several causes. The first run lost turns to a validator
bug and delayed the author write. The retry made a grouping mistake, received
an underspecified native compiler diagnostic, and spent its remaining turns
reviewing instead of repairing. Available evidence cannot determine why it
chose to leave the customer warning unresolved. [Original scores and receipts](books-snowflake-completion.md)

## Timing and token measurements

The table reports exact Airbyte and file receipt intervals, plus action-phase
estimates reconstructed from the quantized remaining-time messages. These
action intervals include sampler and dispatcher overhead. The historical
traces have no independent sampler or tool start/finish timestamps. The 27
submission tokens are exact in both runs. The separated submission duration
cannot be recovered from the historical remaining-time messages.

| Phase or usage | `002` | `003` |
| --- | ---: | ---: |
| Working load, adjacent tool receipts | 21m 00s | 21m 43s |
| Six working Airbyte syncs, first start to last finish | 16m 50s | 17m 23s |
| Inspection and review intervals / sampled tokens | 94s / 1,224 | 167s / 2,163 |
| First writes, including the manifest / sampled tokens | 25s / 3,727 | 42s / 3,532 |
| Transform tests, including rejected tests / sampled tokens | 199s / 198 | 173s / 167 |
| Rewrites or diagnostic overwrite / sampled tokens | 21s / 2,437 | 4s / 82 |
| Load action sampled tokens | 54 | 41 |
| Terminal submission sampled tokens | 27 | 27 |
| CLI start to acceptance | 27m 27s | 29m 25s |
| Acceptance to native grade | 19m 41s | 22m 24s |
| Six grading Airbyte syncs | 15m 51s | 18m 14s |
| Native grade to final manifest | 42s | 38s |
| Total sampled / cached prefill / uncached prefill | 7,667 / 166,784 / 20,120 | 6,025 / 207,872 / 24,350 |

The final pre-submission receipts show 794 and 703 action seconds remaining.
The model also had 4,621 and 6,263 unused sampled tokens, respectively. The
observed first-pass SQL testing and writing times fit the action window with
room for several file-level repairs. Both episodes ran out of turns first.
Repeat inspection consumed turns cheaply in wall time and used 36% of all
sampled tokens in the retry. The Airbyte loads dominate wall time. The
independent grading load remains necessary for the existing isolation
contract. The closer replay had about 2m 36s of grading margin. Public SQL
checks use several Snowflake requests per test, so the immediately practical
latency improvement is to avoid redundant inspection and retesting. This
follow-up did not measure native performance after the changes.

Recompute the per-turn table from the ignored archives.

```powershell
.\.venv-core\Scripts\python.exe scripts/measure_books_rollout.py runs/books-official-qwen35b-002 runs/books-official-qwen35b-003
```

## Verified local behavior and workflow changes

- A named warehouse inspection now displays actual physical types for its
  columns. Brief load and context summaries retain the important date types.
  Airbyte-managed CDC metadata no longer competes with domain columns.
- A failed draft remains distinct from a saved, untested revision. Per-file
  execution failures and unresolved public checks survive compaction. The
  recovery cue asks for repair after a failed test. It identifies an open
  public check once all files have been tested.
- Replacing a SQL file makes its immediately preceding bytes available with
  `read_pipeline_file version=previous`. Unchanged files retain their tests.
  A new draft requires testing, and the candidate snapshot contains the
  tested current artifacts selected at explicit submission.
- New receipts measure per-tool and per-sampler elapsed seconds, with
  separate replay-plus-cleanup timing. They preserve the pinned evaluators,
  reward formula, and 40-minute action / 25-minute grading limits.

The fresh local replay used the official staged sources, the pinned
evaluators, and Snowflake SQL translated into DuckDB. With the publication
date mirrored as `VARCHAR`, the second native author draft reproduced the
grouping failure. Correcting only the grouping left the total-page and price
ranking fields unmatched, and the customer percentage errors remained. The
isolated semantic control matched all three outputs. The separate first-run
control reproduced the author ambiguity and year-format problem, then scored
1.0 with developer-side corrections. The edited SQL remained inside those
developer diagnostics.

The archived full-score 35B tools replayed under the current 40-turn,
60-tool, 12,288-token settings with inferred DuckDB dates. All three files
were submitted in 30 recorded actions and 7,284 archived sampled tokens.
Both stages and the delivered trajectory reward were 1.0. The same saved
actions on the TEXT date mirror failed the author's date extraction and
could not submit a complete candidate. These are two deterministic replays.
They contain no new model samples and do not prove current model reliability.

The new no-cost local Llama 3.2 smoke actually sampled on loopback. It ended
after 19 turns and 748 sampled tokens with malformed load manifests and no
submission. No grader executed. Its tool rendering and model are different
from the 35B setup. No complete Qwen3.6-35B-A3B weights are installed locally.

The full offline suite exited 0 with **120 passed in 42.20s**. The added
regression exercises a public warning across an overwrite and retest,
demonstrating that an unrelated tested file remains intact. The full suite
also exercises named failure attribution, previous draft access, submission
deadlines, the pinned renderer, and Terraform validation.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:CHECKPOINT_DISABLE = '1'
$env:ELT_TEST_REAL_RENDERER = '1'
$env:ELT_TEST_TERRAFORM = (Resolve-Path .venv-core/tf-tools/terraform.exe).Path
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' -q --tb=short --basetemp .venv/books-offline-readiness-regressions
```

## Next validation and spending gate

The controlled next run uses the already verified hosted Qwen model with
the pinned no-thinking renderer against local DuckDB. It uses staged source
counts, the observed TEXT date mirror, exactly the retry's context, output,
turn and tool limits, a fresh workspace, and private pinned grading. The
matching profile's read-only preflight passed with an uncached ceiling of
**USD 0.23758848**. No sampling session was created. [Tinker rate card](https://thinkingmachines.ai/tinker/pricing/)

**Proposed authorization** is one hosted local validation capped at
**USD 0.25** in Tinker token estimates, with no Snowflake workload and no
automatic paid retries. Review the three independently written SQL files,
their individual execution receipts, the sampled submission, the two pinned
stage results, and the returned reward before requesting a native attempt.

```powershell
$env:HF_HOME = (Resolve-Path runs/books-offline-model/hf).Path
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:CHECKPOINT_DISABLE = '1'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix)/""Lib""/""site-packages"")); sys.path.append("".venv-core/Lib/site-packages""); sys.path.insert(0,""scripts""); runpy.run_path(""scripts/books_model_rehearsal.py"",run_name=""__main__"")' --checkout ../upstream-elt-bench --assets runs/books-assets --book-publication-date-text --hosted --books-35b-profile --model Qwen/Qwen3.6-35B-A3B --budget-usd 0.25 --out runs/books-offline-readiness/qwen35b-validation --allow-paid
```

Use `--preflight-only` in place of `--allow-paid` with a fresh output
directory for the no-session check. The forecast for one later native run
with this profile is another **USD 0.23758848** Tinker bound and **0.75–1.10
Snowflake credits** for planning. Before authorizing it, verify at least
**1.30 credits to immediate suspension**, the active trial, and the dedicated
X-Small warehouse's 60-second auto-suspend. The last confirmed monitor
configuration is a 3.00 credit quota with immediate suspension at 2.70
credits. The final cumulative balance after the second attempt is still
unverified. The fresh read-only service-role `SHOW` returned no visible
monitor. An administrator can run the following without warehouse compute.
[Snowflake monitor documentation](https://docs.snowflake.com/en/user-guide/resource-monitors)

```sql
SHOW RESOURCE MONITORS LIKE 'ELT_BOOKS_COMPLETION_MONITOR';
SHOW WAREHOUSES LIKE 'ELT_BOOKS_WH';
```

The timing JSON, local traces, deterministic replays, developer-only
controls and read-only preflight manifests are under the ignored
`runs/books-offline-readiness/` directory. The official baseline still needs
one independently completed all-three-model Snowflake submission.
