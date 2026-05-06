---
name: conductor-scaffold-ai-director-os
description: Scaffold the AI Director's OS Standard Pack into a project (CLAUDE.md, .claude/current-phase.md, .claude/settings.json with hooks, .claude/rules/*, .claude/prd/template.md) using values from the enriched spec. Atomic-write contract; rejects targets under ~/.claude/.
allowed-tools: Read, Write, Edit, Bash(mkdir,cp,rm)
---

## When to invoke

The conductor invokes this skill once per session, during Phase 1, after spec enrichment is approved AND the user has answered the scaffold offer affirmatively.

## Inputs

- `.conductor/scaffold-payload.json` — typed enriched-spec values (canonical)
- `templates/` directory bundled with TheConductor (resolved via installer-baked path)
- The scaffold-input block, when this skill is invoked from a delegated sub-agent (see §4.3 of the spec):
  ```
  <scaffold-input>
  {
    "PROJECT_NAME": "...",
    "STACK": "...",
    ...
  }
  </scaffold-input>
  ```

## Outputs

- Files written into the user's project (cwd-relative):
  - `CLAUDE.md`
  - `.claude/current-phase.md`
  - `.claude/settings.json` (hooks pre-wired)
  - `.claude/rules/frontend.md`, `.claude/rules/api.md`, `.claude/rules/tests.md`
  - `.claude/prd/template.md`
- A row appended to `.conductor/decisions.md` describing the scaffold action + file list + TODO marker count
- For collisions, suggestion files: `<target>.scaffold-suggestion.<ISO-8601-timestamp>` (never overwrites the target)

## Procedure

1. **Read `.conductor/scaffold-payload.json`.** If absent → abort with stderr "scaffold-payload.json missing; run conductor-spec-enrichment first".

2. **Count required fields with literal value `TODO: <fieldname>`**. ≥3 → emit thin-spec circuit-breaker line and STOP awaiting user reply:
   ```
   scaffold: spec is thin (missing: X, Y, Z). Reply 'scaffold with TODOs' to continue or 'rerun enrichment' to fix.
   ```

3. **Render ALL templates to memory first** (atomic-write contract, §4.2):
   a. For each template in `templates/` (resolved via installer-baked path), call `lib/template_render.render(template_path, payload)` → rendered string.
   b. Compute target path under cwd. If target exists, retarget to `<target>.scaffold-suggestion.<ISO-8601>`.
   c. If any target resolves under `~/.claude/`, abort with stderr "scaffold target outside project — check template paths".

4. **Write all rendered strings to staging directory** `.conductor/scaffold-staging-<ts>/`.

5. **On success, atomically rename each staged file to its final target** using `os.replace`. On any failure, remove staging directory and abort.

6. **Append to `.conductor/decisions.md`:**
   ```
   [timestamp] scaffold action + file list + TODO marker count
   ```

7. **Surface to user:**
   ```
   Scaffolded N files. M TODO markers in <list-of-files> — please review.
   ```

## Examples

(Skill #7 does not require few-shot examples per the spec — only skills #3 and #4 do. Examples here would only be illustrative.)

## Failure modes

- **`.conductor/scaffold-payload.json` missing** → abort with stderr "scaffold-payload.json missing; run conductor-spec-enrichment first".
- **`<scaffold-input>` block missing in delegated mode** → abort with stderr "scaffold-input block missing in delegated invocation; the parent conductor must pass the typed payload as a fenced block".
- **≥3 required fields are TODO placeholders** → thin-spec circuit-breaker; STOP, wait for user reply (not a hard error).
- **Target path resolves under `~/.claude/`** → abort with stderr "scaffold target outside project — check template paths"; log to `.conductor/findings.md`. This is the load-bearing §3.1 boundary check.
- **Template render fails** (KeyError, IO error, etc.) → remove staging directory; abort scaffold; log exact error to `.conductor/decisions.md`; surface to user.
- **`os.replace` fails on any staged file** → remove staging directory; abort scaffold (do NOT leave partially-renamed state); log to `.conductor/decisions.md`; surface to user.
- **Compaction fires mid-scaffold** → on next turn, recovery rule (§4.4) applies: read state.json, scaffold-payload.json, decisions.md; if `.conductor/scaffold-staging-<ts>/` exists, remove it and re-run scaffold from scratch.
- **A `.scaffold-suggestion.<ts>` file already exists for the same target** → write a new one with a different timestamp. Do NOT overwrite or delete the existing suggestion. User hygiene cleans up old suggestions.

