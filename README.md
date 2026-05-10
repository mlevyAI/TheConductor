# Project Conductor

> An autonomous, end-to-end project execution manager for Claude Code.

Project Conductor takes a spec file and runs your entire build — from environment discovery through final delivery — with minimal interruptions. It discovers what tools are actually available in your environment, routes tasks to the right subagents, enforces budgets, and produces a final report with a surgical debug map.

## What's new in v6

v6 makes every conductor session **replayable, evidence-backed, and bulletproof at install time.** The body now records per-task evidence as it runs, the install path auto-wires the enforcement hooks, and a SessionStart bootstrap closes the chicken-and-egg gap that previously let the conductor walk past its own gates.

| Change | What it fixes |
|---|---|
| **Per-task evidence + coverage matrix + live debug map** (v6.0.0) | Builds proof as the run happens. `lib/evidence.py` records artifacts per task; `lib/coverage.py` tracks acceptance criteria → evidence; `lib/debug_map.py` keeps the post-mortem map current during execution, not just at the end. |
| **Block large unsplit specs + advisory on incomplete evidence** (v6.0.1) | A Stop hook flags any task that finishes without recorded evidence; a PreToolUse hook blocks `Read` on specs over the size threshold until `conductor-spec-splitter` has run. |
| **Hooks manifest + bundles install + e2e integration test** (v6.0.2) | `hooks/MANIFEST.json` is the single source of truth for every hook (event, bundle, blocking, version). `lib/hooks_manifest.py` renders the `settings.json` block from the manifest. `tests/test_v6_e2e_integration.py` walks a spec from submission to replay and proves all 9 hooks compose without conflicts. |
| **Bulletproof enforcement via SessionStart bootstrap + §3.1 amendment** (v6.0.3) | `hooks/bootstrap_phase_0a.py` is wired once into user-global `~/.claude/settings.json` (with explicit Y/n consent at `install.sh` Step 8). It detects conductor sessions on startup and auto-installs the 9 per-project enforcement hooks — so the conductor's own gates are active *before* it gets a chance to skip them. §3.1 amended to permit this single SessionStart entry; runtime read-only contract unchanged. |
| **9 modular skills, body under 450 lines** (refactor) | Promoted the 63-line First Response template into `conductor-first-response`; conductor body is back under the 450-line maintenance target. |

### Earlier v5 highlights (still active)

- **Complexity-scored routing** — model selection (Haiku / Sonnet / Opus) and retry budget derived from a score, not ad-hoc conditionals.
- **Dispatch envelope** — every outbound agent call carries literalism rules, effort, model, and pre-dispatch research in one typed envelope.
- **Effort router** — resolves spec hints + score override + explicit flag into a single effort level.
- **6 Phase B PreToolUse / Stop hooks** — busy-wait blocking, lock enforcement, Phase 0 read-only guard, first-response gate, output-quality check, final-report validation.
- **AI Director scaffold** — `install.sh --for-project` writes a full project CLAUDE.md + rules + PRD template into a new repo in one command.
- **`lib/conductor_state.py`** — typed access to `.conductor/` state, migration-safe from v4.
- **`lib/template_render.py`** — path-safety enforced; resolves `{{VARIABLES}}` from a dict; refuses writes outside the target directory.

See [CHANGELOG.md](CHANGELOG.md) for the full history.

## What it does

You hand it a spec. It builds your project.

```
Use project-conductor to build from [your-spec.md]
```

It will:
1. **Discover** your environment (subagents, skills, MCPs, CLIs, plugins)
2. **Analyze** your spec and enrich it with execution metadata
3. **Route** each task to the best available tool — dynamically, not hardcoded
4. **Execute** all phases continuously, stopping only for true blockers
5. **Verify** every completion claim before marking tasks done
6. **Deliver** a final report with plan-vs-actual and a debug map

## Key design principles

**Reality over reports.** Never trusts completion claims. Runs the tests, reads the files, checks the commits.

**Adaptation over assumption.** Discovers what's actually installed before routing. Agent libraries vary wildly between users.

**Transparency over silence.** Maintains a live `status.md` file — you can ask "status" at any point and get an immediate, accurate answer.

## Safety mechanisms

Project Conductor v6 is hardened against autonomous-agent failure modes (mechanisms listed by version):

**v3 mechanisms (still active):**

| Mechanism | What it prevents |
|-----------|-----------------|
| **Spec enrichment review gate** | Building against conductor's interpretation, not yours |
| **Canary model check** | Paying Opus rates when you requested Haiku |
| **Lock enforcement** (via `git diff`) | Parallel tasks overwriting each other's files |
| **Permissions sanity test** | Settings that look active but silently don't apply |

**v4 mechanisms (still active):**

