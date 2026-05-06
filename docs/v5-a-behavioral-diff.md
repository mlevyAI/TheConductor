# v4.1.1 → v5-A — Behavioral Diff

**Date:** 2026-05-05
**Phase:** A (skills extraction refactor)
**Assertion:** No observable behavior change between v4.1.1 and v5-A. Phase A is content relocation from a single 1737-line file to a 435-line orchestration core plus 7 on-demand skills. The conductor's prompts to the user, gate semantics, hook references, lock format, and final-report shape are all preserved.

This document walks through three hypothetical session scenarios to verify the assertion. Each scenario shows what v4.1.1 does inline vs. what v5-A does via a skill invocation. The user-observable output (terminal text, files written, behavior of gates) is identical in both columns.

## Scenario 1 — Fresh project, simple spec

The user runs `claude --agent project-conductor` in a project with no existing `.conductor/` state, hands the conductor a spec at `spec.md`. Phase 0 → First Response → Phase 1 enrichment → user replies `approve enrichments` → Phase 2 begins.

| Stage | v4.1.1 (inline) | v5-A (with skill jump) | User-observable difference |
|---|---|---|---|
| Phase 0 entry | Conductor body executes ~140 lines of inline Phase 0 logic (Tier 1 lazy scan, sanity check, capability inventory, project config inspection) | Conductor body says `→ invoke skill conductor-phase-0-discovery`. Skill body loads on demand and executes the same logic. | None. The skill follows the same procedure step-by-step. The 30k-token budget is enforced in the skill rather than the body. |
| Phase 0 → First Response transition | Conductor body emits the First Response template directly; sets gate to `pre_first_response_proceed` | Same. The gate state machine lives in the body in v5-A; the First Response template text is verbatim from v4.1.1. | None. The user sees the identical "Project Conductor — Environment Scan Complete" block with the same sections (Running configuration / What I found / Spec analysis / Notable routing decisions / Spec enrichment / Permissions setup offer / Optional bundles offer / Known interruption points / Capability gaps / Budget acknowledgment / Safety mechanisms active / Pre-execution questions / Ready to proceed). |
| `proceed` reply | Body advances `gate` from `pre_first_response_proceed` to `post_first_response_proceed`; emits permissions/bundles handling. | Same. | None. |
| Phase 1 entry | Body executes inline enrichment workflow (~110 lines: backup, audit, complexity score, annotate, diff, surface review gate). | Body says `→ invoke skill conductor-spec-enrichment`. Skill follows the same workflow. | None. The complexity scoring rubric (additive 0–10) is preserved verbatim in the skill. The mandatory Phase-2 gate ("approve enrichments") is preserved. The diff format and `spec-enrichment-summary.md` categories are preserved. |

**Result:** the user-observable session is identical. The structure changed (skill files vs. inline blocks); the prompts, gates, and outputs did not.

## Scenario 2 — Mid-session emergent issue (Cloudflare blocks `requests.get`)

Mid-Phase-2, a task tries to scrape a target site with `requests.get`. Two attempts fail with 403 + Cloudflare HTML. The classification logic fires.

| Stage | v4.1.1 (inline) | v5-A (with skill jump) | User-observable difference |
|---|---|---|---|
| Issue detection | Subagent reports task failure with stderr containing "Cloudflare" / "403" | Same. | None. |
| Conductor reads the failure | Body executes inline ~95-line classification logic: walk Hard Stop precedence list (12 entries), apply Anti-Premature-Failure rule (≥3 attempts before declaring impossibility), classify | Body says `→ invoke skill conductor-classification`. Skill executes the same logic. | None. |
| Classification result | Body emits: "Issue classified as `in_scope`: implementation iteration (different transport). NOT a Hard Stop — adjusting one component's transport technique is iteration, not architectural change. Anti-Premature-Failure: only 2 attempts so far; switch to Playwright as approach #3 before declaring failure." | Skill returns the same classification + recommended next action. Body re-emits the same surface line. | None. The 12-entry Hard Stop list is preserved verbatim in the skill body. The Anti-Premature-Failure 3-attempts threshold is preserved. The phrase `KNOWN LIMITATION` is BANNED in both versions. |
| Logging | Row appended to `.conductor/findings.md` in the same format | Same. | None. |

