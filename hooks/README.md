# project-conductor — Hooks

This directory contains all hooks that ship with project-conductor. As of v6.0.3 they fall into **two install paths**:

## (A) Auto-installed in Phase 0a — enforcement hooks (9 total)

The conductor automatically wires these into `<project>/.claude/settings.json` on the first session in a project, before Phase 0 begins. They convert the conductor's prompt-only rules into deterministic runtime enforcement. No prompt; no opt-in. The user signed up for them by invoking the conductor.

**`bundle: phase_b`** (6 hooks, since v3–v5):

| File | Event | Blocking? | Purpose |
|---|---|---|---|
| `pre_phase0_readonly.py` | PreToolUse | yes | Phase 0 strict read-only |
| `pre_first_response_gate.py` | PreToolUse | yes | First Response hard gate (overrides accept-edits) |
| `pre_busy_wait_block.py` | PreToolUse | yes | Forbids busy-wait Bash patterns |
| `pre_lock_enforcement.py` | PreToolUse | yes | Files-write declaration enforcement |
| `post_output_quality.py` | PostToolUse | no | Structured-output completeness check |
| `stop_validate_final_report.py` | Stop | no | FINAL_REPORT.md section validator |

**`bundle: v6_replayability`** (3 hooks, since v6):

| File | Event | Blocking? | Purpose |
|---|---|---|---|
| `pre_state_committed.py` | PreToolUse | no | Advisory if `.conductor/` is gitignored |
| `pre_spec_split_enforce.py` | PreToolUse | yes | Blocks Read of large unsplit specs |
| `stop_evidence_completeness_check.py` | Stop | no | Flags tasks with no recorded commit_sha |

The canonical list lives in `hooks/MANIFEST.json` and is generated into settings.json by `lib/hooks_manifest.py::render_settings_block(["phase_b", "v6_replayability"], hook_dir=...)`. See `project-conductor.md` § Phase 0a for the install procedure.

### Removing the auto-installed enforcement hooks

If you want to disable enforcement (not recommended — these hooks catch known agent failure modes), edit `<project>/.claude/settings.json` and remove the relevant entries from `hooks.PreToolUse`, `hooks.PostToolUse`, and `hooks.Stop`. Permissions in `permissions.allow` can stay (no-ops without the hook commands). The agent will not re-install them on subsequent sessions because `.conductor/state.json` exists by then (Phase 0a is first-session-only).

## (B) Opt-in via Optional Bundles Offer — monitoring / recovery (2 hooks)

These have privacy or runtime characteristics that warrant explicit consent. They're offered in the conductor's First Response and installed only after the user replies `install 1,2,3` (or any subset).

| File | Event | Bundle | Purpose |
|---|---|---|---|
| `heartbeat.py` | PostToolUse | `monitoring` | Updates `.conductor/heartbeat.json` so parent agents can read background-mode status without spawning a second conductor instance |
| `usage_limit_wakeup.py` | PostToolUse | `recovery` | Detects API rate-limit / usage-limit errors, writes `.conductor/usage-limit-paused.json` with a recommended wakeup time, and prints a systemMessage so the conductor can pick it up and call `ScheduleWakeup` |

The third bundle in the offer is **`agent-monitor/`** (a separate directory), which logs every tool call's bash command + agent prompt snippet — review the README in that directory before installing.

## Why opt-in for the monitoring/recovery bundle

`heartbeat.py` and `usage_limit_wakeup.py` write `.conductor/heartbeat.json` and `.conductor/usage-limit-paused.json` continuously throughout a session, and `agent-monitor/` records command/prompt content. They're harmless (no network, no secrets) but they ARE observation tools. Explicit consent is preserved for them.

## Security & privacy notes

Both scripts:
- Make NO network calls
- Read NO secrets, NO `.env`, NO `.ssh`, NO `.aws` credentials
- Write ONLY to `.conductor/heartbeat.json` and `.conductor/usage-limit-paused.json` (your own project state)
- Print only short systemMessage strings (no payloads, no tool input/output sent anywhere)

You can read both scripts top-to-bottom in under 5 minutes. Do that before installing if you're being cautious — recommended.

## Install

### 1. Copy the directory into your project's `.claude/`

```bash
cp -r hooks/ /path/to/your/project/.claude/
```

### 2. Wire the hooks into your settings

Open `.claude/settings.json` (committed) or `.claude/settings.local.json` (gitignored, personal). Add to the `hooks.PostToolUse` array:

```json
"hooks": {
  "PostToolUse": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"/path/to/your/project/.claude/hooks/heartbeat.py\"",
          "async": true
        },
        {
          "type": "command",
          "command": "python3 \"/path/to/your/project/.claude/hooks/usage_limit_wakeup.py\"",
          "async": true
        }
      ]
    }
  ]
}
```

You can install **either or both**. Replace `/path/to/your/project/` with the real absolute path.

### 3. Allow the hook commands in your permissions

Add to `permissions.allow`:

```json
"Bash(python3 \"/path/to/your/project/.claude/hooks/heartbeat.py\")",
"Bash(python3 \"/path/to/your/project/.claude/hooks/usage_limit_wakeup.py\")"
```

## How they interact with the conductor

### `heartbeat.py`

- After every tool call, this hook updates `.conductor/heartbeat.json` with a timestamp and the last tool name.
- It also computes a `stuck_check` field: `"ok"` if there was a recent Write/Edit, `"slowing"` if no progress signal in 2 min, `"stuck"` if none in 5 min.
- The conductor reads this file (or the parent agent reads it on the conductor's behalf) for instant status. **No second conductor instance needed for status checks.**
- Cost: ~10ms per tool call. Negligible.

### `usage_limit_wakeup.py`

- Watches every PostToolUse for error responses matching usage-limit patterns (`rate limit`, `usage limit`, `quota exceeded`, `429`, `resource_exhausted`, etc.).
- On detection: extracts a recommended wait time from the error message if present (e.g., "resets in 47 minutes"), or defaults to 30 minutes.
- Writes `.conductor/usage-limit-paused.json` with `{detected_at, expected_resume_at, wait_seconds, instruction_for_agent}`.
- Prints a systemMessage to the chat so you (and the conductor) immediately see what was detected.
- The conductor then reads this file and calls `ScheduleWakeup(delaySeconds=wait_seconds, reason="resume after usage limit reset")` — recovery is automatic.

**Why a hook + agent split:** hooks are shell commands; they cannot directly call agent tools like `ScheduleWakeup`. So the hook detects + signals, and the agent acts on the signal.

## Reading the heartbeat from a parent agent

If you've spawned the conductor as a backgrounded subagent and want to check on it from the parent Claude Code session:

```bash
cat /path/to/your/project/.conductor/heartbeat.json
```

You'll see something like:

```json
{
  "ts": "2026-04-26T14:30:00",
  "last_action": "Bash",
  "last_progress_signal": "Write at 2026-04-26T14:29:42",
  "tool_calls_since_last_progress": 3,
  "stuck_check": "ok",
  "phase": "2.3",
  "task": "scrape lego.com/de-de SKU 42198"
}
```

That's your status. No need to spawn another conductor (which would cost 50k+ tokens just to query state).

## Uninstall

Remove the `hooks` block from your settings file, delete the `hooks/` directory, and remove the relevant `Bash(python3 ...)` permissions. No other cleanup needed.

## Contributing

Found a usage-limit error pattern that the regex doesn't match? Open a PR. The patterns live at the top of `usage_limit_wakeup.py` (`LIMIT_PATTERNS`, `RESET_PATTERNS`).
