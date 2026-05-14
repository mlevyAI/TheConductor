---
name: conductor-routing-rubric
description: Decide which subagent (or inline) handles a dispatched task, what model to request, what effort to recommend, and what pre-dispatch research is needed. Score-derived and few-shot driven; never auto-routes to opus.
allowed-tools: Read
---

## When to invoke

The conductor invokes this skill once per task dispatch, after Phase 1 enrichment is approved and before any `Task` tool call. It returns a routing decision; it does NOT execute the dispatch itself.

## Inputs

- The task block from the enriched spec (including its Execution Plan annotations)
- `.conductor/environment.md` — Phase 0 capability inventory
- `.conductor/routing.md` — prior routing decisions (for consistency across similar tasks)
- The task's complexity score from Phase 1.3.5 (immutable post-gate)

## Outputs

- A routing decision returned to the conductor body, structured as:
  ```
  subagent: <name | "in-process" | "none (inline)">
  reason: <why this match>
  effort: <low|medium|high|xhigh>
  model: <haiku|sonnet|opus|inherit>
  complexity: <N/10>
  pre-dispatch research: <required|optional|skip>
  plan_mode: <mandatory|recommended|skip>     # v6.1.4 — see Procedure §7
  files_write: <list — populated into the eventual active-task.json>
  ```
  **`subagent` vocabulary (v6.1.6+)**:
  - **Named subagent** (e.g., `frontend-developer`, `backend-architect`) → conductor body MUST dispatch via `Task` tool. Binding contract — not advisory.
  - **`in-process`** → trivial scaffolding / mechanical file generation that doesn't benefit from a dispatch envelope. The conductor body handles it directly. Use this for: package.json/tsconfig writes, single-file edits with no domain judgment, atomic refactors named in `agent-usage-discipline.md`.
  - **`none (inline)`** → no work required; routing.md row exists for audit trail only.
- A row appended to `.conductor/routing.md` with the same content

## Procedure

1. **Filter the Tier 1 inventory** from `.conductor/environment.md` by keyword match against the task description and domain. Build a candidate list.

