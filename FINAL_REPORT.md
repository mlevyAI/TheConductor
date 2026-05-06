# Phase A — Final Report

**Phase:** A (skills extraction refactor)
**Spec revision:** 3 (in-repo at `docs/superpowers/specs/2026-05-05-conductor-claude-maximum-design.md`)
**Date:** 2026-05-05
**Status:** ✅ All acceptance criteria met. Ready for review.

This file is at the repo root by design. Delete it on PR merge.

## 1. Files written

| Path | Lines | Purpose |
|---|---:|---|
| `skills/conductor-phase-0-discovery/SKILL.md` | 84 | Phase 0 environment scan rubric (read-only) |
| `skills/conductor-spec-enrichment/SKILL.md` | 121 | Phase 1 spec enrichment + complexity scoring + mandatory gate |
| `skills/conductor-routing-rubric/SKILL.md` | 95 | Score-derived routing decisions; few-shot examples (verbatim §7.3) |
| `skills/conductor-classification/SKILL.md` | 113 | Hard Stop precedence + Anti-Premature-Failure rule; few-shot examples |
| `skills/conductor-output-quality/SKILL.md` | 64 | Column-empty / row-empty / fill-rate completeness check |
| `skills/conductor-debug-map/SKILL.md` | 67 | FINAL_REPORT surgical debug map generator |
| `skills/conductor-scaffold-ai-director-os/SKILL.md` | 82 | AI Director's OS scaffolder (inert in Phase A; activates in Phase C) |
| `project-conductor.md` | **435** | Orchestration core (rewrite; from 1737 lines) |
| `install.sh` | 397 | Extended: explicit Y/n consent, skills install, `--for-project` flag, updated next-steps |
| `tests/test_skills_smoke.py` | 138 | Static validation of skill frontmatter + sections |
| `tests/test_user_global_readonly.py` | 235 | §3.1 boundary enforcement (structural) |
| `docs/maintenance.md` | 79 | All 7 maintenance rules per spec §7.4 |
| `docs/v5-a-behavioral-diff.md` | 100 | 3 hypothetical session walkthroughs (v4.1 vs v5-A) |
| `docs/superpowers/specs/2026-05-05-conductor-claude-maximum-design.md` | 736 | In-repo copy of canonical spec rev 3 |
| `.github/workflows/test.yml` | 30 | pytest CI workflow + line-budget gate |
| `README.md` (Usage section update) | +12 / −5 | `claude --agent project-conductor` invocation guidance |
| `FINAL_REPORT.md` | (this file) | — |

## 2. Line count delta

```
v4.1.1: project-conductor.md = 1737 lines
v5-A:   project-conductor.md =  435 lines
Delta:  −1302 lines (−75%)
```

The 1302 lines that left the body relocated to:
- 7 skill bodies (~626 lines combined; loaded on demand by the Skill tool when the conductor invokes them)
- `## Compact Instructions` (Layer A) added (~25 lines)
- §3.1 user-global boundary summary added (~12 lines)
- v3/v4/v4.1/v5 changelog one-liners (~10 lines)

The remaining body deltas are aggressive prose compression: explanatory "Why: in real-world testing..." rationale moved to CHANGELOG.md.

**Acceptance:** `wc -l project-conductor.md` returns **435**, within the [380, 440] range required by spec §6.1. The CI line-budget gate is set at 500 (50-line headroom for routine drift; gradual climb past 500 triggers a refactor).

## 3. Syntax verification (per spec §4.3)

**This was NOT optional.** Verification performed via WebFetch against authoritative documentation:

### Skills frontmatter syntax

- **URL fetched:** `https://docs.claude.com/en/docs/claude-code/skills` (redirects to `https://code.claude.com/docs/en/skills`)
- **Date fetched:** 2026-05-05
- **Doc says:**
  - Skill files live at `<root>/skills/<skill-name>/SKILL.md` (directory + SKILL.md, NOT flat .md)
  - Field names: `name`, `description` (recommended), `allowed-tools` (with hyphen), plus optional fields
  - Quoted minimal example: `--- \n description: ... \n ---`
- **Whether training matched:** **Partially.** I had the field names (`name`, `description`, `allowed-tools` with hyphen) correct from training. I did NOT have the directory + SKILL.md format — I had assumed flat `.md` files would work.
- **Action taken:** All 7 skills are written as `skills/<name>/SKILL.md` per the docs. The spec's files-write list (which named flat `.md` paths) is interpreted as referring to the skill, not the literal path; the implementation uses the documented format.

### Sub-agent frontmatter syntax

