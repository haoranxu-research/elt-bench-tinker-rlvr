# Why the second official ELT-Bench books rollout stopped before grading

See [the follow-up fix and verification](evidence/books-feedback-fix.md) for
changes made after this investigation and replay of the archived trajectory.

The [final workflow audit](evidence/books-final-audit.md) distinguishes
this run, which wrote three SQL files, from the later local model smoke,
which put SQL in actions that do not write files. The final workflow adds
single-file execution and explicit partial submission. This historical
trace still ends with reward zero.

## November 21 follow-up

The final authorized rollout loaded all 15 tables and 84,337 rows.
File-level feedback directed the model to `publishers.sql`. It fixed
the original parse error, then spent several turns on a Snowflake
`PUBLISHER_NAME` error and two rejected table qualifications. Its
turn-21 batch passed the publisher and customer statements and stopped at
an author statement with SQLSTATE `42601`. The model rewrote
`authors.sql` but had already consumed the four warehouse transform
attempts. The underlying author error text was unavailable in the bounded
tool feedback.

Successful statements earlier in a failed batch did not create tested-file
eligibility. The trajectory used whole-batch calls exclusively and did not
request individual validation or partial submission. The episode ended at
turn 24 with reward 0. This eligibility gap is separate from SQL correctness and
from the earlier lack of file attribution. [Latest evidence](evidence/books-snowflake-final.md)

## 1. Executive summary

I investigated the rollout at commit `bbd1574` using the saved live trajectory
in `runs/books-official-003/`. The client sampled the original
`Qwen/Qwen3.5-4B` with thinking disabled. The agent selected all 15 official
streams, and the six Airbyte jobs committed **84,337 rows** to Snowflake.
The agent then wrote three invalid or incomplete transformations. It fixed
the first publisher error but subsequently spent its repair turns on
`publishers.sql`, while the active customer and author files still had errors.

**The immediate failure was model-generated SQL. The clearest system weakness
was that the repair tool reported a batch-wide error for the first failing
file without naming that file, the line, or the offending reference.** Five
consecutive transform calls returned the same generic parser message from
`customers.sql`. Three of the intervening edits changed a publisher query
that already passed the static validator. The model acknowledged the syntax
error but repeatedly chose the wrong file. The evidence supports improving and
testing that repair loop before attributing the outcome to model size.

The rollout stopped at 24 sampled turns, with no successful transformation,
no submit call, and no grading replay. Its environment reward was **0.0
under the unsubmitted rule**. Official Stage 1 and Stage 2 were never invoked.
Their scores remain unknown.

## 2. Chronological reconstruction

I decoded the 24 recorded token sequences with the pinned Qwen tokenizer and
Cookbook renderer, reconstructed the messages, and replayed the actual host
validation and submission logic offline. The table summarizes the sampled
text and the corresponding tool receipt. The prompt and output columns are
recorded token counts, reproduced locally for each prompt.

