---
name: conductor-spec-splitter
description: Split a large spec file (>300 lines) into focused parts before enrichment, so Phase 1 and Phase 2 dispatch never load the full document into context. Produces a manifest that maps each task to its spec part, reducing per-dispatch token cost from O(spec) to O(part).
allowed-tools: Read, Write, Bash(wc,grep,head,tail,diff)
---

## When to invoke

The conductor invokes this skill at the start of Phase 1, BEFORE `conductor-spec-enrichment`, when the spec file exceeds 300 lines. For specs ≤300 lines, skip this skill entirely — the overhead is not worth it.

Trigger condition (check in conductor body, pre-Phase 1):
```bash
wc -l < <spec-file>
```
If output > 300 → invoke this skill. Otherwise → proceed directly to `conductor-spec-enrichment`.

## Inputs

- The spec file path passed by the user (e.g., `spec.md`)
- Target part size in lines (default: 250; min: 150; max: 400)

## Outputs

- `.conductor/spec-parts/part-N.md` — one file per logical section, each ≤ target_lines
- `.conductor/spec-parts/manifest.json` — maps task IDs and part indices to file paths
- `.conductor/spec-parts/global-header.md` — project-wide context prepended to every part (stack, auth model, data model, out-of-scope constraints)

The original spec file is **not modified**. Parts are read-only views for enrichment and dispatch.

## Procedure

### 1. Measure and decide

```bash
wc -l < <spec-file>
```

Compute: `num_parts = ceil(total_lines / target_lines)`. If `num_parts == 1`, abort the skill and return "spec does not need splitting" — caller proceeds to normal enrichment.

### 2. Extract the global header

The global header is project context that every subagent needs regardless of which task it handles. Extract lines that match:

- Project name / overview paragraph (typically the first 5–20 lines)
- Stack declaration (`## Stack`, `## Tech Stack`, `## Language`)
- Authentication model (`## Auth`, `## Authentication`)
- Data model tables (if present and ≤80 lines total — if larger, summarise to table names only)
- Out-of-scope section (`### Out of scope`, `## Constraints`)

Write to `.conductor/spec-parts/global-header.md`. Cap at 80 lines. If the spec's global context exceeds 80 lines, extract only: project name, stack, out-of-scope items, and a one-line summary of the data model.

### 3. Find natural split boundaries

Scan the spec for heading boundaries in this priority order:

1. `## Phase N` or `## Part N` markers — split on phase boundaries first
2. `### Task N` or `#### N.` task-level markers — split at task groups
3. `## ` level-2 headings — split at top-level sections
4. If no structural headings exist — split by line count (hard splits at `target_lines`)

A split boundary must not land inside a fenced code block (```) or a table. If the nearest heading would produce a part > `target_lines * 1.5`, insert a hard split at `target_lines` anyway and note it in the manifest as `split_type: hard`.

### 4. Write part files

For each part N (1-indexed):

```
.conductor/spec-parts/part-N.md
```

Content structure:
```markdown
<!-- Spec part N of M — global context in global-header.md -->
<!-- Split boundary: <heading or "line NNN"> -->

[part content verbatim]
```

Do NOT include the global header content inside each part file — the manifest tells the conductor to prepend it at dispatch time.

### 5. Write the manifest

`.conductor/spec-parts/manifest.json`:

```json
{
  "schema_version": 1,
  "spec_file": "<original spec path>",
  "total_lines": <N>,
  "num_parts": <M>,
  "global_header": ".conductor/spec-parts/global-header.md",
  "target_lines_per_part": <target>,
  "parts": [
    {
      "index": 1,
      "file": ".conductor/spec-parts/part-1.md",
      "lines_start": 1,
      "lines_end": 250,
      "split_type": "heading|hard",
      "heading": "## Phase 1: Core Features",
      "task_ids": []
    }
  ]
}
```

The `task_ids` array is empty on creation — it is populated by `conductor-spec-enrichment` after enrichment annotates each task with its `part_index`.

### 6. Surface to conductor

Return to the conductor body:

```
Spec split complete: <total_lines> lines → <M> parts of ~<target> lines each.
Global header: .conductor/spec-parts/global-header.md (<N> lines)
Parts: .conductor/spec-parts/part-1.md … part-<M>.md
Manifest: .conductor/spec-parts/manifest.json

Proceed to conductor-spec-enrichment, passing each part file in sequence.
```

### 7. Integration with conductor-spec-enrichment

When the manifest exists, `conductor-spec-enrichment` runs once **per part** (not on the full spec). Each enrichment run annotates the tasks within that part and populates `manifest.json::parts[N].task_ids[]`.

The global `plan.md` and `routing.md` are assembled by merging the per-part enrichment results. The conductor body is responsible for the merge — this skill only produces the parts.

### 8. Integration with Phase 2 dispatch

Before dispatching task T, the conductor:
1. Reads `manifest.json` → finds the part index for task T
2. Prepends `global-header.md` to that part's content
3. Passes the combined ~330-line context block (header + part) as the `<context>` element in `dispatch_envelope.build_prompt()`

This replaces loading the full 2000-line spec into every dispatch prompt.

## Failure modes

- **Spec ≤300 lines** → abort with "spec does not need splitting"; caller proceeds normally.
- **No structural headings detected** (pure prose spec) → use hard line-count splits; note `split_type: hard` for all parts; log a warning to `.conductor/findings.md` recommending the user add `## Phase` or `### Task` headings for better splits in future.
- **Global header > 80 lines** → truncate to 80 lines; log truncated sections to `.conductor/findings.md`; surface to user that data model was summarised.
- **Part file would exceed target_lines * 2** (single section is very large) → split it with a hard boundary mid-section; add a comment in the part file noting the mid-section split.
- **Manifest already exists from a prior session** → skip splitting; log "manifest exists, skipping re-split" to `.conductor/decisions.md`; return the existing manifest path to the conductor body.
- **Write fails on any part file** → delete all `.conductor/spec-parts/` files written so far; abort with error; surface to user. Do NOT leave a partial manifest.
