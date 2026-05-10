#!/usr/bin/env python3
"""
Agent Monitor — Self-learning SessionStart hook (Layer 2).

Reads .claude/agent-monitor/memory.json (written by reporter.py at the end of
each session) and emits a short advisory `additionalContext` block via the
SessionStart hook protocol so the agent starts the new session aware of
anti-patterns it has tripped in this project before.

Privacy:
- Purely local. Reads memory.json and writes last_injection.md (consumed and
  cleared by reporter.py at the next Stop). Nothing leaves the machine.
- memory.json contains ONLY pattern_ids + counts + timestamps. No paths,
  commands, prompts, or project names are stored there.

Failure-safety:
- Never blocks. Any error → log to hook-errors.log and exit 0 with no output.
- Honors a `selflearn.disabled` flag file: if present, emit nothing.

Tunables (constants near the top): MAX_PATTERNS, INJECTION_TOKEN_BUDGET.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import datetime

LOG_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(LOG_DIR, "memory.json")
LAST_INJECTION_FILE = os.path.join(LOG_DIR, "last_injection.md")
DISABLED_FLAG = os.path.join(LOG_DIR, "selflearn.disabled")
HOOK_ERRORS_FILE = os.path.join(LOG_DIR, "hook-errors.log")

# Top-N patterns by hit-count to surface in the injection. Hard cap.
MAX_PATTERNS = 5

# Soft token budget for the injected context. We approximate 1 token ~= 4 chars.
# At 300 tokens that's ~1200 chars; we truncate aggressively if exceeded.
INJECTION_CHAR_BUDGET = 1200

# One-line "avoid" advice per pattern_id. The pattern_ids match the `id` field
# in reporter.detect_patterns(). Keep these short — they're injected verbatim.
PATTERN_ADVICE = {
    "probe_sprawl": (
        "Don't write more than 2 throwaway research scripts before committing "
        "to a draft implementation. Iterate against real failures."
    ),
    "busy_wait": (
        "Don't write `until ...; do sleep N; done` loops. Use ScheduleWakeup "
        "for time-based polling or an mtime check for event-based polling."
    ),
    "repeat_bash": (
        "If you run the same bash command 3+ times, pause and reconsider — "
        "it usually means a stuck-check loop. Switch to event-driven polling."
    ),
    "no_forward_progress": (
        "After ~10 read-only tool calls with zero Write/Edit, force a draft "
        "commit so progress is observable. Diagnosing? Capture findings to a file."
    ),
    "scope_shrink": (
        "Don't auto-shrink scope under perceived budget pressure. Deliver "
        "partial output (rolling save) and continue — partial-200 beats clean-55."
    ),
}


def _log_error(msg: str) -> None:
    try:
        with open(HOOK_ERRORS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "hook": "selflearn.py",
                "error": msg[:500],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _drain_stdin() -> None:
    try:
        sys.stdin.read()
    except Exception:
        pass


def _load_memory() -> dict | None:
    if not os.path.exists(MEMORY_FILE):
        return None
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def build_injection(memory: dict) -> str:
    """Return the advisory text to inject, or empty string if nothing to say."""
    patterns = memory.get("patterns") or {}
    if not patterns:
        return ""
    sessions_observed = memory.get("sessions_observed", 0)
    if sessions_observed == 0:
        return ""

    # Top-N by hits, ties broken by most-recent last_seen.
    ranked = sorted(
        patterns.items(),
        key=lambda kv: (kv[1].get("hits", 0), kv[1].get("last_seen", "")),
        reverse=True,
    )
    ranked = ranked[:MAX_PATTERNS]

    lines = [
        f"[Self-learning context — based on your last {sessions_observed} session(s) in this project]",
        "The following anti-patterns recurred. Avoid repeating them this session:",
        "",
    ]
    for pid, stats in ranked:
        advice = PATTERN_ADVICE.get(pid)
        if not advice:
            continue
        hits = stats.get("hits", 0)
        lines.append(f"- {pid} ({hits} of last {sessions_observed}): {advice}")
    lines.append("")
    lines.append(
        "This context is local-only and based on agent-monitor reports from "
        "this project. Disable with `touch .claude/agent-monitor/selflearn.disabled`."
    )

    text = "\n".join(lines)
    if len(text) > INJECTION_CHAR_BUDGET:
        text = text[:INJECTION_CHAR_BUDGET].rsplit("\n", 1)[0] + "\n…"
    return text


def _record_injection(text: str) -> None:
    """Persist the injection so reporter.py can show it in the next session report."""
    try:
        with open(LAST_INJECTION_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def main() -> int:
    try:
        _drain_stdin()
        if os.path.exists(DISABLED_FLAG):
            return 0
        memory = _load_memory()
        if memory is None:
            return 0  # cold start — nothing to inject
        injection = build_injection(memory)
        if not injection:
            return 0
        _record_injection(injection)
        # Claude Code SessionStart hook protocol: emit JSON with
        # hookSpecificOutput.additionalContext to inject context for the agent.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": injection,
            }
        }))
        return 0
    except Exception:
        _log_error("uncaught: " + traceback.format_exc())
        return 0  # never block the session


if __name__ == "__main__":
    sys.exit(main())
