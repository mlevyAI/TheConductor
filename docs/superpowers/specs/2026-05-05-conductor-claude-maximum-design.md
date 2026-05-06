# TheConductor — Claude-Maximum Upgrade

**Status:** Design (awaiting user approval)
**Date:** 2026-05-05
**Revision:** 3 (skills install default = global with explicit consent; rev 2 boundary preserved)
**Source material:** *Claude at Maximum Capacity — The AI Director's Operating Manual* (provided by user)
**Branch target:** `main` (eventual; staged via 4 sub-PRs — see §6)
**Authors:** mlevyAI (AI Director), Claude (drafting)

---

## 1. Context

TheConductor v4.1.1 is a 1737-line single-file subagent (`project-conductor.md`) that orchestrates spec-driven project execution. It already ships hooks (`heartbeat.py`, `usage_limit_wakeup.py`), an agent-monitor bundle, and a lock-check library. The AI Director's Operating Manual identifies several mechanisms TheConductor is not yet exploiting:

- **Size discipline.** A 1737-line system prompt produces uniform attention degradation; the manual targets ≤200 lines, ideally ≤100.
- **Skills (progressive disclosure).** Heavy domain content should load on demand via the Skill tool, not always.
- **Hooks as the only deterministic layer.** Several "must always" rules in the conductor body are text-only and have been observed to be ignored under accept-edits mode.
- **`## Compact Instructions`.** Long multi-phase runs hit compaction; without explicit preserve/discard rules, decisions vanish silently.
- **AI Director's OS scaffolding.** Per the manual, projects should ship with a CLAUDE.md table-of-contents, `.claude/current-phase.md`, scoped `.claude/rules/`, pre-wired hooks, and a PRD template. TheConductor doesn't currently scaffold any of this.

This spec defines an upgrade that addresses each gap without breaking the v4.1 CLI surface or in-flight sessions.

## 2. Goals

1. Reduce the conductor body from 1737 → ~400 lines via skills extraction.
2. Convert text-only "must always" rules to deterministic hook backstops (6 new hooks).
3. Add `## Compact Instructions` to both the conductor body and the templated CLAUDE.md.
4. Ship a "Standard pack" AI Director's OS scaffolder driven by Phase 1 enriched-spec values.
5. Apply the manual's prompting techniques (XML envelopes, long-context positioning, Opus literalism rules) to every Task dispatch.
6. Encode an effort-recommendation router with honest framing about its probabilistic nature.
7. Land in 4 stageable phases that can be promoted independently using observable regression signals.

## 3. Non-goals

- Auto-populating `~/.claude/CLAUDE.md` (user-global is sacred — see §3.1).
- Full-pack scaffolding (auto `.claude/architecture.md`, auto-generated specialist subagents). Standard pack only — full pack is a follow-up.
- Changing the conductor's `model: opus` / `effort: medium` defaults.
- New MCP servers.
- CI/CD pipeline integration for the conductor itself.
- Auto-migrating in-flight v4.1 sessions; users finish those, then upgrade.

## 3.1 Boundary: user-global is read-only at runtime

**This is a hard architectural rule, not a guideline.** TheConductor agent has TWO distinct components with different rights regarding `~/.claude/`:

### 3.1.1 The agent at runtime — READ-ONLY in `~/.claude/`

The conductor agent, while running in any session, **MAY**:
- Scan `~/.claude/agents/` to discover available subagents and match them to dispatched tasks
- Scan `~/.claude/skills/` to discover available user-installed skills and reference them in execution plans
- Read `~/.claude/CLAUDE.md` and `~/.claude/imports/` to understand the user's standing preferences and incorporate them into orchestration decisions
- Read `~/.claude/settings.json` to discover available MCPs and capabilities
- Read `~/.claude/memory/` entries for context on prior conductor work

This read-only scanning is **central to the conductor's value proposition** — execution plans become more efficient when the conductor knows what's already installed on the user's machine.

The conductor agent at runtime, **MUST NOT**:
- Write, edit, append to, or delete any file under `~/.claude/`
- Suggest "let me update your CLAUDE.md" or similar — even as an offer
- Create files under `~/.claude/imports/`
- Modify `~/.claude/settings.json`
- Touch `~/.claude/memory/` (read OK, write forbidden)

If the conductor identifies that a user-global change *would* benefit the user (e.g., "your CLAUDE.md is missing `## Compact Instructions`"), it surfaces this as a one-line *informational notice* in `decisions.md` and moves on. It does not act, offer, or prompt.

### 3.1.2 `install.sh` — single permitted writer, with explicit consent

`install.sh` is the only TheConductor component permitted to write to `~/.claude/`, and only:
- `~/.claude/skills/` for the 7 bundled skill files
- `~/.claude/agents/` for `project-conductor.md` itself

Both writes require explicit user consent at install time. The installer surfaces a single disclosure prompt before any `~/.claude/` write:

```
About to write to ~/.claude/:
  - 7 skill files → ~/.claude/skills/conductor-*.md
  - 1 agent file  → ~/.claude/agents/project-conductor.md

No other files under ~/.claude/ will be modified.

Proceed? [Y/n]
```

**Default = Y (global install).** The reasoning: TheConductor's value proposition is "works in any project the user invokes it from." The agent file is global (`~/.claude/agents/project-conductor.md`); skills are functionally paired with the agent. A project-scoped skills install would mean the conductor only works correctly in that one project, contradicting the value prop.

The user-global boundary from §3.1 is preserved by the **explicit consent** step (default Y, but the Y/n prompt is mandatory and visible). What the default optimizes for is the recommended answer for the conductor's typical use case — not the absence of a consent step.

**Alternative install modes:**
- `n` (skip) — abort install with notice "conductor not installed; re-run when ready"
- `--for-project <path>` flag (advanced) — writes skills to `<path>/.claude/skills/` instead of `~/.claude/skills/`. The agent file still goes to `~/.claude/agents/`. For users with strong project-isolation requirements.

**The installer never modifies** `~/.claude/CLAUDE.md`, never creates files under `~/.claude/imports/`, never touches `~/.claude/settings.json`, and never reads/writes `~/.claude/memory/`. This is enforced by `tests/test_user_global_readonly.py` (§7.2), which greps `install.sh` source for any write context referencing those paths.

### 3.1.3 Why this matters