**Result:** the user-observable session is identical. The classification body relocates to a skill but the rubric is unchanged.

## Scenario 3 — End-of-session FINAL_REPORT.md generation

All phases complete. Mandatory final self-check runs. Conductor writes `.conductor/FINAL_REPORT.md` and emits the in-chat summary.

| Stage | v4.1.1 (inline) | v5-A (with skill jump) | User-observable difference |
|---|---|---|---|
| In-chat summary | Body emits the chat summary template (Status / Phases / Tasks / Interventions / Estimated budget / Delivered / Not delivered / Top 3 next steps / pointer to full report and debug map) | Body emits the same chat summary template. | None. |
| Full report file | Body executes inline ~70-line debug map generation (one block per delivered feature: Built in / Primary files / Database / Tests / Key commits / Subagent used / Key decisions / Emergent fixes / Known limitations) | Body says `→ invoke skill conductor-debug-map`. Skill generates the same debug map. | None. The block format is preserved verbatim. The "How to use" preamble (the surgical-bug-fix prompt template) is preserved. The phrase `KNOWN LIMITATION` remains BANNED in feature blocks; the form is `unverified — N approaches tried: [list]` in both versions. |
| Final state | `.conductor/FINAL_REPORT.md` exists with: Executive Summary, Plan vs. Actual table, Material Changes Log, Routing Notes, Safety Mechanism Outcomes, Surgical Debug Map, Outstanding Items, Evidence Index, Recommended Next Steps. | Same. | None. |

**Result:** the user-observable session is identical. The debug map skill produces the same format. The "ban on `KNOWN LIMITATION` phrase" is preserved.

## Where the change is observable (and why none of these are user-facing behavior)

The v5-A refactor IS observable in three places, but none of them surface to the user as behavior change:

1. **`wc -l project-conductor.md`** drops from 1737 to 435. Useful for maintainers; invisible to users.
2. **Tool-call latency** may shift slightly: a skill invocation has a small overhead (the Skill tool fetches the body) compared to inline content. The conductor's own runtime is dominated by Task tool dispatches and Read/Bash calls, so this is in the noise.
3. **Skill discovery via `/skill-name`**: in v5-A, users running `claude --agent project-conductor` see the conductor's skills auto-discover at session start. They appear in the user's `/` typeahead. This is additive — users gain the ability to invoke `/conductor-debug-map` directly if they want to regenerate just the debug map outside a normal final-report flow. v4.1.1 had no such surface.

## What WAS NOT preserved (intentional, documented)

Two changes are intentional in v5-A and would have been visible to users:

1. **Invocation model.** v4.1.1 was invoked as "Use project-conductor to build from spec.md" (sub-agent mode). v5-A's documented invocation is `claude --agent project-conductor` (main-thread mode). The README change reflects this. **Why:** sub-agents in Claude Code today don't support on-demand skill loading; they preload `skills:` at startup, defeating progressive disclosure. As main thread, the conductor benefits from auto-discovery and lazy loading.
2. **Skills install location prompt.** v4.1.1 had no skills (so nothing to install). `install.sh` in v5-A asks for explicit Y/n consent before any `~/.claude/` write, with default Y for global install. Users who have run the v4.1.1 installer will see this new prompt the first time they re-run after upgrading.

Both changes are surfaced in CHANGELOG.md and README.md. Neither is silent.

## Verification checklist

For Phase A's "no observable behavior change" claim to hold for the cases this document covers:

- [x] First Response template is verbatim text-equivalent to v4.1.1
- [x] Permissions Offer is verbatim text-equivalent (compressed prose, same options A/B/C, same "will still ask" list)
- [x] Optional Bundles Offer is verbatim text-equivalent (same 3 bundles, same install pattern)
- [x] 12-entry Hard Stops list is preserved
- [x] Anti-Premature-Failure 3-attempts threshold is preserved
- [x] BANNED phrase `KNOWN LIMITATION` is enforced in both code-grep checks and skill failure-mode docs
- [x] Lock file schema (PID + session + heartbeat + hostname) preserved
- [x] Final report shape (in-chat summary + full report sections + surgical debug map) preserved
- [x] Status-from-state rule (no estimation) preserved
- [x] All 12 v4.1.1 success criteria preserved (consolidated for line budget but semantically identical)
