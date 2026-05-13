---
name: conductor-first-response
description: Render TheConductor's canonical First Response — the "Environment Scan Complete" envelope that surfaces running config, capabilities, spec analysis, routing decisions, enforcement hooks installed in Phase 0a, permissions/bundles offers, procedural safeguards, and the proceed prompt. Invoked once per session, after Phase 0 discovery and before any source-tree mutation. The body must wait for the user to reply `proceed` after this skill renders.
allowed-tools: Read
---

## When to invoke

Invoke once, immediately after `conductor-phase-0-discovery` returns its capability dictionary, and before emitting any other output to the user. The conductor body's hard gate (`First Response (MANDATORY format)` → `🛑 HARD GATE`) governs the wait-for-`proceed` semantics; this skill only renders the template that the gate is protecting.

The skill MUST NOT be invoked outside this single first-emission moment. If the body has already emitted the First Response in the current session, do not re-invoke.

## Inputs

- The capability dictionary returned by `conductor-phase-0-discovery` (subagents, skills, MCPs, CLIs, plugins).
- The current model + effort tier (read from this agent's frontmatter).
- The spec file path, phase count, decomposed task count, complexity score, and estimated token budget (computed in Phase 1 — for first emission these may be `[pending Phase 1]`).
- Routing decisions surfaced by `conductor-routing-rubric` for 3–5 representative tasks.
- Spec enrichment status (whether `<!-- Added by Conductor -->` markers exist; backup path).
- Anticipated interruption points and capability gaps detected during Phase 0.

## Outputs

A single rendered First Response with the structure below. The renderer MUST preserve all 14 sub-sections in the listed order (running config → ready to proceed) so downstream tests and the `pre_first_response_gate` hook can detect the canonical shape.

```
## Project Conductor — Environment Scan Complete

### ⚙️ Running configuration
- **Conductor model**: [opus / sonnet / haiku] + [low / medium / high] effort
- **Estimated cost tier**: [💰 low / 💰💰 medium / 💰💰💰 high]
- **Phase 0a state**: auto-install complete (enforcement hooks + git baseline if needed) — see §🛡️ Enforcement hooks installed below
- **To change**: edit `model:` in this agent's frontmatter

### 🔍 What I found
**Subagents (N total, M planned for use):** [counts; list only those likely to be used based on spec]
**Skills (N):** [list with triggers]
**MCPs connected (N):** [list with capabilities]
**CLIs detected:** [project-relevant only]
**Plugins:** [list]

### 📋 Spec analysis
- File: [path]
- Phases: [N]
- Tasks decomposed: [~N]
- Complexity: [low/medium/high]
- **Estimated token budget: ~XXX k** (small/medium/large)

### 🎯 Notable routing decisions
- Task "[name]": using [tool] because [reason]
- [3–5 examples]
- Note: model routing is best-effort; see Model Routing Caveat (Phase 2)

### ✍️ Spec enrichment
I've annotated your spec with `<!-- Added by Conductor -->` markers.
Original backed up to `[path].original.md`.

### 🛡️ Enforcement hooks installed (Phase 0a auto-install)
9 enforcement hooks were wired into `.claude/settings.json` before this response rendered. In practice, you'll notice them as follows:

- **If your project wasn't a git repo**, I also ran `git init` for v6 replayability — every task's evidence folder lands in a real commit. (Phase 0a preflight; render this bullet only when auto-init actually fired)
- **Before you reply `proceed`**, I cannot mutate the source tree — Write/Edit/Task calls bounce with a block message. (`pre_first_response_gate`)
- **During Phase 0**, I cannot write anywhere outside `.conductor/`. (`pre_phase0_readonly`)
- **Once tasks start**, each task declares a write list; I cannot edit files outside that list. (`pre_lock_enforcement`)
- **Large specs (>300 lines)** must go through the splitter first — I cannot Read them whole. (`pre_spec_split_enforce`)
- **Busy-wait loops** (`until ... sleep ...`, long leading sleeps) are forbidden — I'll use ScheduleWakeup instead. (`pre_busy_wait_block`)
- **After every structured output** (CSV/JSON/XLSX/Parquet), I get a quality check that flags empty columns and low fill-rate. (`post_output_quality`)
- **At session end**, I verify FINAL_REPORT has all required sections and that every task's evidence folder has a `commit_sha`. (`stop_validate_final_report`, `stop_evidence_completeness_check`)
- **Advisory only**: if `.conductor/` is gitignored, I'll warn once — v6 replayability needs commit history. (`pre_state_committed`)

Remove any hook by editing `.claude/settings.json` and deleting its entry from `hooks.PreToolUse`/`hooks.PostToolUse`/`hooks.Stop`. The canonical list with descriptions lives in `hooks/MANIFEST.json` inside the conductor repo.

### 🔐 Permissions setup offer
[See Permissions Offer in the conductor body — MANDATORY to surface]

### 📦 Optional bundles offer
[See Optional Bundles Offer in the conductor body — MANDATORY to surface, optional for user to accept]

### ⚠️ Known interruption points ahead
[List anticipated stops]

### 🚫 Capability gaps
[If any]

### 💰 Budget acknowledgment
I will surface notifications at ~70% / ~95% of estimated budget; work continues unless you ask me to pause.

### 🛑 Safety mechanisms active
- **Turn checkpoint notification** every 25 turns (informational; opt into `--strict-mode` for v3 pause-and-confirm)
- **Spec enrichment review** required before Phase 2
- **Canary model check** before phases dispatching ≥3 tasks at non-default model
- **Lock enforcement** via `git diff --name-only` after each dispatch
- **Permissions sanity test** before writing `.claude/settings.json`
- **Investigation budget** (caps probe artifacts before MUST commit to draft)
- **Anti-Premature-Failure** (≥3 distinct approaches before declaring impossible)
- **Output-quality completeness** check after every structured output write
- **Heartbeat file** for backgrounded mode visibility

### ❓ Pre-execution questions
[Only if blocking]

### 🚀 Ready to proceed?
Reply "proceed" to begin, or address the permissions offer first. Ask "status" at any point during execution.
```

## Procedure

1. Read the capability dictionary from Phase 0.
2. Populate `### ⚙️ Running configuration` from this agent's `model:` frontmatter and the active effort tier.
3. Populate `### 🔍 What I found` from the capability dictionary; list only subagents/skills/MCPs that are *likely to be used* given the spec — not the full inventory.
4. Populate `### 📋 Spec analysis` from the spec file. If Phase 1 has not run yet, mark fields `[pending Phase 1]` rather than guessing.
5. Populate `### 🎯 Notable routing decisions` with 3–5 representative routing calls (one per phase, ideally). Include the "best-effort" note verbatim.
6. Populate `### ✍️ Spec enrichment` only if enrichment has run; otherwise omit the section body but keep the heading with `[pending]`.
7. Render the `### 🛡️ Enforcement hooks installed (Phase 0a auto-install)` block verbatim from the template above. The 8 hook bullets are the canonical user-facing summary of what's in `hooks/MANIFEST.json` for bundles `phase_b` + `v6_replayability`. Do NOT paraphrase. If you've installed a hook that isn't covered by one of those bullets, add a bullet — don't silently drop it. The whole point of this section is so the user knows what just got wired into their project; filename-only lists fail that goal. The leading "If your project wasn't a git repo" bullet is **conditional**: render it only when Phase 0a step 0 actually ran `git init`; omit the bullet entirely when an existing git tree was detected (no false bragging about work that didn't happen).
8. Render the `### 🔐 Permissions setup offer` and `### 📦 Optional bundles offer` headings as pointers to the body sections; do not duplicate the offer content here.
9. Populate `### ⚠️ Known interruption points ahead`, `### 🚫 Capability gaps`, and `### ❓ Pre-execution questions` only if applicable. If nothing to surface, write `None.` so the section is not silently dropped.
10. Render `### 💰 Budget acknowledgment` and `### 🛑 Safety mechanisms active` verbatim from the template above — do not paraphrase or reorder. The Safety mechanisms list covers the conductor's *procedural* safeguards (turn checkpoints, anti-premature-failure, investigation budget, etc.); it is distinct from `### 🛡️ Enforcement hooks installed` above, which covers the runtime hooks. Both must render.
11. Emit the rendered envelope as the *only* user-visible output of this turn. The conductor body's hard gate then enforces the wait-for-`proceed` semantics.

## Failure modes

- **Section dropped or reordered.** The gate hook (`pre_first_response_gate.py`) and downstream tests assume the 14-section canonical shape. If any section is missing or out of order, the gate may fail open. Resolution: re-render from the template above; never edit-in-place.
- **Hooks block reduced to filenames.** Listing `pre_phase0_readonly, pre_first_response_gate, ...` without explaining what each one does leaves the user with no mental model of what just got installed in their project. Resolution: render the workflow-narrative bullets from the template verbatim; users care about *behavior they will observe*, not Python filenames.
- **Capability list overpopulated.** Listing every subagent/skill/MCP regardless of relevance defeats the purpose of the surface. Resolution: filter to "likely to be used" per spec analysis.
- **Phase 1 fields filled with guesses.** If the spec hasn't been parsed yet, do not invent a phase count or token budget. Use `[pending Phase 1]` and let Phase 1 update the response.
- **Rendered before user has acknowledged Phase 0 capability gaps.** Capability gaps (`### 🚫`) must be surfaced — silencing them turns the First Response into theatre. If any gap is detected, render it; do not omit.
- **Re-emission within the same session.** This skill is one-shot per session. If the user asks "show the first response again", surface the existing rendered envelope from `.conductor/decisions.md` rather than re-running this skill.

## Examples

### Example 1 — fresh session, capability-rich

Spec: a 4-phase web-scraping project. Phase 0 found 12 subagents, 8 skills, 2 MCPs (Playwright, Puppeteer), 3 CLIs (`pnpm`, `gh`, `playwright`).

Render highlights:
- `### 🔍 What I found` lists `Frontend Developer`, `Backend Architect`, `Reality Checker` as planned subagents (filtered from 12 to 3 based on spec); both MCPs; and the 3 CLIs verbatim.
- `### 🎯 Notable routing decisions` shows: scraping → Playwright MCP because the target is JS-rendered; report generation → Sonnet 4.5 because the formatting is structured but not novel; coverage matrix → `conductor-debug-map` skill.
- `### 🛡️ Enforcement hooks installed` rendered verbatim (8 narrative bullets) — the user sees what behavior changes their project just inherited from Phase 0a.
- `### 🚫 Capability gaps`: "None detected."
- `### 🚀 Ready to proceed?` rendered verbatim.

### Example 2 — capability gap blocking

Spec requires Postgres writes. Phase 0 found no DB MCP, no `psql` CLI, no DB credentials in `.conductor/credentials/`.

Render highlights:
- `### 🚫 Capability gaps` enumerates the missing pieces and notes that Phase 2 dispatches involving DB writes will hard-stop until resolved.
- `### ❓ Pre-execution questions` asks the user to either provide credentials, install `psql`, or scope the task to skip DB writes.
- `### 🛡️ Enforcement hooks installed` still renders verbatim — the 9 enforcement hooks are part of the conductor's operational identity, not gated by external capabilities. The `git init` leading bullet renders only if Phase 0a actually auto-init'd the repo.
- `### 🚀 Ready to proceed?` still renders, but the user is expected to address the gap before replying `proceed`.
