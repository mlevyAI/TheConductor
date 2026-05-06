#!/usr/bin/env python3
# This check catches the common mutating patterns. It will NOT catch all possible
# shell constructs. The hook is a safety net, not a fence.

import json
import os
import sys
from pathlib import Path

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

USER_GLOBAL = str(Path.home() / ".claude")

MUTATING_BASH_FRAGMENTS = (
    "mkdir", "touch ", "rm ", "cp ", "mv ", "pip install",
    "npm install", "pnpm install", "yarn install", "playwright install",
    "git add", "git commit", "git push", "git checkout",
    "curl ", "wget ", "tee ",
)


def _is_mutating_bash(cmd: str) -> bool:
    for frag in MUTATING_BASH_FRAGMENTS:
        if frag in cmd:
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

    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        sys.exit(0)

    if state.get("gate") != "pre_first_response_proceed":
        sys.exit(0)

    conductor_dir = str(Path(os.getcwd()) / ".conductor")
    gate_msg = (
        "🛑 HARD GATE — waiting for user to reply 'proceed' before execution begins. "
        "This overrides accept-edits mode."
    )

    if tool == "Write":
        if target:
            resolved_target = str(Path(target).resolve())
            resolved_cdir = str(Path(conductor_dir).resolve())
            if not (resolved_target == resolved_cdir
                    or resolved_target.startswith(resolved_cdir + os.sep)):
                _block(f"{gate_msg} (Write outside .conductor/ blocked)")

    elif tool == "Edit":
        _block(f"{gate_msg} (Edit blocked)")

    elif tool == "Task":
        _block(f"{gate_msg} (Task dispatch blocked)")

    elif tool == "Bash":
        cmd = tool_input.get("command", "")
        if _is_mutating_bash(cmd):
            _block(f"{gate_msg} (mutating Bash blocked: {cmd[:80]!r})")


if __name__ == "__main__":
    main()