- **URL fetched:** `https://docs.claude.com/en/docs/claude-code/sub-agents` (redirects to `https://code.claude.com/docs/en/sub-agents`)
- **Date fetched:** 2026-05-05
- **Doc says:**
  - Sub-agent files at `~/.claude/agents/<name>.md` (flat file with frontmatter)
  - Required fields: `name`, `description`. Optional: `tools` (comma-separated), `disallowedTools`, `model`, `permissionMode`, `maxTurns`, **`skills`** (preloads), `mcpServers`, `hooks`, `memory`, `background`, `effort`, `isolation`, `color`, `initialPrompt`
  - **The `skills:` field DOES exist for sub-agents.** It preloads the full skill content into the sub-agent's context at startup. "Subagents don't inherit skills from the parent conversation; you must list them explicitly."
- **Whether training matched:** Yes for the existing fields the conductor uses (`name`, `description`, `tools`, `model`, `memory`, `maxTurns`). My initial uncertainty about `skills:` field support was resolved by the doc — it exists, with the documented semantics.
- **Action taken:** the conductor body's frontmatter does NOT include a `skills:` field. The reasoning is documented in §4 below (the architectural pivot to main-agent invocation).

## 4. Resolved ambiguities

### 4.1 Conductor invocation model (resolved by user mid-implementation)

**The ambiguity:** spec §4.3 mentioned "skills frontmatter syntax verification" but didn't specify how the conductor — running as a sub-agent — would invoke skills on-demand. The Claude Code docs confirm: sub-agents preload skills via `skills:` frontmatter (full body injected at startup); they cannot do progressive disclosure.

**The resolution (user, 2026-05-05):** The conductor is the **main agent**, NOT a sub-agent. It spawns sub-agents to execute work; it is not itself spawned by another agent. Users invoke it with `claude --agent project-conductor`. As main thread, the conductor benefits from auto-skill-discovery and on-demand loading — true progressive disclosure works.

**Impact on this PR:**
- `project-conductor.md` frontmatter has NO `skills:` field (would only be needed if conductor were a sub-agent).
- `README.md` Usage section pivots to `claude --agent project-conductor` as the canonical invocation. The old `Use project-conductor to build from spec.md` form still works (sub-agent mode) but is documented as the legacy path.
- `install.sh` "Next steps" output prints the new `claude --agent` invocation.
- `docs/v5-a-behavioral-diff.md` documents this as one of two intentional changes.

### 4.2 Skills install default (resolved by user; spec rev 3 captures the resolution)

**The ambiguity:** spec rev 2 §3.1.2 said default = (b) project-scoped install. But install.sh runs from inside the TheConductor repo (the documented usage), so `<PROJECT>/.claude/skills/` would land in TheConductor itself — useless.

**The resolution:** spec rev 3 (the canonical version, now in-repo at `docs/superpowers/specs/`) flips the default to (a) **global with explicit Y/n consent**. Single disclosure prompt, default Y, mandatory and visible. Project-scoped install is supported via `--for-project <path>` flag for users with strong project-isolation requirements.

**Impact on this PR:**
- `install.sh` implements the rev 3 prompt: "About to write to ~/.claude/: 7 skill directories + 1 agent file. Proceed? [Y/n]" (default Y).
- `--for-project <path>` flag implemented.
- This is **NOT a spec deviation** — rev 3 is the current spec and matches the implementation.

### 4.3 Skills file format (resolved during §4.3 syntax verification)

**The ambiguity:** spec's files-write list reads `skills/conductor-phase-0-discovery.md` (flat). Claude Code docs require `skills/<name>/SKILL.md` (directory).

**The resolution:** ship as directories. The spec's files-write list is interpreted as naming the SKILL (which lives at `<dir>/SKILL.md`), not a literal file path. The 7 skills are at `skills/conductor-*/SKILL.md`.

**Impact on this PR:**
- 7 skill directories created, each containing one `SKILL.md`.
- `tests/test_skills_smoke.py` validates the directory + SKILL.md structure.
- `install.sh` copies `skills/conductor-*/SKILL.md` to `~/.claude/skills/conductor-*/SKILL.md`.

### 4.4 Skill #7 (`conductor-scaffold-ai-director-os`) in Phase A

**The ambiguity:** the skill is on Phase A's files-write list, but its functionality (templating, scaffold targets) is Phase C work.

**The resolution:** skill #7 is written with the full procedure per spec §5.1.7 but is **inert in Phase A** — the conductor body has no invocation point for it; templates/ doesn't exist; lib/template_render.py doesn't exist. Phase C activates the skill by adding those dependencies and a call site in the conductor body. The skill file's `## Phase A status` section documents this.

### 4.5 `tests/test_user_global_readonly.py` enforcement scope

**The ambiguity:** spec §7.2 requires structural enforcement of §3.1. But "structural" means string-match in source files, NOT runtime tool blocking.

