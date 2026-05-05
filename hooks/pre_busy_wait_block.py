#!/usr/bin/env python3
# This regex catches the common busy-wait forms. It will NOT catch `bash -c '…'`,
# aliases, or creatively split commands. The hook is a safety net, not a fence.

import json
import os
import re
import sys

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

_BUSY_WAIT = [
    re.compile(r"until\s+.+?;\s*do\s+sleep\s+\d+", re.DOTALL),
    re.compile(r"while\s+.+?;\s*do\s+sleep\s+\d+", re.DOTALL),
    re.compile(r"^\s*sleep\s+\d{3,}", re.MULTILINE),
]


def _is_busy_wait(cmd: str) -> bool:
    return any(p.search(cmd) for p in _BUSY_WAIT)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    cmd = data.get("tool_input", {}).get("command", "")
    if _is_busy_wait(cmd):
        sys.stderr.write(
            "🚫 Forbidden busy-wait pattern — use ScheduleWakeup (time-based) or "
            "file-mtime polling (event-based) instead of sleep loops.\n"
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
