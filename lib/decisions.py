"""decisions.py — Structured decision provenance.

§v6 of the TheConductor spec.

Wraps `.conductor/decisions.md` with an append-only API that allocates a
monotonic decision ID (D001, D002, ...) and links each decision to the task
that produced it (and to the corresponding evidence folder under
`.conductor/evidence/tasks/<task-id>/decisions.json`).

The on-disk format remains markdown — readable, diff-able, git-friendly —
but every entry now carries a stable identifier so downstream artifacts
(debug map, FINAL_REPORT) can reference decisions surgically.

Existing free-text decisions.md files (pre-v6) are preserved: the allocator
scans for `## D###` headings and counts those when assigning the next ID.
Free-text content above/below the structured block is left untouched.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lib import evidence

_DECISION_HEADING_RE = re.compile(r"^##\s+(D\d{3,})\b", re.MULTILINE)
_DECISION_ID_FMT = "D{:03d}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    summary: str
    rationale: str
    task_id: str | None
    recorded_at: str

    def to_dict(self) -> dict:
        """Return the record as a plain dict.

        Convenience for callers that expected the legacy dict-shaped return
        from `append_decision` (e.g., `record.to_dict().get("decision_id")`).
        Fields match the dataclass: `decision_id`, `summary`, `rationale`,
        `task_id`, `recorded_at`.
        """
        return {
            "decision_id": self.decision_id,
            "summary": self.summary,
            "rationale": self.rationale,
            "task_id": self.task_id,
            "recorded_at": self.recorded_at,
        }


def decisions_path(cwd: str | os.PathLike | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".conductor" / "decisions.md"


def next_decision_id(cwd: str | os.PathLike | None = None) -> str:
    """Return the next available decision ID (D001, D002, ...).

    Pure read — does not modify the file.
    """
    p = decisions_path(cwd)
    if not p.exists():
        return _DECISION_ID_FMT.format(1)
    text = p.read_text(encoding="utf-8")
    used = _DECISION_HEADING_RE.findall(text)
    if not used:
        return _DECISION_ID_FMT.format(1)
    nums = []
    for s in used:
        try:
            nums.append(int(s[1:]))
        except ValueError:
            continue
    return _DECISION_ID_FMT.format((max(nums) + 1) if nums else 1)


def append_decision(
    summary: str,
    *,
    rationale: str = "",
    task_id: str | None = None,
    cwd: str | os.PathLike | None = None,
) -> DecisionRecord:
    """Append a structured decision and return its record.

    Returns a ``DecisionRecord`` dataclass (frozen). Access fields by
    attribute (``record.decision_id``) — **not** by ``.get("decision_id")``,
    which raises ``AttributeError``. If you want dict-shaped access, call
    ``record.to_dict()``.

    Side effects:
      1. Append a markdown block to `.conductor/decisions.md`.
      2. If `task_id` is given AND its evidence folder exists, also append
         to `.conductor/evidence/tasks/<task-id>/decisions.json` (via
         `evidence.append_decision`). If the folder doesn't exist, the
         evidence-side write is skipped silently — the markdown record is
         still authoritative.
    """
    if not summary or not summary.strip():
        raise ValueError("decision summary must be non-empty")

    p = decisions_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)

    decision_id = next_decision_id(cwd)
    recorded_at = _utc_now()

    block_lines = [
        f"## {decision_id} — {summary.strip()}",
        f"- **recorded_at**: {recorded_at}",
    ]
    if task_id:
        block_lines.append(f"- **task_id**: `{task_id}`")
        block_lines.append(
            f"- **evidence**: `.conductor/evidence/tasks/{task_id}/`"
        )
    if rationale and rationale.strip():
        block_lines.append("")
        block_lines.append("**Rationale**")
        block_lines.append("")
        block_lines.append(rationale.strip())
    block_lines.append("")  # trailing blank line

    block = "\n".join(block_lines) + "\n"

    if p.exists():
        existing = p.read_text(encoding="utf-8")
        # Ensure separation if the file doesn't already end with a blank line.
        if existing and not existing.endswith("\n\n"):
            existing = existing.rstrip("\n") + "\n\n"
        new_text = existing + block
    else:
        new_text = "# Decisions\n\n" + block

    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, p)

    record = DecisionRecord(
        decision_id=decision_id,
        summary=summary.strip(),
        rationale=rationale.strip(),
        task_id=task_id,
        recorded_at=recorded_at,
    )

    if task_id is not None and evidence.task_dir(task_id, cwd=cwd).exists():
        evidence.append_decision(
            task_id,
            decision_id=decision_id,
            summary=summary.strip(),
            rationale=rationale.strip(),
            cwd=cwd,
        )

    return record


def list_decisions(cwd: str | os.PathLike | None = None) -> list[str]:
    """Return all decision IDs found in decisions.md, in source order."""
    p = decisions_path(cwd)
    if not p.exists():
        return []
    return _DECISION_HEADING_RE.findall(p.read_text(encoding="utf-8"))