| Turn | Prompt / output | Sampled action and observed result |
| ---: | ---: | --- |
| 1 | 642 / 14 | Called `read_task` directly. Received the official books instructions, the five groups, the required SQL files, and the load → transform → submit sequence. |
| 2 | 870 / 174 | Announced a complete load and called `read_task_section` for PostgreSQL, MongoDB, the custom API, S3, and the flat files. Got all five source schemas. |
| 3 | 1,264 / 204 | Wrote `load.json` with all 15 streams. The tool saved it. |
| 4 | 1,420 / 36 | Executed the load. The tool returned all 15 Snowflake tables and their expected counts. Airbyte jobs 12–17 succeeded on their first attempts. |
| 5 | 1,582 / 108 | Recognized the successful load and read all three output-model sections. |
| 6 | 2,235 / 47 | Inspected the warehouse before writing the SQL. It returned the same raw-table inventory and counts. |
| 7 | 2,403 / 680 | Wrote the original `publishers.sql`. Its `publisher_book_counts` CTE joined itself while being defined. The write tool saved the file without testing it. |
| 8 | 3,102 / 1,064 | Wrote the original `customers.sql`. Local replay identifies its first parser error at line 93, where an output alias appears inside `ROUND(...)`. The tool successfully saved the file. |
| 9 | 4,186 / 861 | Wrote the original `authors.sql`. The final join used an output column name in the position of a relation name. The tool saved it. |
| 10 | 5,064 / 41 | Called `execute_pipeline(stage="transform")`. The batch stopped at the publisher file and returned `ERROR: table is outside the approved raw streams`. The customer and author files were not reached by that invocation. |
| 11 | 5,131 / 774 | Correctly restated the raw-table constraint, listed the 15 names from the task, and rewrote the publisher file. The rewrite removed the self-join and passed static validation in replay. |
| 12 | 5,925 / 963 | Rewrote the customer file. Removed the original misplaced alias inside `ROUND`, introduced the malformed `CAST` at line 67, and retained a separate unresolved `pons` alias. |
| 13 | 6,908 / 803 | Rewrote the author file. Changed portions of the CTEs and output expressions, but retained the same undefined final join. |
| 14 | 7,731 / 37 | Retested the whole batch. The publisher SQL passed validation, then the customer parser failed. The only returned error was `ERROR: could not parse the Snowflake SELECT`. |
| 15 | 7,794 / 41 | Acknowledged a parsing error and inspected the warehouse. The inventory confirmed that raw data still existed, which did not locate the bad SQL. |
| 16 | 7,956 / 701 | Said it would fix each file, starting with the publisher. Replaced a scalar average subquery with a cross join and adjusted the grouping. The publisher remained parseable. |
| 17 | 8,677 / 36 | Retested the batch. The unchanged customer file caused the same parser message. |
| 18 | 8,739 / 691 | Said it would try running just the publisher file. It rewrote that file again, changing an aggregate, a cast and grouping. The execute tool had no single-file argument. |
| 19 | 9,450 / 37 | Called the same batch transform. The customer parser error remained. |
| 20 | 9,513 / 87 | Tried to write a minimal `test.sql` containing `SELECT * FROM publisher LIMIT 10`. The tool rejected the unapproved filename. No artifact changed. |
| 21 | 9,626 / 75 | Correctly acknowledged the three approved SQL filenames, then reran transform without changing any file. Got the same parser error. |
| 22 | 9,727 / 137 | Replaced the publisher model with a seven-line probe. It projected three of the seven required columns and used `SUM(b.book_id)` for `num_books`. It passed the static validator, but it was not a complete publisher model. |
| 23 | 9,884 / 35 | Retested the batch with that probe. The customer file still caused the same parser error. |
| 24 | 9,945 / 93 | Asked in its response how to get the actual error, then reread the publisher model specification. No SQL changed. The rollout ended at the turn limit. |

### The three SQL failures

- **Publisher.** Turn 7 declared `publisher_book_counts AS (...)` and also
  referenced `publisher_book_counts` as a relation **inside its own definition**.
  SQLGlot scope analysis treated that self-reference as external to the
  current scope. The adapter rejected the name as outside the approved raw
  streams. Turn 11 removed it. The four publisher versions from turns 11,
  16, 18, and 22 all passed the static validator. None was executed by
  Snowflake, so static acceptance says nothing about correctness of their
  column bindings or metrics.
