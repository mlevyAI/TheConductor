#!/usr/bin/env python3
"""
project-conductor — Lock check (PID + session-aware)

Replaces the previous time-based stale-lock cleanup
(`find .conductor/locks/ -name '*.lock' -mmin +60 -delete`),
which had two failure modes:

1. A long-running task (>1h) had its still-active lock deleted out from under
   it, allowing a concurrent task to write the same files.
2. A second conductor running in the same project could clobber the first
   conductor's locks (unsafe parallel session — silent file corruption).

Liveness model — three signals, in order of confidence:

  a) session_id match (canonical ownership): if a lock's session_id matches
     the CURRENT session's, it's our own — never treat as stale; the caller
     uses it for resume verification.

  b) PID liveness (os.kill(pid, 0)): if the recorded PID is still alive on
     this host, treat the lock as live and REFUSE TO CLOBBER. PIDs can be
     reused by the OS, so we additionally require the lock's hostname to
     match this host before trusting the PID check.

  c) Age fallback: if no heartbeat exists and PID check is inconclusive
     (e.g., cross-host or hostname mismatch), only declare stale if the
     lock is older than --max-age-hours (default 24h). Conservative on
     purpose — better to ask the user than to silently delete a possibly
     active lock.

Usage:
  python3 lock_check.py --current-session-id <SID> [--cleanup] [--max-age-hours N]

  --current-session-id  REQUIRED. The current Claude Code session_id, so we
                        can distinguish own locks from foreign ones.
  --cleanup             Delete classified-stale locks. Without this flag,
                        only classifies and prints; does not modify state.
  --max-age-hours       Age threshold for the conservative fallback when
                        heartbeat/PID don't give a clear answer. Default 24.

Output: a JSON document on stdout with the classification, suitable for the
agent to parse. See SCHEMA below for the shape.

Exit codes:
  0  — success, no foreign-live locks (safe to proceed)
  1  — at least one foreign-live lock detected (CALLER MUST ABORT and
       surface to the user — another conductor is active in this project)
  2  — script error (filesystem / parse / unexpected)

This script is read-only by default (no --cleanup). Even with --cleanup it
only deletes files it has classified as stale by the rules above; it never
touches a lock whose status is "own" or "live".
"""

import argparse
import errno
import json
import os
import socket
import sys
import datetime
from pathlib import Path


SCHEMA_VERSION = 1
HEARTBEAT_STALE_SECONDS = 600  # 10 minutes — heartbeat older than this == dead


def _is_pid_alive(pid):
    """Return True if a process with this PID exists on the current host.

    Uses signal 0 (the standard POSIX 'check existence' idiom). Note: this
    cannot distinguish PID reuse — a brand-new unrelated process with the
    same PID returns True. The caller compensates by also requiring the
    lock's hostname to match this host before trusting this signal.
    """
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but is owned by another user — still alive for our purposes.
        return True
    except OSError as e:
        if e.errno == errno.ESRCH:
            return False
        # Anything else: be conservative and assume alive.
        return True


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _heartbeat_says_alive(conductor_dir, lock_session_id):
    """Returns True iff heartbeat.json exists, names the same session_id as
    the lock, and has been updated within HEARTBEAT_STALE_SECONDS."""
    hb = _read_json(conductor_dir / "heartbeat.json")
    if not hb:
        return False
    if hb.get("session_id") != lock_session_id:
        return False
    ts_str = hb.get("ts")
    if not ts_str:
        return False
    try:
        ts = datetime.datetime.fromisoformat(ts_str)
    except ValueError:
        return False
    age = (datetime.datetime.now() - ts).total_seconds()
    return age <= HEARTBEAT_STALE_SECONDS


def _lock_age_seconds(lock):
    ts_str = lock.get("acquired_at")
    if not ts_str:
        return None
    try:
        # Accept both Z-suffixed and naive ISO timestamps.
        ts_str = ts_str.replace("Z", "+00:00") if ts_str.endswith("Z") else ts_str
        ts = datetime.datetime.fromisoformat(ts_str)
        if ts.tzinfo:
            ts = ts.replace(tzinfo=None) - datetime.timedelta(
                seconds=ts.utcoffset().total_seconds()
            )
    except ValueError:
        return None
    return (datetime.datetime.now() - ts).total_seconds()


