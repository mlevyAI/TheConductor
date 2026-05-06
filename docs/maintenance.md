# TheConductor — Maintenance Rules

Operating rules for keeping TheConductor healthy after the v5 refactor lands. Per spec §7.4. Each rule defines what to check, where the signal lives, and the action when the rule fires.

## 1. Bidirectional skill threshold

**Promote** inline content from `project-conductor.md` to a skill when:
- The content is more than ~10 lines, AND
- The content is phase-specific (only relevant during one phase or in response to one trigger), AND
- It can be invoked via the Skill tool from a clear call site in the conductor body.

**Demote** a skill back into the body when:
- The skill body has shrunk below ~30 lines after iteration, AND
- It is invoked rarely enough that the call-site overhead exceeds the body cost.

The point of the rule is to prevent two opposite drifts: (a) the body bloating with content that should live in skills, and (b) accumulating tiny skills whose invocation overhead exceeds their payload. Audit on each minor version bump.

## 2. Conductor body line budget

- **Target:** ≤450 lines.
- **CI gate:** the workflow at `.github/workflows/test.yml` includes a step that fails if `wc -l project-conductor.md` exceeds **500**. The 50-line headroom between target and gate exists so a routine PR doesn't have to also do compression — but gradual drift past 500 must trigger a refactor.
- **Audit cadence:** quarterly OR whenever the body grows by more than 30 lines in a single PR.

## 3. Hook canary on every install

`install.sh` (Phase B and onward) runs each new hook with synthetic stdin in two configurations: an allow-case (exit 0 expected) and a block-case (exit 2 expected for PreToolUse hooks). If any canary fails, the hook is **not installed** and a row is written to `.conductor/decisions.md` with the failure reason.

Phase A: this rule is forward-compatible. The 6 new hooks land in Phase B; this rule activates then.

## 4. Hook firing-and-runtime health

For each conductor-managed hook, verify two conditions across recent runs (read from `.conductor/decisions.md` and `.conductor/findings.md`):

- **Fired**: the hook fired at least once when its trigger condition was present.
- **Exited cleanly**: there are no rows in `findings.md` matching `hook X exited non-zero non-2`.

Both conditions must hold. Environment drift (Python version change, broken `$CONDUCTOR_HOOKS` after a directory move, etc.) doesn't show up in firing counts alone — a hook that always silently no-ops looks the same as a hook that didn't fire because its trigger wasn't present. Checking exit success too catches the difference.

**Cadence:** weekly during active conductor use, or on demand when investigating a session that felt "off."

## 5. /memory audit (read-only)

Per spec §3.1, the conductor never writes to `~/.claude/memory/`. The user controls that directory.

**The rule:** periodically scan `~/.claude/memory/` for entries that reference TheConductor (file names matching `conductor*` or content containing "TheConductor", "project-conductor", "conductor body", etc.). Identify stale entries — references to v3 or v4 mechanisms that no longer exist, references to removed sections of the conductor body, etc.

**The action:** the **user** deletes stale entries. The conductor surfaces "potential staleness" as informational notices in `.conductor/decisions.md` during a session — never deletes anything from user-global, never offers to delete (per §3.1).

Surviving discoveries (memory entries that captured something worth keeping) get promoted into either the conductor body, a skill, or a CHANGELOG entry via a separate PR.

## 6. Spec drift detection

When the scaffolding skill (Phase C onward) reports >30% of fields filled with `TODO:` markers across two consecutive sessions, surface a notification:

> Spec template may be drifting from current project shape — review `templates/.claude/prd/template.md`.

Phase A note: scaffolding doesn't run yet. The `conductor-scaffold-ai-director-os` skill exists with full procedure but is inert (no invocation point in the conductor body). This rule activates when Phase C lands.

## 7. User-global boundary check

**Quarterly** (and on every PR that touches `install.sh`, `lib/template_render.py` when it lands, or skill `allowed-tools`):

```bash
pytest tests/test_user_global_readonly.py
```

This test:
- Greps `install.sh` for write contexts targeting `~/.claude/CLAUDE.md`, `~/.claude/imports/`, `~/.claude/settings.json`, `~/.claude/memory/` — finds none.
- Asserts every cp/mv in `install.sh` targeting `~/.claude/` lands in `/skills` or `/agents` only.
- Greps `project-conductor.md` for instructions that would write to forbidden paths — finds none.
- Inspects each skill's `allowed-tools` for unscoped writes targeting user-global.
- (Phase C+) Asserts no template in `templates/` resolves to a path under `~/.claude/`.

**This is the load-bearing invariant of the spec.** A new component growing a write path into user-global without the rest of the team noticing would silently violate §3.1. The boundary is enforceable only because this test fails on regression.

If this test ever fails, halt the PR and investigate. There is no acceptable "fix it later" — user-global writes affect every project on the user's machine, and TheConductor is shipped to the community (#buildinpublic). Every install on a stranger's machine inherits the boundary contract.
