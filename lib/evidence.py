"""evidence.py — Per-task evidence folder management.

§v6 of the TheConductor spec.

Every dispatched task produces an evidence folder at
`.conductor/evidence/tasks/<task-id>/` containing:

  envelope.xml   — the dispatch envelope sent to the sub-agent (XML)
  result.md      — the sub-agent's completion report (markdown)
  files.json     — files written by the task + commit SHA + tests run
  decisions.json — structured decision records made during the task

This is the foundation that coverage matrix, decision provenance, and the
live debug map all read from. Per-phase `evidence/phase-N/` is preserved as
a sibling tree for backward compatibility with v4/v5.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# Task IDs land in directory names — restrict to a safe charset.
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
_MAX_TASK_ID_LEN = 80


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_task_id(task_id: str) -> None:
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("task_id must be a non-empty string")
    if len(task_id) > _MAX_TASK_ID_LEN:
        raise ValueError(f"task_id too long (>{_MAX_TASK_ID_LEN} chars)")
    if not _TASK_ID_RE.match(task_id):
        raise ValueError(
            f"task_id {task_id!r} contains invalid characters; "
            "allowed: A-Z a-z 0-9 . _ -"
        )


def task_dir(task_id: str, cwd: str | os.PathLike | None = None) -> Path:
    """Return the evidence directory path for a task. Does not create it."""
    _validate_task_id(task_id)
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".conductor" / "evidence" / "tasks" / task_id


def init_task(
    task_id: str,
    *,
    task_name: str,
    phase: str | int,
    cwd: str | os.PathLike | None = None,
) -> Path:
    """Create the evidence folder for a task and write a bootstrap manifest.

    Idempotent: if the folder exists, the manifest is updated in place but
    existing evidence files are preserved.
    Returns the absolute path to the task directory.
    """
    d = task_dir(task_id, cwd)
    d.mkdir(parents=True, exist_ok=True)

    manifest_path = d / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    else:
        manifest = {}

    manifest.update({
        "schema_version": 1,
        "task_id": task_id,
        "task_name": task_name,
        "phase": str(phase),
        "created_at": manifest.get("created_at", _utc_now()),
        "updated_at": _utc_now(),
    })
    _atomic_write_json(manifest_path, manifest)
    return d


def write_envelope(task_id: str, envelope_xml: str, cwd: str | os.PathLike | None = None) -> Path:
    """Persist the dispatch envelope for a task. Overwrites if present."""
    d = task_dir(task_id, cwd)
    if not d.exists():
        raise FileNotFoundError(
            f"task evidence folder missing: {d}. Call init_task() first."
        )
    p = d / "envelope.xml"
    _atomic_write_text(p, envelope_xml)
    return p


def write_result(task_id: str, result_md: str, cwd: str | os.PathLike | None = None) -> Path:
    """Persist the sub-agent's completion report for a task."""
    d = task_dir(task_id, cwd)
    if not d.exists():
        raise FileNotFoundError(
            f"task evidence folder missing: {d}. Call init_task() first."
        )
    p = d / "result.md"
    _atomic_write_text(p, result_md)
    return p


def record_files(
    task_id: str,
    *,
    files_written: list[str],
    commit_sha: str | None = None,
    tests_run: list[str] | None = None,
    cwd: str | os.PathLike | None = None,
) -> Path:
    """Record the files written by a task plus its commit + tests.

    `files.json` is the authoritative artifact for downstream tools (coverage
    matrix, debug map). Overwrites prior content for the task.
    """
    d = task_dir(task_id, cwd)
    if not d.exists():
        raise FileNotFoundError(
            f"task evidence folder missing: {d}. Call init_task() first."
        )
    payload = {
        "schema_version": 1,
        "task_id": task_id,
        "files_written": list(files_written),
        "commit_sha": commit_sha,
        "tests_run": list(tests_run) if tests_run else [],
        "recorded_at": _utc_now(),
    }
    p = d / "files.json"
    _atomic_write_json(p, payload)
    return p


def append_decision(
    task_id: str,
    *,
    decision_id: str,
    summary: str,
    rationale: str = "",
    cwd: str | os.PathLike | None = None,
) -> Path:
    """Append a structured decision record to the task's evidence.

    `decisions.json` is a JSON array; this preserves order and supports
    multiple decisions per task. The high-level decisions.md aggregator lives
    in lib/decisions.py.
    """
    d = task_dir(task_id, cwd)
    if not d.exists():
        raise FileNotFoundError(
            f"task evidence folder missing: {d}. Call init_task() first."
        )
    p = d / "decisions.json"
    if p.exists():
        try:
            records = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                records = []
        except (OSError, json.JSONDecodeError):
            records = []
    else:
        records = []

    records.append({
        "decision_id": decision_id,
        "summary": summary,
        "rationale": rationale,
        "recorded_at": _utc_now(),
    })
    _atomic_write_json(p, records)
    return p


def list_tasks(cwd: str | os.PathLike | None = None) -> list[str]:
    """Return all task IDs that have an evidence folder, sorted."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    root = base / ".conductor" / "evidence" / "tasks"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def read_files_record(task_id: str, cwd: str | os.PathLike | None = None) -> dict | None:
    """Return the parsed files.json for a task, or None if absent/invalid."""
    p = task_dir(task_id, cwd) / "files.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_manifest(task_id: str, cwd: str | os.PathLike | None = None) -> dict | None:
    """Return the parsed manifest.json for a task, or None if absent/invalid."""
    p = task_dir(task_id, cwd) / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Atomic writes — adapted from lib/conductor_state.py's pattern.
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, payload) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))
