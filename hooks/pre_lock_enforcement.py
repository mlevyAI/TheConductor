#!/usr/bin/env python3
# This path check uses segment-exact prefix matching via path_within_declaration
# from lib/lock_check.py. It will NOT catch all possible write paths (symlinks,
# /proc, etc.). The hook is a safety net, not a fence.

import json
import os
import sys
from pathlib import Path

_REPO_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
sys.path.insert(0, _REPO_LIB)
from lock_check import path_within_declaration  # noqa: E402

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

USER_GLOBAL = str(Path.home() / ".claude")
_ACTIVE_TASK = os.path.join(os.getcwd(), ".conductor", "locks", "active-task.json")
_FINDINGS = os.path.join(os.getcwd(), ".conductor", "findings.md")
_FALLBACK_MARKER = os.path.join(os.getcwd(), ".conductor", ".lock_enforcement_fallback_logged")


def _append_findings(msg: str) -> None:
    try:
        with open(_FINDINGS, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _block(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit"):
        sys.exit(0)

    target = data.get("tool_input", {}).get("file_path", "")

    # User-global write blocker — always
    if target:
        try:
            resolved = str(Path(target).resolve())
            ug = USER_GLOBAL
            if resolved == ug or resolved.startswith(ug + os.sep):
                _block(
                    "refusing to write under ~/.claude/ — "
                    "user-global is read-only at runtime per §3.1"
                )
        except Exception:
            pass

    # Read active-task.json
    active_task = None
    if os.path.exists(_ACTIVE_TASK):
        try:
            with open(_ACTIVE_TASK, encoding="utf-8") as f:
                active_task = json.load(f)
        except Exception:
            pass

    files_write = (active_task or {}).get("files_write", [])

    # Tolerant fallback: no declaration available yet (pre-Phase-D)
    if not files_write:
        if not os.path.exists(_FALLBACK_MARKER):
            _append_findings(
                "pre_lock_enforcement: no active-task.json::files_write[] yet "
                "(pre-Phase-D); not enforcing this session"
            )
            try:
                open(_FALLBACK_MARKER, "w").close()
            except Exception:
                pass
        sys.exit(0)

    if not target:
        sys.exit(0)

    cwd = os.getcwd()
    for declared in files_write:
        if path_within_declaration(target, declared, cwd):
            sys.exit(0)

    _block(
        f"🔒 Lock violation — {target!r} is outside the declared files_write set "
        f"for the active task. Declared: {files_write}. "
        "Log the deviation and surface to user before continuing."
    )


if __name__ == "__main__":
    main()
