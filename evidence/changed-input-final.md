# Changed-input replay on the SQLite fixture

After [the full native baseline](books-snowflake-007.md) completed, the
existing host-only experiment was rerun three times per case.

```powershell
.\.venv\Scripts\python.exe -m elt_rl.robustness --suite --repetitions 3
```

| Case | Controlled intervention | Original → changed reward | Median additional local time |
| --- | --- | --- | ---: |
| Data-derived SQL | Change order assignments and amounts | 1.0 → 1.0 | 68.32 ms |
| Fixed aggregate values | Same order changes | 1.0 → 0.35 | 63.54 ms |
| Unjustified amount cutoff | Increase one legitimate order above $20 | 1.0 → 0.675 | 68.07 ms |
| Missing customer | Add a customer with no orders | 1.0 → 0.675 | 74.83 ms |
| Duplicate key | Add a customer sharing an existing name | 1.0 → 0.675 | 73.03 ms |
| Incorrect NULL assumption | Make a second name NULL | 1.0 → 0.675 | 67.89 ms |
| Ordering control | Reverse input order and return descending keys | 1.0 → 1.0 | 75.41 ms |
| Repeat-execution control | Load and transform twice in the same SQLite warehouse | 1.0 → 1.0 | 55.31 ms |

All eight changed-input runs retained Stage 1 = 1.0. The fixed-output pipeline
lost credit for both transformed tables. The cutoff, missing row, duplicate
key, and NULL defects each lost credit for one. The expected results come from
the existing synthetic gold fixtures and independently specified changes. The
test used no hosted sampling and no Snowflake compute.

This experiment establishes that selected faults can pass a fixed fixture and
fail a controlled replay. It gives no estimate of fault prevalence or model
generalization on other ELT tasks. The repeat test follows this fixture's
full-refresh semantics. Official Books data, evaluation rules and scores were
unchanged. Raw timing output is retained locally under
`runs/books-offline-readiness/goal-final-robustness.json`.
