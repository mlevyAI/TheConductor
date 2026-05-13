# Changelog

All notable changes to Project Conductor are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

> **Note on version numbers:** the public release version (1.0.0 → 4.0.0) is aligned with the internal agent-prompt narrative version (v3 → v4) starting with this release. v4.0.0 jumps the public number forward to match.

---

## [6.1.1] — 2026-05-12

Closes two ordering leaks that let the conductor begin Phase 1 work before the user replied `proceed`, and bypass the spec-splitter via paginated reads. Both observed in real sessions on specs larger than 300 lines; both invisible to the runtime hooks because the hooks deliberately allow `Read` with `limit ≤ 500` as a safety valve for unrelated long documents.

**Why.** v6's replayability + cost model assumes the project spec is *never* loaded into the conductor's main context in full — only the relevant part-file plus the global header is. When the conductor reads a 1500-line spec in three `limit=500` chunks "to populate the First Response analysis fields," it dumps ~25k tokens of spec into every subsequent dispatch envelope's enclosing context. The bypass is silent: the existing `pre_spec_split_enforce.py` hook permits paginated reads (intentional — it must not block reading `CHANGELOG.md`, plugin docs, etc.), so the leak shows up only as elevated per-task token cost.

The runtime hook fence stays as-is (broadening it would harm legitimate uses elsewhere). The fix is at the prompt-instruction layer where it belongs.

### Changed

- **`project-conductor.md` Hard Gate** — adds an explicit "NO `Read` calls against the project spec body" bullet to the pre-`proceed` constraint list, plus a clause that paginated reads (`limit ≤ 500`) do NOT exempt the project spec. The `Allowed while waiting` line is amended to exclude the project spec body. Phase 1 fields in the First Response remain `[pending Phase 1]` per `conductor-first-response` §Procedure step 4 — the gate does not need spec analysis to render.
- **`project-conductor.md` Phase 1 opening** — renames `**Large-spec check (before enrichment):**` to `### 🛑 First action of Phase 1 (HARD ORDERING)` and rewrites the branching language to be unambiguous: `wc -l` is the literal first action, > 300 lines triggers `conductor-spec-splitter` IMMEDIATELY, and the rest of the session reads part files instead of the original spec. Adds two new paragraphs — "Why the strict ordering matters" (quantifies the ~25k-token cost regression) and "Pagination is NOT an escape hatch for the project spec" (closes the rationalization path the prior wording left open).

### Unchanged

- All 9 enforcement hooks under `hooks/`, including `pre_spec_split_enforce.py`. The `limit ≤ 500` escape hatch stays because it serves non-spec long documents.
- `conductor-spec-splitter` skill — unchanged. Its trigger contract was already correct; the conductor body just wasn't honoring it consistently.
- `conductor-first-response` skill — unchanged. The `[pending Phase 1]` placeholder semantics were already documented; the conductor body now matches them.
- All other skills, agents, libs, tests, `install.sh`, `README.md`.

### Migration

None required. Existing installs benefit automatically on next session (the agent body is re-read each time). Users who pinned an old `~/.claude/agents/project-conductor.md` can re-run `install.sh` to update.

### Repro of the failure mode this fixes

Spec: any project spec > 300 lines. Invoke the conductor. Pre-v6.1.1 observed sequence:

1. Phase 0a auto-installs enforcement hooks.
2. Phase 0 discovery runs.
3. **Without rendering the First Response**, the agent issues 3–4 paginated `Read` calls against the spec (offset 1/limit 120, then offset 120/limit 500, …) to populate Phase 1 analysis fields.
4. The `limit ≤ 500` paginations slip past `pre_spec_split_enforce.py`.
5. `.conductor/state.json`, `decisions.md`, `status.md` are written before the user has replied `proceed`.

Post-v6.1.1: step 3 is forbidden by the prompt; the conductor renders the First Response with `[pending Phase 1]` and waits. Step 4 is forbidden by the new "pagination is not an escape hatch" clause; step 5 still happens (writes under `.conductor/` are explicitly allowed pre-gate) but no longer carries spec content into context.

---

## [6.1.0] — 2026-05-10

Adds **cross-session self-learning** to the optional `agent-monitor/` bundle. Per-project, purely local, opt-in via the bundle install (no new consent step). Complements — does not replace — the existing `.conductor/` resume layer.

**Why.** The conductor already remembers *the work* across sessions (`state.json`, `decisions.md`, `evidence/`, `plan.md`). It does not remember *its own behavioral mistakes*. Result: an agent that tripped probe sprawl in three sessions on the same project would, on session four, have no signal that it has a tendency to do so. v6.1.0 closes that gap with a tiny cross-session memory + a SessionStart advisory.

**What this is NOT:**
- Not a resume feature (resume is `.conductor/state.json` etc., already shipping).
- Not learning your codebase or domain — it tracks 5 *meta-behavior* anti-patterns only.
- Not cross-project — each project has its own `memory.json`. A pattern in project A never bleeds into project B.
- Not telemetry — nothing is uploaded; `memory.json` contains pattern_ids + counts + timestamps only (no paths, commands, prompts, or project names).

### Added

- **`agent-monitor/selflearn.py`** — new SessionStart hook (~150 lines). Reads `memory.json`, computes the top-N recurring anti-patterns, formats a short advisory, emits it as `hookSpecificOutput.additionalContext` per the Claude Code SessionStart hook protocol, and writes `last_injection.md` so the next reporter run can show what was applied. Hard-capped at top 5 patterns / ~300 tokens (1200 chars). Always exits 0; failures log to `hook-errors.log`. Honors `selflearn.disabled` flag file (touch to disable injection without losing memory).
- **`agent-monitor/reporter.py` cross-session memory** — new functions `load_memory()`, `update_memory()`, `read_last_injection()`, `format_injection_section()`. Schema versioned (`schema_version: 1`); incompatible schemas archive to `memory.json.vN.bak` and start fresh rather than auto-migrating. Atomic writes (tempfile + os.replace).
- **`agent-monitor/reporter.py` "Self-learning context applied this session" section** — when the previous SessionStart injected advisory context, the next per-session report shows the exact text near the top, so the user can audit why the agent was steered toward/away from a pattern.
- **Pattern IDs on detector findings** — each finding from `detect_patterns()` now carries a stable `id` (`probe_sprawl`, `busy_wait`, `repeat_bash`, `no_forward_progress`, `scope_shrink`). Memory aggregates by these IDs. Display unchanged.
- **`agent-monitor/example-settings.json`** — `SessionStart` array now wires both `logger.py` AND `selflearn.py` (logger continues to log every event; selflearn injects advisory context on cold/warm start).
- **`tests/test_selflearn.py`** (19 tests) — covers cold start (no memory → no injection), single-pattern injection, ordering by hits, top-N cap, unknown-pattern-id skip, `.disabled` flag suppression, corrupted/wrong-schema/list-shaped memory recovery, atomic write, rolling window pruning across `update_memory` calls, and the reporter's `read_last_injection` consume-and-clear semantics.

