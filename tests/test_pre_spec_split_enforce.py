"""Integration tests for hooks/pre_spec_split_enforce.py — v6 large-spec blocker."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "pre_spec_split_enforce.py"
PYTHON = sys.executable


def _run(cwd: Path, payload: dict):
    return subprocess.run(
        [PYTHON, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def _seed_state(cwd: Path):
    d = cwd / ".conductor"
    d.mkdir(exist_ok=True)
    (d / "state.json").write_text('{"phase": "1"}')


def _seed_manifest(cwd: Path):
    d = cwd / ".conductor" / "spec-parts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text('{"parts": []}')


def _make_spec(path: Path, lines: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"line {i}" for i in range(lines)))


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------

def test_noop_when_no_state(tmp_path):
    spec = tmp_path / "spec.md"
    _make_spec(spec, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(spec)}})
    assert r.returncode == 0


def test_noop_when_tool_is_not_read(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 1000)
    r = _run(tmp_path, {"tool_name": "Write", "tool_input": {"file_path": str(spec)}})
    assert r.returncode == 0


def test_noop_when_file_path_missing(tmp_path):
    _seed_state(tmp_path)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {}})
    assert r.returncode == 0


def test_noop_when_file_does_not_exist(tmp_path):
    _seed_state(tmp_path)
    r = _run(tmp_path, {"tool_name": "Read",
                         "tool_input": {"file_path": str(tmp_path / "ghost.md")}})
    assert r.returncode == 0


def test_noop_when_file_is_small(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 100)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(spec)}})
    assert r.returncode == 0


def test_noop_when_manifest_exists(tmp_path):
    _seed_state(tmp_path)
    _seed_manifest(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(spec)}})
    assert r.returncode == 0


def test_noop_when_opt_out_marker_exists(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 1000)
    (tmp_path / ".conductor" / ".spec-split-skipped").write_text("1")
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(spec)}})
    assert r.returncode == 0


def test_noop_when_paginated_with_small_limit(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 1000)
    r = _run(tmp_path, {"tool_name": "Read",
                         "tool_input": {"file_path": str(spec), "limit": 200}})
    assert r.returncode == 0


def test_noop_when_paginated_limit_at_threshold(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 1000)
    r = _run(tmp_path, {"tool_name": "Read",
                         "tool_input": {"file_path": str(spec), "limit": 500}})
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# Excluded paths and filenames
# ---------------------------------------------------------------------------

def test_noop_for_readme(tmp_path):
    _seed_state(tmp_path)
    f = tmp_path / "README.md"
    _make_spec(f, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 0


def test_noop_for_changelog(tmp_path):
    _seed_state(tmp_path)
    f = tmp_path / "CHANGELOG.md"
    _make_spec(f, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 0


def test_noop_for_project_conductor_md(tmp_path):
    _seed_state(tmp_path)
    f = tmp_path / "project-conductor.md"
    _make_spec(f, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 0


def test_noop_for_test_md_file(tmp_path):
    _seed_state(tmp_path)
    f = tmp_path / "auth.test.md"
    _make_spec(f, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 0


def test_noop_for_file_under_dot_conductor(tmp_path):
    _seed_state(tmp_path)
    f = tmp_path / ".conductor" / "spec-parts" / "part-1.md"
    _make_spec(f, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 0


def test_noop_for_non_spec_filename(tmp_path):
    """A 1000-line random source file (e.g., main.py.md) should not be blocked."""
    _seed_state(tmp_path)
    f = tmp_path / "implementation_notes.md"
    _make_spec(f, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 0


def test_noop_for_path_outside_cwd(tmp_path, tmp_path_factory):
    _seed_state(tmp_path)
    other = tmp_path_factory.mktemp("other") / "spec.md"
    _make_spec(other, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(other)}})
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# Blocking cases
# ---------------------------------------------------------------------------

def test_blocks_large_spec_md(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(spec)}})
    assert r.returncode == 2
    assert "Large spec read blocked" in r.stderr
    assert "1000 lines" in r.stderr
    assert "conductor-spec-splitter" in r.stderr


def test_blocks_requirements_md(tmp_path):
    _seed_state(tmp_path)
    f = tmp_path / "requirements.md"
    _make_spec(f, 500)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 2


def test_blocks_prd_md(tmp_path):
    _seed_state(tmp_path)
    f = tmp_path / "prd-v2.md"
    _make_spec(f, 400)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 2


def test_blocks_dotted_spec_md(tmp_path):
    _seed_state(tmp_path)
    f = tmp_path / "auth.spec.md"
    _make_spec(f, 1500)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 2


def test_blocks_file_in_specs_directory(tmp_path):
    _seed_state(tmp_path)
    f = tmp_path / "specs" / "feature-x.md"
    _make_spec(f, 700)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(f)}})
    assert r.returncode == 2


def test_blocks_paginated_read_with_huge_limit(tmp_path):
    """If `limit` is > the paginated threshold, we still block."""
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 2000)
    r = _run(tmp_path, {"tool_name": "Read",
                         "tool_input": {"file_path": str(spec), "limit": 5000}})
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# Threshold edge cases
# ---------------------------------------------------------------------------

def test_exactly_300_lines_does_not_block(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 300)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(spec)}})
    assert r.returncode == 0


def test_301_lines_blocks(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 301)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(spec)}})
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# Error message quality
# ---------------------------------------------------------------------------

def test_block_message_mentions_skipping_marker(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(spec)}})
    assert ".spec-split-skipped" in r.stderr


def test_block_message_mentions_paginated_escape(tmp_path):
    _seed_state(tmp_path)
    spec = tmp_path / "spec.md"
    _make_spec(spec, 1000)
    r = _run(tmp_path, {"tool_name": "Read", "tool_input": {"file_path": str(spec)}})
    assert "Paginated" in r.stderr or "paginated" in r.stderr.lower()
