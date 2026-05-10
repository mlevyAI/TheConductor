---
name: Bug report
about: A failure mode you hit while running project-conductor
title: "[bug] "
labels: bug
assignees: ""
---

<!--
Before filing: check open issues for an existing report. Quote the smallest
piece of state that demonstrates the failure — do NOT paste full agent-monitor
reports or activity.jsonl dumps. They're noisy and tend to leak absolute paths.
-->

## What you ran

- **Spec / task** (1–2 sentences):
- **Conductor version** (from `CHANGELOG.md` top entry, or commit SHA):
- **Claude Code version** (`claude --version`):
- **OS**:
- **Bundles installed**: [ ] agent-monitor [ ] heartbeat [ ] usage_limit_wakeup

## What happened

<!-- Actual behavior. Be specific: which phase, which subagent, which file. -->

## What you expected

<!-- The correct behavior, per project-conductor.md or your understanding. -->

## Minimal reproduction

<!--
Smallest excerpt that demonstrates the issue. Examples of useful evidence:
- 5–20 lines of `.conductor/status.md` covering the bad transition
- The single agent prompt that mis-routed
- The detector row from agent-monitor's report (just the row, not the whole report)
- The exact bash command that failed and its error
Redact absolute paths (`/home/...`, `/Users/...`) and any tokens before pasting.
-->

```
[paste here]
```

## Hypothesis (optional)

<!-- If you have a theory about the root cause or a candidate fix, share it. -->