TheConductor is shipped to the community (#buildinpublic). Every user who installs it has their own `~/.claude/` configuration that reflects their own decisions. A subagent that writes to user-global — or even *offers* to — imposes design choices on people who never agreed to them. The boundary is absolute: **read everything, write only with explicit consent at install time, runtime never.**

## 4. Architecture

### 4.1 Repo layout (after all 4 phases)

```
TheConductor/
├── project-conductor.md            ← 1737 → ~400 lines (orchestration core)
│                                     Frontmatter declares skills, tools, hooks.
├── skills/                         ← NEW — bundled with installer
│   ├── conductor-phase-0-discovery.md
│   ├── conductor-spec-enrichment.md
│   ├── conductor-routing-rubric.md          (with few-shot examples)
│   ├── conductor-classification.md
│   ├── conductor-output-quality.md
│   ├── conductor-debug-map.md
│   └── conductor-scaffold-ai-director-os.md
├── hooks/
│   ├── heartbeat.py                         (existing)
│   ├── usage_limit_wakeup.py                (existing)
│   ├── pre_phase0_readonly.py               ← NEW
│   ├── pre_first_response_gate.py           ← NEW
│   ├── pre_busy_wait_block.py               ← NEW
│   ├── pre_lock_enforcement.py              ← NEW
│   ├── post_output_quality.py               ← NEW
│   └── stop_validate_final_report.py        ← NEW
├── lib/
│   ├── lock_check.py                        (existing — extended w/ path-component match)
│   ├── conductor_state.py                   ← NEW — phase/gate state reader
│   ├── template_render.py                   ← NEW — typed-payload substitution
│   ├── dispatch_envelope.py                 ← NEW — XML wrapper + ordering
│   └── effort_router.py                     ← NEW — complexity → effort mapping
├── templates/                       ← NEW — Standard scaffold pack
│   ├── CLAUDE.md
│   ├── .claude/
│   │   ├── current-phase.md
│   │   ├── settings.json                    (project-scaffolded hooks pre-wired)
│   │   ├── rules/{frontend,api,tests}.md
│   │   └── prd/template.md
│   └── README-scaffold.md
├── tests/                           ← NEW — pytest, repo root
│   ├── test_lock_check.py
│   ├── test_template_render.py
│   ├── test_dispatch_envelope.py
│   ├── test_effort_router.py
│   ├── test_conductor_state.py
│   ├── test_hooks_integration.py
│   ├── test_skills_smoke.py
│   ├── test_e2e_fixture.py
│   ├── test_user_global_readonly.py         ← NEW — enforces §3.1 boundary
│   └── fixtures/
│       └── sample-spec.md
├── docs/
│   ├── maintenance.md                       ← NEW
│   └── superpowers/specs/
│       └── 2026-05-05-conductor-claude-maximum-design.md   (this file)
├── install.sh                       ← EXTENDED — copies skills/, templates/, new hooks
└── .github/workflows/test.yml       ← NEW — pytest on PR
```

**Note on `install.sh`:** the previous revision of this spec proposed a "verbosity-default offer" that scanned and offered edits to `~/.claude/CLAUDE.md`. That capability is **removed** in this revision per §3.1. The installer's user-global footprint is limited to the consented copy of skills and the agent file.

### 4.2 Spec → scaffold injection

After Phase 1 enrichment, the conductor writes `.conductor/scaffold-payload.json` — a flat key/value map distilled from `spec-enrichment-summary.md`. This is the single artifact the scaffold step reads. No re-parsing of prose downstream.

**Templating mechanism.** Plain `{{VAR}}` substitution via Python `string.Template` style (no new deps, predictable, no Jinja control-flow surprises). Single codepath in `lib/template_render.py`.

**Field map:**

| Var | Source field | Falls back to |
|---|---|---|
| `PROJECT_NAME` | spec title / cwd basename | cwd basename |
| `STACK` | enriched `stack` | `TODO: stack` |
| `LANG_PRIMARY` | enriched `language` | `TODO: language` |
| `DOMAIN` | enriched `domain` | `TODO: domain` |
| `TABLES` | enriched `db.tables[]` | `—` (literal em-dash; non-DB project) |
| `TEXT_DIRECTION` | enriched `i18n.direction` | `ltr` |
| `AUTH_MODEL` | enriched `auth.model` | `TODO: auth model` |
| `CURRENT_PHASE_TITLE` | enriched `phases[current].title` | `TODO: current phase` |
| `IN_SCOPE` | enriched `phases[current].in_scope[]` | `TODO: define in-scope items` |
| `OUT_OF_SCOPE` | enriched `phases[current].out_of_scope[]` | `TODO: define out-of-scope items` |

**Template → vars used:**

| Template | Vars |
|---|---|
| `CLAUDE.md` | `PROJECT_NAME`, `STACK`, `LANG_PRIMARY`, `TEXT_DIRECTION`, `AUTH_MODEL` |
| `.claude/current-phase.md` | `CURRENT_PHASE_TITLE`, `IN_SCOPE`, `OUT_OF_SCOPE` |
| `.claude/settings.json` | (none — hook paths come from installer-baked env) |
| `.claude/rules/frontend.md` | `STACK`, `TEXT_DIRECTION` |
| `.claude/rules/api.md` | `STACK`, `AUTH_MODEL` |
| `.claude/rules/tests.md` | `LANG_PRIMARY` |
| `.claude/prd/template.md` | `PROJECT_NAME`, `DOMAIN`, `TABLES` |

**Note:** all scaffold targets are **project-scoped** (relative to cwd). No template ever resolves to a path under `~/.claude/`. This is enforced by `lib/template_render.py::render()` rejecting any target path that resolves under the user's home `.claude/` directory (see §7.2 testing).

**Fallback semantics.** Missing field → literal `TODO: <fieldname>` written into the file AND a row appended to `.conductor/decisions.md`. Visible, auditable, never silent.

**Thin-spec circuit-breaker.** ≥3 missing required fields → scaffold pauses with a one-line surface to user: `scaffold: spec is thin (missing: X, Y, Z). Reply 'scaffold with TODOs' to continue or 'rerun enrichment' to fix.`

**Scaffold collision.** If a target file already exists, write to `<target>.scaffold-suggestion.<ISO-8601-timestamp>` instead. Never overwrite. Never recurse (sortable timestamp suffix prevents `.scaffold-suggestion.scaffold-suggestion`). User hygiene cleans up old suggestions; the conductor logs each path to `decisions.md`.

**Atomic-write contract.** Scaffold writes are all-or-nothing. The skill (a) renders ALL templates to memory first, (b) writes to a temp directory under `.conductor/scaffold-staging-<ts>/`, (c) on success, atomically renames each staged file to its final target (using `os.replace`). If any render or staged-write fails, the staging directory is removed and no target file is touched. This prevents partial scaffold state from a mid-run interruption.

### 4.3 Sub-agent delegation contract (when scaffold delegated)

**Default = inline** (~7 file writes, low context cost). Delegation is opt-in. When used:

1. Delegate's frontmatter MUST declare `skills: [conductor-scaffold-ai-director-os]` AND `tools: [Read, Write, Edit, Bash]`. `lib/conductor_state.py::validate_scaffold_delegate()` enforces this; fall back to inline if missing.
2. The enriched spec is passed as a fenced `<scaffold-input>{...}</scaffold-input>` block in the Task prompt — never assumed via shared context (sub-agents don't inherit it).
3. Skill body's first instruction is to parse the `<scaffold-input>` block; if absent, abort with stderr the parent conductor reads.

**Skills frontmatter syntax verification.** The `skills:` declaration in agent frontmatter is a Claude Code feature whose syntax has evolved. Before Phase A lands, the implementing PR MUST verify current syntax against Anthropic's published Claude Code documentation and adapt if needed. This verification is captured in the Phase A FINAL_REPORT.

### 4.4 Two-layer Compact Instructions

**Layer A — TheConductor body** (inserted near top of `project-conductor.md`, after v4.1 changes block, before Three Prime Directives):

> **Preserve through compaction**
> - `.conductor/scaffold-payload.json` (typed enriched-spec values)
> - `.conductor/spec-enrichment-summary.md` (human-readable)
> - `.conductor/decisions.md` (every routing choice and reason)
> - `.conductor/state.json` (fields: `phase`, `gate`, `scaffold_written`)
> - `.conductor/locks/active-task.json` and `.conductor/locks/*.json`
> - Hard-Stop classifications and Anti-Premature-Failure attempt counters
> - This `## Compact Instructions` section itself
>
> **Discard**
> - Phase 0 discovery dialog turns (resolutions are on disk under `.conductor/`)
> - Intermediate clarification exchanges (resolutions are in `decisions.md`)
> - Tool-call output that has been acted on (results are in files / git)
> - Read-only exploration that informed a decision already recorded
> - Heartbeat / status-line noise
>
> **Recovery rule.** If compaction has occurred, the conductor's first action on the next turn is to read `state.json`, `scaffold-payload.json`, and `decisions.md` before any other tool call.

**Layer B — Templated CLAUDE.md** (written into scaffolded projects by `conductor-scaffold-ai-director-os`):

> **Preserve:** architecture decisions in `.claude/architecture.md` (if present), security constraints, current sprint scope (`.claude/current-phase.md`), acceptance criteria for in-flight work, deploy commands, environment-specific paths, this section.
>
> **Discard:** file contents already written to disk, completed debugging sessions, tool output that has been acted on, long agent transcripts that produced summarized results, read-only exploration that informed a decision already recorded.

## 5. Components

### 5.1 Skills (7)

All skills bundled in TheConductor repo's `skills/` and copied to the user's chosen install location (`~/.claude/skills/` global by default, OR `./.claude/skills/` via `--for-project` flag — see §3.1.2) by the installer with explicit consent. Conductor declares them in frontmatter so name+description load at session start; bodies load only on Skill-tool invocation.

| # | Skill | Trigger | Allowed-tools |
|---|---|---|---|
| 1 | `conductor-phase-0-discovery` | Phase 0 entry | `Read, Glob, Bash(ls,find,grep,git,jq,which)` |
| 2 | `conductor-spec-enrichment` | Phase 1 enrichment | `Read, Write(.conductor/**), Bash(diff,jq)` |
| 3 | `conductor-routing-rubric` | Each task dispatch | `Read` |
| 4 | `conductor-classification` | Emergent issue surfaces | `Read` |
| 5 | `conductor-output-quality` | After structured-output writes | `Read, Bash(jq,awk,sqlite3,head,wc)` |
| 6 | `conductor-debug-map` | FINAL_REPORT generation | `Read, Bash(git log,git show)` |
| 7 | `conductor-scaffold-ai-director-os` | Phase 1, after enrichment approval | `Read, Write, Edit, Bash(mkdir)` |

**Skill #2 tool scope is project-only.** `Write(.conductor/**)` is the literal allowlist — the skill cannot write to any other path, including any `~/.claude/` path. This is enforced at the skill-tool boundary.

**Skill #7 tool scope is project-only.** `Write` and `Edit` are restricted to paths under cwd; `lib/template_render.py::render()` (§7.2 testing) rejects any target path resolving under `~/.claude/`.

**Common skill body shape:**

```markdown
---
name: <skill-name>
description: <one-line trigger description>
allowed-tools: <scoped tool list>
---

## When to invoke
## Inputs
## Outputs
## Procedure (numbered, verifiable steps)
## Examples (required for #3 routing and #4 classification)
## Failure modes (what to write to stderr; never silently swallow)
```

**Few-shot examples (skill #3 — `conductor-routing-rubric`)** are mandatory and complete (no `…` truncation). Three references baked in: a Database Optimizer dispatch, an inline-no-subagent case, and a Security Engineer xhigh dispatch. See §7.3 for the full XML body example.

**Skill #7 procedure (concrete):**

1. Read `.conductor/scaffold-payload.json`. If absent → abort with stderr "scaffold-payload.json missing; run conductor-spec-enrichment first".
2. Count required fields with literal value `TODO: <fieldname>`. ≥3 → emit thin-spec circuit-breaker line and STOP awaiting user reply.
3. Render ALL templates to memory first (atomic-write contract, §4.2):
   a. For each template in `templates/` (resolved via installer-baked path), call `lib/template_render.render(template_path, payload)` → rendered string.
   b. Compute target path under cwd. If target exists, retarget to `<target>.scaffold-suggestion.<ISO-8601>`.
   c. If any target resolves under `~/.claude/`, abort with stderr "scaffold target outside project — check template paths".
4. Write all rendered strings to staging directory `.conductor/scaffold-staging-<ts>/`.
5. On success, atomically rename each staged file to its final target. On any failure, remove staging directory and abort.
6. Append to `.conductor/decisions.md`: scaffold action + file list + TODO marker count.
7. Surface to user: "Scaffolded N files. M TODO markers in <list-of-files> — please review."

### 5.2 Hooks (6 new + 2 existing)

**Universal no-op guard.** First 4 lines of every conductor hook:

```python
import json, os, sys
state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)  # no-op when not in a conductor-managed project
```

**Hook table:**

| Hook | Event | Matcher | Rule | Exit | Backstops |
|---|---|---|---|---|---|
| `pre_phase0_readonly.py` | PreToolUse | `Write\|Edit\|Bash` | If `phase=="0"`, block `Write/Edit` outside `.conductor/**`, block any `Bash` not in read-only allowlist | 2 | v4.1.1 "🚧 Phase 0 is READ-ONLY" |
| `pre_first_response_gate.py` | PreToolUse | `Write\|Edit\|Task\|Bash` | If `gate=="pre_first_response_proceed"`, block `Write` outside `.conductor/**`, all `Edit`, all `Task`, mutating `Bash` | 2 | v4.1.1 "🛑 HARD GATE" |
| `pre_busy_wait_block.py` | PreToolUse | `Bash` | Block `until ...; do sleep N; done`, `while ...; do sleep N; done`, leading `sleep \d{3,}` | 2 | v4 "Forbidden Bash Patterns" |
| `pre_lock_enforcement.py` | PreToolUse | `Write\|Edit` | Block writes to paths NOT segment-prefix-matching any entry in `active-task.json::files_write[]` | 2 | v3 "Lock enforcement" (was post-write) |
| `post_output_quality.py` | PostToolUse | `Write` on csv/json/xlsx/jsonl/parquet, `Bash` on sqlite writes | Run completeness/anomaly check; write findings to `.conductor/findings.md`; non-blocking | 0 | v4 "Output-Quality Completeness Check" |
| `stop_validate_final_report.py` | Stop | (any) | If `phase=="complete"` and FINAL_REPORT missing/incomplete, write findings.md row | 0 | (new — enforces FINAL_REPORT promise) |

**User-global write blocker — implicit but enforced.** All `Write|Edit` PreToolUse hooks (`pre_phase0_readonly`, `pre_first_response_gate`, `pre_lock_enforcement`) include an unconditional check, evaluated BEFORE the gate-specific logic: if the target path resolves under `~/.claude/`, exit 2 with stderr `"refusing to write under ~/.claude/ — user-global is read-only at runtime per §3.1"`. This applies regardless of phase or gate. The conductor agent at runtime can never write to user-global, period.

**Bash regex hermeticity.** Each hook header comment states explicitly: *"This regex catches the common cases. It will NOT catch `bash -c '…'`, aliases, double-spaced commands, or chained `cd && rm`. Truth is `.conductor/state.json` + the conductor's own discipline. The hook is a safety net, not a fence."*

**Lock enforcement uses path-component match**, not string-prefix. `lib/lock_check.py::path_within_declaration(target, declared)` splits both on `/` and requires declared's segments to equal target's leading segments segment-for-segment. Regression test: `src/api` does NOT match `src/api-keys/secrets.ts`.

**Phase B/D dependency resolution.** `pre_lock_enforcement.py` (Phase B) reads `active-task.json::files_write[]`. The full envelope structure including `<files-write>` lands in Phase D (§5.3). To avoid a circular dependency:

- Phase B installs the hook with a tolerant fallback: if `active-task.json` exists with `files_write[]`, enforce. If `active-task.json` is missing OR `files_write[]` is absent/empty, exit 0 (allow) and write a single row to `findings.md` per session: `pre_lock_enforcement: no active-task.json::files_write[] yet (pre-Phase-D); not enforcing this session`.
- The conductor body in v4.1 already writes `.conductor/locks/active-task.json` for in-flight tasks; Phase B's hook reads whatever fields exist there.
- Phase D extends `active-task.json` to include `files_write[]` as part of the envelope construction. After Phase D lands, `pre_lock_enforcement.py` enforces fully.

This staging is documented in §6.2 (Phase B's "looks-healthy example" includes the tolerant-fallback row).

**Sub-agent gate inheritance is intentional, documented.** The conductor body adds a subsection under "First Response Gate":

> *"Hook gate state is read from the parent project's `.conductor/state.json`. When the conductor dispatches a Task, the sub-agent inherits this gate — pre-proceed sub-agents are blocked from mutating the working tree. This is intentional. Sub-agents must not mutate state the user has not yet authorized."*

**Hook canary at install time.** `install.sh` runs each hook with synthetic stdin — allow-case (exit 0 expected) and block-case (exit 2 expected for PreToolUse). Failed canary → hook not installed, row written to `decisions.md`.

**Project-scaffolded hooks (separate set, written by skill #7 into the project's `.claude/settings.json`):**

| Hook | Event | Effect |
|---|---|---|
| `block_prod_env_writes.py` | PreToolUse on `Write\|Edit` | Block writes to `**/.env.production`, `**/.env.prod`, paths containing `production` |
| `auto_lint_on_edit.py` | PostToolUse on `Write\|Edit` | Run `eslint --fix` on `.ts/.tsx`, `ruff check --fix` on `.py`, `gofmt -w` on `.go` — only if binary in PATH |
| `compact_instructions_check.py` | Stop | Warn (non-blocking) if `CLAUDE.md` lacks `## Compact Instructions` |

These are **project-scoped** — they live under the project's `.claude/settings.json`, not the user's. They are independent of `.conductor/state.json` and fire in any session that runs in a project where they're scaffolded.

### 5.3 Dispatch envelope (Phase D)

The conductor's dispatch wrapper (`lib/dispatch_envelope.py::build_prompt()`) wraps every Task prompt with the manual's recommended structure:

**Element order** (top-to-bottom):

Base envelope (8 elements, used when total prompt ≤ 4% of sub-agent context window):
1. `<task>` — full task with context (top — primary attention).
2. `<constraints>` — schema, library versions, forbidden patterns.
3. `<files-write>` — exact list (sub-agent inherits as lock declaration; populated into `active-task.json` for `pre_lock_enforcement.py` consumption).
4. `<acceptance>` — verifiable criteria.
5. `<context>` — relevant snippets.
6. `<effort-recommendation>` — `low|medium|high|xhigh`.
7. `<complexity>` — 1–10 score.
8. `Reminder: <one-line restated objective>` — bottom. Non-identical to top `<task>` (unit-tested).

Split envelope (9 elements, used when total prompt > 4% of sub-agent context window):
1. `<task>` — full task with context.
2. `<constraints>`.
3. `<files-write>`.
4. `<acceptance>`.
5. `<critical-context>` — must-not-be-lost-in-the-middle snippets, kept near top.
6. `<reference-context>` — supporting snippets that can tolerate middle position.
7. `<effort-recommendation>`.
8. `<complexity>`.
9. `Reminder:` line.

**Window-relative threshold.** Read sub-agent context window from agent frontmatter (default 200_000 if absent); split when assembled > 4% of window. Carries forward the implicit 8k-on-200k tuning.

**Opus literalism transformations** (`apply_literalism_rules(prompt)`):

1. Globs, not generalizations: replace "all API routes" → "all files matching `<explicit glob>`. Process each file independently and confirm each one."
2. Root cause appended to bugfix prompts: "Fix the ROOT CAUSE, not just the symptom. If the obvious fix is line-local, surface why and ask before patching only that line."
3. Exact filenames listed when known; if unknown, conductor invokes a research agent first.

### 5.4 Effort router (`lib/effort_router.py`)

The Agent tool exposes `model` override but **no `effort` override**. Effort routing is therefore *recommendation-based* via prompt tag, not mechanically enforced.

**Mapping rule:**

```
complexity 1-3  → effort=low    model=sonnet (or agent default)
complexity 4-6  → effort=medium model=agent default
complexity 7-8  → effort=high   model=opus
complexity 9-10 → effort=xhigh  model=opus
```

**Always-xhigh categories** (with complexity floor of 4 — see rationale below):

```
ALWAYS_XHIGH = {"security_audit", "schema_design", "root_cause_debug", "classification"}

def resolve_effort(category, complexity):
    if complexity < 4:
        return mapping[complexity]              # normal mapping wins for trivia
    if category in ALWAYS_XHIGH:
        return "xhigh"
    return mapping[complexity]
```

**Floor rationale.** The floor of 4 reflects an empirical heuristic: tasks at complexity 1–3 are mechanical regardless of category (`add nullable column`, `rename a constant`, `regex tweak`), and forcing xhigh on them wastes budget without quality gain. At complexity 4 and above, the category-specific risks (security blast radius, schema irreversibility, classification stickiness, debug regression) start dominating, and xhigh's cost is justified. This floor is **not load-bearing** — it can be tuned in `effort_router.py` via the `XHIGH_FLOOR` constant. Maintainers should re-examine it after observing real dispatches if calibration drifts.

**Honest framing in the conductor body:** `<effort-recommendation>` is probabilistic — the sub-agent reads the tag and self-adjusts thinking depth, but no harness mechanism forces extended thinking per dispatch. The deterministic lever the conductor controls is `model` override via the Agent tool.

### 5.5 What stays in the conductor body (not skills)

| Section | Why it stays in body |
|---|---|
| Three Prime Directives | Identity — must be in primary attention every turn |
| Hard Operational Limits | Referenced by hooks; cross-cutting |
| Gate state machine (Phase 0 / First Response / Phase 1+) | Referenced by hooks; cross-cutting |
| Phase-by-phase orchestration loop (with `→ invoke skill X` jumps) | Coordination layer — must always load |
| `## Compact Instructions` (Layer A) | Mandatory at top |
| v3/v4/v4.1/v5 changelog summary | Short reference; full detail in CHANGELOG.md |
| Inline dispatch wrapper invocation (delegates to `lib/dispatch_envelope.py`) | Single-line call site |
| §3.1 user-global read-only rule (one-paragraph summary) | Cross-cutting; must always load |

### 5.6 Verbosity controls

The conductor incorporates verbosity preferences from the user's `~/.claude/CLAUDE.md` via **read-only inheritance** — Claude Code's standard CLAUDE.md cascade already loads user-global into context for any session. The conductor does **not** scan, parse, modify, or supplement this file. If a user has output preferences set globally, sub-agents inherit them through the standard cascade. If not, the conductor uses defaults from the templated project-level CLAUDE.md (Layer B, §4.4) for projects where it has scaffolded.

**Removed from this revision:** the prior "Verbosity-default offer" in `install.sh` (§7.5 #1 in revision 1) is removed entirely. The installer does not scan or offer to edit `~/.claude/CLAUDE.md`. See §3.1.

## 6. Rollout — 4 phases, regression-signal gates

Each phase lands as a separate PR with its own plan-mode cycle (per the user's `superpowers-priority.md`). The user gates each phase before the next starts using observable regression signals — not time/session thresholds.

### 6.1 Phase A — Refactor (skills extraction)

**Touches:** `project-conductor.md`, new `skills/`, `install.sh`, `tests/test_user_global_readonly.py`.
**Behavior change:** None — pure content relocation + boundary tests.
**Risk:** Low.

**Files to read for regression signals:**
- `.conductor/decisions.md` (in any conductor session run after install)
- `.conductor/findings.md`
- `wc -l project-conductor.md` output

**Don't-promote patterns:**
- decisions.md row matching `skill not found, fell back to inline` — refactor regression (skill body missing or wrong path)
- decisions.md row matching `skill body parse error`
- findings.md row indicating behavior change between v4.1 and v5-A (this phase is supposed to be content-relocation, not behavior change)
- findings.md row matching `refusing to write under ~/.claude/` — boundary breach attempted (if this fires in Phase A, something is fundamentally wrong)
- `wc -l project-conductor.md` returns > 500 — refactor incomplete

**Looks-healthy example:**
- Conductor runs through Phase 0 → First Response → Phase 1 just like v4.1 (same prompts, same gates).
- decisions.md shows skill invocations succeeding (e.g., `invoked conductor-phase-0-discovery; completed in 2 turns`).
- Zero fall-back-to-inline rows over a real session.
- `wc -l project-conductor.md` returns 380–440.
- `pytest tests/test_user_global_readonly.py` passes (asserts no template path resolves under `~/.claude/`, asserts skill #7 procedure aborts on out-of-project target).

**Definition of done for Phase A:**
- All 7 skill files exist and pass smoke tests.
- Conductor body line count is in [380, 440].
- v4.1.1 → v5-A behavioral diff document at `docs/v5-a-behavioral-diff.md` asserts "no observable behavior change" with evidence (3 sample sessions side-by-side).
- `pytest tests/` green.
- §4.3 skills frontmatter syntax verification documented in FINAL_REPORT.

### 6.2 Phase B — Hooks (backstops)

**Touches:** `hooks/pre_*.py`, `hooks/post_*.py`, `hooks/stop_*.py`, `lib/conductor_state.py`, `install.sh` (extended).
**Behavior change:** New determinism on existing rules.
**Risk:** Medium — hook failure modes.

**Files to read:**
- `.conductor/findings.md`
- `.conductor/decisions.md`
- `.conductor/state.json`

**Don't-promote patterns:**
- findings.md row `hook X exited non-zero non-2` — runtime error in hook
- findings.md row `hook X expected to fire (block-case) but exited 0`
- decisions.md row `hook canary failed at install time` — install regression
- state.json `gate` or `phase` fields stuck (still `pre_first_response_proceed` after user said `proceed`) — state machine regression

**Looks-healthy example:**
- findings.md has at least one row per hook showing it fired with exit 0 in allow-cases.
- At least one row per PreToolUse hook showing it fired with exit 2 in block-cases (i.e., it actually caught something during a session).
- decisions.md shows install canary passed for all 6 new hooks.
- findings.md may include the tolerant-fallback row for `pre_lock_enforcement` (`no active-task.json::files_write[] yet (pre-Phase-D); not enforcing this session`) — this is expected and not a regression signal.
- No "hook silently broken" patterns over a real session.

**Definition of done for Phase B:**
- All 6 hooks installed and canary-passing.
- Each hook has at least one observed real-session firing recorded in findings.md.
- User-global write blocker tested via integration test (synthetic stdin with `~/.claude/skills/foo.md` target → exit 2).

### 6.3 Phase C — Scaffolding

**Touches:** `templates/`, `lib/template_render.py`, skill `conductor-scaffold-ai-director-os`, `install.sh`.
**Behavior change:** New opt-in capability — Phase 1 scaffold step.
**Risk:** Low (opt-in, gated by First Response offer).

**Files to read:**
- `.conductor/decisions.md`
- `.conductor/scaffold-payload.json`
- The scaffolded files in cwd (CLAUDE.md, .claude/*)

**Don't-promote patterns:**
- decisions.md row `scaffold collision: existing file` without a corresponding `.scaffold-suggestion.<ts>` next to it — collision policy didn't work
- ≥3 rows in one session matching `TODO marker for <field>` — spec is too thin OR enrichment broken
- Rendered files containing literal `{{VAR}}` — template render escaped wrong or var unmapped
- Two `.scaffold-suggestion.<ts>` files with identical content next to the same target — no-op re-scaffold writing duplicates
- Any `.conductor/scaffold-staging-<ts>/` directory persisting across sessions — atomic-write contract violated
- decisions.md row `scaffold target outside project` — boundary breach attempted

**Looks-healthy example:**
- Scaffolded CLAUDE.md (project-level) contains real values (no `{{VAR}}` literals; TODO markers only when legitimately missing).
- decisions.md has one row `scaffolded N files, M TODO markers` with `M ≤ 2`.
- Re-running scaffold against a project with existing CLAUDE.md produces `<target>.scaffold-suggestion.<ts>` files (single suffix, no recursion).
- `~/.claude/CLAUDE.md` is byte-identical before and after a scaffold run (sanity check — runtime never writes user-global).

**Definition of done for Phase C:**
- All 7 templates render correctly with sample-spec.md fixture.
- Atomic-write contract verified: forced mid-render failure leaves no partial files.
- User-global isolation verified: forced render with malicious payload (e.g., `PROJECT_NAME = "../../../.claude/CLAUDE.md"`) is rejected.

### 6.4 Phase D — Prompting + Compact Instructions

**Touches:** `project-conductor.md` (Compact Instructions, literalism rules), `lib/dispatch_envelope.py`, `lib/effort_router.py`.
**Behavior change:** Improved dispatch quality. Also: `pre_lock_enforcement.py` (from Phase B) becomes fully active because `<files-write>` is now populated into `active-task.json`.
**Risk:** Medium — changes prompt shape sub-agents see.

**Files to read:**
- `.conductor/evidence/` — captured dispatched-prompt logs
- `.conductor/findings.md`
- Sub-agent outputs

**Don't-promote patterns:**
- findings.md row `sub-agent failed to parse <task> tag` — envelope malformed
- Sub-agent outputs showing they wrote outside `<files-write>` declaration (Phase B `pre_lock_enforcement.py` should catch and log to findings.md)
- findings.md row `compact occurred, recovery from disk failed` — Compact Instructions not load-bearing
- A captured dispatched prompt where top `<task>` and bottom `Reminder:` are identical strings — `build_prompt()` regression
- findings.md row `pre_lock_enforcement: no active-task.json::files_write[] yet` AFTER Phase D lands — Phase D didn't actually populate the field

**Looks-healthy example:**
- Each Phase D dispatched task has a prompt envelope with all required elements (8 base; 9 when split — see §5.3).
- Top task ≠ bottom reminder.
- At least one task that should benefit from xhigh routes there per `effort_router` (visible as a row in decisions.md citing `effort=xhigh, model=opus`).
- `pre_lock_enforcement.py` enforces fully (no more tolerant-fallback rows).

**Definition of done for Phase D:**
- 5 captured dispatches in `.conductor/evidence/` show full envelope structure.
- `pre_lock_enforcement.py` blocks at least one out-of-declaration write attempt in real session (recorded in findings.md).
- Compact-instructions recovery rule exercised at least once (forced compaction during long session, verified state restoration).

### 6.5 Phase ordering

A → B → C → D. Phase A is risk-free warm-up. Phase B adds backstops where text rules already exist (with the documented Phase B/D dependency staging). Phase C is purely additive. Phase D changes prompt shape — riskiest, lands when everything else is stable, and completes the Phase B/D dependency.

The user makes the promotion call by reading the regression-signal files above. No automated time/session threshold.

## 7. Error handling, testing, maintenance

### 7.1 Error handling matrix

| Failure | Detection | Behavior | Surface |
|---|---|---|---|
| Hook script missing at install path | `install.sh` canary | Don't install that entry | decisions.md row + stderr at install time |
| Hook script runtime error (not exit 2) | Stderr non-empty + exit ≠ 0/2 | Treat as exit 0, log | findings.md row with hook name + stderr |
| Skill body file missing | Skill tool returns "skill not found" | Fall back to inline behavior with warning | decisions.md row noting fallback used |
| Template render KeyError on var | `template_render.render()` | Substitute `TODO: <fieldname>`, log | decisions.md row per missing var |
| `lib/template_render.py` itself crashes | Exception | Abort scaffold; do not partially write; remove staging dir | Surface to user with exact error; decisions.md row |
| Compact fires mid-scaffold | Next-turn recovery rule (§4.4); staging dir persistence | Read state.json, scaffold-payload.json, decisions.md; if `.conductor/scaffold-staging-<ts>/` exists, remove it (atomic-write principle) and re-run scaffold from scratch | One-line user notice on resume |
| State file corrupted (invalid JSON) | Read fails on every hook entry | `state.json.corrupt.<ts>` backup; refuse to proceed | Hard stop with reconstruction prompt |
| Sub-agent dispatched with malformed envelope | Agent returns error / nonsensical output | Conductor classifies as iteration (not hard-stop); retry with re-built envelope | findings.md row |
| Template path resolves under `~/.claude/` | `lib/template_render.py::render()` | Reject; abort scaffold | findings.md row + user-visible error |
| Hook attempt to write under `~/.claude/` at runtime | All `Write|Edit` PreToolUse hooks | exit 2 with stderr `"refusing to write under ~/.claude/ — user-global is read-only at runtime per §3.1"` | findings.md row |

**Three non-negotiables:**
1. Never silently fall back. Every fallback writes a `decisions.md` row.
2. Never partially write. Scaffold either writes all files (with TODO markers if needed) or none.
3. Never write under `~/.claude/` at runtime. The conductor agent has read access to user-global; only `install.sh` writes, only with explicit consent.

### 7.2 Testing strategy

**Unit tests** (`tests/` at repo root, pytest):

| Module | Tests |
|---|---|
| `lib/lock_check.py::path_within_declaration` | `src/api` ≠ `src/api-keys/x.ts` (segment-match regression); declared-dir matches subpath; trailing-slash equivalence |
| `lib/template_render.py::render` | Var substitution; missing var → `TODO: x`; nested var rejected; literal `{{` escaped; **target path under `~/.claude/` is rejected**; **target path with `..` traversal that resolves under `~/.claude/` is rejected** |
| `lib/dispatch_envelope.py::build_prompt` | Top `<task>` ≠ bottom `Reminder:`; ordering matches §5.3; long-context threshold uses window-relative split |
| `lib/effort_router.py::resolve_effort` | Always-xhigh below floor → mapping wins; complexity=4 in security category → xhigh; complexity=2 in schema category → low |
| `lib/conductor_state.py::validate_scaffold_delegate` | Missing skill → reject; missing tool → reject; both present → accept |

**Integration tests** (hooks, synthetic stdin):

- Each PreToolUse hook with allow-case (exit 0) and block-case (exit 2). 12 cases for 6 hooks.
- **User-global write blocker:** every `Write|Edit` PreToolUse hook fed a target under `~/.claude/` → exit 2 with the canonical stderr message. Run regardless of phase/gate.
- `post_output_quality.py` fed CSV with one all-empty column → expect findings.md row.
- `stop_validate_final_report.py` fed state with `phase=complete` + missing FINAL_REPORT → expect findings.md row.
- Universal no-op guard: every conductor hook fed a payload with no `.conductor/` → exit 0, no side effects.
- **Pre-Phase-D tolerant fallback:** `pre_lock_enforcement.py` with `active-task.json` missing `files_write[]` → exit 0 with single findings.md fallback row.

**Skill smoke tests:**

- `conductor-routing-rubric` against three reference tasks → expected route.
- `conductor-classification` against three reference issues → expected class.
- `conductor-scaffold-ai-director-os` thin payload (3 missing fields) → circuit-breaker stop. Complete payload → 7 files written, all rendered correctly. Malicious payload (e.g., var value containing `../../`) → render rejects.

**Boundary test (`tests/test_user_global_readonly.py`):**

- Assert no template in `templates/` resolves to a path under `~/.claude/` when rendered with realistic payload.
- Assert `lib/template_render.py::render()` rejects a payload that would cause output to land under `~/.claude/`.
- Assert `install.sh --dry-run` shows no writes to `~/.claude/CLAUDE.md`, `~/.claude/imports/`, or `~/.claude/settings.json` (only `~/.claude/skills/` and `~/.claude/agents/` with consent).
- Assert the conductor body's frontmatter does NOT declare any tool that would permit writing under `~/.claude/` at runtime.

**End-to-end fixture** (`tests/fixtures/sample-spec.md`): conductor against fixture in tmp dir. Assert state.json transitions; `.conductor/scaffold-payload.json` exists; 7 scaffolded files exist; CLAUDE.md (project-level) contains rendered `STACK` value; FINAL_REPORT.md has all required sections; `~/.claude/` is byte-identical to before the run.

**CI:** `.github/workflows/test.yml` runs `pytest tests/` on every PR. Phase A adds the workflow.

### 7.3 Few-shot example: `conductor-routing-rubric` body

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

### 7.4 Maintenance rules (`docs/maintenance.md`)

1. **Bidirectional skill threshold.** Promote inline content >10 lines + phase-specific → skill. Demote skill <30 lines + low invocation count → fold back into body.
2. **Conductor body line budget.** Target ≤450 lines. CI fails if `wc -l project-conductor.md > 500`.
3. **Hook canary on every install.** All 6 new hooks. `install.sh` exits non-zero on canary failure.
4. **Hook firing-and-runtime health.** Read `decisions.md` and `findings.md` across recent runs. Verify each hook (a) fired at least once when its trigger condition was present, AND (b) exited cleanly (no `findings.md` rows of `hook X exited non-zero non-2`). Both conditions checked — environment drift (Python version change, broken `$CONDUCTOR_HOOKS` after directory move) doesn't show up in firing alone.
5. **/memory audit.** Periodic review of `~/.claude/memory/` entries that reference the conductor — stale entries identified for *user* deletion (the conductor never deletes from user-global). Surviving discoveries promoted into the conductor body or a skill via PR.
6. **Spec drift detection.** When >30% of fields fill with `TODO:` markers across two consecutive sessions, surface "spec template may be drifting from current project shape — review `templates/.claude/prd/template.md`".
7. **User-global boundary check.** Quarterly: run `pytest tests/test_user_global_readonly.py` against latest main. Fails if any new component grew a write path into user-global. This is the spec's load-bearing invariant.

### 7.5 Installer hardening

`install.sh` extensions:

1. **Skills install location prompt.** Per §3.1.2: a single Y/n disclosure prompt before any `~/.claude/` write. Default Y (global install). Alternative modes: `n` (abort with notice), `--for-project <path>` flag (advanced — project-scoped skills only). The prompt is mandatory and visible; consent is explicit even when the default is accepted.
2. **Existing CLAUDE.md detection (project-scope only).** When the installer is invoked from within a project that has its own `CLAUDE.md`, warn (do not touch). Documents the `.scaffold-suggestion` collision policy will engage at scaffold time. The installer NEVER reads or touches `~/.claude/CLAUDE.md`.
3. **v4.1 → v5 state migration.** Once-only: read existing `.conductor/state.json` if present; add `gate` (default `post_first_response_proceed` for in-flight) and `scaffold_written` (default `false`). Backup original to `.conductor/state.json.v4.1.bak`. Project-scope only.
4. **Idempotency.** Re-running with no changes is silent no-op.
5. **Hook canary.** Per §5.2, all 6 new hooks tested with synthetic stdin allow/block cases. Failure → hook not installed, decisions.md row.
6. **User-global footprint disclosure.** At install time, before any `~/.claude/` write, the installer prints exactly what it will write and asks Y/n: `"This will copy 7 skill files to ~/.claude/skills/ and project-conductor.md to ~/.claude/agents/. No other files under ~/.claude/ will be modified. Proceed? [Y/n]"`. Default: **Y** (see §3.1.2 for rationale). Consent is explicit; the prompt is mandatory and visible.

**Removed from this revision:** the prior "Verbosity-default offer" (revision 1, §7.5 #1) is removed. The installer does not scan or offer to edit `~/.claude/CLAUDE.md`. See §3.1 and §5.6.

### 7.6 Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Hook silently doesn't fire (settings.json syntax error) | Medium | Hook canary at install time + firing-and-runtime health check (7.4 #4) |
| Hook silently broken by post-install environment drift | Medium | Firing-and-runtime health check explicitly verifies exit success, not just firing (7.4 #4) |
| Skill body becomes stale relative to body's invocation point | Medium | Bidirectional threshold rule + line-budget CI (7.4 #1, #2) |
| Templated CLAUDE.md (project-level) drifts from current Claude Code best practices | High over time | Templates dated; quarterly review; source-of-truth is `templates/` in repo |
| Scaffold writes wrong content for an unfamiliar stack | Medium | Thin-spec circuit-breaker (≥3 missing fields → pause); user can edit templates locally |
| Sub-agent ignores `<effort-recommendation>` tag | High (probabilistic) | Honest framing in §5.4; conductor falls back to model override (deterministic) |
| User edits scaffolded files, loses changes on re-scaffold | Low (collision policy) | `.scaffold-suggestion.<ts>` never overwrites; user diffs and merges manually |
| Phase D dispatch envelope changes break user's existing custom sub-agents | Medium | XML envelope is purely additive — sub-agents that ignore tags still work |
| Conductor accidentally writes to user-global | Low (multi-layer prevented) | §3.1 boundary; hook-level write blocker; template-render path validation; integration test; quarterly boundary check (7.4 #7) |
| Phase B hook depends on Phase D state shape (circular) | Resolved | Tolerant fallback in `pre_lock_enforcement.py` documented in §5.2; Phase B "looks-healthy" includes the fallback row |
| Skills frontmatter syntax has changed in Claude Code | Medium | §4.3 verification step required before Phase A lands; FINAL_REPORT documents what was checked |

### 7.7 Backward compatibility

- CLI surface (`status`, `proceed`, `permissions yes`, `approve enrichments`, etc.) — unchanged.
- Existing `.conductor/` state files — migrated by installer with backup.
- Existing 2 hooks (heartbeat, usage_limit_wakeup) — untouched.
- `--strict-mode` flag — preserved.
- Existing optional bundles — preserved.
- v3/v4/v4.1 mechanisms in body — preserved (relocated where they cross the 10-line threshold).
- **User's `~/.claude/` directory — never modified after install (§3.1).**

## 8. Open follow-ups (post-this-spec)

- **Full pack scaffold:** auto-populated `.claude/architecture.md` from spec enrichment, stack-detected `security-checklist.md`, auto-generated specialist subagents under the project's `.claude/agents/` (project-scope). Out of scope here.
- **CI/CD integration for the conductor itself:** GitHub Action that runs the conductor against PR descriptions. Out of scope.
- **Routines for the conductor's own runtime** (vs. its maintenance): scheduled re-runs of in-flight builds. Out of scope.
- **Auto-migration of in-flight v4.1 sessions:** users finish those on v4.1, then upgrade.
- **User-global capability surfacing:** a future enhancement could surface to the user "your `~/.claude/agents/` contains X, Y, Z which would help with this task — consider running them" — this is purely informational and does not violate §3.1. Deferred.

## 9. Appendix — manual sections this spec implements

| Manual section | Implementation |
|---|---|
| §1 Context window mechanics | Layer A Compact Instructions (§4.4); state-on-disk recovery rule |
| §1 Size discipline | §4.1 repo layout; skills extraction; ≤450-line conductor body |
| §1 Skills vs Rules vs CLAUDE.md vs Hooks | §5.1 + §5.2; 7 skills + 6 hooks |
| §1 Sub-agent inheritance | §4.3 delegation contract; §5.2 gate inheritance documented |
| §2 XML tags | §5.3 dispatch envelope |
| §2 Long context positioning | §5.3 element ordering + window-relative split |
| §2 Few-shot prompting | §5.1 skill #3 + #4; §7.3 example |
| §2 Effort levels | §5.4 effort_router with honest framing |
| §2 Opus literalism | §5.3 `apply_literalism_rules()` |
| §3 CLAUDE.md hierarchy and `## Compact Instructions` | §4.4 two-layer; §5.6 verbosity inheritance |
| §3 Hooks as deterministic layer | §5.2 + §7.6 risk matrix |
| §6 AI Director's OS | §4.1 templates/; §5.1 skill #7 |
| §7 Routines | §7.4 #4 firing-and-runtime health (scheduled, separate from this spec's main delivery) |

## 10. Revision history

| Rev | Date | Changes |
|---|---|---|
| 1 | 2026-05-05 | Initial design |
| 2 | 2026-05-05 | Added §3.1 user-global read-only boundary as load-bearing architectural rule. Removed §7.5 #1 "Verbosity-default offer". Rewrote §5.6 to read-only inheritance only. Added user-global write blocker to all `Write\|Edit` PreToolUse hooks (§5.2). Added template-render path validation (§4.2, §5.1, §7.2). Added `tests/test_user_global_readonly.py` (§4.1, §7.2). Added atomic-write contract for scaffold (§4.2, §5.1, §7.1). Resolved Phase B/D circular dependency with tolerant-fallback pattern (§5.2, §6.2). Added skills frontmatter syntax verification step (§4.3, §7.6). Added effort-router floor rationale (§5.4). Converted §5.5 to table format. Added Definition of Done per phase (§6.1–6.4). Added §7.4 #7 quarterly user-global boundary check. Added §7.5 #6 user-global footprint disclosure. Added §3.1 row to risk matrix (§7.6). Added §3.1 row to backward compatibility (§7.7). |
| 3 | 2026-05-05 | Skills install default flipped from project-scoped (rev 2) to global (rev 3) with explicit consent. §3.1.2 rewritten to describe a single Y/n disclosure prompt with default Y; the (b)/(c) options from rev 2 became `--for-project` flag and `n` answer respectively. §5.1 + §7.5 #1 + §7.5 #6 updated for consistency. **Boundary unchanged**: explicit consent step preserved; what changed is the recommended default answer. Rationale: agent file is global, skills are functionally paired with agent, project-scoped skills would contradict "works in any project" value prop. |
