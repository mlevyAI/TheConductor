# Agent Monitor

Optional bundled monitoring for project-conductor (and Claude Code in general).

## What it does

- **Logs every tool call** the agent makes — Bash, Read, Write, Edit, Agent, Skill, WebSearch, etc. — to `activity.jsonl`.
- **Generates a markdown report** at the end of each session with tool usage, files touched, agents spawned, and bash commands executed.
- **Auto-detects anti-patterns** (NEW in v4): probe sprawl, busy-wait loops, no-forward-progress clusters, repeat-bash, scope-shrink signals. Findings appear in a pre-filled "Issues & Patterns to Improve" table at the top of the report.
- **Includes an opt-in share-footer** with a GitHub issue URL template, so you can contribute interesting patterns back to the maintainers.

## Privacy

**All data stays local.** Nothing is sent anywhere. The reporter writes to your local disk only. The share-footer is just a URL template — you decide whether to click it, what to paste, and what to redact first.

> ⚠️ **Add the log paths to your project's `.gitignore` after copying.** `logger.py` writes `activity.jsonl` and `reporter.py` writes `reports/` next to the script. Once you copy `agent-monitor/` into your own project, those files live inside *your* repo tree — and they capture bash commands (which may include tokens or secrets pasted on the command line), agent prompts, and file paths. If you `git add .` and push, that data becomes public on your remote. Add this to your project's `.gitignore` immediately after the copy in step 1:
>
> ```
> .claude/agent-monitor/activity.jsonl
> .claude/agent-monitor/reports/
> ```

## Install (3 steps)

### 1. Copy the directory into your project's `.claude/`

```bash
cp -r agent-monitor/ /path/to/your/project/.claude/
```

After this you should have:
```
/path/to/your/project/.claude/agent-monitor/
  ├── logger.py
  ├── reporter.py
  ├── README.md
  └── example-settings.json
```

### 2. Wire the hooks into your settings

Open `example-settings.json` for reference. Copy its `hooks` block into your project's `.claude/settings.json` (committed, shared with team) or `.claude/settings.local.json` (personal, gitignored).

**You must replace `<absolute-path-to>` with the real absolute path** to your `agent-monitor/` directory. Example for a project at `/home/me/myproject/`:

```json
"hooks": {
  "SessionStart": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"/home/me/myproject/.claude/agent-monitor/logger.py\"",
          "async": true
        }
      ]
    }
  ],
  ...
}
```

(Same path for `PreToolUse`, `PostToolUse`. Use `reporter.py` for `Stop`.)

### 3. Allow the hook commands in your permissions

Add to your `.claude/settings.json` `permissions.allow`:

```json
"Bash(python3 \"/home/me/myproject/.claude/agent-monitor/logger.py\")",
"Bash(python3 \"/home/me/myproject/.claude/agent-monitor/reporter.py\")"
```

This avoids permission prompts on every tool call.

## Output

After each Claude Code session ends (Stop hook fires), you'll see in the UI:

```
[Agent Monitor] Report saved → /path/to/.claude/agent-monitor/reports/report_2026-04-26_14-30-00.md
```

Open the markdown file to see:
- **Issues & Patterns to Improve** — auto-detected anti-patterns, with observations + impact + suggested fix
- **Per-session breakdown** — tool counts, bash commands, files touched, agents spawned
- **Share footer** — opt-in URL template if you want to file a useful report upstream

## What it auto-detects

| Pattern | Threshold | Why it matters |
|---|---|---|
| **Probe sprawl** | ≥3 throwaway research scripts (`probe*.py`, `scratch*.py`, `smoke_*.py`, ad-hoc `test_*.py`) written without later edits | Agent stuck in research mode instead of committing to a draft |
| **Busy-wait** | ≥2 bash commands using `until ... ; do sleep N; done` | Burns turns/tokens with zero forward progress; should use ScheduleWakeup or mtime-poll |
| **No-forward-progress cluster** | ≥10 consecutive tool calls without any Write/Edit | Reading/diagnosing without producing output |
| **Repeat-bash** | Identical bash command ≥3 times | Often indicates a stuck-check loop |
| **Scope-shrink signals** | Agent prompt contains `wrap up`, `deliver partial`, `stop here`, `give up on`, etc. | Agent is reducing scope under perceived pressure instead of delivering partial output and continuing |

Detection thresholds are configurable in `reporter.py` — search for the constants near the top.

## Contributing back

The auto-detection patterns above are derived from real-world test sessions. If you spot a NEW failure mode the detector misses, please:

1. Note the pattern (when it triggered, what the agent was doing, what impact it had)
2. Open an issue on the project-conductor repo using the share-footer URL in your report
3. If you can express the pattern as a regex or counter, propose a PR that adds a detector

The most valuable monitor reports are the ones that catch behavior the maintainers haven't seen yet.

## Uninstall

Remove the `hooks` block from your settings file, delete the `agent-monitor/` directory, and remove the two `Bash(python3 ...)` permissions. No other cleanup needed.
