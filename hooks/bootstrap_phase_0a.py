#!/usr/bin/env python3
"""bootstrap_phase_0a.py — v6.0.3 SessionStart enforcement bootstrap.

Purpose:
  Make Phase 0a auto-install bulletproof. Before v6.0.3 the conductor's
  prompt described "Phase 0a: auto-install enforcement hooks" but nothing
  forced it — if the agent skipped Phase 0a, no hook caught it because no
  hooks were installed yet (chicken-and-egg).

  This script breaks the cycle by being a SessionStart hook wired ONCE in
  user-global `~/.claude/settings.json` (by `install.sh`, with explicit
  consent). It fires on every Claude Code session start, but it is
  conservative: it only acts when there's clear evidence of a conductor
  session AND the per-project enforcement hooks aren't already wired.

Behavior:
  1. Drain stdin (SessionStart payload).
  2. Detect "is this a conductor session" by combining signals:
     - `~/.claude/agents/project-conductor.md` exists (conductor installed)
     - AND any of:
       - `<cwd>/.conductor/` exists (resumed conductor session)
       - SessionStart stdin mentions `project-conductor`
       - `<cwd>/.claude/settings.json` already has any conductor hook
         (re-wire-on-update case)
       - `<cwd>/spec.md` AND a relevant CLAUDE.md mentions the conductor
  3. If not a conductor session → exit 0 silently.
  4. If conductor session but enforcement hooks already present in
     `<cwd>/.claude/settings.json` → exit 0 silently.
  5. Otherwise: render via `lib.hooks_manifest.render_settings_block` for
     `["phase_b", "v6_replayability"]`, merge into existing settings.json
     (preserving user-authored entries), atomic-write, log to
     `<cwd>/.conductor/decisions.md`.

Privacy:
  - PURELY LOCAL. No network, no secret reads.
  - Reads: SessionStart stdin, presence checks for ~/.claude/agents/,
    settings.json, spec.md, CLAUDE.md, .conductor/.
  - Writes: ONLY <cwd>/.claude/settings.json AND <cwd>/.conductor/decisions.md.
  - Never blocks (always exits 0).

Failure-safety:
  - JSON parse errors on existing settings.json → log advisory, do not
    overwrite.
  - Any unhandled exception → log to ~/.claude/conductor-bootstrap.log
    (best-effort) and exit 0. The conductor can still run with prompt-only
    enforcement; it's degraded but not broken.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# These are the bundles auto-installed in Phase 0a. Match what
# project-conductor.md § Phase 0a says.
BOOTSTRAP_BUNDLES = ["phase_b", "v6_replayability"]

# Quick-reject markers in <cwd>/.claude/settings.json — if any of these
# strings appear, we assume hooks are already wired.
_ENFORCEMENT_HOOK_NAMES = (
    "pre_phase0_readonly.py",
    "pre_first_response_gate.py",
    "pre_busy_wait_block.py",
    "pre_lock_enforcement.py",
    "post_output_quality.py",
    "stop_validate_final_report.py",
    "pre_state_committed.py",
    "pre_spec_split_enforce.py",
    "stop_evidence_completeness_check.py",
)

_BOOTSTRAP_LOG = Path.home() / ".claude" / "conductor-bootstrap.log"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_log_error(msg: str) -> None:
    """Best-effort error log. Never raises."""
    try:
        _BOOTSTRAP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _BOOTSTRAP_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{_utc_now()}] {msg}\n")
    except Exception:
        pass


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except Exception:
        return ""


def _is_conductor_installed() -> bool:
    return (Path.home() / ".claude" / "agents" / "project-conductor.md").is_file()


def _is_conductor_session(cwd: Path, stdin_text: str) -> bool:
    """Conservative heuristic — multiple signals must align before we act.

    Required: the conductor agent file exists user-globally.
    Plus any one of: existing .conductor/ dir, payload mention, existing
    enforcement-hook reference in settings.json, or spec.md + CLAUDE.md
    naming the conductor.
    """
    if not _is_conductor_installed():
        return False

    # Signal 1: existing conductor project (resumed session)
    if (cwd / ".conductor").is_dir():
        return True

    # Signal 2: SessionStart payload mentions the conductor agent name
    if "project-conductor" in stdin_text:
        return True

    # Signal 3: settings.json already references our hooks (re-wire/update case)
    settings = cwd / ".claude" / "settings.json"
    if settings.is_file():
        try:
            text = settings.read_text(encoding="utf-8")
            if any(name in text for name in _ENFORCEMENT_HOOK_NAMES):
                return True
        except OSError:
            pass

    # Signal 4: spec.md + a CLAUDE.md naming the conductor
    has_spec = (cwd / "spec.md").is_file()
    if has_spec:
        for cm in (cwd / "CLAUDE.md", cwd / ".claude" / "CLAUDE.md"):
            if cm.is_file():
                try:
                    if "project-conductor" in cm.read_text(encoding="utf-8"):
                        return True
                except OSError:
                    continue

    return False


def _hooks_already_wired(settings: dict) -> bool:
    """Return True if any of the 9 enforcement hook scripts are referenced."""
    if not isinstance(settings, dict):
        return False
    blob = json.dumps(settings)
    return any(name in blob for name in _ENFORCEMENT_HOOK_NAMES)


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _merge_hooks(existing: dict, generated: dict) -> dict:
    """Merge generated hooks block into existing settings.json structure.

    Preserves user-authored hook entries. Generated entries are APPENDED
    to the per-event arrays — Claude Code runs all entries.
    """
    out = dict(existing)
    out.setdefault("hooks", {})
    for event, entries in generated.get("hooks", {}).items():
        out["hooks"].setdefault(event, []).extend(entries)
    return out


def _merge_permissions(existing: dict, allow_strings: list[str]) -> dict:
    out = dict(existing)
    out.setdefault("permissions", {})
    out["permissions"].setdefault("allow", [])
    seen = set(out["permissions"]["allow"])
    for s in allow_strings:
        if s not in seen:
            out["permissions"]["allow"].append(s)
            seen.add(s)
    return out


def _log_decision(cwd: Path, hook_dir: Path, hook_count: int) -> None:
    p = cwd / ".conductor" / "decisions.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"\n## bootstrap auto-install ({_utc_now()})\n\n"
        f"Phase 0a auto-install: {hook_count} enforcement hooks wired into "
        f"`{cwd}/.claude/settings.json` (bundles: {', '.join(BOOTSTRAP_BUNDLES)}). "
        f"Hook source directory: `{hook_dir}`.\n"
    )
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _do_install(cwd: Path) -> int:
    """Render and merge the enforcement hooks. Returns count installed."""
    # Hook scripts live next to this script. The script's directory is the
    # canonical hook_dir for the rendered settings.json command paths.
    hook_dir = Path(__file__).resolve().parent
    repo_root = hook_dir.parent

    sys.path.insert(0, str(repo_root))
    try:
        from lib.hooks_manifest import render_permissions, render_settings_block
    except Exception as e:
        _safe_log_error(f"failed to import lib.hooks_manifest: {e}")
        return 0

    block = render_settings_block(BOOTSTRAP_BUNDLES, hook_dir=str(hook_dir))
    perms = render_permissions(BOOTSTRAP_BUNDLES, hook_dir=str(hook_dir))

    settings_path = cwd / ".claude" / "settings.json"
    if settings_path.is_file():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except (OSError, json.JSONDecodeError) as e:
            _safe_log_error(f"unreadable settings.json at {settings_path}: {e}")
            return 0
    else:
        existing = {}

    merged = _merge_hooks(existing, block)
    merged = _merge_permissions(merged, perms)

    try:
        _atomic_write_json(settings_path, merged)
    except Exception as e:
        _safe_log_error(f"failed to write {settings_path}: {e}")
        return 0

    # Count how many hooks the manifest says we're installing
    hook_count = 0
    for entries in block.get("hooks", {}).values():
        for entry in entries:
            hook_count += len(entry.get("hooks", []))

    _log_decision(cwd, hook_dir, hook_count)
    return hook_count


def main() -> int:
    try:
        stdin_text = _read_stdin()
        cwd = Path(os.getcwd())

        if not _is_conductor_session(cwd, stdin_text):
            return 0

        # Check if already wired
        settings_path = cwd / ".claude" / "settings.json"
        if settings_path.is_file():
            try:
                existing = json.loads(settings_path.read_text(encoding="utf-8"))
                if _hooks_already_wired(existing):
                    return 0
            except (OSError, json.JSONDecodeError):
                pass

        _do_install(cwd)
        return 0
    except Exception:
        _safe_log_error("uncaught exception in bootstrap_phase_0a:\n"
                        + traceback.format_exc())
        return 0  # never block a Claude Code session


if __name__ == "__main__":
    sys.exit(main())