### Changed

- **`agent-monitor/README.md`** — new "Cross-session memory (self-learning)" section describing the schema, window, cap, disable flag, and reset path. Output section gains the new "Self-learning context applied this session" item. Install instructions updated to reflect the second SessionStart entry and the third permission allow rule. Gitignore guidance adds `memory.json`, `last_injection.md`, `selflearn.disabled`, and `hook-errors.log` (so neither memory nor diagnostics leak via `git add .`).
- **`README.md`** — Optional bundles row for `agent-monitor/` updated to describe the cross-session self-learning capability (replacing the previous "planned input for a future loop" text). New "In-session features" section (separate from this changelog entry) catalogs every user-facing trigger (`proceed`, `approve enrichments`, `permissions yes A/B/C`, `install 1,2,3 from /path`, `skip bundles`, `status`, `show progress`, `continue` / `pause` / `wrap-up`, `key added` / `skip`, plus the auto-enforced boundaries).
- **`README.md` Session resumption** — adds a one-paragraph clarification distinguishing resume (work state, via `.conductor/`) from self-learning (behavioral memory, via `agent-monitor/`). They complement each other; neither replaces the other.

### Unchanged

- `agent-monitor/logger.py` — fully unchanged. The `activity.jsonl` format is unchanged so existing reports keep working.
- `project-conductor.md` — unchanged. Self-learning is bundle-only, not part of the conductor's hard rules. The agent receives the advisory as context but is not bound by it (the prompt's hard stops still take precedence).
- `install.sh` — unchanged. The bundle install path (offered in conductor's First Response) carries the new SessionStart wiring through `agent-monitor/example-settings.json` automatically.
- All 9 enforcement hooks under `hooks/` — unchanged.

### Tunables

In `agent-monitor/selflearn.py`:
- `MAX_PATTERNS = 5` — top-N patterns to surface in the injection.
- `INJECTION_CHAR_BUDGET = 1200` — ~300 tokens.
- `PATTERN_ADVICE` dict — one-line "avoid" message per pattern_id. Edit to tune wording.

In `agent-monitor/reporter.py`:
- `MEMORY_WINDOW_SIZE = 20` — rolling session window.
- `MEMORY_SCHEMA_VERSION = 1` — bump if schema changes; old files archive automatically.

### Migration

None required. Existing `agent-monitor/` installs continue to work; the new SessionStart entry only takes effect after you copy the updated `example-settings.json` (or manually add the second SessionStart `command` entry). On first session after upgrading: no injection (cold-start memory). After ~2 sessions with detections: injections begin.

### Notes

- **Bug-fix vs feature classification.** This is a minor (`6.1.0`) because it adds a new agent-visible behavior (advisory context at SessionStart). The opt-in surface is unchanged — same bundle, same install path.
- **What it does NOT do.** It does not modify the conductor's runtime rules, does not auto-tune detector thresholds, does not store any user-confirmed labels (false-positive marking), does not share state across projects, and does not let the agent write to `memory.json` directly. All four are deliberate scope cuts; user-label support is the most likely follow-up.
- **The reporter's memory write is best-effort.** If `update_memory()` fails for any reason, the report is still saved and the activity log is still rotated. Corrupted memory recovery is silent: load returns empty memory, the next session's update writes a fresh file.

---

## [6.0.4] — 2026-05-10

Reframes the contribution model and the role of `agent-monitor/`. No behavior change to the conductor itself; this release is documentation + one code removal in `agent-monitor/reporter.py`.

**Why.** The previous "share your monitor reports" contribution path put a high redaction burden on contributors (every Bash cwd, every Read path) and asked them to do something no comparable OSS project (VS Code, React, Next.js, Kubernetes, Rails, Vite, Astro) asks for: paste raw runtime telemetry into public issues. The structured 5-field template helped, but most users would still bounce on the redaction step or skip the form. The valuable signal — narrative description of a failure mode — was already covered by the existing PR-description format. So we drop the share-footer flow entirely and re-anchor contribution on the standard issue/PR pattern that mainstream OSS uses.

`agent-monitor/` itself stays. Its job is now scoped clearly: **personal after-action review today, foundation for future local self-learning tomorrow.** The `activity.jsonl` and `report_*.md` formats are unchanged so a future SessionStart hook can read past reports and inject anti-pattern context for the agent to avoid repeating its own mistakes — without anything ever leaving the user's machine.

### Removed

- **`agent-monitor/reporter.py` `share_footer()` function and its call site in `generate_report()`.** Reports no longer end with a GitHub issue URL template, the 5-field contribution form, or the redaction checklist. Reports are now purely local artifacts.
- **`CONTRIBUTING.md` "Sharing your monitor reports" section** (the v4.0.1 5-field template description, the "What makes a useful monitor report contribution" list, and the redaction checklist). The contribution path is now the standard issue + PR flow.

### Added

- **`.github/ISSUE_TEMPLATE/bug_report.md`** — standard bug-report template modeled on the conventions used by Next.js, Vite, and similar repos: what you ran, what happened vs. expected, a *small* minimal reproduction (with explicit guidance not to paste full agent-monitor reports or `activity.jsonl` dumps), environment, optional hypothesis.
- **`.github/ISSUE_TEMPLATE/feature_request.md`** — feature / new-detector template with a dedicated "If proposing a new agent-monitor detector" section that asks for the pattern as a counter or regex.
- **`.github/ISSUE_TEMPLATE/config.yml`** — disables blank issues, points open-ended questions to Discussions.
- **`CONTRIBUTING.md` "A note on agent-monitor reports"** — explicit statement that the bundle is a local debugging tool, reports are not for upstream, and contributors should quote small excerpts (not raw dumps) when describing a failure.

### Changed

- **`agent-monitor/README.md`** — opening reframed: "Purely local — nothing leaves your machine." New "What it's for" section names the two uses (personal after-action review; foundation for future local self-learning). The "Contributing back" section is replaced with "Suggesting new detectors" pointing to `CONTRIBUTING.md`. The "Output" section no longer mentions a share footer.
- **`agent-monitor/reporter.py` module docstring** — removed v4 historical framing; now states the report format is the foundation for a future local self-learning loop (SessionStart context injection from past reports).
- **`README.md` Optional bundles table** — `agent-monitor/` row no longer mentions an opt-in share-footer or GitHub issue URL template. Now describes the bundle as a local after-action artifact and signals the future self-learning use of the same format.
- **`CONTRIBUTING.md`** — streamlined. New "How to file an issue" section points at the templates and explicitly tells contributors to quote small excerpts rather than paste full reports. PR description format unchanged in spirit but tightened ("smallest excerpt" wording for evidence).

### Unchanged

- `agent-monitor/logger.py` — unchanged. The on-disk data format (`activity.jsonl`) is preserved so a future self-learning loop can consume it.
- `agent-monitor/example-settings.json` — unchanged. The hook wiring (SessionStart / PreToolUse / PostToolUse / Stop) is the same.
- `install.sh` — unchanged. The bundle install path (offered in conductor's First Response, walked through with sanity-test) is unaffected.
- `project-conductor.md` — Optional Bundles Offer wording unchanged. The bundle is still offered as `(1) agent-monitor/`.
- All 9 enforcement hooks under `hooks/` — unchanged.

### Migration

None required. If you previously had `agent-monitor/` installed, your existing reports keep working — only newly-generated reports from this version onward will lack the share footer. No settings.json or permissions change is needed. `activity.jsonl` format is unchanged.

### Notes

- **No data was ever uploaded by `agent-monitor/`** — the share-footer was a URL template only. Privacy posture is unchanged in practice; this release just removes a flow that wasn't being used productively and was setting users up to leak paths if they followed it without careful redaction.
- **Future self-learning:** the natural next step is a SessionStart hook that reads the last N reports from `.claude/agent-monitor/reports/` and injects "your last 3 sessions tripped probe sprawl — avoid throwaway research files this run" into the agent's context. Today's report format is exactly the right input for that. Out of scope for this release.

---

## [6.0.3] — 2026-05-08

Four changes that close the operational loop on v6 — and one architectural amendment to §3.1 to make Layer 4 enforcement actually work:

1. **Phase 0a — first-session auto-install of all 9 enforcement hooks.** Previously the conductor would describe the Phase B + v6 hooks in a "bundles offer" and wait for the user to reply `install 1,2,3,4,5`. In practice users skipped or partially accepted, leaving prompt-only rules without hook-level enforcement. v6.0.3 makes the 9 enforcement hooks auto-install on first conductor session in a project — no user prompt, they're part of the conductor's operational identity.
2. **Optional Bundles Offer reduced to 3 items.** Now offers only (1) `agent-monitor/`, (2) `hooks/heartbeat.py`, (3) `hooks/usage_limit_wakeup.py` — the monitoring/recovery hooks that legitimately warrant explicit consent (they observe tool calls + record activity).
3. **`install.sh` skill-count constants removed.** The installer hardcoded "7 skills" in three places plus a numeric `-ne 7` guard. With 8 skills present since v5-D the guard fired a spurious warning every run. v6.0.3 removes all hardcoded counts; the installer operates on whatever `conductor-*/` skills are present.
4. **Layer-4 enforcement: `bootstrap_phase_0a.py` SessionStart hook + install.sh Step 8.** The Phase 0a description in (1) above is prompt-only — if the agent skipped Phase 0a, no hook caught it (chicken-and-egg: hooks weren't installed yet). v6.0.3 closes this with a SessionStart hook wired ONCE in user-global `~/.claude/settings.json` by `install.sh` (with separate Y/n consent). On every Claude Code session start, the bootstrap hook checks if it's a conductor session (multi-signal heuristic: existing `.conductor/`, payload mention of `project-conductor`, existing enforcement hooks reference, or `spec.md` + `CLAUDE.md` naming the conductor). If yes AND the 9 hooks aren't already wired in `<project>/.claude/settings.json`, it auto-installs them via `lib.hooks_manifest.render_settings_block(["phase_b", "v6_replayability"], ...)` and `render_permissions(...)`. Conservative no-op for non-conductor sessions. Idempotent. Atomic JSON merge. Logs to `<project>/.conductor/decisions.md`.

### Added

- **`hooks/bootstrap_phase_0a.py`** — SessionStart hook (Layer 4). 200 lines. Conservative multi-signal detection (4 signals must align before acting). Atomic JSON merge into `<project>/.claude/settings.json`. Preserves user-authored entries. Logs to `decisions.md`. Catches all exceptions and exits 0 (never blocks Claude Code).
- **`hooks/MANIFEST.json` `bundle: bootstrap`** — new bundle category for the SessionStart hook (separate from `phase_b`/`v6_replayability` because it's user-global, not per-project).
- **`install.sh` Step 8** — new step at end of installer: separate Y/n consent ("Wire the SessionStart bootstrap entry?"), inline Python heredoc for atomic JSON merge of `~/.claude/settings.json`, idempotent (detects duplicate command), preserves all other settings.json keys.
- **`project-conductor.md` Phase 0a section** — runs before Phase 0 when `.conductor/state.json` is absent. Documents the bootstrap-hook-driven install path and the 4-layer enforcement chain (prompt → test → skill → SessionStart hook).
- **`hooks/README.md` rewrite** — documents both install paths (Layer 4 auto vs opt-in bundles), shows the full hook inventory in tables, includes `Removing the auto-installed enforcement hooks` section per the user choice "always install, document removal".
- **`tests/test_bootstrap_phase_0a.py`** (15 tests) — covers conservative no-op for non-conductor sessions, each detection signal in isolation, idempotency under repeated invocation, settings.json merge preservation, JSON corruption recovery, "always exit 0" failure-safety, the spec-md-alone-doesn't-trigger negative case.
- **`tests/test_prompt_phase_0a.py`** (12 tests) — pin the prompt contract: Phase 0a section exists, runs before Phase 0, references manifest + render, documents removal; bundles offer no longer mentions (4) or (5); install command reads `install 1,2,3`; `hooks/README.md` references Phase 0a + MANIFEST.json + removal path.
- **`tests/test_installer_skill_count.py`** (4 tests) — pin the installer: forbid `7 skill directories` / `-ne 7` strings (and inverse `8`/`-ne 8`); every `conductor-*/` directory has a SKILL.md; the empty-skills error path still exists.
- **`tests/test_v6_e2e_integration.py::test_full_conductor_session_writes_all_state_files`** — comprehensive lifecycle test that creates EVERY state file the conductor writes during a real session.

### Changed (§3.1 amendment)

- **`project-conductor.md` §3.1** — installer-write scope amended to permit ONE SessionStart entry in `~/.claude/settings.json`, with explicit Y/n consent at Step 8, structurally enforced by the new `test_install_sh_settings_json_writes_only_bootstrap_entry` test. The runtime read-only contract for the agent itself is unchanged.
- **`tests/test_user_global_readonly.py`** — `~/.claude/settings.json` removed from `FORBIDDEN_WRITE_TARGETS` and added to `ALLOWED_WRITE_TARGETS`. Two new structural tests: `test_install_sh_settings_json_writes_only_bootstrap_entry` (asserts the Step 8 PYEOF block touches `hooks.SessionStart` only, never clobbers `model`/`env`/`permissions`) and `test_install_sh_bootstrap_entry_is_idempotent` (asserts dedup logic is present).

### Changed

- **`install.sh`** — line 3, 67, 172 strings de-numerified ("7 skill directories" → "all conductor-*/ skill directories" etc.). Lines 176-178 (the `-ne 7` warning block) removed entirely. The empty-case error at line 170-174 preserved.
- **`project-conductor.md` Optional Bundles Offer** — three opt-in bundles (was five). The auto-install of (4) and (5) is now in Phase 0a.

### Why "always install, no prompt"

Asking "do you want enforcement?" is functionally asking "do you want the conductor to do its job?" The user signed up for that by invoking the conductor. The previous opt-in flow added friction without adding meaningful choice — in practice it produced a population of conductor sessions running prompt-only rules without the hook safety net. v6.0.3 takes the position: enforcement is part of the contract; if you want the conductor without enforcement, edit `settings.json` to remove the hooks (one-time, persistent, not session-by-session).

### Migration

- Existing projects that already accepted bundles 4+5 manually: nothing changes; the auto-install path detects existing entries via `lib.hooks_manifest` and is idempotent.
- Existing projects that declined bundles 4+5: on the next conductor session, Phase 0a will auto-install the 9 enforcement hooks. No prompt. Documented removal path is editing `settings.json` directly.
- New projects: Phase 0a runs on first session, before any source-file work. Adds ~2 seconds + a canary `git status`.

### Enforcement chain (4 layers, post-v6.0.3)

| Layer | What it does | Active? |
|---|---|---|
| 1. Prompt-level | `project-conductor.md` § Phase 0a describes the auto-install | ✅ always |
| 2. Test-level | `test_prompt_phase_0a.py` pins the prompt contract | ✅ in CI |
| 3. Skill-level | (would be the conductor-phase-0-discovery skill performing the install) | ❌ not done — would violate skill's read-only contract |
| 4. Runtime hook | `bootstrap_phase_0a.py` SessionStart hook in user-global ~/.claude/settings.json | ✅ active when install.sh Step 8 was Y |

Layers 1+2+4 give bulletproof enforcement when the user accepted Step 8 at install time. If they declined Step 8 (or use `--force` without it), enforcement drops to prompt-only — documented as the manual fallback path. The bootstrap hook is the *only* component that crosses the §3.1 boundary, with explicit consent and structurally limited scope (single SessionStart entry, JSON-merge only).

### Tests

373 total (358 → 373; +15 from `test_bootstrap_phase_0a.py`). 100% passing. Hook precedence table from v6.0.2 still holds — the new auto-install path uses the same `render_settings_block` that v6.0.2 introduced.

---

## [6.0.2] — 2026-05-08

Closes the integration loop on v6: turns the bundles offer from prose into a structured artifact, adds the v6 hooks to the install path, and ships an end-to-end test that walks a spec from submission through replay to prove all 9 hooks compose without overriding each other.

### Added

- **`hooks/MANIFEST.json`** — single source of truth for every conductor hook. Each entry carries `name`, `event` (PreToolUse/PostToolUse/Stop/SessionStart), `bundle` (`phase_b`/`v6_replayability`/`monitoring`/`recovery`), `blocking` (bool), `since_version`, and `description`. Adding a new hook is now: drop the file in `hooks/`, add the entry, ship — no other code changes.
- **`lib/hooks_manifest.py`** — typed loader + settings generator. `load_manifest()` validates schema; `list_hooks(bundle=...)` filters; `render_settings_block(["phase_b", "v6_replayability"], hook_dir=...)` returns a dict ready to merge into `.claude/settings.json`; `render_permissions(...)` returns the `Bash(...)` allow strings; `validate_against_disk()` cross-checks the manifest against actual files in `hooks/`. Blocking hooks correctly omit `async`; advisory hooks set `async: true`. Output event order is deterministic.
- **`tests/test_hooks_manifest.py`** (26 tests) — schema validation, bundle membership invariants ("phase_b has exactly 6 hooks", "v6_replayability has exactly 3", "blocking hooks are PreToolUse only"), `validate_against_disk` round-trip.
- **`tests/test_v6_e2e_integration.py`** (5 tests) — end-to-end simulation of the v6 lifecycle: pre-`proceed` gate blocks mutations + spec read; `proceed` opens gate but spec-split-enforce still blocks the spec; splitter unblocks; coverage criteria registered (0/2 → 1/2 after first task completes); `pre_lock_enforcement` allows declared writes and blocks rogues; `record_files` + `decisions.append_decision` + `debug_map.upsert_feature` produce a coherent evidence trail; Stop hook is silent when complete, flags incomplete tasks correctly; replay reads back the original envelope verbatim.

### Changed

- **`project-conductor.md` "Optional Bundles Offer"** — adds bundle (5) "v6 replayability hooks" to the offer text. Install command updated to `install 1,2,3,4,5`. Install procedure now references `lib/hooks_manifest.render_settings_block()` instead of "build hook block + permission entries" prose. Version summary mentions the manifest + e2e test.

### Why this matters

v6.0.0 added the libs, v6.0.1 added the hooks, but the hooks weren't in the install offer text — meaning the conductor would describe v6 features at runtime without enabling the deterministic enforcement. v6.0.2 closes that loop. The e2e test is the proof: a developer can read `tests/test_v6_e2e_integration.py` top-to-bottom and see exactly what happens when a spec lands, including which hooks fire at which transitions and why none of them step on each other.

### Hook precedence (documented, verified by e2e test)

In normal Phase 2 execution with `state.gate == post_first_response_proceed`:

| Tool call                            | Which hook owns it                            |
|--------------------------------------|-----------------------------------------------|
| `Read(small file)`                   | none (all no-op)                              |
| `Read(spec.md, no manifest, full)`   | `pre_spec_split_enforce` BLOCKS               |
| `Read(spec.md, paginated limit≤500)` | none (allow)                                  |
| `Write(declared file)`               | none (`pre_lock_enforcement` allows)          |
| `Write(undeclared file)`             | `pre_lock_enforcement` BLOCKS                 |
| `Write(under ~/.claude/)`            | `pre_first_response_gate` / `pre_lock_enforcement` / `pre_phase0_readonly` all BLOCK (defense-in-depth) |
| `Bash("until ...; do sleep")`        | `pre_busy_wait_block` BLOCKS                  |
| `Bash(git commit)`                   | none (allow); evidence recording happens after |
| Stop event                           | `stop_validate_final_report` + `stop_evidence_completeness_check` both run; both advisory |

There is **one intentional precedence boundary** documented in the test: `pre_lock_enforcement` will block a `Write` to `.conductor/evidence/tasks/<id>/` if that path is not in the active task's `files_write[]`. This is by design — evidence is written via `lib.evidence.*` (Python imports), not via the `Write` tool. If you need to write evidence files via `Write`, add them explicitly to `files_write[]` in `active-task.json`.

### Not changed

- Existing v3/v4/v5 behavioral rules are unchanged.
- v6.0.0 lib API (`lib/evidence.py`, `lib/coverage.py`, `lib/decisions.py`, `lib/debug_map.py`) unchanged.
- v6.0.1 hooks unchanged.
- `install.sh` flow for `~/.claude/agents/` and `~/.claude/skills/` unchanged. Only the runtime bundles offer is affected.

---

## [6.0.1] — 2026-05-08

Adds two hooks that close enforcement gaps left in v6.0.0. The "every task is replayable" promise was previously prompt-only — agents that skipped the splitter step or forgot to record commit SHAs created silent debt that only surfaced months later when a developer needed to debug. v6.0.1 makes both deterministic.

### Added

- **`hooks/pre_spec_split_enforce.py`** (PreToolUse, **BLOCKING**) — exits 2 when an agent attempts to `Read` a spec-shaped file > 300 lines without `.conductor/spec-parts/manifest.json` present. Closes a measurable Claude-degradation path: monolithic specs read in full bury the relevant section. Heuristic for "spec-shaped": filename matches `spec*.md`, `requirements*.md`, `prd*.md`, `*.spec.md`, OR path contains `/specs/` segment. Excluded: `README.md`, `CHANGELOG.md`, `project-conductor.md`, `*.test.md`, paths under `.conductor/`, `.git/`, `node_modules/`. Paginated reads (`limit ≤ 500`) explicitly allowed. Opt-out marker `.conductor/.spec-split-skipped` available.
- **`hooks/stop_evidence_completeness_check.py`** (Stop, advisory) — at session end, scans `.conductor/evidence/tasks/*/manifest.json` and flags tasks with no `files.json` or null `commit_sha`. Appends a structured advisory to `findings.md`. Deduplicated across runs via `.conductor/.evidence-completeness-last-warned` (hash of failing-task set) — only re-warns when the gap set actually changes.
- **39 new tests** — `tests/test_pre_spec_split_enforce.py` (26), `tests/test_stop_evidence_completeness_check.py` (13). Both new hooks added to the universal no-op-when-no-state-json guard in `tests/test_hooks_integration.py`.

### Changed

- **`project-conductor.md`** — Phase 1 large-spec section now documents the new enforcement and lists the override paths. Version summary updated.

### Why Stop hook for evidence-completeness, not PostToolUse on `git commit`

v6 convention is `evidence.record_files()` runs *after* the commit. A PostToolUse-on-commit check would always false-positive on the immediately-following PostToolUse event (the agent hasn't called `record_files` yet — it's the next tool call). Stop runs once per session, after all task work is complete — race-free.

### Not changed

- v6.0.0 lib API surface unchanged.
- All existing v5/v4/v3 hooks unchanged.
- Backwards-compatible: projects without v6 evidence folders simply produce zero gaps and the new Stop hook is a no-op.

---

## [6.0.0] — 2026-05-08

Theme: **"Every task is replayable."** Turns `.conductor/` from a session log into a time-travelable evidence store. Every dispatched task produces a structured per-task evidence folder; every spec criterion is mapped to the task and commit that satisfied it; every routing decision gets a stable `D###` ID; the surgical debug map updates live as features complete instead of only at end-of-session. Designed so a developer can come back months later and replay any task surgically from git history alone.

### Added

- **`lib/evidence.py`** — per-task evidence folder API. `init_task()`, `write_envelope()`, `write_result()`, `record_files()` (files written + commit SHA + tests run), `append_decision()`. Persists to `.conductor/evidence/tasks/<task-id>/{manifest.json, envelope.xml, result.md, files.json, decisions.json}`. Validates task IDs against path traversal. Atomic writes throughout.
- **`lib/coverage.py`** — spec coverage matrix. `register_criterion(text, source=...)` allocates `C###` IDs idempotently; `link_task(criterion_id, task_id)` is many-to-many; `derive_status()` reads from per-task evidence to decide `not_started | in_progress | complete`; `write_coverage_md()` renders `.conductor/coverage.md` with completion percentage, short commit SHAs, and pipe-escaped criterion text. Authoritative state in `.conductor/coverage.json`.
- **`lib/decisions.py`** — structured decision provenance. `append_decision(summary, rationale=..., task_id=...)` allocates monotonic `D###` IDs by scanning existing `## D###` headings in `decisions.md` (so pre-v6 free-text content is preserved). When `task_id` is provided, mirrors the record to the task's evidence folder via `lib/evidence.py`.
- **`lib/debug_map.py`** — live surgical debug map. `upsert_feature()` is idempotent by feature name; `add_limitation()` enforces ≥3 approaches tried (per §v4 Anti-Premature-Failure) and rejects the banned phrase `KNOWN LIMITATION`; `write_debug_map_md()` writes `.conductor/debug-map.md`. The existing `conductor-debug-map` skill remains the post-flight synthesizer; this lib is the live, mid-run counterpart.
- **`hooks/pre_state_committed.py`** — advisory hook (PreToolUse, never blocks). On first invocation per session, if `.gitignore` excludes `.conductor/`, appends a one-time advisory to `findings.md` recommending the user remove the line so per-task evidence is captured in git history (or to gitignore only `locks/` and `probes/` instead). Idempotent via marker file `.conductor/.gitignore-warning-logged`.
- **88 new tests** — `tests/test_evidence.py` (22), `tests/test_coverage.py` (21), `tests/test_decisions.py` (15), `tests/test_debug_map.py` (18), `tests/test_pre_state_committed.py` (12).

### Changed

- **`project-conductor.md`** — added a v6 section explicitly wiring `lib/evidence.py`, `lib/coverage.py`, `lib/decisions.py`, and `lib/debug_map.py` into the Phase 1 → Phase 2 → completion flow. The Compact Instructions "Preserve through compaction" list now includes the four new artifacts. Phase completion language is sharper: "are we done?" is answered by the coverage matrix, not by task counts.
- **State-commit guidance.** New explicit rule: stage and commit per-task evidence in the SAME commit as the task's source-code changes, so `git checkout <SHA>` restores both. Fall back to a separate commit only when source code didn't change for the task.

### Why

v5 already had `plan.md`, `progress.md`, `decisions.md`, and a final-only debug map. The gap was **debug-ability across time**: if a feature broke six weeks after delivery, the developer had to scroll through a flat `progress.md` to find the relevant task, then reverse-engineer "which spec criterion did this satisfy, and was it actually verified?" v6 closes that gap by making the per-task evidence the unit of recall, the coverage matrix the unit of completeness, and the live debug map the surgical entry point — all addressable by stable IDs.

### Not changed

- All v5 behavioral rules (Investigation Budget, Anti-Premature-Failure, Hard Stops, Phase 0 read-only, First Response gate) are unchanged.
- Existing hooks unchanged. The new hook is opt-in via the bundles install flow; default-off.
- `lib/dispatch_envelope.py`, `lib/effort_router.py`, `lib/lock_check.py`, `lib/conductor_state.py`, `lib/template_render.py` unchanged.
- Existing `decisions.md` files (free-text, no `D###` headings) continue to work — `decisions.next_decision_id()` starts at `D001` for legacy files and treats hand-edited gaps as `max+1`.

### Migration notes

- No code changes required for existing projects. v6 adds new files; never modifies v5 artifacts. A pre-v6 `decisions.md` with free-text bullets continues to render and `next_decision_id()` will start fresh from `D001`.
- If you have `.conductor/` in your project's `.gitignore`, the new advisory hook will surface that to `findings.md` once. Acting on the advisory is recommended but not required.

---

## [4.1.1] — 2026-04-27

Hardens the gate between Phase 0 (environment scan) and Phase 1+ (build). Closes a real-world failure mode in which the conductor — running with `⏵⏵ accept edits on` — walked past the Permissions Offer and Optional Bundles Offer and went straight into writing source files. The user never saw the offers because per-edit prompts were suppressed by accept-edits mode, and the agent's own prompt had no enforced stop.

### Changed

- **Phase 0 is now strictly READ-ONLY.** Explicit allowlist of inspection-only Bash (`ls`, `cat`, `command -v`, `--version`, `test -f/-d`, `wc -l`, `grep`, import probes, `openpyxl.load_workbook(..., data_only=True)` reads of an existing input file, and `mkdir -p .conductor/{locks,evidence}`). No `Write` / `Edit` outside `.conductor/`, no source-dir `mkdir`, no target-site network probes.
- **First Response is a HARD GATE.** No `Write` / `Edit` / tree-mutating Bash and no `Task` dispatches until the user replies `proceed`. `accept-edits` mode explicitly does NOT authorize skipping the gate.
- **Gate violations are classified as hard-stop class events.** Logged to `.conductor/decisions.md` and surfaced to the user.

### Why

v4.0 *described* the First Response structure (permissions offer, bundles offer, "reply 'proceed' to begin") but did not *enforce* the gate between Phase 0 (scan) and Phase 1+ (build). In real runs with `⏵⏵ accept edits on` active, the conductor walked past the offers and went straight into writing source files — the user never saw the offers because the natural per-edit prompts were suppressed by accept-edits mode, and the agent's own prompt had no hard stop.

### Not changed

- v4.0 behavioral rules (Investigation Budget, Anti-Premature-Failure, Hard Stops, etc.) all unchanged
- v4.1.0 install flow (`install.sh`, flat-file destination, path substitution) unchanged
- Bundle code (no changes to `agent-monitor/` or `hooks/`)

---

## [4.1.0] — 2026-04-27

Adds an `install.sh` script and consolidates the install path. Previously the README walked users through `git clone` + `mkdir` + `cp`, and the agent's bundle install offer asked users to type the source repo path on every invocation. Both problems were caused by the agent having no anchor to its source repo. v4.1.0 fixes that with an installer that bakes the real path in at install time.

### Added

- **`install.sh`** — single-command installer. Detects the cloned repo's location (works wherever you cloned it: `~/TheConductor`, `~/Code/TheConductor`, `/opt/TheConductor`, etc.), patches `project-conductor.md` so every `/path/to/TheConductor` placeholder is replaced with the real absolute path, and copies the patched file to `~/.claude/agents/project-conductor.md`. Supports macOS / Linux / Windows Git Bash / WSL.
- **`--force` flag** for `install.sh` — skips the overwrite prompt for scripted update flows (`git -C <path> pull && <path>/install.sh --force`).
- **Idempotency** — re-running `install.sh` on an unchanged install is a silent no-op (uses `cmp -s` to compare the patched temp file against the deployed file before prompting).

### Changed

- **Install destination changed from `~/.claude/agents/project-conductor/agent.md` (subdirectory + `agent.md`) to `~/.claude/agents/project-conductor.md` (flat file).** Both forms work in Claude Code. The flat form matches community convention (e.g., the `msitarzewski/agency-agents` repo) and removes one layer of nesting. Existing users updating from a previous version should run `rm -rf ~/.claude/agents/project-conductor` after running the new installer (see Migration below).
- **Standardized the placeholder in `project-conductor.md`** — all 5 occurrences of `/path/to/repo` (lines 519, 522, 523, 529, 530) renamed to `/path/to/TheConductor` to match the 4 existing `/path/to/TheConductor` occurrences in the same file. After `install.sh` runs, all 9 placeholders are substituted with the user's real repo path. The agent's bundle install offer now shows the real path the user can copy-paste, not a placeholder.
- **README install section simplified** — replaced the manual `git clone` + `mkdir` + `cp` sequence (and a separate "project-level install" section) with a single `git clone` + `./install.sh` flow. Update is now a one-liner: `git -C <path> pull && <path>/install.sh`. The project-level install pattern is no longer documented (was rarely used; manual `cp` still works for advanced users who need it).
- **README "Optional monitoring" + "Optional hooks" sections collapsed into one "Optional bundles" section** — manual `cp -r` install instructions removed. Users are pointed to the runtime offer (which now knows the source path) and to `agent-monitor/README.md` / `hooks/README.md` for advanced manual install.

### Why

Two problems with the v4.0.2 install flow:

1. **The agent had no anchor to its source repo.** When it offered bundle install (`install bundles N,M from /path/to/repo`), the user had to type the source path manually every time — because the deployed agent file in `~/.claude/agents/` had no way to know where the cloned repo lived. With v4.1.0's `install.sh`, the path is substituted into the deployed file at install time, so the offer shows the real path on the user's machine.
2. **Multi-step manual install was error-prone.** `git pull` succeeded silently when the follow-up `cp` was forgotten, leaving users on stale agent code while thinking they had updated. `install.sh` is one command for both initial install and updates.

### Migration

If you've installed any version before v4.1.0:

```bash
# 1. Remove the old subdirectory-form install
rm -rf ~/.claude/agents/project-conductor

# 2. Pull the new repo state
git -C <wherever-you-cloned> pull

# 3. Run the new installer
<wherever-you-cloned>/install.sh
```

After this, the agent lives at `~/.claude/agents/project-conductor.md` (flat file), and the bundle install offer will show your real repo path instead of a placeholder.

### Not changed

- Agent prompt's behavioral rules (Investigation Budget, Anti-Premature-Failure, Hard Stops, etc., all unchanged from v4.0.2)
- Bundle code (no changes to `agent-monitor/` or `hooks/` scripts in this release)
- `bundles_already_handled` opt-out flag (still works the same way)
- Detector thresholds (unchanged)
- Privacy posture (still 100% local, opt-in, no telemetry)

---

## [4.0.2] — 2026-04-26

Surfaces the optional bundles in the conductor's first response so users discover them without reading the README. Without this, new users had no in-flow signal that `agent-monitor/` and `hooks/` exist — they only ride along if explicitly cp'd from the source repo.

### Added

- **First-response "Optional bundles offer" section** — appears after the existing Permissions setup offer. Surfaces the three bundles with one short paragraph each:
  1. `agent-monitor/` — session reports with auto-detected anti-patterns
  2. `hooks/heartbeat.py` — background-mode status visibility
  3. `hooks/usage_limit_wakeup.py` — auto-resume after API rate/usage limits
- **"Optional Bundles Offer" procedure section** in `project-conductor.md` — full install handling: source-path verification, file copy, settings.json hook block + permission entries draft, sanity-test before activation (mirrors the v3 Permissions Offer posture).
- **Mid-run install controls** — users can install bundles mid-session with `install bundles 1,2,3 from /path/to/TheConductor` or decline with `skip bundles`.
- **`bundles_already_handled: true`** opt-out flag in `.conductor/config.json` for users who don't want the offer to appear (e.g., project-level pre-decision).

### Why

v4.0.0 introduced the bundles but they require manual `cp -r` + manual `settings.json` editing. Most new users don't read the README first, so most users never discovered the bundles existed. v4.0.2 makes discovery part of the standard Phase 0 flow — same posture as the permissions offer (surface, ask, respect the answer, don't re-ask).

### Not changed

- Bundle code (no changes to `agent-monitor/` or `hooks/` scripts in this release)
- Bundle install posture (still opt-in, still local-only, no telemetry)
- Agent prompt's behavioral rules (Investigation Budget, Anti-Premature-Failure, etc., all unchanged from v4.0.0)
- Detector thresholds (unchanged from v4.0.1)

---

## [4.0.1] — 2026-04-26

Improves the monitor-report → maintainer feedback loop. v4.0.0's share-footer just said "paste this report" — maintainers received tool-call dumps without context on what the user wanted or whether the patterns were bad-in-context. v4.0.1 adds a structured contribution template.

### Changed

- **`agent-monitor/reporter.py` — `share_footer()` now emits a 5-field contribution template** (What I was trying to do / Did the agent succeed / Which patterns were BAD vs NEUTRAL vs FALSE-POSITIVE / What should it have done / Anything else). Users fill the template before pasting the raw report. Takes ~2 minutes; makes the difference between an actionable report and a tool-call dump.
- **`CONTRIBUTING.md` — "Sharing your monitor reports" section updated** to explain the template, why each field matters, and what makes a useful report.

### Why

The auto-detector is static (regex + thresholds). It cannot judge whether a flagged pattern was bad-in-context — that requires knowing the user's goal. Without that context, contributed reports are observations, not actionables. The structured template captures the missing context cheaply.

### Not changed

- Detector thresholds and patterns (no detector logic changes in this release)
- Privacy posture (still 100% local, opt-in, no telemetry)
- Agent prompt (`project-conductor.md` unchanged in this release)

---

## [4.0.0] — 2026-04-26

Behavior-shift release derived from real-world test sessions. v3 was over-cautious; v4 is biased toward iterating before asking, discovering before declaring impossible, and notifying without blocking. Twelve discrete process failures observed in v3 → addressed in v4.

### Breaking changes

- **Hard Stop semantics reclassified.** "Site needs Playwright instead of `requests`" is now explicitly NOT a Hard Stop — it's implementation iteration. An architectural decision is one that affects MULTIPLE components OR introduces a NEW SYSTEM-LEVEL dependency (database, message queue, deployment target, auth provider). Adjusting one component's transport/parsing technique is implementation-level. See "Hard Stops" section in `project-conductor.md`.
- **Turn-25 checkpoint demoted from mandatory pause to informational notification.** v3 required explicit user confirmation at every 25-turn boundary; this caused unnecessary interruption and never caught a real problem in testing. v4 surfaces a one-line notification and continues. Opt into `--strict-mode` (or `strict_checkpoints: true` in `.conductor/config.json`) for v3 behavior.
- **Budget thresholds (70%/95%) demoted from blocking to notification (the "Notify, Don't Block" rule).** Work continues past notification — user is informed, not stopped. Anti-shrinkage clause: deliver partial output and continue, do not auto-shrink scope.
- **Removed from Hard Stops:** budget threshold, turn checkpoint, self-check counter exhaustion. These are now notifications/logs, not stops.
- **Public version number jumped 1.x → 4.x** to align with internal agent-prompt versioning narrative (v3 → v4). Future releases will increment normally.

### New

- **Investigation Budget** rule (max 3 throwaway research artifacts before MUST commit to a draft implementation; max 5 ever per task)
- **Per-resource Discovery** rule (when ≥2 peer external resources involved, each gets independent discovery — no blanket-applying)
- **Anti-Premature-Failure** rule (≥3 distinct approaches before declaring impossible; phrase "KNOWN LIMITATION" BANNED in shipped code)
- **Status from State, not Estimation** rule (status responses MUST come from a state file, log, or directly-observed signal — never elapsed-time estimation)
- **Forbidden Bash Patterns** section (`until ... ; do sleep N; done` busy-wait loops banned; identical command ≥3 times triggers stuck-check)
- **Output-Quality Completeness Check** in Phase 2.5 (detects column-empty / row-empty / fill-rate-<50% / regression-vs-prior anomalies BEFORE declaring task success)
- **Heartbeat for Background Mode** (`.conductor/heartbeat.json` so parent agents read background-mode status without spawning a second conductor)
- **`agent-monitor/` bundle** — opt-in monitoring with auto-pattern detection (probe sprawl, busy-wait, no-forward-progress, repeat-bash, scope-shrink signals) pre-fills the "Issues & Patterns" table in session reports. Includes opt-in share-footer with GitHub issue URL template.
- **`hooks/` bundle** — two opt-in PostToolUse hooks: `heartbeat.py` (writes heartbeat file) and `usage_limit_wakeup.py` (detects API limits, writes recovery instructions for the conductor to `ScheduleWakeup`).

### Fixed

- **Probe-loop without commitment** — agent would write throwaway research scripts indefinitely, never committing to a draft. Investigation Budget rule + auto-detection in `agent-monitor/` address this.
- **Misclassified Hard Stop on implementation detail** — agent treated discovering "site needs different transport" as architectural change requiring user decision. Hard Stop reclassification + NOT Hard Stops expansion address this.
- **Status reports based on time estimates** — agent answered "probably 25-55 minutes remaining" with no actual signal. Status from State rule addresses this.
- **Busy-wait via shell loops** — agent used `until grep -q "...";  do sleep N; done` to wait on background tasks, burning turns/tokens. Forbidden Bash Patterns rule + auto-detection address this.
- **Auto-shrinkage of scope under perceived time pressure** — agent stopped at 55/200 SKUs instead of delivering partial output and continuing. Notify-Don't-Block + anti-shrinkage clause address this.
- **Premature acceptance of failure as "known limitation"** — agent baked failure into code comments after only 2 attempts. Anti-Premature-Failure rule (with explicit ban on "KNOWN LIMITATION") addresses this.
- **Background-agent visibility black hole** — parent Claude Code couldn't see backgrounded conductor's progress, resorted to spawning a second conductor (50k+ tokens) just to query state. Heartbeat protocol addresses this.
- **No output-quality verification** — `verify_workbook` checked file structure but not field-fill rates. Entire-column-empty patterns slipped through as "success." Output-Quality Completeness Check addresses this.
- **Empty observation tables in monitor reports** — reporter generated `| 1 | | | |` placeholders for the user to fill in manually. Auto-pattern detection in v4 reporter pre-fills detected patterns.

### Documentation

- README.md: new "What's new in v4" table, updated Safety mechanisms table, new Optional monitoring + Optional hooks sections, new `--strict-mode` description, fixed `project-conductor-v3.md` → `project-conductor.md` filename reference
- CONTRIBUTING.md: new "Sharing your monitor reports" section explaining the share-footer flow and what to redact
- agent-monitor/README.md, hooks/README.md: full install instructions, security notes, uninstall steps

### Telemetry

**None.** All data stays local. The opt-in `agent-monitor/` reports include a GitHub issue URL template in the share-footer, but you decide what (if anything) to share. No automatic data collection.

---

## [1.0.0] — 2026-04-25

Initial public release.

### Core capabilities
- Autonomous end-to-end project execution from a spec file
- Lazy two-tier environment discovery (subagents, skills, MCPs, CLIs, plugins)
- Dynamic task routing — discovers actual tools available, never hardcodes
- Continuous execution across all phases with configurable interruption model
- Reality verification on every task completion (never trusts reports)
- Session resumption from `.conductor/` state

### Safety mechanisms
- **Turn checkpoint** (every 25 turns) — deterministic pause-and-confirm, independent of token estimation
- **Spec enrichment review gate** — mandatory user approval before Phase 2 begins; no silent enrichment-then-build
- **Canary model check** — heuristic detection of Task tool model parameter being ignored (GitHub issue #18873)
- **Lock enforcement** — post-dispatch `git diff --name-only` verification that subagents honored declared file boundaries
- **Permissions sanity test** — canary command before writing `.claude/settings.json` to catch broken permission syntax
- **Budget enforcement** — soft stop at 70%, hard stop at 95% of session token budget

### Governance
- Hard stop hierarchy (15 conditions, in priority order)
- No automatic Opus escalation — user must explicitly authorize premium retries
- Self-check system with cap (12/session) and distribution enforcement
- Concurrency locks with conflict resolution (write-write, read-write, read-read)
- Credentials detection with guided acquisition flow

### Outputs
- Live `status.md` — always current, queryable mid-execution
- `FINAL_REPORT.md` — plan-vs-actual, routing notes, v3 mechanism outcomes
- Surgical debug map — feature → files/commits/decisions/limitations index

### Integration
- Works with Superpowers plugin (brainstorming, TDD, planning, code review)
- Adaptive behavior for small (<20), medium (20-80), and large (80+) agent libraries
- Project-aware CLI detection — only scans for CLIs the project actually needs
