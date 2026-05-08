"""Tests for lib/coverage.py — v6 spec coverage matrix."""

import json

import pytest

from lib import coverage, evidence


# ---------------------------------------------------------------------------
# register_criterion
# ---------------------------------------------------------------------------

def test_register_assigns_c001_first(tmp_path):
    c = coverage.register_criterion("User can sign up with email", cwd=tmp_path)
    assert c.criterion_id == "C001"
    assert c.text == "User can sign up with email"


def test_register_assigns_sequential_ids(tmp_path):
    c1 = coverage.register_criterion("a", cwd=tmp_path)
    c2 = coverage.register_criterion("b", cwd=tmp_path)
    c3 = coverage.register_criterion("c", cwd=tmp_path)
    assert [c1.criterion_id, c2.criterion_id, c3.criterion_id] == ["C001", "C002", "C003"]


def test_register_is_idempotent_on_text(tmp_path):
    c1 = coverage.register_criterion("dup", cwd=tmp_path)
    c2 = coverage.register_criterion("dup", cwd=tmp_path)
    assert c1.criterion_id == c2.criterion_id


def test_register_distinguishes_by_source(tmp_path):
    c1 = coverage.register_criterion("dup", source="spec.md:10", cwd=tmp_path)
    c2 = coverage.register_criterion("dup", source="spec.md:42", cwd=tmp_path)
    assert c1.criterion_id != c2.criterion_id


def test_register_rejects_empty(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        coverage.register_criterion("", cwd=tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        coverage.register_criterion("   ", cwd=tmp_path)


def test_register_persists_to_json(tmp_path):
    coverage.register_criterion("a", source="spec.md:1", cwd=tmp_path)
    data = json.loads((tmp_path / ".conductor" / "coverage.json").read_text())
    assert data["schema_version"] == 1
    assert data["criteria"][0]["criterion_id"] == "C001"
    assert data["criteria"][0]["source"] == "spec.md:1"


# ---------------------------------------------------------------------------
# link_task
# ---------------------------------------------------------------------------

def test_link_task_appends(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    coverage.link_task("C001", "p2.t1", cwd=tmp_path)
    coverage.link_task("C001", "p2.t2", cwd=tmp_path)
    crits = coverage.list_criteria(cwd=tmp_path)
    assert crits[0].tasks == ["p2.t1", "p2.t2"]


def test_link_task_is_idempotent(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    coverage.link_task("C001", "p2.t1", cwd=tmp_path)
    coverage.link_task("C001", "p2.t1", cwd=tmp_path)
    crits = coverage.list_criteria(cwd=tmp_path)
    assert crits[0].tasks == ["p2.t1"]


def test_link_task_unknown_criterion_raises(tmp_path):
    with pytest.raises(KeyError):
        coverage.link_task("C999", "p2.t1", cwd=tmp_path)


# ---------------------------------------------------------------------------
# derive_status
# ---------------------------------------------------------------------------

def test_status_not_started_with_no_tasks(tmp_path):
    c = coverage.register_criterion("a", cwd=tmp_path)
    assert coverage.derive_status(c, cwd=tmp_path) == "not_started"


def test_status_not_started_when_evidence_folder_missing(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    coverage.link_task("C001", "ghost", cwd=tmp_path)
    c = coverage.list_criteria(cwd=tmp_path)[0]
    assert coverage.derive_status(c, cwd=tmp_path) == "not_started"


def test_status_in_progress_when_evidence_but_no_commit(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    coverage.link_task("C001", "p2.t1", cwd=tmp_path)
    evidence.init_task("p2.t1", task_name="x", phase=2, cwd=tmp_path)
    c = coverage.list_criteria(cwd=tmp_path)[0]
    assert coverage.derive_status(c, cwd=tmp_path) == "in_progress"


def test_status_complete_when_commit_recorded(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    coverage.link_task("C001", "p2.t1", cwd=tmp_path)
    evidence.init_task("p2.t1", task_name="x", phase=2, cwd=tmp_path)
    evidence.record_files("p2.t1", files_written=["a.py"], commit_sha="abc123", cwd=tmp_path)
    c = coverage.list_criteria(cwd=tmp_path)[0]
    assert coverage.derive_status(c, cwd=tmp_path) == "complete"


def test_status_complete_if_any_linked_task_completes(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    coverage.link_task("C001", "p2.t1", cwd=tmp_path)
    coverage.link_task("C001", "p2.t2", cwd=tmp_path)
    evidence.init_task("p2.t1", task_name="x", phase=2, cwd=tmp_path)
    evidence.init_task("p2.t2", task_name="y", phase=2, cwd=tmp_path)
    evidence.record_files("p2.t2", files_written=["b.py"], commit_sha="xyz", cwd=tmp_path)
    c = coverage.list_criteria(cwd=tmp_path)[0]
    assert coverage.derive_status(c, cwd=tmp_path) == "complete"


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

def test_render_empty_state(tmp_path):
    md = coverage.render_markdown(cwd=tmp_path)
    assert "# Spec Coverage Matrix" in md
    assert "No criteria registered" in md


def test_render_includes_table_header(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    md = coverage.render_markdown(cwd=tmp_path)
    assert "| ID | Criterion |" in md
    assert "C001" in md


def test_render_shows_completion_percentage(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    coverage.register_criterion("b", cwd=tmp_path)
    coverage.link_task("C001", "t1", cwd=tmp_path)
    evidence.init_task("t1", task_name="x", phase=2, cwd=tmp_path)
    evidence.record_files("t1", files_written=["a.py"], commit_sha="aaa", cwd=tmp_path)
    md = coverage.render_markdown(cwd=tmp_path)
    assert "1/2 criteria complete (50%)" in md


def test_render_escapes_pipes_in_criterion_text(tmp_path):
    coverage.register_criterion("can do A | B | C", cwd=tmp_path)
    md = coverage.render_markdown(cwd=tmp_path)
    assert "can do A \\| B \\| C" in md
    # Sanity: the table still has exactly one row body (header + sep + 1 data)
    body_rows = [line for line in md.splitlines() if line.startswith("| C001")]
    assert len(body_rows) == 1


def test_render_shows_short_commit_sha(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    coverage.link_task("C001", "t1", cwd=tmp_path)
    evidence.init_task("t1", task_name="x", phase=2, cwd=tmp_path)
    evidence.record_files(
        "t1",
        files_written=["a.py"],
        commit_sha="abcdef1234567890",
        tests_run=["tests/test_a.py"],
        cwd=tmp_path,
    )
    md = coverage.render_markdown(cwd=tmp_path)
    assert "`abcdef12`" in md
    assert "`tests/test_a.py`" in md


# ---------------------------------------------------------------------------
# write_coverage_md
# ---------------------------------------------------------------------------

def test_write_coverage_md_writes_file(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    p = coverage.write_coverage_md(cwd=tmp_path)
    assert p.exists()
    assert "# Spec Coverage Matrix" in p.read_text()


def test_write_coverage_md_overwrites(tmp_path):
    coverage.register_criterion("a", cwd=tmp_path)
    coverage.write_coverage_md(cwd=tmp_path)
    coverage.register_criterion("b", cwd=tmp_path)
    coverage.write_coverage_md(cwd=tmp_path)
    md = (tmp_path / ".conductor" / "coverage.md").read_text()
    assert "C001" in md
    assert "C002" in md
