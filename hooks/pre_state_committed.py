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
    `.conductor/advisories.md` and writes a marker file so subsequent
    invocations are no-ops.
  - NEVER blocks. Always exit 0 even on advisory.

Detection:
  Considers `.conductor/`, `.conductor`, `/.conductor/`, `/.conductor`
  appearing as a non-negated, non-commented entry anywhere in the
  project's `.gitignore` to be the trigger. Trailing/leading whitespace
  is tolerated. Negation (`!.conductor/`) suppresses the warning.

Privacy & security:
  PURELY LOCAL. Reads only `.gitignore` and writes only to
  `.conductor/advisories.md` + a one-byte marker file.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


_PATTERNS = (".conductor/", ".conductor", "/.conductor/", "/.conductor")
_PROBES_PATTERNS = (".conductor/probes/", ".conductor/probes")
_MARKER_REL = ".conductor/.gitignore-warning-logged"
_PROBES_MARKER_REL = ".conductor/.probes-gitignore-warning-logged"
_ADVISORIES_REL = ".conductor/advisories.md"
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


def _is_probes_gitignored(cwd: Path) -> bool:
    """Return True if .conductor/probes/ appears as a positive ignore.

    v6.1.6+ — Probes are part of the v6 'every task replayable' promise;
    silently gitignoring them undermines the surgical-debug-map guarantee
    just like gitignoring the whole `.conductor/` does, but more subtly
    (the user thinks they're tracking evidence but their investigation
    artifacts vanish across re-clones).
    """
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
            if line[1:].strip() in _PROBES_PATTERNS:
                return False
            continue
        if line in _PROBES_PATTERNS:
            triggered = True
    return triggered


def _state_present(cwd: Path) -> bool:
    return (cwd / ".conductor" / "state.json").is_file()


def _marker_present(cwd: Path) -> bool:
    return (cwd / _MARKER_REL).is_file()


def _probes_marker_present(cwd: Path) -> bool:
    return (cwd / _PROBES_MARKER_REL).is_file()


def _append_probes_advisory(cwd: Path) -> None:
    """v6.1.6+ — Append a one-time advisory if `.conductor/probes/` is gitignored.

    Idempotent via `_PROBES_MARKER_REL`.
    """
    advisories = cwd / _ADVISORIES_REL
    advisories.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"\n## advisory ({_utc_now()}): `.conductor/probes/` is in `.gitignore`\n\n"
        "v6's 'every task replayable' promise covers `.conductor/probes/` — "
        "throwaway exploration artifacts a future debug session may want to "
        "see (e.g., 'what did we try before settling on this approach?'). "
        "With `probes/` gitignored, that history vanishes on re-clone. "
        "Recommendation: remove the `.conductor/probes/` line from "
        "`.gitignore` OR move probes under `.conductor/evidence/<task-id>/probes/` "
        "(which is tracked by default). Keeping `probes/` untracked is a "
        "soft v6 contract violation — flagged once per session, never "
        "blocks.\n"
    )
    try:
        with advisories.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass

    marker = cwd / _PROBES_MARKER_REL
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass


def _append_finding(cwd: Path) -> None:
    advisories = cwd / _ADVISORIES_REL
    advisories.parent.mkdir(parents=True, exist_ok=True)
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
        with advisories.open("a", encoding="utf-8") as f:
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

    # First advisory: whole .conductor/ gitignored
    if not _marker_present(cwd) and _is_gitignored(cwd):
        _append_finding(cwd)

    # Second advisory (v6.1.6+): just .conductor/probes/ gitignored
    # — independent of the first; both can fire on the same .gitignore.
    if not _probes_marker_present(cwd) and _is_probes_gitignored(cwd):
        _append_probes_advisory(cwd)

    return 0


if __name__ == "__main__":
    sys.exit(main())
