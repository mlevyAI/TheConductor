"""Tests for lib/decisions.py — v6 structured decision provenance."""

import json

import pytest

from lib import decisions, evidence


def _read_md(tmp_path):
    return (tmp_path / ".conductor" / "decisions.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# next_decision_id
# ---------------------------------------------------------------------------

def test_next_id_is_d001_when_file_absent(tmp_path):
    assert decisions.next_decision_id(cwd=tmp_path) == "D001"


def test_next_id_increments_after_first_append(tmp_path):
    decisions.append_decision("Use Postgres", cwd=tmp_path)
    assert decisions.next_decision_id(cwd=tmp_path) == "D002"


def test_next_id_skips_pre_v6_freetext(tmp_path):
    """A pre-v6 decisions.md with no D### headings should still start at D001."""
    p = tmp_path / ".conductor" / "decisions.md"
    p.parent.mkdir()
    p.write_text("# Decisions\n\n- Picked Vue (no rationale captured)\n")
    assert decisions.next_decision_id(cwd=tmp_path) == "D001"


def test_next_id_handles_gaps(tmp_path):
    """If someone hand-edits decisions.md to skip an ID, next is max+1."""
    p = tmp_path / ".conductor" / "decisions.md"
    p.parent.mkdir()
    p.write_text("## D005 — first\n\n## D003 — second\n")
    assert decisions.next_decision_id(cwd=tmp_path) == "D006"


# ---------------------------------------------------------------------------
# append_decision — basic
# ---------------------------------------------------------------------------

def test_append_creates_file(tmp_path):
    rec = decisions.append_decision("Use Postgres", cwd=tmp_path)
    assert rec.decision_id == "D001"
    md = _read_md(tmp_path)
    assert "# Decisions" in md
    assert "## D001 — Use Postgres" in md


def test_append_records_rationale(tmp_path):
    decisions.append_decision(
        "Use Postgres",
        rationale="Project needs joins; ORM compatibility matters.",
        cwd=tmp_path,
    )
    md = _read_md(tmp_path)
    assert "**Rationale**" in md
    assert "Project needs joins" in md


def test_append_omits_rationale_section_when_empty(tmp_path):
    decisions.append_decision("Use Postgres", cwd=tmp_path)
    md = _read_md(tmp_path)
    assert "**Rationale**" not in md


def test_append_rejects_empty_summary(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        decisions.append_decision("", cwd=tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        decisions.append_decision("   ", cwd=tmp_path)


def test_append_returns_record(tmp_path):
    rec = decisions.append_decision("Pick Vue", rationale="lighter", cwd=tmp_path)
    assert rec.summary == "Pick Vue"
    assert rec.rationale == "lighter"
    assert rec.task_id is None
    assert rec.recorded_at  # non-empty timestamp


def test_append_assigns_sequential_ids(tmp_path):
    r1 = decisions.append_decision("first", cwd=tmp_path)
    r2 = decisions.append_decision("second", cwd=tmp_path)
    r3 = decisions.append_decision("third", cwd=tmp_path)
    assert [r1.decision_id, r2.decision_id, r3.decision_id] == ["D001", "D002", "D003"]


# ---------------------------------------------------------------------------
# append_decision — task linkage
# ---------------------------------------------------------------------------

def test_append_with_task_writes_link_in_md(tmp_path):
    evidence.init_task("p2.t1", task_name="Signup", phase=2, cwd=tmp_path)
    decisions.append_decision("Use bcrypt", task_id="p2.t1", cwd=tmp_path)
    md = _read_md(tmp_path)
    assert "task_id" in md
    assert "p2.t1" in md
    assert ".conductor/evidence/tasks/p2.t1" in md


def test_append_with_task_mirrors_to_evidence(tmp_path):
    evidence.init_task("p2.t1", task_name="Signup", phase=2, cwd=tmp_path)
    decisions.append_decision(
        "Use bcrypt",
        rationale="standard, audited",
        task_id="p2.t1",
        cwd=tmp_path,
    )
    j = tmp_path / ".conductor" / "evidence" / "tasks" / "p2.t1" / "decisions.json"
    records = json.loads(j.read_text())
    assert records[0]["decision_id"] == "D001"
    assert records[0]["summary"] == "Use bcrypt"
    assert records[0]["rationale"] == "standard, audited"


def test_append_with_unknown_task_skips_evidence_silently(tmp_path):
    """If the task evidence folder doesn't exist, the markdown record is still
    written but the evidence side-effect is skipped (no exception)."""
    rec = decisions.append_decision("decision", task_id="nonexistent", cwd=tmp_path)
    assert rec.decision_id == "D001"
    assert "## D001" in _read_md(tmp_path)


# ---------------------------------------------------------------------------
# Coexistence with pre-v6 free-text content
# ---------------------------------------------------------------------------

def test_append_preserves_existing_freetext(tmp_path):
    p = tmp_path / ".conductor" / "decisions.md"
    p.parent.mkdir()
    original = "# Decisions\n\n- Picked Vue (legacy)\n"
    p.write_text(original)
    decisions.append_decision("New decision", cwd=tmp_path)
    md = p.read_text()
    assert "Picked Vue (legacy)" in md
    assert "## D001 — New decision" in md


def test_list_decisions_returns_ids_in_source_order(tmp_path):
    decisions.append_decision("a", cwd=tmp_path)
    decisions.append_decision("b", cwd=tmp_path)
    decisions.append_decision("c", cwd=tmp_path)
    assert decisions.list_decisions(cwd=tmp_path) == ["D001", "D002", "D003"]


# ---------------------------------------------------------------------------
# DecisionRecord.to_dict() (v6.1.6+)
# ---------------------------------------------------------------------------

def test_to_dict_returns_all_fields(tmp_path):
    record = decisions.append_decision(
        "approve enrichments",
        rationale="user replied 'approve enrichments'",
        task_id="phase-1.foundation",
        cwd=tmp_path,
    )
    d = record.to_dict()
    assert d["decision_id"] == "D001"
    assert d["summary"] == "approve enrichments"
    assert d["rationale"] == "user replied 'approve enrichments'"
    assert d["task_id"] == "phase-1.foundation"
    assert isinstance(d["recorded_at"], str)
    # exhaustive — no extra or missing fields
    assert set(d.keys()) == {"decision_id", "summary", "rationale", "task_id", "recorded_at"}


def test_to_dict_handles_none_task_id(tmp_path):
    record = decisions.append_decision("setup event", cwd=tmp_path)
    d = record.to_dict()
    assert d["task_id"] is None
    assert d["rationale"] == ""
