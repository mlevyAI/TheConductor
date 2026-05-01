#!/usr/bin/env python3
"""
project-conductor — Heartbeat hook
Wired via PostToolUse hook (opt-in). Writes/updates `.conductor/heartbeat.json`
in the current working directory's nearest `.conductor/` ancestor (or cwd if none).

Purpose:
- When the conductor is running as a backgrounded subagent, parent agents
  cannot see its progress. This file gives them a cheap, file-based status
  source — no need to spawn a second conductor instance to query state.
- The heartbeat file is the protocol described in project-conductor.md
  ("Heartbeat for Background Mode" section, NEW in v4).

Privacy & security:
- PURELY LOCAL — no network calls.
- Reads NO secrets, NO .env, NO ssh keys.
- Writes only to `.conductor/heartbeat.json` (timestamps and tool names).
- Idempotent — safe to run on every PostToolUse event.
"""

import json
import sys
import os
import datetime
import traceback
from pathlib import Path

# Best-effort file locking. fcntl is unix-only; on Windows-native Python
# the heartbeat falls back to lock-free RMW (still safe single-threaded,
# only racy under parallel hook fires which is rare on Windows anyway).
try:
    import fcntl  # type: ignore
    _HAS_FLOCK = True
except ImportError:
    _HAS_FLOCK = False

# Bump when the heartbeat file format changes incompatibly.
# A conductor that reads a heartbeat with an unknown schema_version should
# treat the file as opaque rather than guess at fields.
HEARTBEAT_SCHEMA_VERSION = 1


def find_conductor_dir():
    """Walk up from cwd looking for nearest .conductor/. Fallback: create in cwd."""
    cwd = Path.cwd()
    for candidate in [cwd] + list(cwd.parents):
        cd = candidate / ".conductor"
        if cd.exists() and cd.is_dir():
            return cd
    # Fallback: create in cwd
    cd = cwd / ".conductor"
    cd.mkdir(parents=True, exist_ok=True)
    return cd


def log_hook_error(conductor_dir, exc):
    """Write hook failures to .conductor/hook-errors.log so the conductor
    surfaces them to the user instead of running with a silently-broken
    heartbeat."""
    try:
        err_path = conductor_dir / "hook-errors.log"
        with open(err_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(),
                "hook": "heartbeat.py",
                "error": str(exc),
                "traceback": traceback.format_exc()[:1000],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def update_heartbeat(hb_path, data):
    """Read-modify-write heartbeat.json under an exclusive lock so parallel
    PostToolUse hooks don't lose counter increments."""
    tool = data.get("tool_name", "")
    tool_response = data.get("tool_response")
    success = True
    if isinstance(tool_response, dict):
        success = not tool_response.get("is_error", False)

    # Open with O_RDWR|O_CREAT so we can both read and write under one lock.
    fd = os.open(str(hb_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if _HAS_FLOCK:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError:
                pass

        # Read existing content (may be empty on first call).
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 65536).decode("utf-8", errors="replace")
        existing = {}
        if raw.strip():
            try:
                existing = json.loads(raw)
            except Exception:
                existing = {}

        # If the file was written by a future schema we don't recognize,
        # bail out rather than overwriting with potentially-wrong state.
        existing_version = existing.get("schema_version")
        if existing_version is not None and existing_version > HEARTBEAT_SCHEMA_VERSION:
            return  # Newer conductor wrote this; older hook should not clobber.

        counter = int(existing.get("tool_calls_since_last_progress", existing.get("tool_calls_since_last_heartbeat", 0))) + 1
        last_progress_signal = existing.get("last_progress_signal", "")
        if tool in ("Write", "Edit", "NotebookEdit", "TaskCreate", "TaskUpdate"):
            last_progress_signal = f"{tool} at {datetime.datetime.now().isoformat()}"
            counter = 0  # forward progress observed; reset stuck-counter

        last_progress_ts = None
        if last_progress_signal and " at " in last_progress_signal:
            try:
                last_progress_ts = datetime.datetime.fromisoformat(last_progress_signal.split(" at ")[-1])
            except Exception:
                last_progress_ts = None
        now = datetime.datetime.now()
        if last_progress_ts is None:
            stuck_check = "unknown"
        elif (now - last_progress_ts).total_seconds() > 300:
            stuck_check = "stuck"
        elif (now - last_progress_ts).total_seconds() > 120:
            stuck_check = "slowing"
        else:
            stuck_check = "ok"

        heartbeat = {
            "schema_version": HEARTBEAT_SCHEMA_VERSION,
            "ts": now.isoformat(),
            "last_action": f"{tool}{'' if success else ' (FAILED)'}",
            "last_progress_signal": last_progress_signal,
            "tool_calls_since_last_progress": counter,
            "stuck_check": stuck_check,
            "session_id": data.get("session_id", existing.get("session_id", "")),
        }

        for k in ("phase", "phase_name", "task", "task_index", "task_total"):
            if k in existing:
                heartbeat[k] = existing[k]

        payload = json.dumps(heartbeat, ensure_ascii=False, indent=2).encode("utf-8")
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)
        os.ftruncate(fd, len(payload))
    finally:
        os.close(fd)  # releases flock


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    conductor_dir = find_conductor_dir()
    hb_path = conductor_dir / "heartbeat.json"

    try:
        update_heartbeat(hb_path, data)
    except Exception as exc:
        log_hook_error(conductor_dir, exc)


if __name__ == "__main__":
    main()
