"""Integration tests for Phase B hooks.

Each test runs the hook script via subprocess from a temp dir that either has
or lacks .conductor/state.json, simulating real Claude Code PreToolUse/Stop invocations.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
PYTHON = sys.executable


def run_hook(hook_name: str, stdin_data: dict, state: dict = None,
             active_task: dict = None) -> subprocess.CompletedProcess:
    """Run hook from a fresh temp dir; optionally seed .conductor/state.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        if state is not None:
            conductor_dir = Path(tmpdir) / ".conductor"
            conductor_dir.mkdir()
            (conductor_dir / "state.json").write_text(json.dumps(state))
            if active_task is not None:
                locks_dir = conductor_dir / "locks"
                locks_dir.mkdir()
                (locks_dir / "active-task.json").write_text(json.dumps(active_task))
        return subprocess.run(
            [PYTHON, str(HOOKS_DIR / hook_name)],
            input=json.dumps(stdin_data),
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )


# ---------------------------------------------------------------------------
# Universal no-op guard — all 6 hooks must exit 0 when state.json absent
# ---------------------------------------------------------------------------

HOOK_NAMES = [
    "pre_phase0_readonly.py",
    "pre_first_response_gate.py",
    "pre_busy_wait_block.py",
    "pre_lock_enforcement.py",
    "post_output_quality.py",
    "stop_validate_final_report.py",
    "pre_state_committed.py",
    "pre_spec_split_enforce.py",
    "stop_evidence_completeness_check.py",
]


def test_noop_guard_all_hooks_exit_0_when_no_state_json():
    payload = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x.py"}}
    for hook in HOOK_NAMES:
        r = run_hook(hook, payload, state=None)
        assert r.returncode == 0, (
            f"{hook} should exit 0 (no-op) when state.json absent, "
            f"got {r.returncode}\nstderr: {r.stderr}"
        )


# ---------------------------------------------------------------------------
# User-global write blocker — all Write|Edit PreToolUse hooks must block
# ~/.claude/ targets regardless of phase/gate
# ---------------------------------------------------------------------------

USER_GLOBAL_TARGET = str(Path.home() / ".claude" / "skills" / "foo.md")

PRETOOLUSE_WRITE_HOOKS = [
    "pre_phase0_readonly.py",
    "pre_first_response_gate.py",
    "pre_lock_enforcement.py",
]


def test_user_global_write_blocker():
    state = {"phase": "1", "gate": "post_first_response_proceed"}
    payload = {"tool_name": "Write", "tool_input": {"file_path": USER_GLOBAL_TARGET}}
    for hook in PRETOOLUSE_WRITE_HOOKS:
        r = run_hook(hook, payload, state=state)
        assert r.returncode == 2, (
            f"{hook} must exit 2 for ~/.claude/ target, got {r.returncode}\n"
            f"stderr: {r.stderr}"
        )
        assert "refusing to write under ~/.claude/" in r.stderr, (
            f"{hook} must emit canonical §3.1 stderr\nstderr: {r.stderr}"
        )


# ---------------------------------------------------------------------------
# pre_phase0_readonly
# ---------------------------------------------------------------------------

def test_pre_phase0_readonly_allows_write_in_phase1():
    state = {"phase": "1", "gate": "post_first_response_proceed"}
    r = run_hook("pre_phase0_readonly.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 0


def test_pre_phase0_readonly_blocks_write_outside_conductor_in_phase0():
    state = {"phase": "0", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_phase0_readonly.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 2
    assert "Phase 0 is READ-ONLY" in r.stderr


def test_pre_phase0_readonly_allows_write_to_conductor_dir_in_phase0(tmp_path):
    state = {"phase": "0", "gate": "pre_first_response_proceed"}
    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    target = str(conductor_dir / "findings.md")
    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "pre_phase0_readonly.py")],
        input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": target}}),
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0


def test_pre_phase0_readonly_blocks_mutating_bash_in_phase0():
    state = {"phase": "0", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_phase0_readonly.py",
                 {"tool_name": "Bash", "tool_input": {"command": "git add src/app.py"}},
                 state=state)
    assert r.returncode == 2
    assert "READ-ONLY" in r.stderr


def test_pre_phase0_readonly_allows_readonly_bash_in_phase0():
    state = {"phase": "0", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_phase0_readonly.py",
                 {"tool_name": "Bash", "tool_input": {"command": "git status"}},
                 state=state)
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# pre_first_response_gate
# ---------------------------------------------------------------------------

