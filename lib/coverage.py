"""coverage.py — Spec coverage matrix.

§v6 of the TheConductor spec.

Tracks acceptance criteria from the spec → tasks that implement them → the
evidence (commit, tests) that proves them. The conductor (or a skill)
registers criteria explicitly via `register_criterion()`; this module does
NOT try to auto-parse the spec, because spec formats vary too widely for
heuristic extraction to be reliable. Explicit registration also makes the
coverage matrix auditable: every criterion has a known origin.

Persistence:

  .conductor/coverage.json   — authoritative structured state
  .conductor/coverage.md     — rendered markdown view (overwritten on each
                                update; do not hand-edit)

Derived status (per criterion):
  not_started — no task linked, or all linked tasks lack evidence
  in_progress — at least one linked task has an evidence folder
  complete    — at least one linked task has a recorded commit_sha
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from lib import evidence

_CRITERION_ID_FMT = "C{:03d}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Criterion:
    criterion_id: str
    text: str
    source: str  # human-readable origin, e.g., "spec.md:42"
    tasks: list[str] = field(default_factory=list)
    registered_at: str = ""

    def to_dict(self) -> dict:
        return {
            "criterion_id": self.criterion_id,
            "text": self.text,
            "source": self.source,
            "tasks": list(self.tasks),
            "registered_at": self.registered_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Criterion":
        return cls(
            criterion_id=d["criterion_id"],
            text=d["text"],
            source=d.get("source", ""),
            tasks=list(d.get("tasks", [])),
            registered_at=d.get("registered_at", ""),
        )


def coverage_json_path(cwd: str | os.PathLike | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".conductor" / "coverage.json"


def coverage_md_path(cwd: str | os.PathLike | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".conductor" / "coverage.md"


def _load(cwd: str | os.PathLike | None) -> list[Criterion]:
    p = coverage_json_path(cwd)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("criteria", []) if isinstance(data, dict) else []
    return [Criterion.from_dict(c) for c in raw if isinstance(c, dict)]


def _save(criteria: list[Criterion], cwd: str | os.PathLike | None) -> None:
    p = coverage_json_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": _utc_now(),
        "criteria": [c.to_dict() for c in criteria],
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _next_criterion_id(existing: list[Criterion]) -> str:
    if not existing:
        return _CRITERION_ID_FMT.format(1)
    nums = []
    for c in existing:
        if c.criterion_id.startswith("C"):
            try:
                nums.append(int(c.criterion_id[1:]))
            except ValueError:
                continue
    return _CRITERION_ID_FMT.format((max(nums) + 1) if nums else 1)


def register_criterion(
    text: str,
    *,
    source: str = "",
    cwd: str | os.PathLike | None = None,
) -> Criterion:
    """Register a new acceptance criterion. Idempotent on text+source.

    If a criterion with the same `text` (and matching `source` if provided)
    already exists, returns the existing record without modification.
    """
    if not text or not text.strip():
        raise ValueError("criterion text must be non-empty")
    text = text.strip()

    existing = _load(cwd)
    for c in existing:
        if c.text == text and (not source or c.source == source):
            return c

    new = Criterion(
        criterion_id=_next_criterion_id(existing),
        text=text,
        source=source,
        tasks=[],
        registered_at=_utc_now(),
    )
    existing.append(new)
    _save(existing, cwd)
    return new


def link_task(
    criterion_id: str,
    task_id: str,
    cwd: str | os.PathLike | None = None,
) -> None:
    """Associate a task with a criterion. Idempotent."""
    if not criterion_id or not task_id:
        raise ValueError("criterion_id and task_id must be non-empty")
    existing = _load(cwd)
    for c in existing:
        if c.criterion_id == criterion_id:
            if task_id not in c.tasks:
                c.tasks.append(task_id)
                _save(existing, cwd)
            return
    raise KeyError(f"criterion {criterion_id!r} not found")


def list_criteria(cwd: str | os.PathLike | None = None) -> list[Criterion]:
    return _load(cwd)


def derive_status(criterion: Criterion, cwd: str | os.PathLike | None = None) -> str:
    """Return one of: not_started | in_progress | complete."""
    if not criterion.tasks:
        return "not_started"
    has_evidence = False
    for task_id in criterion.tasks:
        if not evidence.task_dir(task_id, cwd=cwd).exists():
            continue
        has_evidence = True
        rec = evidence.read_files_record(task_id, cwd=cwd)
        if rec and rec.get("commit_sha"):
            return "complete"
    return "in_progress" if has_evidence else "not_started"


def render_markdown(cwd: str | os.PathLike | None = None) -> str:
    criteria = _load(cwd)
    if not criteria:
        return (
            "# Spec Coverage Matrix\n\n"
            "_No criteria registered yet. The conductor registers criteria "
            "during Phase 1 enrichment via `lib.coverage.register_criterion()`._\n"
        )

    rows = []
    for c in criteria:
        status = derive_status(c, cwd=cwd)
        emoji = {
            "not_started": "⬜",
            "in_progress": "🟡",
            "complete": "✅",
        }.get(status, "❓")
        commits = []
        tests = []
        for tid in c.tasks:
            rec = evidence.read_files_record(tid, cwd=cwd)
            if not rec:
                continue
            sha = rec.get("commit_sha")
            if sha:
                commits.append(f"`{sha[:8]}`")
            for t in rec.get("tests_run", []) or []:
                tests.append(f"`{t}`")
        rows.append({
            "criterion_id": c.criterion_id,
            "text": c.text,
            "tasks": ", ".join(f"`{t}`" for t in c.tasks) or "—",
            "status": f"{emoji} {status.replace('_', ' ')}",
            "commits": ", ".join(commits) or "—",
            "tests": ", ".join(tests) or "—",
        })

    total = len(criteria)
    complete = sum(1 for c in criteria if derive_status(c, cwd=cwd) == "complete")
    pct = (complete * 100) // total if total else 0

    out = []
    out.append("# Spec Coverage Matrix\n")
    out.append(f"**Coverage: {complete}/{total} criteria complete ({pct}%)**\n")
    out.append("| ID | Criterion | Tasks | Status | Commit | Tests |")
    out.append("|----|-----------|-------|--------|--------|-------|")
    for r in rows:
        # Pipes inside the criterion text would break the table — escape.
        text = r["text"].replace("|", "\\|")
        out.append(
            f"| {r['criterion_id']} | {text} | {r['tasks']} | "
            f"{r['status']} | {r['commits']} | {r['tests']} |"
        )
    out.append("")  # trailing newline
    return "\n".join(out)


def write_coverage_md(cwd: str | os.PathLike | None = None) -> Path:
    p = coverage_md_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = render_markdown(cwd=cwd)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
    return p
