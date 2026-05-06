---
name: conductor-spec-enrichment
description: Run Phase 1 spec enrichment — backup the user's spec, audit it, score each task's complexity, attach Execution Plan blocks, generate the diff, and gate Phase 2 on explicit user approval. Writes only under .conductor/ and to the original spec file's directory.
allowed-tools: Read, Write, Edit, Bash(diff,jq,cp,mkdir)
---

## When to invoke

The conductor invokes this skill once per session, after the user replies `proceed` to the First Response and before any task dispatch. Phase 2 cannot start until the user explicitly approves the enrichment diff.

## Inputs

- The spec file path passed by the user (e.g., `spec.md`)
- `.conductor/environment.md` from Phase 0 (capability inventory)
- Any prior `.conductor/spec-enrichment-summary.md` if this is a session resume

## Outputs

- `<spec-file>.original.md` — byte-for-byte backup of the user's spec
- `<spec-file>` — annotated with `<!-- Added by Conductor -->` blocks per task
- `.conductor/plan.md` — task list with statuses
- `.conductor/routing.md` — tool assignments with reasoning
- `.conductor/spec-enrichment.diff` — focused diff of original vs enriched
- `.conductor/spec-enrichment-summary.md` — categorized review for the user
- `.conductor/scaffold-payload.json` — typed enriched-spec values used by skill #7 (Phase C; populated as TODO placeholders in Phase A)

## Procedure

1. **Read spec fully.**

2. **Backup:**
   ```bash
   cp <spec-file> <spec-file>.original.md
   ```

3. **Audit:**
   - Missing acceptance criteria
   - Contradictions
   - Hidden dependencies
   - Missing NFRs
   - Credentials anticipation
   - Estimate token budget category (small/medium/large) based on task count and complexity

4. **Complexity scoring (per task, before enrichment annotation).**

   **Scoring rubric (additive — each signal contributes its points once):**

   | Signal | How to detect | Points |
   |---|---|---|
   | External API or third-party service | task names a service, API endpoint, or auth flow (Stripe, Supabase, OAuth, etc.) | +2 |
   | UI / frontend with visual output | task names a component, page, render, form, or frontend framework | +2 |
   | DB schema mutation | task mentions schema, migration, CREATE/ALTER TABLE, column, or index | +2 |
   | Writes/reads >5 distinct files | sum of declared `files_write` + `files_read` > 5 | +1 |
   | No acceptance criteria in task | no "success when", "acceptance criteria", or "expected outcome" | +1 |
   | New runtime dependency not in project | library/package absent from detected package.json / requirements.txt | +1 |
   | Cross-system coordination (≥2 independent backends) | task explicitly coordinates DB + API, frontend + API + cache, or similar | +1 |

   **Score → binding decisions:**

   | Score | Model at dispatch | Max retries | Pre-dispatch research |
   |---|---|---|---|
   | 1–3 | `haiku` | 1 | `skip` |
   | 4–6 | `sonnet` | 2 | `optional` (run only if ≥1 external API signal AND investigation budget has room) |
   | 7–10 | Respect subagent frontmatter; floor at `sonnet` if frontmatter is haiku | 3 | `required` if external API or new dependency signal present; `optional` otherwise |

   **Hard constraints:**
   - Score never auto-triggers `opus`. Score 7–10 + user asks for opus = Hard Stop → surface cost estimate, wait.
   - The score is **immutable after the enrichment review gate is approved**. If the spec changes materially before Phase 2, re-run enrichment and surface a new gate.
   - Trivial tasks that fail their single retry (score 1–3) are surfaced immediately — more retries won't fix a spec gap or a missing credential.

5. **Enrich** — for each task, append (don't modify original):
   ```markdown
   [original task — UNTOUCHED]

   <!-- Added by Conductor -->
   ### Execution Plan
   - **Assigned to**: [tool/subagent OR "TBD - decide at dispatch"]
   - **Complexity score**: [N/10] — active signals: [list each signal that contributed points]
   - **Model requested**: [haiku ≤3 / sonnet 4–6 / frontmatter ≥7 floored at sonnet — never opus]
   - **Max retries**: [1 / 2 / 3] — score-derived
   - **Pre-dispatch research**: [required / optional / skip] — score-derived
   - **Dependencies**: [task IDs]
   - **Duration estimate**: [range]
   - **Criticality**: [critical/standard/optional]
   - **Parallelizable**: [yes/no — based on file overlap]

   ### Verification
   - **Immediate checkpoint**: [what]
   - **Evidence required**: [specifics]

   ### Resources (for lock detection)
   - **Files written**: [paths]
   - **Files read**: [paths]
   - **Other resources**: [DB tables, APIs, etc.]

   ### Anticipated interruptions
   - [credentials, decisions, etc.]
   <!-- End Conductor additions -->
   ```

   For tasks with "TBD" assignment, the routing decision happens just-in-time at dispatch (Tier 2 lazy load).

6. **Initialize state files:**
   - `.conductor/plan.md`
   - `.conductor/routing.md`
   - `.conductor/status.md` (initial)
   - `.conductor/budget.md` (initial estimate)

7. **Generate diff and summary:**
   ```bash
   diff -u <spec-file>.original.md <spec-file> > .conductor/spec-enrichment.diff
   ```
   Categorize additions in `.conductor/spec-enrichment-summary.md`:
   - Assumptions made
   - Gaps filled
   - NFRs inferred
   - Architectural decisions
   - Routing decisions

8. **Surface to user (mandatory gate):**
   ```
   📝 Spec enrichment review required before Phase 2

   I've added [N] enrichments across [M] tasks. Material categories:
   - Assumptions: [count] — see summary
   - Gaps filled: [count]
   - NFRs inferred: [count]
   - Architectural decisions: [count]

   Please review:
   - Diff: `.conductor/spec-enrichment.diff`
   - Summary: `.conductor/spec-enrichment-summary.md`

   Reply:
   (a) "approve enrichments" — proceed to Phase 2
   (b) "revise [item]" — I'll adjust and re-show
   (c) "remove [item]" — I'll strip that enrichment, leaving spec ambiguous (will ask at task time)
   (d) "show details" — I'll explain a specific addition

   I will NOT begin Phase 2 without explicit approval.
   ```

9. **Wait.** Iterate on revisions if requested. Do NOT proceed silently.

10. **On approval**, log to `.conductor/decisions.md`: `Spec enrichments approved by user at [timestamp]`.

## Failure modes

- **Backup file `<spec>.original.md` already exists with different content** → ASK before overwriting. The user may have an in-progress edit you'd clobber.
- **Spec file unreadable or empty** → abort with stderr; log to decisions.md; surface to user.
- **User replies anything other than approve/revise/remove/show** → wait. Do not begin Phase 2 silently.
- **Score becomes inconsistent across tasks** (e.g., two tasks claim "writes >5 files" without enumeration) → surface as gap; ask user before proceeding.
- **Diff is empty** (enrichment added nothing material) → surface that finding; ask user whether to proceed without explicit gate or skip enrichment review.