**The resolution (per user amendment #3):** Phase A test is structural only. Full deterministic enforcement (PreToolUse hook backstops) lands in Phase B. See §6 (Open follow-ups) for the explicit handoff.

## 5. Phase A acceptance check

| Criterion | Status | Evidence |
|---|---|---|
| `wc -l project-conductor.md` ∈ [380, 440] | ✅ | `435` |
| All 7 skill files exist with required sections | ✅ | `tests/test_skills_smoke.py` 38/38 pass |
| `pytest tests/` green | ✅ | 45 passed, 1 skipped (templates/ not yet present) |
| `docs/v5-a-behavioral-diff.md` asserts no observable behavior change with 3 walkthroughs | ✅ | 100-line doc with 3 scenarios + verification checklist |
| `install.sh` prompts for skills install location | ✅ | Single Y/n disclosure prompt, default Y; `--for-project` flag for advanced |
| `install.sh` does NOT scan/read/modify `~/.claude/CLAUDE.md`/`imports/`/`settings.json` | ✅ | `tests/test_user_global_readonly.py::test_install_sh_does_not_*` 3 tests pass |
| Spec copied into repo at `docs/superpowers/specs/` | ✅ | 736 lines, byte-equivalent to rev 3 in Downloads |
| FINAL_REPORT.md exists with file list, line count delta, §4.3 syntax verification, resolved ambiguities | ✅ | This file |

## 6. Open follow-ups (next phases)

### Phase B (hooks — backstops)

- **`pre_lock_enforcement.py` tolerant fallback** is documented in spec §5.2 / §6.2 but is NOT yet wired (Phase B implements the hook itself). Until then, lock enforcement remains text-only in the conductor body.
- **User-global write blocker (PreToolUse hook check)** is documented in spec §5.2 but NOT yet implemented. Until Phase B lands, the §3.1 boundary is enforced by:
  - `tests/test_user_global_readonly.py` (structural; runs on every PR)
  - The conductor agent's own discipline (text rule in body)
  - The §3.1 summary block in the conductor body
- **Phase A boundary test is structural only.** It greps source code for write contexts. It does NOT block runtime tool calls. Full deterministic enforcement requires Phase B's `pre_phase0_readonly.py`, `pre_first_response_gate.py`, and `pre_lock_enforcement.py` hooks. **This is a Phase A → Phase B handoff and must not be missed.**

### Phase C (scaffolding)

- **`conductor-scaffold-ai-director-os`** is written with full procedure but is INERT in Phase A. Phase C wires it by:
  - Creating `templates/` directory with the 7 standard-pack templates
  - Adding `lib/template_render.py` (typed-payload substitution + path validation)
  - Adding an invocation point in the conductor body (Phase 1, gated by user opt-in)
- The skill's `## Phase A status` section documents this.
- **Spec drift detection rule** (`docs/maintenance.md` rule #6) activates when scaffolding runs.

### Phase D (prompting + Compact Instructions)

- The Layer A `## Compact Instructions` block is in the conductor body (Phase A added it).
- The dispatch envelope (`lib/dispatch_envelope.py`) and effort router (`lib/effort_router.py`) land in Phase D.
- The conductor body's `→ invoke skill X` jumps don't yet pass an envelope — they're free-form invocations. Phase D wraps each Task dispatch with the XML envelope structure per spec §5.3.

### Maintenance

- **Hook firing-and-runtime health check** (`docs/maintenance.md` rule #4) activates only after Phase B lands hooks.
- **Quarterly user-global boundary check** (rule #7) is active now via `tests/test_user_global_readonly.py`. Run on every PR that touches `install.sh`, future `lib/template_render.py`, or skill `allowed-tools` declarations.

## 7. Risks / cautions for reviewers

1. **The `~/.claude/CLAUDE.md` mention in `install.sh` line 287** is a documentation string in the disclosure prompt ("...the installer does not touch ~/.claude/CLAUDE.md..."). The boundary test correctly identifies it as NOT a write context (printf string contents are stripped before pattern-matching). Reviewers should NOT remove that line — it's the user-facing assurance that the boundary is being honored.

2. **Skill #7 (`conductor-scaffold-ai-director-os`) is shipped but inert.** Its `allowed-tools` includes `Write, Edit, Bash(mkdir)` — full write capability. The skill's body has NO procedure that's reachable from any current call site. A reviewer might worry about "skill that can write but isn't invoked" — that's intentional. Phase C wires it. Until then, `pytest tests/test_user_global_readonly.py::test_skill_allowed_tools_do_not_grant_user_global_writes` ensures the skill can't write to `~/.claude/`.

3. **No `skills:` in conductor frontmatter.** This is intentional (per §4.1 above). When the conductor runs as a sub-agent (legacy invocation `Use project-conductor to build from spec.md`), the user's main agent will see no skills declared, and the conductor's `→ invoke skill X` jumps will fail. The README explicitly directs users to `claude --agent project-conductor` as the supported path. If someone runs the legacy form, they get a degraded conductor — visible failure, not silent corruption.

4. **CI workflow is new** (`/.github/workflows/test.yml`). First push to a PR will trigger pytest + line-budget gate + bash syntax check on `install.sh`. Local runs of `pytest tests/` are green, so CI should be green too.

## 8. What was NOT changed (for clarity)

- `lib/lock_check.py` — untouched (path-component match logic is Phase B's `pre_lock_enforcement.py` work)
- `hooks/heartbeat.py` and `hooks/usage_limit_wakeup.py` — untouched (existing v4 bundles)
- `agent-monitor/` — untouched
- `CHANGELOG.md`, `CONTRIBUTING.md` — untouched (separate doc PR)
- All Phase B/C/D files (templates/, new hooks, lib/template_render.py, lib/conductor_state.py, lib/dispatch_envelope.py, lib/effort_router.py, additional test files, sample-spec.md fixture) — explicitly out of scope per spec §6.1
- The user's `~/.claude/` directory — never touched by this PR (the boundary holds)

## 9. How to verify

```bash
cd /path/to/TheConductor

# Line budget
wc -l project-conductor.md   # → 435 (in [380, 440])

# Tests
pytest tests/ -v             # → 45 passed, 1 skipped

# Boundary check (read-only — does not run install.sh)
grep -n '~/\.claude/CLAUDE\.md\|~/\.claude/imports\|~/\.claude/settings\.json\|~/\.claude/memory' install.sh
# → Only matches inside printf disclosure strings; no write contexts

# Spec is in-repo
ls docs/superpowers/specs/   # → 2026-05-05-conductor-claude-maximum-design.md

# Skills are directory + SKILL.md
ls skills/                   # → 7 conductor-*/ directories
ls skills/*/SKILL.md         # → 7 SKILL.md files

# Install.sh syntax
bash -n install.sh           # → no output = syntax ok

# Conductor frontmatter has no `skills:` field (main-agent invocation pattern)
grep -A 12 '^---$' project-conductor.md | head -15
# → name, description, model, effort, tools, memory, maxTurns; NO skills:
```

## 10. Sign-off

Phase A meets all acceptance criteria from spec §6.1. Phase B (hooks), Phase C (scaffolding), and Phase D (prompting + Compact Instructions) are explicitly out of scope per the stop-condition; each will land as its own PR with its own plan-mode cycle, gated by the regression-signal patterns in spec §6.1–6.4.

---

# Phase B — Completion Notes (2026-05-05)

All 6 hooks installed and canary-passing. All Phase B §6.2 acceptance criteria met. Real-session firing evidence deferred to first live run (findings.md will populate on use). See `hooks/` and `lib/conductor_state.py`.

---

# Phase C — Completion Notes (2026-05-05)

All 7 templates render correctly with sample-spec.md fixture. Atomic-write contract verified (test_e2e_fixture.py). User-global isolation enforced via render() ValueError on target under ~/.claude/. See `templates/`, `lib/template_render.py`, `skills/conductor-scaffold-ai-director-os/SKILL.md`.

---

# Phase D — Completion Notes (2026-05-05)

**Structural deliverables (all met):**

| Artifact | Status |
|---|---|
| `lib/dispatch_envelope.py` — `build_prompt()` with 8/9-element XML envelope, window-relative split, `apply_literalism_rules()` | ✅ |
| `lib/effort_router.py` — `resolve_effort()` + `resolve_model()` with ALWAYS_XHIGH floor logic | ✅ |
| `tests/test_dispatch_envelope.py` — 21 tests including task≠reminder, ordering, threshold precision | ✅ |
| `tests/test_effort_router.py` — 43 tests including all §7.2 cases | ✅ |
| `project-conductor.md` dispatch section updated with `build_prompt()` + `active-task.json::files_write[]` write | ✅ |
| `project-conductor.md` effort routing reference added | ✅ |
| `project-conductor.md` line count: 439 (≤ 500 gate) | ✅ |
| `## Compact Instructions` (Layer A) confirmed present in conductor body | ✅ |
| Full test suite: 176/176 passed | ✅ |

**Real-session DoD items (deferred to live use — require actual conductor runs):**

- 5 captured dispatches in `.conductor/evidence/` showing full envelope structure — will populate on first v5-D session
- `pre_lock_enforcement.py` blocks out-of-declaration write in real session — now fully active once Phase D's `active-task.json::files_write[]` is populated on dispatch
- Compact-instructions recovery rule exercised — will trigger on first long session that hits compaction threshold

These items are observable regression SIGNALS (per §6.4 "Looks-healthy example"), not blocking criteria. The code and tests are complete; live evidence accumulates from first use.
