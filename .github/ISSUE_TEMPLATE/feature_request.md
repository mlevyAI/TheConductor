---
name: Feature request / new detector
about: A new safety mechanism, hard stop, routing rule, or anti-pattern detector
title: "[feature] "
labels: enhancement
assignees: ""
---

<!--
Project-conductor accepts features that address a *real* failure mode you
observed. Speculative features without a concrete failure behind them are
typically declined — see CONTRIBUTING.md ("What NOT to contribute").
-->

## The failure mode this would address

<!--
Describe the agent behavior you observed and why the current conductor
doesn't catch it. Reference the phase, the subagent, or the rule that
should have intervened but didn't.
-->

## Proposed change

<!--
Where in the conductor it lives:
- [ ] `project-conductor.md` (rule / phase / hard stop)
- [ ] A skill under `skills/conductor-*/`
- [ ] A hook under `hooks/`
- [ ] A new detector in `agent-monitor/reporter.py`
- [ ] Other: ____
-->

## If proposing a new agent-monitor detector

<!--
Express the pattern as a counter or regex if possible. Example:
- Name: subagent-thrash
- Trigger: ≥3 Agent dispatches with same `subagent_type` and >70% prompt similarity
- Why it matters: agent re-prompting the same subagent instead of changing strategy
- Suggested fix message: "Pause and re-evaluate routing — three near-identical dispatches usually means the wrong subagent type."
-->

## Evidence

<!--
The smallest excerpt from a real run that shows the failure mode. Quote a
few rows from `.conductor/status.md` or the agent-monitor report — do not
paste the full report. Redact absolute paths.
-->

```
[paste here]
```
