---
name: conductor-debug-map
description: Generate the surgical debug map section of the FINAL_REPORT, mapping each delivered feature to its files, commits, subagent used, key decisions, and known limitations. The format is designed to be quoted back to Claude for targeted bug fixes.
allowed-tools: Read, Bash(git log,git show,git diff)
---

## When to invoke

The conductor invokes this skill once per session, during Final Delivery Report generation, after all phases have completed and the in-chat summary has been emitted. The output of this skill is appended to `.conductor/FINAL_REPORT.md` (the file written to disk, not the chat summary).

## Inputs

- `.conductor/plan.md` — task list with statuses
- `.conductor/progress.md` — chronological log
- `.conductor/decisions.md` — choices with rationale
- `.conductor/deviations.md` — in-scope fixes and lock violations
- `.conductor/findings.md` — emergent issues
- `git log` from session start to now

## Outputs

- A markdown section appended to `.conductor/FINAL_REPORT.md` with the structure below
- One feature block per major delivered feature (typically 3–10 blocks per session)

## Procedure

1. **Extract the feature list** from `plan.md` — each completed phase delivers one or more features. A "feature" is a user-visible capability (e.g., "user signup endpoint", "RLS policies for invoices table"). Do NOT include sub-tasks that were implementation details of a feature.

2. **For each feature, gather:**
   - Phase + Tasks where it was built (e.g., `Phase 2, Tasks 3–5`)
   - Primary files (paths, from `routing.md` and `git diff --name-only`)
   - Database tables touched (from task `Resources` annotations)
   - Test files (from primary files, filtered by `*.test.*` / `*_test.*`)
   - Key commit SHAs (`git log --oneline <range>`)
   - Subagent used (from `routing.md`)
   - Model requested (from `routing.md` — note "as requested vs as actually run" if model routing was suspected)
   - Key decisions referenced (from `decisions.md`)
   - Emergent fixes (from `deviations.md`)
   - Known limitations (from `findings.md` — only `unverified — N approaches tried` rows; the phrase `KNOWN LIMITATION` is banned)

3. **Write the feature block** in this format:

   ```markdown
   #### Feature: [Name]
   - **Built in**: Phase [P], Tasks [range]
   - **Primary files**: [paths]
   - **Database**: [tables]
   - **Tests**: [paths]
   - **Key commits**: [SHAs]
   - **Subagent used**: [name] ([model requested — possibly different from actual])
   - **Key decisions**: [refs to decisions.md entries]
   - **Emergent fixes**: [refs to deviations.md entries]
   - **Known limitations**: [if any — must be of the form "unverified — N approaches tried: [list]"]
   ```

4. **Append the "How to use" preamble** at the top of the debug map section:

   ```markdown
   ## 🔧 Surgical Debug Map

   **Use this to fix bugs found after delivery.**

   ### How to use
   > "Bug in [feature]. Per debug map: phase [P.T], files [list], commit [SHA].
   > Fix surgically without touching unrelated code."

   ### Feature → Debug Context map
   ```

5. **Validate completeness** before returning:
   - Every feature in `plan.md` with status=complete must have a block
   - No block can have `Known limitations: KNOWN LIMITATION` (banned phrase) — replace with the unverified-N-approaches form
   - No block can list a commit SHA that doesn't appear in `git log`

## Failure modes

- **`git log` returns empty** (no commits in this session) → emit a single block per feature listing files only (no commits); add a one-line note "No commits in this session — files referenced are uncommitted as of report time."
- **A feature has no entry in `routing.md`** (routing was inline, no subagent) → use `subagent: inline` and skip the model line.
- **Feature in `plan.md` is marked complete but no files were written** → flag as a verification gap; do NOT emit the block; surface to user as "feature [X] marked complete but no files / commits / tests found — investigate."
- **`KNOWN LIMITATION` phrase detected** in any code file (via `grep -r "KNOWN LIMITATION"`) → STOP. The phrase is banned. Refuse to generate the report until it's replaced with the unverified-N-approaches form. Surface to user.
