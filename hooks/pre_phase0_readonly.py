#!/usr/bin/env python3
# This prefix check catches the common cases. It will NOT catch `bash -c '…'`,
# aliases, double-spaced commands, or chained `cd && rm`. Truth is
# .conductor/state.json + the conductor's own discipline. The hook is a safety
# net, not a fence.

import json
import os
import sys
from pathlib import Path

# --- Universal no-op guard ---
state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

USER_GLOBAL = str(Path.home() / ".claude")

BASH_READONLY_PREFIXES = (
    "ls", "find", "cat", "head", "tail", "grep", "rg", "ag",
    "git status", "git diff", "git log", "git branch", "git show",
    "git ls-files", "git rev-parse", "git stash list",
    "which", "type", "echo", "printf", "wc", "jq", "stat",
    "python3 lib/lock_check", "python3 -c",
)


def _is_bash_allowed(cmd: str) -> bool:
    s = cmd.strip()
    for prefix in BASH_READONLY_PREFIXES:
        if s == prefix or s.startswith(prefix + " ") or s.startswith(prefix + "\n"):
            return True
    return False


def _block(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    target = tool_input.get("file_path", "")

    # User-global write blocker — applies regardless of phase
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

    # Phase 0 enforcement
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        sys.exit(0)

    if state.get("phase") != "0":
        sys.exit(0)

    conductor_dir = str(Path(os.getcwd()) / ".conductor")

    if tool in ("Write", "Edit"):
        if not target:
            sys.exit(0)
        resolved_target = str(Path(target).resolve())
        resolved_cdir = str(Path(conductor_dir).resolve())
        if not (resolved_target == resolved_cdir
                or resolved_target.startswith(resolved_cdir + os.sep)):
            _block(
                f"🚧 Phase 0 is READ-ONLY — Write/Edit outside .conductor/ is blocked "
                f"(target: {target}). Phase 0 is environment discovery only."
            )

    if tool == "Bash":
        cmd = tool_input.get("command", "")
        if not _is_bash_allowed(cmd):
            _block(
                f"🚧 Phase 0 is READ-ONLY — Bash command not in read-only allowlist "
                f"(command: {cmd[:120]!r}). Use Read/Grep/Glob for discovery."
            )


if __name__ == "__main__":
    main()
