#!/usr/bin/env python3
"""stop_evidence_completeness_check.py — v6 evidence-folder completeness.

Purpose:
  At session end, identify tasks whose evidence folder was *initialized*
  (`manifest.json` present) but never *finalized* (no `files.json`, or
  `commit_sha` is null). These are the v6 gaps that break the
  "every task is replayable" promise — manifest without commit means we
  can't know which commit corresponds to the task months later.

Behavior:
  - Stop hook (fires when Claude Code session ends). Drains stdin.
  - No-op when `.conductor/state.json` is absent (universal guard).
  - Scans `.conductor/evidence/tasks/*/manifest.json`.
  - For each task missing `files.json` OR with `files.json::commit_sha`
    null/empty → flag.
  - If any flagged: append a single advisory block to `.conductor/advisories.md`.
  - Deduplicates across runs via `.conductor/.evidence-completeness-last-warned`
    holding a hash of the failing-task list — if the gap set is unchanged
    since last warn, skip re-logging.
  - Always exit 0 (advisory only).

Why Stop and not PostToolUse on `git commit`:
  v6 convention is `evidence.record_files()` runs *after* the commit, so a
  PostToolUse-on-commit check would always false-positive on the
  immediately-following PostToolUse event. Stop runs once per session,
  after all task work is done — race-free.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _scan_for_gaps(evidence_root: Path) -> list[dict]:
    """Return a list of {task_id, task_name, missing} for incomplete tasks."""
    gaps: list[dict] = []
    if not evidence_root.is_dir():
        return gaps
    for task_dir in sorted(evidence_root.iterdir()):
        if not task_dir.is_dir():
            continue
        manifest = _load_json(task_dir / "manifest.json")
        if manifest is None:
            continue  # not a v6 task folder
        task_id = manifest.get("task_id", task_dir.name)
        task_name = manifest.get("task_name", "")
        files_json = task_dir / "files.json"
        if not files_json.is_file():
            gaps.append({
                "task_id": task_id,
                "task_name": task_name,
                "missing": "files.json",
            })
            continue
        rec = _load_json(files_json)
        if rec is None:
            gaps.append({
                "task_id": task_id,
                "task_name": task_name,
                "missing": "files.json (unreadable)",
            })
            continue
        if not rec.get("commit_sha"):
            gaps.append({
                "task_id": task_id,
                "task_name": task_name,
                "missing": "commit_sha",
            })
    return gaps


def _gap_hash(gaps: list[dict]) -> str:
    payload = json.dumps(
        sorted([(g["task_id"], g["missing"]) for g in gaps]),
        ensure_ascii=False,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _append_advisories(advisories: Path, gaps: list[dict]) -> None:
    advisories.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "",
        f"## advisory ({_utc_now()}): incomplete v6 evidence",
        "",
        f"{len(gaps)} task(s) have a `manifest.json` but no recorded "
        "`commit_sha`. Without a commit SHA, surgical debugging across time "
        "is impossible — `git checkout <SHA>` cannot restore the state of "
        "the project at that task's completion.",
        "",
        "**Affected tasks:**",
        "",
    ]
    for g in gaps:
        name = f" — {g['task_name']}" if g["task_name"] else ""
        lines.append(f"- `{g['task_id']}`{name} → missing `{g['missing']}`")
    lines.append("")
    lines.append(
        "**Action:** for each task above, after its commit has landed, call "
        "`lib.evidence.record_files(task_id, files_written=[...], "
        "commit_sha=<SHA>, tests_run=[...])`. If the task was never "
        "completed (e.g., session ended mid-dispatch), document the reason "
        "in `advisories.md` and consider removing the manifest."
    )
    lines.append("")
    try:
        with advisories.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass


def main() -> int:
    try:
        sys.stdin.read()
    except Exception:
        pass

    cwd = Path(os.getcwd())
    state_path = cwd / ".conductor" / "state.json"
    if not state_path.is_file():
        return 0

    evidence_root = cwd / ".conductor" / "evidence" / "tasks"
    gaps = _scan_for_gaps(evidence_root)
    if not gaps:
        return 0

    marker = cwd / ".conductor" / ".evidence-completeness-last-warned"
    new_hash = _gap_hash(gaps)
    try:
        last_hash = marker.read_text(encoding="utf-8").strip()
    except OSError:
        last_hash = ""

    if last_hash == new_hash:
        return 0

    advisories = cwd / ".conductor" / "advisories.md"
    _append_advisories(advisories, gaps)

    try:
        marker.write_text(new_hash, encoding="utf-8")
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
