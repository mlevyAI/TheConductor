"""Integration tests for hooks/stop_evidence_completeness_check.py."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "stop_evidence_completeness_check.py"
PYTHON = sys.executable


def _run(cwd: Path, payload: dict | None = None):
    return subprocess.run(
        [PYTHON, str(HOOK)],
        input=json.dumps(payload or {}),
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def _seed_state(cwd: Path):
    d = cwd / ".conductor"
    d.mkdir(exist_ok=True)
    (d / "state.json").write_text('{"phase": "1"}')


def _seed_task(cwd: Path, task_id: str, *, with_files: bool = False,
               commit_sha: str | None = None, task_name: str = ""):
    d = cwd / ".conductor" / "evidence" / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "task_id": task_id,
        "task_name": task_name,
        "phase": "2",
    }))
    if with_files:
        (d / "files.json").write_text(json.dumps({
            "schema_version": 1,
            "task_id": task_id,
            "files_written": ["a.py"],
            "commit_sha": commit_sha,
            "tests_run": [],
        }))


def _findings(cwd: Path) -> str:
    p = cwd / ".conductor" / "advisories.md"
    return p.read_text() if p.exists() else ""


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------

def test_noop_when_no_state(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert not (tmp_path / ".conductor").exists()


def test_noop_when_no_evidence_dir(tmp_path):
    _seed_state(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "advisory" not in _findings(tmp_path)


def test_noop_when_all_tasks_complete(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=True, commit_sha="abc123")
    _seed_task(tmp_path, "p2.t2", with_files=True, commit_sha="def456")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "advisory" not in _findings(tmp_path)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_flags_task_with_no_files_json(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=False, task_name="Implement signup")
    r = _run(tmp_path)
    assert r.returncode == 0
    findings = _findings(tmp_path)
    assert "advisory" in findings
    assert "p2.t1" in findings
    assert "Implement signup" in findings
    assert "files.json" in findings


def test_flags_task_with_null_commit_sha(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=True, commit_sha=None)
    r = _run(tmp_path)
    assert r.returncode == 0
    findings = _findings(tmp_path)
    assert "advisory" in findings
    assert "commit_sha" in findings


def test_flags_task_with_empty_commit_sha(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=True, commit_sha="")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "p2.t1" in _findings(tmp_path)


def test_flags_only_incomplete_tasks(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=True, commit_sha="abc")  # complete
    _seed_task(tmp_path, "p2.t2", with_files=False, task_name="Incomplete")
    _seed_task(tmp_path, "p2.t3", with_files=True, commit_sha="def")  # complete
    r = _run(tmp_path)
    findings = _findings(tmp_path)
    assert "p2.t1" not in findings
    assert "p2.t3" not in findings
    assert "p2.t2" in findings
    assert "Incomplete" in findings


def test_handles_unreadable_files_json(tmp_path):
    _seed_state(tmp_path)
    d = tmp_path / ".conductor" / "evidence" / "tasks" / "p2.t1"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"task_id": "p2.t1"}))
    (d / "files.json").write_text("not json {{")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "p2.t1" in _findings(tmp_path)
    assert "unreadable" in _findings(tmp_path)


# ---------------------------------------------------------------------------
# Idempotency / dedup
# ---------------------------------------------------------------------------

def test_does_not_relog_unchanged_gap_set(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=False)
    _run(tmp_path)
    findings1 = _findings(tmp_path)
    _run(tmp_path)
    _run(tmp_path)
    findings2 = _findings(tmp_path)
    assert findings1 == findings2


def test_relogs_when_gap_set_changes(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=False)
    _run(tmp_path)
    # New gap appears
    _seed_task(tmp_path, "p2.t2", with_files=False)
    _run(tmp_path)
    findings = _findings(tmp_path)
    # both advisories should be present (two appended blocks)
    assert findings.count("advisory") == 2
    assert "p2.t1" in findings
    assert "p2.t2" in findings


def test_relogs_when_gap_resolved_then_new_appears(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=False)
    _run(tmp_path)
    # Resolve t1
    _seed_task(tmp_path, "p2.t1", with_files=True, commit_sha="abc")
    # Add new gap
    _seed_task(tmp_path, "p2.t2", with_files=False)
    _run(tmp_path)
    findings = _findings(tmp_path)
    # advisory appended twice; second mentions only t2
    assert findings.count("advisory") == 2


def test_marker_persisted_between_runs(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=False)
    _run(tmp_path)
    marker = tmp_path / ".conductor" / ".evidence-completeness-last-warned"
    assert marker.is_file()
    assert marker.read_text().strip()  # non-empty hash


# ---------------------------------------------------------------------------
# Always-zero exit
# ---------------------------------------------------------------------------

def test_always_exits_zero(tmp_path):
    _seed_state(tmp_path)
    _seed_task(tmp_path, "p2.t1", with_files=False)
    r = _run(tmp_path)
    assert r.returncode == 0
