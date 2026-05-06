---
name: conductor-output-quality
description: Inspect a structured output (Excel, CSV, JSON, Parquet, DB write) for completeness anomalies before declaring task success. Catches column-empty, row-empty, fill-rate <50%, regression vs prior run, and default-leak patterns.
allowed-tools: Read, Bash(jq,awk,sqlite3,head,wc,python3)
---

## When to invoke

The conductor invokes this skill after producing any structured output, BEFORE declaring the task complete. Output existence (file present, valid format) is necessary but NOT sufficient — empty columns and broken pipelines often pass file-existence checks.

## Inputs

- Path to the output file (CSV, JSON, JSONL, XLSX, Parquet, SQLite DB)
- Optional path to a prior run's output for delta comparison (typically `output/<filename>` from a previous session)
- Optional expected ranges from the spec (column types, value ranges, expected row count)

## Outputs

- A finding written to `.conductor/findings.md` if any anomaly triggers
- An anomaly classification returned to the conductor: `clean | broken-component:<col> | broken-record-handler | broken-pipeline | regression:<delta>% | default-leak:<col>`
- For non-clean classifications: a user-facing surface line the conductor body emits before continuing

## Procedure

1. **Load the output and compute fill-rate per column and per row:**
   - For CSV/JSONL: count rows, then per column count non-null/non-empty values; per row count non-null/non-empty cells
   - For JSON: walk the structure; flag any array of objects where a key has 0 or near-0 non-null values across the array
   - For XLSX: same logic per sheet, per column
   - For SQLite/Parquet: query schema; for each column, count NULL and non-NULL; for each row, count NULL across all columns

2. **Anomalies to flag (any one triggers a finding):**

   | Anomaly | Detection | Classification |
   |---|---|---|
   | Any column 100% empty / 100% error | column non-null count == 0 | `broken-component:<col>` |
   | Any row 100% empty | row non-null count == 0 | `broken-record-handler` |
   | Overall fill rate <50% | (total non-null / (rows × cols)) < 0.5 | `broken-pipeline` |
   | Drop vs prior run >20% | (this_rows - prior_rows) / prior_rows < -0.2 | `regression:<delta>%` |
   | Identical values across all rows in a column (when variance was expected) | column distinct count == 1 across N>1 rows | `default-leak:<col>` |

3. **Compare to expected ranges** (if spec provided them):
   - Column type mismatches → flag as `type-mismatch:<col>`
   - Out-of-range numeric values → flag as `range-violation:<col>`
   - Missing required columns → flag as `missing-column:<col>`

4. **Append findings.md row** for each anomaly:
   ```
   [timestamp] output-quality anomaly in <output_path>
     - <anomaly type>: <details>
     - likely cause: <component>
     - suggested action: <investigate | fix | accept-as-known>
   ```

5. **Surface user-facing line** for any anomaly that triggers (the conductor body prints this before continuing):
   ```
   ⚠️ Output-quality anomaly in [output_path]:
     - [anomaly type]: [details]
     - Likely cause: [component]
     - Suggested action: [investigate / fix / accept-as-known]
   ```

6. **Do NOT mark the task complete** until anomalies are addressed:
   - Either fixed (re-run the producing task)
   - Or explicitly acknowledged as known limitations of the **input data** (never of the conductor's own implementation)

## Failure modes

- **Output file unreadable** → log to findings.md as `output-quality: cannot read <path> (<reason>)`; surface to user; do NOT mark task complete.
- **Output format unrecognized** (not in CSV/JSON/JSONL/XLSX/Parquet/SQLite) → log to findings.md as `output-quality: unsupported format`; ask the user whether to skip the check or treat as unknown-quality.
- **Prior-run delta requested but prior file missing** → skip the delta check; do not penalize on first run; log a single line to findings.md noting "no prior run for delta comparison".
- **A `KNOWN LIMITATION` comment is found in the output-producing code** → block. The phrase is banned by the Anti-Premature-Failure rule (see `conductor-classification`). Surface to user.
