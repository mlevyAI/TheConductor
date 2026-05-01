#!/usr/bin/env python3
"""
project-conductor — Usage Limit → ScheduleWakeup hook
Wired via PostToolUse hook (opt-in). Detects API rate-limit / usage-limit
errors in tool responses, computes a recommended wakeup time, and writes
`.conductor/usage-limit-paused.json` so the conductor can pick it up and
call ScheduleWakeup itself.

Why a hook + agent split:
- Hooks run as shell commands — they CANNOT invoke agent tools (like
  ScheduleWakeup). They can only signal via stdout (systemMessage JSON)
  and write state files.
- The agent sees the systemMessage on its next turn, reads
  `.conductor/usage-limit-paused.json`, and calls ScheduleWakeup with the
  recommended delay. The hook's job is detection + signaling.

Privacy & security:
- PURELY LOCAL — no network calls.
- Reads tool responses (which are passed to the hook by Claude Code).
- Writes only `.conductor/usage-limit-paused.json` and prints systemMessage.
- Does NOT touch .env, secrets, ssh keys, or anything outside .conductor/.
"""

import json
import sys
import os
import re
import datetime
import traceback
from pathlib import Path

try:
    import fcntl  # type: ignore
    _HAS_FLOCK = True
except ImportError:
    _HAS_FLOCK = False

# Bump when the paused-state file format changes incompatibly.
PAUSED_SCHEMA_VERSION = 1


# Patterns indicating usage/rate limit errors. Match case-insensitively
# against the tool error response body.
LIMIT_PATTERNS = [
    r"rate[\s_-]?limit",
    r"usage[\s_-]?limit",
    r"quota[\s_-]?exceeded",
    r"too[\s_-]?many[\s_-]?requests",
    r"\b429\b",
    r"resource_exhausted",
    r"limit[\s_-]?reached",
    r"over[\s_-]?quota",
]

# Patterns to extract a "resets in N <unit>" or "retry after N seconds" hint
RESET_PATTERNS = [
    re.compile(r"reset[s]?\s+(?:in|at)\s+(\d+)\s*(second|sec|minute|min|hour|hr)s?", re.I),
    re.compile(r"retry[\s\-]?after[:\s]+(\d+)\s*(second|sec|minute|min|hour|hr)?s?", re.I),
    re.compile(r"try\s+again\s+(?:in\s+)?(\d+)\s*(second|sec|minute|min|hour|hr)s?", re.I),
    re.compile(r"available\s+(?:in|at)\s+(\d+)\s*(second|sec|minute|min|hour|hr)s?", re.I),
]

DEFAULT_WAIT_SECONDS = 30 * 60  # 30 minutes


def find_conductor_dir():
    """Walk up from cwd looking for nearest .conductor/. Fallback: create in cwd."""
    cwd = Path.cwd()
    for candidate in [cwd] + list(cwd.parents):
        cd = candidate / ".conductor"
        if cd.exists() and cd.is_dir():
            return cd
    cd = cwd / ".conductor"
    cd.mkdir(parents=True, exist_ok=True)
    return cd


def matches_limit(text: str) -> bool:
    if not text:
        return False
    for pat in LIMIT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def extract_reset_seconds(text: str) -> int:
    """Return suggested wait in seconds based on patterns in error text. Fallback to DEFAULT."""
    for pat in RESET_PATTERNS:
        m = pat.search(text)
        if m:
            n = int(m.group(1))
            unit = (m.group(2) or "").lower() if m.lastindex and m.lastindex >= 2 else ""
            if unit.startswith("hour") or unit.startswith("hr"):
                return n * 3600
            if unit.startswith("min"):
                return n * 60
            if unit.startswith("sec") or unit == "":
                return n
    return DEFAULT_WAIT_SECONDS


def log_hook_error(conductor_dir, exc):
    """Surface failures to .conductor/hook-errors.log instead of swallowing
    them. Without this, a broken hook never wakes the conductor and the
    user has no signal that recovery is dead."""
    try:
        err_path = conductor_dir / "hook-errors.log"
        with open(err_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(),
                "hook": "usage_limit_wakeup.py",
                "error": str(exc),
                "traceback": traceback.format_exc()[:1000],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def write_paused_state(paused_path, payload):
    """Write under exclusive lock so two near-simultaneous limit errors
    don't produce a half-written file or a torn JSON."""
    fd = os.open(str(paused_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        if _HAS_FLOCK:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError:
                pass
        os.write(fd, json.dumps(payload, indent=2).encode("utf-8"))
    finally:
        os.close(fd)


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return  # No payload — silently exit

    tool_response = data.get("tool_response")
    if not isinstance(tool_response, dict):
        return
    if not tool_response.get("is_error"):
        return

    err_text = str(tool_response.get("content", ""))
    if not matches_limit(err_text):
        return

    # Detected — compute wakeup
    wait_seconds = extract_reset_seconds(err_text)
    now = datetime.datetime.now()
    resume_at = now + datetime.timedelta(seconds=wait_seconds)

    conductor_dir = find_conductor_dir()
    paused_path = conductor_dir / "usage-limit-paused.json"

    try:
        write_paused_state(paused_path, {
            "schema_version": PAUSED_SCHEMA_VERSION,
            "detected_at": now.isoformat(),
            "expected_resume_at": resume_at.isoformat(),
            "wait_seconds": wait_seconds,
            "tool": data.get("tool_name", ""),
            "reason": err_text[:300],
            "instruction_for_agent": (
                "Usage limit detected. Read this file, then call ScheduleWakeup "
                f"with delaySeconds={wait_seconds} and reason='resume after usage limit reset'. "
                "After scheduling, surface a one-line notification to the user "
                "(no need to ask permission — this is the planned recovery path)."
            ),
        })
    except Exception as exc:
        log_hook_error(conductor_dir, exc)
        return

    msg = (
        f"[Usage Limit] Detected rate-limit/usage-limit error from {data.get('tool_name', 'tool')}. "
        f"Wrote {paused_path} with recommended wakeup at {resume_at.strftime('%H:%M:%S')} "
        f"(in ~{wait_seconds // 60} min). The conductor will pick this up and ScheduleWakeup."
    )
    print(json.dumps({"systemMessage": msg}))


if __name__ == "__main__":
    main()
