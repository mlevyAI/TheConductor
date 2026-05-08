"""Integration tests for hooks/pre_state_committed.py — v6 advisory hook."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "pre_state_committed.py"
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
    d.mkdir()
    (d / "state.json").write_text('{"phase": "1"}')


# ---------------------------------------------------------------------------
# No-op when state.json absent
# ---------------------------------------------------------------------------

def test_noop_when_no_state(tmp_path):
    (tmp_path / ".gitignore").write_text(".conductor/\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert not (tmp_path / ".conductor").exists()


def test_noop_when_no_gitignore(tmp_path):
    _seed_state(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert not (tmp_path / ".conductor" / "findings.md").exists()


def test_noop_when_gitignore_does_not_match(tmp_path):
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules/\n.env\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert not (tmp_path / ".conductor" / "findings.md").exists()


# ---------------------------------------------------------------------------
# Advisory triggers on positive match
# ---------------------------------------------------------------------------

def test_advisory_when_conductor_is_gitignored(tmp_path):
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").write_text(".conductor/\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    findings = (tmp_path / ".conductor" / "findings.md").read_text()
    assert "advisory" in findings
    assert ".gitignore" in findings


def test_advisory_matches_bare_conductor(tmp_path):
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").write_text(".conductor\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert (tmp_path / ".conductor" / "findings.md").exists()


def test_advisory_matches_rooted_form(tmp_path):
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").write_text("/.conductor/\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert (tmp_path / ".conductor" / "findings.md").exists()


def test_negation_suppresses_advisory(tmp_path):
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").write_text(".conductor/\n!.conductor/\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert not (tmp_path / ".conductor" / "findings.md").exists()


def test_comment_does_not_trigger(tmp_path):
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").write_text("# .conductor/\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert not (tmp_path / ".conductor" / "findings.md").exists()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_advisory_logged_only_once(tmp_path):
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").write_text(".conductor/\n")
    _run(tmp_path)
    findings1 = (tmp_path / ".conductor" / "findings.md").read_text()
    _run(tmp_path)
    _run(tmp_path)
    findings2 = (tmp_path / ".conductor" / "findings.md").read_text()
    assert findings1 == findings2


def test_marker_written_after_first_run(tmp_path):
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").write_text(".conductor/\n")
    _run(tmp_path)
    assert (tmp_path / ".conductor" / ".gitignore-warning-logged").exists()


# ---------------------------------------------------------------------------
# Never blocks
# ---------------------------------------------------------------------------

def test_always_exits_zero_even_on_advisory(tmp_path):
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").write_text(".conductor/\n")
    r = _run(tmp_path, payload={"tool_name": "Write", "tool_input": {"file_path": "/tmp/x"}})
    assert r.returncode == 0


def test_handles_unreadable_gitignore_gracefully(tmp_path):
    """If .gitignore exists as a directory (or otherwise unreadable), don't crash."""
    _seed_state(tmp_path)
    (tmp_path / ".gitignore").mkdir()  # exists, but reading raises
    r = _run(tmp_path)
    assert r.returncode == 0