def classify_lock(lock_path, lock, current_session_id, conductor_dir, max_age_hours):
    """Classify a single lock file. Returns ("own"|"live"|"stale"|"uncertain", reason)."""
    this_host = socket.gethostname()

    lock_session = lock.get("session_id")
    lock_pid = lock.get("acquired_pid")
    lock_host = lock.get("hostname")

    # 1. Own session — keep, caller decides what to do (resume, etc.).
    if lock_session and lock_session == current_session_id:
        return "own", "session_id matches current session"

    # 2. Heartbeat says the foreign session is alive.
    if lock_session and _heartbeat_says_alive(conductor_dir, lock_session):
        return "live", "heartbeat.json shows session active within last 10 min"

    # 3. PID check — only trustworthy if hostname matches.
    if lock_pid and lock_host == this_host and _is_pid_alive(lock_pid):
        return (
            "live",
            f"PID {lock_pid} is alive on this host (hostname={this_host})",
        )

    # 4. Age fallback. If we get here:
    #    - session_id doesn't match current
    #    - heartbeat is missing/stale/different session
    #    - PID is dead OR cross-host OR missing
    age = _lock_age_seconds(lock)
    if age is None:
        return "uncertain", "cannot parse acquired_at timestamp"

    if age > max_age_hours * 3600:
        return "stale", f"older than {max_age_hours}h with no live signal"

    return (
        "uncertain",
        f"age {int(age)}s under fallback threshold; heartbeat absent/stale and "
        "PID inconclusive — caller should ask the user before deleting",
    )


def main():
    ap = argparse.ArgumentParser(description="PID + session aware lock check")
    ap.add_argument("--current-session-id", required=True)
    ap.add_argument("--cleanup", action="store_true")
    ap.add_argument("--max-age-hours", type=int, default=24)
    ap.add_argument("--locks-dir", default=".conductor/locks")
    ap.add_argument("--conductor-dir", default=".conductor")
    args = ap.parse_args()

    locks_dir = Path(args.locks_dir)
    conductor_dir = Path(args.conductor_dir)

    if not locks_dir.exists():
        # Nothing to do — empty result.
        print(json.dumps({
            "schema_version": SCHEMA_VERSION,
            "current_session_id": args.current_session_id,
            "host": socket.gethostname(),
            "own": [], "live": [], "stale": [], "uncertain": [],
            "deleted": [], "errors": [],
        }, indent=2))
        return 0

    own, live, stale, uncertain, deleted, errors = [], [], [], [], [], []

    for lock_path in sorted(locks_dir.glob("*.lock")):
        lock = _read_json(lock_path)
        if lock is None:
            errors.append({"path": str(lock_path), "reason": "unreadable or invalid JSON"})
            continue

        kind, reason = classify_lock(
            lock_path, lock, args.current_session_id, conductor_dir, args.max_age_hours
        )
        record = {
            "path": str(lock_path),
            "task_id": lock.get("task_id"),
            "session_id": lock.get("session_id"),
            "pid": lock.get("acquired_pid"),
            "hostname": lock.get("hostname"),
            "acquired_at": lock.get("acquired_at"),
            "reason": reason,
        }
        if kind == "own":
            own.append(record)
        elif kind == "live":
            live.append(record)
        elif kind == "stale":
            stale.append(record)
            if args.cleanup:
                try:
                    lock_path.unlink()
                    deleted.append(record["path"])
                except OSError as e:
                    errors.append({"path": str(lock_path), "reason": f"delete failed: {e}"})
        else:
            uncertain.append(record)

    result = {
        "schema_version": SCHEMA_VERSION,
        "current_session_id": args.current_session_id,
        "host": socket.gethostname(),
        "own": own,
        "live": live,
        "stale": stale,
        "uncertain": uncertain,
        "deleted": deleted,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))

    # Exit 1 if a foreign-live lock was found — caller MUST abort.
    return 1 if live else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Last-resort: emit error to stderr + machine-readable JSON to stdout.
        sys.stderr.write(f"lock_check.py: {exc}\n")
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
