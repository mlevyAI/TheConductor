---
name: conductor-phase-0-discovery
description: Run TheConductor's Phase 0 environment scan — discover available subagents, skills, MCPs, CLIs, and project signals using a strict two-tier lazy approach. Phase 0 is READ-ONLY; no Write, no Edit, no source-tree mkdir, no target-site network probes.
allowed-tools: Read, Glob, Grep, Bash(ls,find,grep,git,jq,which,test,cat,wc,command,head,tail,mkdir)
---

## When to invoke

The conductor invokes this skill at the start of every session, immediately after reading any project-level CLAUDE.md and before emitting the First Response. Total budget: 30k tokens. If you cannot complete it under budget, abort and report.

## Inputs

- Read `~/.claude/CLAUDE.md` if it exists
- Read `<project>/CLAUDE.md` if it exists
- Read existing `.claude/settings.json` and `.claude/settings.local.json` (project + user scope) if any
- Read `.conductor/state.json` if present (resume case)

## Outputs

- `.conductor/locks/` directory (created via `mkdir -p`)
- `.conductor/evidence/` directory (created via `mkdir -p`)
- `.conductor/probes/` directory (created via `mkdir -p`) — canonical home for throwaway exploration artifacts per `project-conductor.md` §Investigation budget; created in Phase 0 to avoid a later mkdir during a more sensitive phase
- `.conductor/environment.md` — capability inventory snapshot, written by the conductor body after this skill returns
- A capability dictionary returned to the conductor body, used to populate the First Response "What I found" section

The skill itself MUST NOT use `Write` or `Edit` for any file outside `.conductor/`. The only write operations allowed are the three `mkdir -p` calls listed above. Source-directory `mkdir` (anything outside `.conductor/`), `Write`, `Edit`, `pip install`, `playwright install`, and any outbound network request to a target site/API named in the spec are all forbidden until the user has replied `proceed` to the First Response gate.

**Do not Read the project spec body during Phase 0** — not even with `offset`/`limit ≤ 500`. The runtime hook `pre_spec_split_enforce.py` permits paginated reads as a safety valve for unrelated long documents, but the conductor agent's discipline rule (`project-conductor.md` §First Response HARD GATE) forbids it on the project spec. Use `wc -l <spec>` for the size signal in `### 📋 Spec analysis`; the spec body waits until Phase 1, where `conductor-spec-splitter` handles >300-line specs and `conductor-spec-enrichment` handles the rest.

## Procedure

1. **Read personal preferences**
   - `~/.claude/CLAUDE.md` if exists
   - `<project>/CLAUDE.md` if exists

2. **Tier 1 lightweight scan** — counts only, no file bodies:
   ```bash
   ls ~/.claude/agents/ 2>/dev/null | wc -l
   ls .claude/agents/ 2>/dev/null | wc -l
   ls /mnt/skills/public/ ~/.claude/skills/ .claude/skills/ 2>/dev/null | wc -l
   ```
   Build a mental index of `{name → one-line description}` from agent metadata that Claude Code preloaded at session start. Do NOT open agent file bodies.

3. **Sanity check the metadata preload**: if `ls ~/.claude/agents/` returns N files, attempt to recall descriptions for 3 of them by name (first, middle, last alphabetically). If you cannot produce descriptions for any of the 3:
   - Flag in `environment.md`: "Subagent metadata not preloaded — falling back to explicit listing"
   - Read the first line (frontmatter `description:` field) of each agent file via Grep, NOT full body. Budget: 1k tokens for this fallback regardless of library size.
   - If even fallback cannot complete under budget, abort Phase 0 and report.

4. **Adaptive behavior based on inventory size:**
   - Small library (<20 agents): index all; deep-read up to 5 candidates total per session
   - Medium library (20–80 agents): index all names; deep-read up to 8 per session
   - Large library (80+ agents): build keyword index from descriptions; deep-read max 10% of library, capped at 12

5. **Tier 2 deep-read on demand** — only when routing a specific task:
   - Filter Tier 1 inventory by keyword match against task description and domain
   - 1 clear match → use it, no deep read needed
   - 2–3 candidates → read full body of candidates only (NOT all 150)
   - 0 matches → use general-purpose, log gap in `routing.md`
   - Track cumulative deep-reads against the adaptive cap

6. **MCPs:** identify from tools already exposed in the session. Do not probe.

7. **CLIs — project-aware scan only:**
   ```bash
   for cli in git node npm pnpm yarn bun; do command -v $cli >/dev/null 2>&1 && echo "✓ $cli"; done
   test -f supabase/config.toml && command -v supabase >/dev/null 2>&1 && echo "✓ supabase"
   test -e .vercel -o -f vercel.json && command -v vercel >/dev/null 2>&1 && echo "✓ vercel"
   test -f netlify.toml && command -v netlify >/dev/null 2>&1 && echo "✓ netlify"
   test -f Dockerfile && command -v docker >/dev/null 2>&1 && echo "✓ docker"
   test -f .github/workflows/*.yml 2>/dev/null && command -v gh >/dev/null 2>&1 && echo "✓ gh"
   ```
   Skip terraform/kubectl/aws/gcloud unless infrastructure files exist.

8. **Plugins:** check for Superpowers and others actually relevant to the spec.

9. **Project config (lightweight):**
   ```bash
   test -f package.json && grep -E '"(test|lint|build|typecheck|format|dev|start)"' package.json
   ls *.config.* 2>/dev/null
   ```

10. **Check existing permissions:**
    ```bash
    test -f .claude/settings.json && echo "exists: project settings"
    test -f .claude/settings.local.json && echo "exists: local settings"
    test -f ~/.claude/settings.json && echo "exists: global settings"
    ```
    Read existing settings if found.

11. **Initialize state directory:**
    ```bash
    mkdir -p .conductor/locks .conductor/evidence .conductor/probes
    ```
    All three are listed in **Outputs** above. Creating `.conductor/probes/` here (rather than lazily mid-investigation) keeps the Phase 0 mkdir surface concentrated to a single eyeballed line and avoids a later mkdir during a more sensitive phase where `pre_phase0_readonly` or `pre_lock_enforcement` may fire on adjacent calls.

12. **Build dynamic routing matrix (lazy):** "for capability X, use tool Y, fallback Z, or alert if missing." Do NOT pre-route every task. Routing happens just-in-time per task in Tier 2.

## Failure modes

- **Cannot complete under 30k token budget** → abort Phase 0, write a short `.conductor/environment.md` with what was scanned + the abort reason, surface to user.
- **Phase 0 violation attempted** (Write/Edit/source-mkdir/network probe) → STOP. Do not emit the First Response. Log to `.conductor/decisions.md` as a hard-stop class violation. Do not auto-recover.
- **Subagent metadata fully unavailable** even with fallback → continue with a degraded inventory; log in `environment.md`; surface to user as a known-limitation in the First Response so they can decide.
- **Capability required by spec is unavailable** → surface as a blocking gap in the First Response; do NOT proceed silently.
