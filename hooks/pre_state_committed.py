#!/usr/bin/env python3
"""pre_state_committed.py — v6 state-tracking advisory hook.

Purpose:
  Warn (non-blocking) once per session if `.conductor/` is excluded from
  the project's git tracking. This matters because v6 treats
  `.conductor/evidence/tasks/<task-id>/` plus `.conductor/decisions.md`,
  `.conductor/coverage.md`, and `.conductor/debug-map.md` as the
  authoritative time-travel artifacts. If they are gitignored, the
  surgical-debug-map promise ("go back to any task") cannot be kept.

Behavior:
  - PreToolUse hook. Runs on every tool call but is cheap and idempotent.
  - Only inspects `.gitignore` patterns, never modifies them.
  - On first detection per session, appends a single advisory line to
    `.conductor/findings.md` and writes a marker file so subsequent
    invocations are no-ops.
  - NEVER blocks. Always exit 0 even on advisory.

Detection:
  Considers `.conductor/`, `.conductor`, `/.conductor/`, `/.conductor`
  appearing as a non-negated, non-commented entry anywhere in the
  project's `.gitignore` to be the trigger. Trailing/leading whitespace
  is tolerated. Negation (`!.conductor/`) suppresses the warning.

Privacy & security:
  PURELY LOCAL. Reads only `.gitignore` and writes only to
  `.conductor/findings.md` + a one-byte marker file.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


_PATTERNS = (".conductor/", ".conductor", "/.conductor/", "/.conductor")
_MARKER_REL = ".conductor/.gitignore-warning-logged"
_FINDINGS_REL = ".conductor/findings.md"
_GITIGNORE = ".gitignore"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_gitignored(cwd: Path) -> bool:
    """Return True if .conductor/ appears as a positive ignore in .gitignore."""
    p = cwd / _GITIGNORE
    if not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return False

    triggered = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            # Negation — if it un-ignores .conductor, suppress the warning.
            if line[1:].strip() in _PATTERNS:
                return False
            continue
        if line in _PATTERNS:
            triggered = True
    return triggered


def _state_present(cwd: Path) -> bool:
    return (cwd / ".conductor" / "state.json").is_file()


def _marker_present(cwd: Path) -> bool:
    return (cwd / _MARKER_REL).is_file()


def _append_finding(cwd: Path) -> None:
    findings = cwd / _FINDINGS_REL
    findings.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"\n## advisory ({_utc_now()}): `.conductor/` is in `.gitignore`\n\n"
        "v6 treats `.conductor/evidence/tasks/`, `decisions.md`, "
        "`coverage.md`, and `debug-map.md` as authoritative time-travel "
        "artifacts. With `.conductor/` gitignored, surgical debugging "
        "across commits is impossible. Recommendation: remove the "
        "`.conductor/` line from `.gitignore` so per-task evidence is "
        "captured in git history. If you have privacy concerns, "
        "consider gitignoring only `.conductor/locks/` and "
        "`.conductor/probes/` instead.\n"
    )
    try:
        with findings.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass

    marker = cwd / _MARKER_REL
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    # Drain stdin if present so Claude Code's pipe doesn't block.
    try:
        sys.stdin.read()
    except Exception:
        pass

    cwd = Path(os.getcwd())
    if not _state_present(cwd):
        return 0
    if _marker_present(cwd):
        return 0
    if not _is_gitignored(cwd):
        return 0
    _append_finding(cwd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
