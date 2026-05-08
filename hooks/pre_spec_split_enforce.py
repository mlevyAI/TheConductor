#!/usr/bin/env python3
"""pre_spec_split_enforce.py — v6 large-spec blocker.

Purpose:
  Prevent the conductor from reading a large spec file in full when the
  `conductor-spec-splitter` skill should have run first. Large specs read
  monolithically degrade Claude's reasoning measurably (the relevant
  section gets buried under unrelated material), which is exactly what the
  splitter solves: focused parts ≤ 250 lines each plus a global header.

  v5 specified this as a prompt-only rule:
      "If line count > 300 → invoke skill conductor-spec-splitter first."
  In practice the agent sometimes skipped the splitter and read the full
  document. v6 makes it a hard hook.

Behavior:
  - PreToolUse hook on `Read`. Exits 2 (blocking) when:
      1. tool_name == "Read"
      2. The target path looks like a spec (filename or path heuristic)
      3. File exists and is > 300 lines
      4. The agent is NOT using a small `limit` (≤ 500) — paginated reads
         are explicitly allowed
      5. `.conductor/spec-parts/manifest.json` does NOT exist
      6. `.conductor/.spec-split-skipped` opt-out marker does NOT exist
  - Otherwise exits 0 (no-op).

  When blocked, stderr explains exactly what to do: invoke
  `conductor-spec-splitter`, OR if the user explicitly does not want the
  spec split, write the opt-out marker.

Heuristics for "looks like a spec":
  Filename patterns (case-insensitive):
    spec*.md, *spec.md, requirements*.md, prd*.md, *.spec.md
  Path patterns:
    /specs/, /spec/  (anywhere in the resolved path, NOT inside .conductor/)

  Excluded everywhere: paths under .conductor/, .git/, node_modules/,
  ~/.claude/, README.md, CHANGELOG.md, project-conductor.md, *.test.md.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


_SPEC_NAME_PATTERNS = [
    re.compile(r"^spec[\w\-.]*\.md$", re.IGNORECASE),
    re.compile(r"^[\w\-.]*spec\.md$", re.IGNORECASE),
    re.compile(r"^requirements[\w\-.]*\.md$", re.IGNORECASE),
    re.compile(r"^prd[\w\-.]*\.md$", re.IGNORECASE),
    re.compile(r"^[\w\-.]+\.spec\.md$", re.IGNORECASE),
]

_NEVER_SPECS = {
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE.md",
    "project-conductor.md",
    "SKILL.md",
    "CLAUDE.md",
}

_EXCLUDED_PATH_FRAGMENTS = (
    ".conductor",
    ".git",
    "node_modules",
    ".claude",
    "site-packages",
    "__pycache__",
)

_PAGINATED_LIMIT_THRESHOLD = 500
_LINE_COUNT_THRESHOLD = 300


def _looks_like_spec(path: Path) -> bool:
    name = path.name
    if name in _NEVER_SPECS:
        return False
    if name.endswith(".test.md"):
        return False
    # Filename-based detection
    for pat in _SPEC_NAME_PATTERNS:
        if pat.match(name):
            return True
    # Path-based detection: /specs/ or /spec/ segment
    parts = {p.lower() for p in path.parts}
    if "specs" in parts or "spec" in parts:
        # but not when nested under any excluded fragment
        return True
    return False


def _is_excluded(path: Path, cwd: Path) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return True
    parts_lower = [p.lower() for p in resolved.parts]
    for frag in _EXCLUDED_PATH_FRAGMENTS:
        if frag in parts_lower:
            return True
    # Outside the project tree (e.g., /tmp, ~/.something) — don't second-guess
    try:
        resolved.relative_to(cwd.resolve())
    except ValueError:
        return True
    return False


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _block(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    cwd = Path(os.getcwd())
    if not (cwd / ".conductor" / "state.json").is_file():
        return 0

    if data.get("tool_name") != "Read":
        return 0

    tool_input = data.get("tool_input", {}) or {}
    raw_path = tool_input.get("file_path", "")
    if not raw_path:
        return 0

    target = Path(raw_path)
    if not target.is_absolute():
        target = cwd / target

    if _is_excluded(target, cwd):
        return 0
    if not target.is_file():
        return 0
    if not _looks_like_spec(target):
        return 0

    # Paginated read = explicit pagination intent. Allow it.
    limit = tool_input.get("limit")
    if isinstance(limit, int) and limit <= _PAGINATED_LIMIT_THRESHOLD:
        return 0

    manifest = cwd / ".conductor" / "spec-parts" / "manifest.json"
    if manifest.is_file():
        return 0

    opt_out = cwd / ".conductor" / ".spec-split-skipped"
    if opt_out.is_file():
        return 0

    lines = _line_count(target)
    if lines <= _LINE_COUNT_THRESHOLD:
        return 0

    rel_target = target
    try:
        rel_target = target.relative_to(cwd)
    except ValueError:
        pass

    _block(
        f"🚫 Large spec read blocked — {str(rel_target)!r} is {lines} lines.\n\n"
        f"Reading specs > {_LINE_COUNT_THRESHOLD} lines monolithically degrades "
        "Claude's focus on the relevant section.\n\n"
        "Required action: invoke skill `conductor-spec-splitter` first. "
        "It will write `.conductor/spec-parts/manifest.json` plus per-section "
        "files ≤ 250 lines each, and Phase 1 enrichment will then run per-part.\n\n"
        "If you genuinely want to read the full file (override): "
        "`touch .conductor/.spec-split-skipped` and retry. Override is logged "
        "to `findings.md` when used.\n\n"
        "Paginated reads (`limit` ≤ "
        f"{_PAGINATED_LIMIT_THRESHOLD}) are not blocked."
    )
    return 0  # unreachable; _block exits


if __name__ == "__main__":
    sys.exit(main())