def test_first_response_gate_allows_when_gate_open():
    state = {"phase": "1", "gate": "post_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 0


def test_first_response_gate_blocks_write_outside_conductor():
    state = {"phase": "1", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 2
    assert "HARD GATE" in r.stderr


def test_first_response_gate_blocks_edit():
    state = {"phase": "1", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 2


def test_first_response_gate_blocks_task():
    state = {"phase": "1", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Task", "tool_input": {"description": "do something"}},
                 state=state)
    assert r.returncode == 2


def test_first_response_gate_blocks_mutating_bash():
    state = {"phase": "1", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Bash", "tool_input": {"command": "npm install"}},
                 state=state)
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# pre_busy_wait_block
# ---------------------------------------------------------------------------

def test_busy_wait_allows_normal_bash():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
                 state=state)
    assert r.returncode == 0


def test_busy_wait_blocks_until_sleep():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash",
                  "tool_input": {"command": "until check; do sleep 5; done"}},
                 state=state)
    assert r.returncode == 2
    assert "busy-wait" in r.stderr.lower()


def test_busy_wait_blocks_while_sleep():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash",
                  "tool_input": {"command": "while true; do sleep 30; done"}},
                 state=state)
    assert r.returncode == 2


def test_busy_wait_blocks_leading_long_sleep():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash", "tool_input": {"command": "sleep 300"}},
                 state=state)
    assert r.returncode == 2


def test_busy_wait_allows_short_sleep():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash", "tool_input": {"command": "sleep 5"}},
                 state=state)
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# pre_lock_enforcement
# ---------------------------------------------------------------------------

def test_lock_enforcement_tolerant_fallback_when_no_active_task():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_lock_enforcement.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/anything.py"}},
                 state=state)
    assert r.returncode == 0


def test_lock_enforcement_allows_declared_path(tmp_path):
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    active_task = {"task_id": "t1", "files_write": [str(src_dir)]}
    target = str(src_dir / "app.py")

    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    locks_dir = conductor_dir / "locks"
    locks_dir.mkdir()
    (locks_dir / "active-task.json").write_text(json.dumps(active_task))

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "pre_lock_enforcement.py")],
        input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": target}}),
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0


def test_lock_enforcement_blocks_undeclared_path(tmp_path):
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    active_task = {"task_id": "t1", "files_write": [str(src_dir)]}
    target = str(tmp_path / "config" / "secret.env")

    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    locks_dir = conductor_dir / "locks"
    locks_dir.mkdir()
    (locks_dir / "active-task.json").write_text(json.dumps(active_task))

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "pre_lock_enforcement.py")],
        input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": target}}),
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 2
    assert "Lock violation" in r.stderr


# ---------------------------------------------------------------------------
# post_output_quality
# ---------------------------------------------------------------------------

def test_output_quality_allows_non_structured_file():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("post_output_quality.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 0


def test_output_quality_writes_finding_for_empty_csv_column(tmp_path):
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    csv_path = tmp_path / "output.csv"
    csv_path.write_text("name,age,email\nAlice,30,\nBob,25,\n")

    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "post_output_quality.py")],
        input=json.dumps({"tool_name": "Write",
                          "tool_input": {"file_path": str(csv_path)}}),
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0  # non-blocking
    findings = (conductor_dir / "findings.md").read_text()
    assert "email" in findings
    assert "empty" in findings.lower()


# ---------------------------------------------------------------------------
# stop_validate_final_report
# ---------------------------------------------------------------------------

def test_stop_validator_noop_when_phase_not_complete():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("stop_validate_final_report.py", {}, state=state)
    assert r.returncode == 0


def test_stop_validator_writes_finding_when_report_missing(tmp_path):
    state = {"phase": "complete", "gate": "post_first_response_proceed"}
    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "stop_validate_final_report.py")],
        input="{}",
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    findings = (conductor_dir / "findings.md").read_text()
    assert "FINAL_REPORT.md not found" in findings


def test_stop_validator_writes_finding_when_sections_missing(tmp_path):
    state = {"phase": "complete", "gate": "post_first_response_proceed"}
    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    (tmp_path / "FINAL_REPORT.md").write_text("# Report\n\n## Summary\nDone.\n")

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "stop_validate_final_report.py")],
        input="{}",
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    findings = (conductor_dir / "findings.md").read_text()
    assert "missing sections" in findings


def test_stop_validator_passes_complete_report(tmp_path):
    state = {"phase": "complete", "gate": "post_first_response_proceed"}
    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    (tmp_path / "FINAL_REPORT.md").write_text(
        "# Report\n## Executive Summary\n## Plan vs Actual\n"
        "## Material Changes Log\n## Routing Notes\n## Safety Mechanism Outcomes\n"
        "## Surgical Debug Map\n## Outstanding Items\n## Evidence Index\n"
        "## Recommended Next Steps\n"
    )

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "stop_validate_final_report.py")],
        input="{}",
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    findings_path = conductor_dir / "findings.md"
    assert not findings_path.exists() or "missing sections" not in findings_path.read_text()