| Mechanism | What it prevents |
|-----------|-----------------|
| **Investigation Budget** (cap on probe artifacts) | Probe-loop without commitment — agent writes throwaway scripts forever |
| **Hard Stop reclassification** | Mistaking implementation iteration ("needs Playwright") for architectural change requiring user decision |
| **Per-resource Discovery** | Blanket-applying one technique to all peer resources when each needs its own |
| **Anti-Premature-Failure rule** | "KNOWN LIMITATION" baked into code after only 2 attempts |
| **Status from State, not Estimation** | Fabricated progress reports ("probably 25 min remaining" with no signal) |
| **Forbidden Bash Patterns** | Busy-wait `until ...; do sleep N; done` loops that burn turns with zero progress |
| **Notify, Don't Block** budget | Auto-shrinking scope (200 → 55) under perceived time pressure |
| **Output-Quality Completeness Check** | Declaring success when one entire output column is 100% empty |
| **Turn checkpoint** (informational, non-blocking) | Was mandatory pause in v3; demoted to notification in v4 — opt into `--strict-mode` for v3 behavior |
| **Heartbeat for Background Mode** | Parent agents losing visibility into backgrounded conductor instances |

**v5 mechanisms (still active):**

| Mechanism | What it prevents |
|-----------|-----------------|
| **Phase 0 read-only enforcement** | Conductor writing source files during the discovery scan — only `.conductor/` is writable, only inspection-only Bash is allowed |
| **First Response hard gate** | Conductor walking past the Permissions / Bundles offers and starting to build before the user replies `proceed` (the `accept-edits`-mode failure mode) |
| **Complexity-scored routing** | Over-spending Opus on trivial tasks; under-provisioning Haiku tasks that silently need more model capability |
| **Dispatch envelope + literalism rules** | Subagents ignoring spec requirements or adding unrequested features — envelope enforces caller intent on every dispatch |
| **6 Phase B hook backstops** | Busy-wait loops, phantom locks, Phase 0 writes, premature starts, empty-column output, and invalid final reports — each caught and blocked by a dedicated hook |

**v6 mechanisms (NEW):**

| Mechanism | What it prevents |
|-----------|-----------------|
| **Per-task evidence record** | Tasks marked complete with no recorded artifact — evidence is registered as the task runs, not asserted at the end |
| **Coverage matrix** | Acceptance criteria silently dropped — every criterion is mapped to evidence; Stop hook fires on uncovered criteria |
| **Live debug map** | Post-mortem maps that drift from reality — the map is updated during execution, not retrofitted from memory |
| **Spec-split-enforce hook** | Reading a 5 000-line spec into context as one chunk — `Read` on oversized specs is blocked until `conductor-spec-splitter` has run |
| **Stop evidence-completeness check** | Final report claiming success while individual tasks have no evidence rows — Stop hook scans coverage matrix before allowing the final report |
| **Phase 0a SessionStart bootstrap** | Chicken-and-egg: hooks not yet installed when the conductor first runs, so prompt-only rules went unenforced. Bootstrap detects conductor sessions on Claude Code startup and auto-wires the 9 per-project enforcement hooks before Phase 0 begins. |
| **Hooks manifest as single source of truth** | Drift between `settings.json`, the prompt, and the actual hook files. `hooks/MANIFEST.json` is rendered into both at install time; `lib.hooks_manifest.validate_against_disk()` catches divergence. |

## Installation

Clone the repo wherever you like, then run `install.sh`:

```bash
git clone https://github.com/mlevyAI/TheConductor && cd TheConductor && ./install.sh
```

The installer:
- Detects the repository's path on this machine (so the agent can find its `hooks/` and `agent-monitor/` bundles when it offers to install them)
- Patches an in-memory copy of `project-conductor.md`, replacing every `/path/to/TheConductor` placeholder with the real path
- Copies the patched file to `~/.claude/agents/project-conductor.md`
- Copies the conductor skills (`conductor-*/SKILL.md`) into `~/.claude/skills/`
- Asks (separate Y/n at Step 8) whether to wire the **SessionStart bootstrap entry** into `~/.claude/settings.json`. This is the only user-global write — it adds one entry pointing at `hooks/bootstrap_phase_0a.py`, which auto-installs the 9 per-project enforcement hooks the first time the conductor runs in a new project. Decline if you'd rather wire the per-project hooks yourself; documented removal path lives in `hooks/README.md`.
- Never modifies the in-repo source

You can clone to any path you like — the command above clones into the current directory, but `~/TheConductor`, `~/Code/TheConductor`, `/opt/TheConductor` etc. all work. The installer figures it out from where the script lives.

**To update:**

```bash
git -C <path-to-TheConductor> pull && <path-to-TheConductor>/install.sh
```

`install.sh` is idempotent: re-running with no changes is a silent no-op. If new commits change `project-conductor.md`, it asks before overwriting (or pass `--force` to skip the prompt in scripted update flows).

## Usage

