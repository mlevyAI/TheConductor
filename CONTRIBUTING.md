# Contributing to Project Conductor

Thank you for your interest. Contributions are welcome.

## What's worth contributing

The most valuable contributions are:
- **Real failure modes** you encountered while running the conductor — what condition triggered it, what actually happened vs. what should have happened
- **Environment compatibility** — gaps where the conductor assumed something about Claude Code that didn't hold in your version/config
- **Routing improvements** — cases where tasks were routed to the wrong subagent and how you fixed it
- **New hard stop conditions** — situations that should have been a hard stop but weren't
- **New anti-pattern detectors** for `agent-monitor/reporter.py` — if you spot a behavior the auto-detection misses, propose a regex or counter

Less valuable: cosmetic changes, speculative features, or additions that increase complexity without addressing a real failure mode.

## How to file an issue

Use the issue templates in `.github/ISSUE_TEMPLATE/`. The bug-report template asks for:

- **What you ran** — the spec, the command, the conductor version
- **What happened** vs. **what you expected**
- **Minimal reproduction** — the smallest excerpt that demonstrates the failure (a single phase output, a `status.md` snippet, the prompt that mis-routed). Do **not** paste full session reports or `activity.jsonl` dumps; they're noisy and tend to leak absolute paths.
- **Environment** — OS, Claude Code version, conductor version

If you have an `agent-monitor/` report that captured the failure, quote only the relevant rows from the "Issues & Patterns to Improve" table. Redact paths first.

## How to open a pull request

1. **Fork the repo** and create a branch from `main`
2. **Make your change** in `project-conductor.md`, the relevant skill, or a hook
3. **Test it** — run the conductor on at least one real project with your change
4. **Describe the failure mode** your change addresses (or the gap it fills) in the PR description
5. **Reference evidence** — quote the smallest excerpt from `.conductor/status.md` or `FINAL_REPORT.md` that demonstrates the problem and the fix

## PR description format

```
## What this fixes / adds

[One paragraph: the specific failure mode or gap]

## Evidence

[Smallest excerpt from .conductor/status.md, FINAL_REPORT.md, or a run transcript that shows the problem and/or the fix]

## How it's tested

[Which spec/project you ran it against, outcome]
```

## Versioning

Project Conductor uses [Semantic Versioning](https://semver.org/):

- **PATCH** (1.0.x) — bug fixes to existing mechanisms, no behavior changes
- **MINOR** (1.x.0) — new safety mechanisms, new governance rules, new outputs
- **MAJOR** (x.0.0) — changes to the three prime directives, the phase structure, or the hard stop hierarchy

## What NOT to contribute

- Changes that reduce safety (removing checkpoints, relaxing hard stops, enabling auto-Opus escalation)
- Hardcoded tool assumptions — the conductor must adapt to what's available
- Line-level implementation detail in status/progress files — those are operator outputs, not documentation
- Speculative features without a real failure mode behind them
- Raw `agent-monitor/` reports or `activity.jsonl` dumps. Quote the smallest excerpt that demonstrates the issue instead.

## A note on agent-monitor reports

The `agent-monitor/` bundle is a **local** debugging tool. Its reports stay on your machine. There is no upload, no telemetry, and no expectation that you share them. If a report helps you describe a failure mode, quote a short excerpt in your issue or PR — but the report itself is for you, not for upstream.

## Questions

Open an issue. Describe the run that produced the unexpected behavior and quote the smallest piece of `.conductor/` state that demonstrates it.