2. **Determine candidate count:**
   - **1 clear match** → use it. No deep read needed.
   - **2–3 candidates** → deep-read full body of those candidates ONLY (NOT the entire library). 📦 batch: issue all 2–3 `Read` calls in a single assistant turn — the candidate files are independent and their order does not change the routing decision. Track against the adaptive cap (each file in the batch counts as one deep-read).
   - **0 matches** → use `general-purpose`. Log the gap to `.conductor/routing.md`.
   - **Trivial mechanical task** (single-file edit fully described in spec, scaffolding ≤5 files where every file's content is derivable from the spec, atomic refactor named in `agent-usage-discipline.md`) → output `subagent: in-process`. v6.1.6+: do NOT name a subagent just to "be safe" — naming a subagent makes dispatch binding; if dispatch would be theatre, mark in-process upfront. This prevents the routing-discipline drift where the body sees a named subagent in routing.md and disregards it in favor of in-process work.

3. **Resolve the model** (score-derived from Phase 1.3.5):
   - Score 1–3 → request `haiku`
   - Score 4–6 → request `sonnet`
   - Score 7–10 → respect subagent frontmatter; floor at `sonnet` if frontmatter is haiku. Do NOT request opus.
   - **TBD tasks**: apply score-based selection AFTER the Tier 2 deep-read completes, not before.
   - **Never auto-route to opus.** Opus requires explicit user approval per the retry policy.

4. **Resolve effort** (recommendation only — see §5.4 of the spec for the honest framing):
   - Complexity 1–3 → `low`
   - Complexity 4–6 → `medium`
   - Complexity 7–8 → `high`
   - Complexity 9–10 → `xhigh`
   - Always-xhigh categories (with floor of complexity ≥4): `security_audit`, `schema_design`, `root_cause_debug`, `classification`. Below complexity 4, the normal mapping wins.

5. **Pre-dispatch research:**
   - If score is 7–10 AND task names an external API or new dependency → `required`
   - If score is 4–6 AND task names an external API → `optional` (only if investigation budget has room)
   - Otherwise → `skip`

6. **Files-write declaration:** extract from the task's "Files written" annotation. This list populates `active-task.json::files_write[]` for `pre_lock_enforcement.py` (Phase B onward).

7. **Plan-mode decision** (v6.1.4 — write-bearing subagents only):
   - Read-only subagent (`Explore`, `Reality Checker`, `Evidence Collector`) → **always `skip`**. Plan mode is write-bearing only; emitting it for research dispatches is overhead without payoff.
   - Complexity ≥ 7 AND `len(files_write) > 3` → **`mandatory`**. Subagent MUST enter Claude Code plan mode before writing.
   - Complexity ≥ 7 AND task names a sensitive area (schema, auth, billing, security, deploy) → **`mandatory`**. Even one-file changes here benefit from a written approach before code.
   - Complexity 4–6 AND `len(files_write) > 5` → **`recommended`**. Cross-file coordination is non-trivial but the formula is generally followable.
   - Otherwise → **`skip`**.

   **Vocabulary note.** The value `mandatory` matches the user's CLAUDE.md `## Mandatory plan mode` heading — they're the same concept, kept identical so routing.md and the user's mental model don't drift.

   Rationale: complements the enrichment Execution Plan rather than duplicating it. Enrichment is global-scope (one gate, all tasks) and floors the baseline; plan-mode is local-scope (just-in-time, subagent-authored) and fills in the file order, rollback strategy, and codebase-specific gotchas the enrichment formula cannot predict. The flag is **advisory** — a subagent that finds an Execution Plan block already detailed enough may downgrade `mandatory` → noop in its own judgment, but should log that decision.

8. **Pre-approved dependencies** (v6.1.6+ — escape valve for spurious Hard Stops):
   The following deps may be added (e.g., via `pnpm add`) WITHOUT triggering the "new dep → Hard Stop" rule, when justified by the task description and falling under their listed purpose:
   - **Input validation**: `zod`, `valibot`, `arktype`
   - **Utility classnames**: `clsx`, `tailwind-merge`, `class-variance-authority`
   - **Icons**: `lucide-react`
   - **Testing**: `vitest`, `@vitest/coverage-v8`, `@testing-library/react`, `@testing-library/jest-dom`
   - **Dates** (small): `date-fns` (NOT `moment`, NOT `dayjs+plugins` — bundle size concerns)

   Adding anything OUTSIDE this whitelist (paid SDKs, infrastructure clients like `stripe` or `@upstash/redis`, anything that pulls native bindings) → Hard Stop as before. Rationale: prior simulation surfaced that `zod` install tripped Hard Stop and the agent wrote a worse `.safeParse()`-shaped shim instead of installing zod — the protocol forced a worse solution.

9. **Infra-dependency detection** (v6.1.6+):
   Some patterns require an **external store** to be correct on serverless (Vercel, Lambda, etc.) but pass typecheck silently with in-memory stubs. When the task description names any of these patterns, the rubric MUST flag the resulting code as scaffold-only with a deferral note unless a compatible external store is connected:
   - **Rate limiter** → needs Upstash Redis / Cloudflare KV / DurableObjects. In-memory Map = per-instance, not per-user.
   - **Session cache / hot data cache** → same.
   - **Background job queue** → needs Inngest, QStash, BullMQ-with-Redis. Not in-memory.
   - **WebSocket fan-out** → needs Pusher, Ably, or sticky-session adapter.

   When flagged: routing.md row gets `infra_dep: required` annotation; the `plan.md` Gated Dependencies section lists the gap; the subagent dispatch envelope `<constraints>` includes: "Scaffold-only — DO NOT claim production-ready without external store. Wrap the in-memory impl behind an interface so swap-in is mechanical."

10. **Append routing.md row** with the decision and a one-line reason. Same row format used for consistency across the session — future task dispatches can match against it.

## Examples

```xml
<examples>
  <example>
    <task>Add Supabase RLS policies for the `invoices` table</task>
    <route>
      subagent: Database Optimizer
      reason: schema/RLS work matches its persona
      effort: high
      complexity: 6/10
      pre-dispatch research: read existing RLS in supabase/migrations/*
    </route>
  </example>
  <example>
    <task>Write a regex to slugify post titles</task>
    <route>
      subagent: none (inline)
      reason: single-function utility, no domain context, sub-agent overhead exceeds work
      effort: low
    </route>
  </example>
  <example>
    <task>Audit the auth flow for tenant isolation gaps</task>
    <route>
      subagent: Security Engineer
      reason: explicit security review = persona match
      effort: xhigh
      complexity: 8/10
      pre-dispatch research: read src/middleware.ts + every src/api/**/*.ts
    </route>
  </example>
</examples>
```

## Failure modes

- **Tier 2 deep-read attempted but the agent file is unreadable** → fall back to general-purpose; log gap to routing.md; surface to user only if the task requires a specific persona that's now unavailable.
- **More than the adaptive cap of deep-reads attempted in one session** → halt deep-reads; use general-purpose for remaining unclassified tasks; log the cap-hit to routing.md.
- **Score / complexity inconsistency** (e.g., score 8 but no signals listed) → STOP. The score is supposed to be immutable post-gate; an inconsistency means enrichment was malformed. Surface to user; do NOT silently fix.
- **Skill is invoked for a routing decision but the conductor body has not yet recorded a complexity score for this task** → return an error string; the conductor body should re-run enrichment for this task before dispatching.
- **Caller requests opus** → return a Hard Stop signal with cost estimate; do NOT auto-escalate.