- **Customer.** The original turn-8 file first failed at line 93, column 47:
  `ROUND(COALESCE(pbo.pre_books_over_13, 0) as per_books_over_13),`.
  The result alias appears inside `ROUND`, where the parser expects a closing
  parenthesis. The turn-12 rewrite replaced that expression. Its new
  line 67 placed the rounding precision inside the cast:
  `ROUND(CAST(<expression>, 2) AS FLOAT) as per_order_shipped_internationally`.
  The valid syntactic arrangement would be
  `ROUND(CAST(<expression> AS FLOAT), 2) AS per_order_shipped_internationally`.
  Replay returned SQLGlot's missing-`to` parse diagnostic at column 105
  on token `2`. The agent never wrote another customer version. The initial
  alias error and persistent CAST error are separate defects in successive
  versions. [Snowflake CAST](https://docs.snowflake.com/en/sql-reference/functions/cast)
  [Snowflake ROUND](https://docs.snowflake.com/en/sql-reference/functions/round)
- **Author.** The CTE was named `wrote_fewer_total_pages`. It produced the
  column `wrote_fewer_total_pages_than_the_average`. Both author versions
  joined the **column name as a relation** instead of the CTE name at
  turn-9 line 79 and turn-13 line 76. Local validation rejected both versions.
  After the publisher repair, every live batch stopped at the earlier
  customer file, masking the independent author error.

I applied one targeted edit at a time to in-memory copies. Correcting
the relation name cleared local syntax and scope checks for both author
versions. Correcting only the first syntax error in either customer version
made it parse, then exposed a separate adapter rejection of `EXISTS`, which
SQLGlot classifies as a function and the adapter does not allow. The model
never saw that rejection. Both customer queries' `EXISTS` expressions also
lack a relationship to the current customer's orders, which would make the
test global rather than per customer if executed as written. These checks
did not repair the saved artifacts or test the SQL against Snowflake.

Further static issues would matter after syntax repair. Both customer
versions select `pons.per_order_shipped_internationally` while the join
declares alias `bons`. Turn 8 also selects `pbo.pre_books_over_13` although
the CTE projects `per_books_over_13`. The customer SQL uses
`ca.country_id` with `ca` bound to `customer_address`. The pinned schema puts
`country_id` in `address`. It joins `shipping_method.method_id` to
`customer_address.status_id` despite `cust_order.shipping_method_id` being
available. These are static findings from the SQL and source schema, with
subsequent query behavior and grading effects unmeasured.

### Where the errors occurred

The six transform calls failed in the host-side SQLGlot validation and
scope checks, before the backend increments its actual transform-execution
counter or sends any CTAS. The private Airbyte logs contain separate JDBC
messages during loading. For example, job 12 logged that
`BOOKS.ADDRESS_STATUS` did not exist or was unauthorized, followed by
explicit creation of the missing final table and a successful commit of
two records. Jobs 13–17 also logged missing or unauthorized destination
tables while preparing the new namespace and eventually committed the
expected counts. Those load-time messages are distinct from the model's SQL
validation errors. There is no Snowflake execution error for the generated
customer or author transformations in this run.

## 3. Root causes and confidence

| Category | Confirmed by the trajectory or code | Interpretation or uncertainty |
| --- | --- | --- |
| Base model reasoning | The model understood the raw-table constraint, the generic syntax failure, and the artifact whitelist. It fixed one dependency error. It then edited the wrong file and reran an unchanged failing batch. | This trajectory shows poor fault isolation and repair prioritization. It gives no estimate of the failure rate across seeds or models. |
| Snowflake SQL knowledge | The two customer forms are syntactically invalid. The final publisher probe also counts by summing IDs and omits four required columns. | Syntax and aggregate mistakes are demonstrated. Model knowledge apart from this sampling configuration and task is unmeasured. |
| Schema understanding | The customer SQL used a country column on the wrong source and joined a shipping method to an address status. The agent had already read the corresponding input schemas. | A typed inspection tool or a shorter schema reference could help the model use what was available. Their effects have not been tested. |
| Dependency planning | The original publisher CTE was self-referential. The author rewrite kept a column-as-relation reference. The customer rewrite kept a mismatched alias. | The evidence concerns dependencies and aliases **within** output queries. It does not show that the task requires dependencies between the three generated files. |
| Context management | All 24 responses stopped normally. Max prompt was 9,945 tokens, max completion 1,064, and total sampled 7,739. Limits were 16,384 context, 2,048 per turn, 8,192 sampled, and 32 tool calls. The run used 30 calls. | There was no observed truncation or hard context overflow. Prioritizing the wrong file in a growing history is possible, but a context-length explanation is unproven. Only 453 generation tokens remained at the end, so simply adding turns is a weak first remedy. |
| Tool integration and feedback | Tool calls and feedback reached the reconstructed conversation. The adapter reported the first failing file's error without filename, stage, location or reference. In turns 14–23 it hid the author defect behind the customer parser error. | No transport or ordering defect was found. The diagnostic design made the failing file hard to identify, and the trajectory directly shows the resulting misdirected edits. |
| Agent loop and stopping | The whole batch was validated in fixed order on every transform call. The agent could neither validate a single model through a dedicated tool nor write an arbitrary diagnostic file. It reached 24 turns as configured. | Stopping and the submission guard behaved as specified. The loop lacked a way to isolate validation and detect unchanged failures. |
| Prompt or task specification | The task named all three files, described source tables and outputs, and instructed separate-turn submission. The initial complete load indicates that the agent understood that part. The execute-tool schema exposes only a stage, with no per-file format or structured diagnostic. | There is no demonstrated blocker in the upstream task wording. Clarifying the adapter's batch semantics and required-column checks is a testable workflow intervention. |

## 4. Model capability and the previous LoRA update

One Qwen3.5-4B trajectory is insufficient to conclude the model is too small.
Its **first-pass SQL reliability was insufficient in this run**. So was its
repair strategy. It understood the general error class and applied one
effective correction, but it did not localize the remaining errors or
change strategy when the same batch failed. The episode shows a repetitive
repair loop with verified defects in both the generated SQL and the host's
diagnostic design. It supports testing the agent workflow first. It does not
establish that diagnostics alone would yield a semantically correct pipeline.

A larger Qwen-family model could plausibly track the CTEs, joins, and output
specifications more reliably. This is a hypothesis. A larger model could also
consume the same generic feedback without localizing the fault. The 9B
comparison should distinguish first-pass SQL quality, effective repairs, and
final correctness from overall size.

The prior pilot completed **one rank-16 LoRA optimizer step** on the local
SQLite task. It used three rollouts with rewards `[1.0, 0.0, 1.0]`, six
training datums, and 3,125 aligned action targets. A forward probe found a
maximum action log-probability change of about 0.546. That verifies a parameter
update, with no evidence of a gain on held-out tasks or Snowflake. The pilot
did not observe this three-file SQL failure or teach Snowflake syntax and
schema relationships. Transfer of general tool discipline or submission
behavior is plausible, but the base policy already loaded all sources here
and the critical errors were in SQL and repair localization. There is no
measured basis to predict a meaningful improvement from this update.

The saved pilot artifact is a training-state checkpoint with a 24-hour TTL,
saved on November 19 around 09:57 UTC. Its configured lifetime points to
approximately November 20 at 09:57 UTC. I inspected only the local manifest,
so its current availability is unverified. The existing post-update state
would need to be restored and exported as sampler weights for a sampling
comparison if still available. The official runner at this commit samples
from a base model ID. If the saved state is unavailable, report the LoRA arm
as unavailable. A new training run would be a different intervention.
[Pilot evidence](evidence/tinker-pilot.md)
[Tinker checkpoint types](https://tinker-docs.thinkingmachines.ai/tinker/howto/checkpoints/)

## 5. Agent architecture and submission

The host groups all three SQL validations into a single execution request
and processes them in publisher, customer, author order. The two error
strings in the trace carried no location beyond the class of problem. The
wrapper records each tool result, appends it to the conversation, and
renders the next observation. I checked all **24** reconstructed prompt
lengths against the recordings, all **30** parsed calls, arguments and
receipts against the tool trace, and prior feedback in every reconstructed
next prompt. The observed model responses also directly acknowledge the
errors. The archive stores prompt lengths and generated tokens rather
than the full transmitted prompt bytes, so byte-for-byte remote confirmation
is unavailable.

The submission guard requires the active artifacts to have passed a
transform in an earlier turn. Failed execution clears the tested marker,
and editing invalidates a previously tested version. Here the marker was
never set. No actual `submit_pipeline` call appears in the trace. To check the
guard causally, I replayed all 30 calls through the real host state machine
using the saved load receipt and an offline warehouse stub. It reproduced
every feedback string, made **zero** transform SQL calls and consumed **zero**
submission attempts. An extra, counterfactual submit returned
`ERROR: successfully execute current artifacts in an earlier turn before submitting`.
There is no evidence that the replay stage or grading logic caused the stop.

A workflow can retain the same SQL safety rules while making the next action
clear. A bounded diagnostic could report the file, line and column, and
offending identifier, or report the status of all three files in one
validation pass. A per-file validation step would support the isolation the
model attempted at turn 18. A required-column check would have flagged the
turn-22 probe before submission. A repair loop could carry a compact table
of file revisions and unresolved failures, and surface a repeated error
when the implicated file has not changed. These are proposed changes.
The investigation did not implement them.

## 6. Recommended experiments

1. **Start with the offline regression from this trajectory.** Keep the
   saved files, generated tokens and receipts fixed. Reproduce turns 10 and
   14–23 with the existing validator, then build an offline diagnostic
   report that identifies the publisher self-reference, both versions'
   customer parser errors, and the author CTE mismatch independently.
   Verify that publisher edits alone never clear the customer and author
   failures, and that the submit guard still rejects an untested version.
   Fixed actions can show that feedback quality improved. Adaptive repair
   requires new model responses.
2. **Isolate the workflow effect with the base 4B.** Use the saved
   post-turn-14 conversation and active files as the common starting state.
   Give one arm the original generic feedback and give the other the
   file-specific diagnostics. Use an offline validator and recorded
   source receipts. Repeat from a fixed set of seeds if the inference
   backend supports seed control. Local inference is an option if the
   weights and compatible runtime are available. Any remote sampling
   would require new approval. This contrast answers whether the same
   model can repair the known failure when the tool names it.
3. **Compare the three policies in one fixed workflow.** Run the original
   Qwen3.5-4B, the same 4B with the verified post-update LoRA weights
   if recoverable, and `Qwen/Qwen3.5-9B` as the larger arm. Hold the task
   revision, schemas, saved starting artifacts, load receipts, tool
   definitions and diagnostic format, validator, no-thinking policy,
   temperature 0.8, and turn, tool and token limits fixed. Use each
   model's compatible text renderer and record the tokenizer revision,
   prompt token counts, and seed or sample identifiers. Begin with one
   matched replay per arm as a feasibility check, then add paired samples
   before making a comparative performance claim. Use a fresh matched
   start from turn 1 as a separate check of first-pass generation.
4. **Keep the metrics separate.** Record first-pass parser and scope
   success per file, remaining dependency and column errors, first edit
   to the actual failing file, turns to all three files passing static
   validation, redundant attempts, required-column coverage, submit
   eligibility, prompt/output tokens, and time and cost per arm. With
   separate live authorization, measure successful CTAS, accepted
   submission, official Stage 1 and Stage 2 scores, and execution-derived
   reward on fresh isolated data. Count an evaluator that did not run as
   unexecuted. Offline validation from recorded receipts cannot measure
   the official warehouse scores.

The current public model table lists 9B at `$0.30` per million uncached
prefill tokens and `$0.807` per million sampled tokens. With this run's
limits, its conservative token estimate is **$0.124575744**, versus
**$0.13799424** for 4B. One full-sized sampling run per arm would therefore
total about **$0.401** at those rates before any checkpoint restore, storage,
or Snowflake usage. A shorter repair-only experiment should cost less.
The earlier **$0.15** approval applied to a single run. Account access,
checkpoint availability and the 9B renderer have not been verified for
the proposed comparison. [Tinker public pricing](https://tinker-docs.thinkingmachines.ai/tinker/models.json)

## 7. Evidence and limitations

- Live provenance, warehouse receipts and cleanup results are summarized in
  [the second rollout evidence](evidence/books-snowflake-second.md). I read
  the live manifest, sampled token/log-probability trace, tool-call JSONL,
  saved SQL embedded in tool arguments, Airbyte job receipts and private
  connector logs. The episode did not produce submitted artifact copies or
  official evaluator result files.
- The untracked private audit directory
  `runs/books-official-003/failure-replay/` contains the reconstruction
  script, `reconstructed.json`, extracted per-turn SQL files, the replay
  transcript, and `replay-host.py`. The Python versions observed for the
  replay dependencies were SQLGlot 30.33.0 and Tinker Cookbook 0.7.0.
- The live archive's SHA-256 values were independently checked.

  | File | SHA-256 |
  | --- | --- |
  | `manifest.json` | `d90bdea0d2d7102d4a5750413934e38a3ec8a5b0496db8743fc5ab9b1cff5bc9` |
  | `sampled-actions.jsonl` | `45a2cae4be467089a697e0a58baf940cae143afe5401b24528b208e4f5021f75` |
  | `pipelines/episode-a6bn4pe2.tools.jsonl` | `be46beb708a1e44e83762c1b8f99fdf06efe73e75703e75d9dc58a3443d3f099` |

The executed local replay commands were:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:TINKER_TELEMETRY='0'
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import runpy,sys; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_path(""runs/books-official-003/failure-replay/replay.py"", run_name=""__main__"")'
.\.venv-core\Scripts\python.exe runs/books-official-003/failure-replay/replay-host.py
```

Both exited 0. The first replay reuses stored tool responses. The second
replays the real host logic with an offline backend for the prior successful
load. Neither generates new model actions, checks Snowflake SQL execution,
nor runs official evaluators. This investigation made no paid calls and
changed no implementation.