```
Use project-conductor to build from spec.md
```

That's it. The conductor handles the rest.

### Status check (anytime during execution)

```
status
```

### Mid-run controls

| Command | Effect |
|---------|--------|
| `status` | Show current phase, task, budget |
| `show progress` | Phase-level summary |
| `proceed` | Continue after a checkpoint |
| `permissions yes` | Accept permissions offer |
| `approve enrichments` | Approve spec additions (required before Phase 2) |
| `install bundles N,M from /path/to/TheConductor` | Install one or more optional bundles (1=monitor, 2=heartbeat, 3=usage-limit) — see Optional bundles offer in first response. After running `install.sh`, the path is already baked into the agent — the offer prompt shows the real path on this machine, not a placeholder. (NEW in v4.0.2) |
| `skip bundles` | Decline the optional bundles offer (NEW in v4.0.2) |

## Configuration

The conductor's own model is set in the frontmatter of `project-conductor.md`:

```yaml
---
model: opus      # opus (best orchestration) or sonnet (5x cheaper, good for prototypes)
effort: medium   # medium recommended; high not worth the cost for orchestration
---
```

This controls the **orchestration quality**, not the tasks themselves. Tasks are dispatched to subagents with their own models.

See the header comment in `project-conductor.md` for the full decision guide.

### Strict mode (opt-in)

By default in v4, the turn-25 checkpoint and budget thresholds are **notifications**, not pauses — the conductor surfaces them and continues working. If you prefer the v3 pause-and-confirm behavior (e.g., for high-stakes production work where you want explicit confirmation at every checkpoint), invoke the conductor with `--strict-mode` or set `strict_checkpoints: true` in `.conductor/config.json`.

## Permissions offer

On first run, the conductor offers to set up permission rules so it can run `npm test`, `git status`, etc. without prompting you on every command. You choose:

- **A** — write to `.claude/settings.json` (shared if committed)
- **B** — write to `.claude/settings.local.json` (personal, gitignored)
- **C** — merge with existing settings

It will **never auto-allow** `git push`, destructive git ops, `rm -rf`, production deploys, or `.env*` writes.

## State files

All conductor state lives in `<project>/.conductor/`:

```
.conductor/
  plan.md                    — task list with statuses
  status.md                  — live status (update on every task change)
  progress.md                — chronological log
  budget.md                  — token usage tracking
  decisions.md               — choices with rationale
  deviations.md              — in-scope fixes and lock violations
  findings.md                — emergent issues classified
  checkpoint-N.md            — turn checkpoints (every 25 turns)
  spec-enrichment.diff       — diff of original vs enriched spec
  spec-enrichment-summary.md — categorized enrichment review
  locks/                     — active task locks
  evidence/                  — artifacts by phase
  FINAL_REPORT.md            — post-execution delivery report
```

## Session resumption

If a session ends mid-build, just start a new one in the same project directory. The conductor reads `.conductor/` state, cleans stale locks, verifies file state matches its claims, and continues from where it left off.

## Final report

Every completed run produces `.conductor/FINAL_REPORT.md` with:

- Plan vs. actual (per phase)
- Token budget used
- All deviations logged
- safety mechanism outcomes
- **Surgical debug map** — for every major feature: files, commits, subagent used, key decisions, known limitations

The debug map format is designed to be quoted back to Claude:

> "Bug in [feature]. Per debug map: phase [P.T], files [list], commit [SHA]. Fix surgically without touching unrelated code."

## Optional bundles (monitoring + hooks)

Three opt-in bundles ship with the conductor:

| Bundle | What it does |
|---|---|
| `agent-monitor/` | After each session, generates a **local** markdown report with auto-detected anti-patterns (probe sprawl, busy-wait loops, no-forward-progress clusters, repeat-bash, scope-shrink). Pre-fills the "Issues & Patterns to Improve" table for your own after-action review. Reports stay on your machine; nothing is uploaded. The same report format is the planned input for a future local self-learning loop (SessionStart context injection from past sessions). |
| `hooks/heartbeat.py` | Updates `.conductor/heartbeat.json` after every tool call so parent agents can read background-mode status without spawning a second conductor instance. |
| `hooks/usage_limit_wakeup.py` | Detects API rate-limit / usage-limit errors, computes a recommended wakeup time, writes `.conductor/usage-limit-paused.json` so the conductor can `ScheduleWakeup` and resume after the limit resets. |

All three are **opt-in, purely local — no network calls, no secret reads.**

**You don't install them by hand.** When you start a session, the conductor offers to install them for you and walks through the settings.json + permissions wiring with a sanity-test before activating. Just answer the prompt (`install 1,2,3`, `install 2`, `skip bundles`, etc.).

For the implementation details, security notes, and manual install steps (advanced users only), see [agent-monitor/README.md](agent-monitor/README.md) and [hooks/README.md](hooks/README.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
