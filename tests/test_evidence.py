"""Tests for lib/evidence.py — v6 per-task evidence folder."""

import json

import pytest

from lib.evidence import (
    append_decision,
    init_task,
    list_tasks,
    read_files_record,
    read_manifest,
    record_files,
    task_dir,
    write_envelope,
    write_result,
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_task_dir_rejects_empty_id(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        task_dir("", cwd=tmp_path)


def test_task_dir_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="invalid characters"):
        task_dir("../../etc/passwd", cwd=tmp_path)


def test_task_dir_rejects_slashes(tmp_path):
    with pytest.raises(ValueError, match="invalid characters"):
        task_dir("phase-2/task-3", cwd=tmp_path)


def test_task_dir_rejects_too_long(tmp_path):
    with pytest.raises(ValueError, match="too long"):
        task_dir("a" * 81, cwd=tmp_path)


def test_task_dir_accepts_dotted_form(tmp_path):
    # The conductor uses IDs like "phase-2.task-3"
    p = task_dir("phase-2.task-3", cwd=tmp_path)
    assert p.name == "phase-2.task-3"


# ---------------------------------------------------------------------------
# init_task
# ---------------------------------------------------------------------------

def test_init_creates_directory_and_manifest(tmp_path):
    d = init_task("p2.t1", task_name="Implement signup", phase=2, cwd=tmp_path)
    assert d.is_dir()
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["task_id"] == "p2.t1"
    assert manifest["task_name"] == "Implement signup"
    assert manifest["phase"] == "2"
    assert manifest["schema_version"] == 1
    assert "created_at" in manifest


def test_init_is_idempotent(tmp_path):
    init_task("p2.t1", task_name="Implement signup", phase=2, cwd=tmp_path)
    # Write some content that should survive a re-init
    (tmp_path / ".conductor/evidence/tasks/p2.t1/result.md").write_text("ok")
    init_task("p2.t1", task_name="Implement signup (renamed)", phase=2, cwd=tmp_path)
    assert (tmp_path / ".conductor/evidence/tasks/p2.t1/result.md").read_text() == "ok"
    manifest = read_manifest("p2.t1", cwd=tmp_path)
    assert manifest["task_name"] == "Implement signup (renamed)"


def test_init_preserves_created_at_on_reinit(tmp_path):
    init_task("p2.t1", task_name="x", phase=2, cwd=tmp_path)
    first = read_manifest("p2.t1", cwd=tmp_path)["created_at"]
    init_task("p2.t1", task_name="x", phase=2, cwd=tmp_path)
    second = read_manifest("p2.t1", cwd=tmp_path)["created_at"]
    assert first == second


# ---------------------------------------------------------------------------
# write_envelope / write_result
# ---------------------------------------------------------------------------

def test_write_envelope_persists_xml(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    xml = "<task>Build a thing</task>"
    p = write_envelope("t", xml, cwd=tmp_path)
    assert p.read_text() == xml


def test_write_envelope_overwrites(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    write_envelope("t", "<task>v1</task>", cwd=tmp_path)
    write_envelope("t", "<task>v2</task>", cwd=tmp_path)
    assert (task_dir("t", cwd=tmp_path) / "envelope.xml").read_text() == "<task>v2</task>"


def test_write_envelope_requires_init(tmp_path):
    with pytest.raises(FileNotFoundError, match="init_task"):
        write_envelope("never-initialized", "<task>x</task>", cwd=tmp_path)


def test_write_result_persists_md(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    md = "# Result\n\nAll tests pass."
    p = write_result("t", md, cwd=tmp_path)
    assert p.read_text() == md


# ---------------------------------------------------------------------------
# record_files
# ---------------------------------------------------------------------------

def test_record_files_writes_json(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    record_files(
        "t",
        files_written=["src/a.py", "src/b.py"],
        commit_sha="abc123",
        tests_run=["tests/test_a.py"],
        cwd=tmp_path,
    )
    rec = read_files_record("t", cwd=tmp_path)
    assert rec["files_written"] == ["src/a.py", "src/b.py"]
    assert rec["commit_sha"] == "abc123"
    assert rec["tests_run"] == ["tests/test_a.py"]
    assert rec["schema_version"] == 1


def test_record_files_optional_fields_default_safely(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    record_files("t", files_written=[], cwd=tmp_path)
    rec = read_files_record("t", cwd=tmp_path)
    assert rec["files_written"] == []
    assert rec["commit_sha"] is None
    assert rec["tests_run"] == []


def test_record_files_overwrites(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    record_files("t", files_written=["a.py"], commit_sha="aaa", cwd=tmp_path)
    record_files("t", files_written=["a.py", "b.py"], commit_sha="bbb", cwd=tmp_path)
    rec = read_files_record("t", cwd=tmp_path)
    assert rec["files_written"] == ["a.py", "b.py"]
    assert rec["commit_sha"] == "bbb"


def test_read_files_record_returns_none_when_absent(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    assert read_files_record("t", cwd=tmp_path) is None


def test_read_files_record_returns_none_for_invalid_json(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    (task_dir("t", cwd=tmp_path) / "files.json").write_text("not json {{{")
    assert read_files_record("t", cwd=tmp_path) is None


# ---------------------------------------------------------------------------
# append_decision
# ---------------------------------------------------------------------------

def test_append_decision_creates_array(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    append_decision(
        "t",
        decision_id="D001",
        summary="Use Postgres",
        rationale="Project needs joins",
        cwd=tmp_path,
    )
    records = json.loads((task_dir("t", cwd=tmp_path) / "decisions.json").read_text())
    assert len(records) == 1
    assert records[0]["decision_id"] == "D001"
    assert records[0]["summary"] == "Use Postgres"


def test_append_decision_preserves_order(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    append_decision("t", decision_id="D001", summary="first", cwd=tmp_path)
    append_decision("t", decision_id="D002", summary="second", cwd=tmp_path)
    append_decision("t", decision_id="D003", summary="third", cwd=tmp_path)
    records = json.loads((task_dir("t", cwd=tmp_path) / "decisions.json").read_text())
    assert [r["decision_id"] for r in records] == ["D001", "D002", "D003"]


def test_append_decision_recovers_from_corrupted_file(tmp_path):
    init_task("t", task_name="x", phase=2, cwd=tmp_path)
    (task_dir("t", cwd=tmp_path) / "decisions.json").write_text("not json")
    append_decision("t", decision_id="D001", summary="ok", cwd=tmp_path)
    records = json.loads((task_dir("t", cwd=tmp_path) / "decisions.json").read_text())
    assert len(records) == 1


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------

def test_list_tasks_returns_empty_when_no_evidence(tmp_path):
    assert list_tasks(cwd=tmp_path) == []


def test_list_tasks_returns_sorted_ids(tmp_path):
    init_task("p2.t3", task_name="x", phase=2, cwd=tmp_path)
    init_task("p1.t1", task_name="x", phase=1, cwd=tmp_path)
    init_task("p2.t1", task_name="x", phase=2, cwd=tmp_path)
    assert list_tasks(cwd=tmp_path) == ["p1.t1", "p2.t1", "p2.t3"]
