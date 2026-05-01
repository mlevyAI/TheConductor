#!/usr/bin/env python3
"""
Agent Monitor — Logger
Appends structured events to activity.jsonl for every tool call.
Wired via PreToolUse, PostToolUse, and SessionStart hooks.

This script is path-agnostic — it stores its log next to itself, so you can
copy the entire `agent-monitor/` directory into any project's `.claude/`
subdirectory without editing paths.

Privacy: all data stays local. Nothing leaves your machine.
"""

import json
import sys
import os
import re
import datetime
import traceback

# Best-effort file locking. fcntl is unavailable on Windows-native Python,
# so we degrade to no-op there (WSL/macOS/Linux all support it).
try:
    import fcntl  # type: ignore
    _HAS_FLOCK = True
except ImportError:
    _HAS_FLOCK = False

LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "activity.jsonl")
HOOK_ERRORS_FILE = os.path.join(LOG_DIR, "hook-errors.log")

# Patterns matched against bash commands and agent prompts BEFORE they're
# written to activity.jsonl. Goal: catch the common ways a secret ends up
# on the command line or pasted into a prompt, so the on-disk log (and
# anything the user later shares) doesn't carry the raw secret. This is
# a best-effort filter — exotic formats will slip through; treat the log
# as still-sensitive even after redaction.
SECRET_PATTERNS = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "sk-[REDACTED]"),
    (re.compile(r"sk_(?:test|live)_[A-Za-z0-9_\-]{10,}"), "sk_[REDACTED]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "ghp_[REDACTED]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github_pat_[REDACTED]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "xox-[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{10,}", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(Authorization:\s*)[^\s]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(api[_-]?key\s*[=:]\s*)[^\s&'\"]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(secret[_-]?key\s*[=:]\s*)[^\s&'\"]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(access[_-]?token\s*[=:]\s*)[^\s&'\"]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(token\s*[=:]\s*)[A-Za-z0-9._\-]{12,}", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(password\s*[=:]\s*)[^\s&'\"]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(AWS_SECRET_ACCESS_KEY\s*=\s*)[^\s]+"), r"\1[REDACTED]"),
)


def sanitize(text):
    if not text:
        return text
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def log_hook_error(exc):
    """Surface hook failures instead of swallowing them. The reporter reads
    this file and warns the user at session-end, so a silently-broken
    logger can't run for weeks unnoticed."""
    try:
        with open(HOOK_ERRORS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(),
                "hook": "logger.py",
                "error": str(exc),
                "traceback": traceback.format_exc()[:1000],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Last resort — if we can't even write the error, give up silently.


def extract_summary(tool: str, tool_input: dict) -> dict:
    if tool == "Bash":
        return {"cmd": sanitize(str(tool_input.get("command", "")))[:600]}
    if tool in ("Write", "Edit", "Read", "NotebookEdit"):
        s = {"file": tool_input.get("file_path", "")}
        if tool == "Write":
            s["bytes"] = len(str(tool_input.get("content", "")))
        elif tool == "Edit":
            s["old_preview"] = sanitize(str(tool_input.get("old_string", "")))[:120]
            s["new_preview"] = sanitize(str(tool_input.get("new_string", "")))[:120]
        return s
    if tool == "Agent":
        return {
            "description": tool_input.get("description", ""),
            "subagent_type": tool_input.get("subagent_type", "general-purpose"),
            "background": tool_input.get("run_in_background", False),
            "prompt_preview": sanitize(str(tool_input.get("prompt", "")))[:300],
        }
    if tool == "WebSearch":
        return {"query": tool_input.get("query", "")}
    if tool == "WebFetch":
        return {"url": tool_input.get("url", "")}
    if tool == "Glob":
        return {"pattern": tool_input.get("pattern", ""), "path": tool_input.get("path", "")}
    if tool == "Grep":
        return {"pattern": tool_input.get("pattern", ""), "path": tool_input.get("path", "")}
    if tool == "Skill":
        return {"skill": tool_input.get("skill", ""), "args": tool_input.get("args", "")}
    if tool == "TaskCreate":
        return {"subject": tool_input.get("subject", ""), "description": sanitize(str(tool_input.get("description", "")))[:200]}
    if tool == "ScheduleWakeup":
        return {"delaySeconds": tool_input.get("delaySeconds"), "reason": tool_input.get("reason", "")}
    return {k: sanitize(str(v))[:150] for k, v in list(tool_input.items())[:5]}


def append_event(entry):
    """Append one JSON line under an exclusive file lock so concurrent
    PostToolUse hooks (parallel tool calls) don't interleave writes."""
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        if _HAS_FLOCK:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except OSError:
                pass  # Filesystem doesn't support flock (some network FS) — proceed.
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # Lock auto-released on close.


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response")

    if tool:
        event_type = "post_tool" if tool_response is not None else "pre_tool"
        entry = {
            "ts": datetime.datetime.now().isoformat(),
            "event": event_type,
            "tool": tool,
            **extract_summary(tool, tool_input),
        }
        if tool_response is not None:
            if isinstance(tool_response, dict):
                entry["success"] = not tool_response.get("is_error", False)
                if tool_response.get("is_error"):
                    entry["error"] = sanitize(str(tool_response.get("content", "")))[:300]
            else:
                entry["success"] = True
    else:
        entry = {
            "ts": datetime.datetime.now().isoformat(),
            "event": "session_start",
            "session_id": data.get("session_id", ""),
        }

    append_event(entry)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log_hook_error(exc)
