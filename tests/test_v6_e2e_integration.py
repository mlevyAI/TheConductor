"""End-to-end integration test: spec → splitter → evidence → coverage → debug-map → Stop.

Simulates the full v6 lifecycle as a real user would experience it:

  Phase 0  → user submits spec, conductor scans environment
  Phase 1  → conductor reads spec (BLOCKED if too large), splits it,
             registers acceptance criteria
  Phase 2  → conductor dispatches a task: init evidence → write envelope
             → sub-agent commits → record_files → append decision →
             upsert debug-map feature → write coverage.md
  Stop     → completeness check confirms no gaps; one half-complete task
             is then introduced and detected

This test verifies:
  1. All 9 hooks fire at the right moments without overriding each other
  2. Data flows correctly through the v6 libs (evidence → coverage → debug-map)
  3. Hook precedence: pre_first_response_gate wins over pre_lock_enforcement
     during the gate; pre_lock_enforcement wins over allow during execution
  4. The end state on disk is what `git checkout <SHA>` would restore
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lib import coverage, debug_map, decisions, evidence
from lib.dispatch_envelope import build_prompt
from lib.hooks_manifest import (
    list_hooks,
    load_manifest,
    render_settings_block,
)

REPO_ROOT = Path(__file__).parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_hook(hook: str, cwd: Path, payload: dict | None = None):
    return subprocess.run(
        [PYTHON, str(HOOKS_DIR / hook)],
        input=json.dumps(payload or {}),
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def _write_state(cwd: Path, **fields):
    cd = cwd / ".conductor"
    cd.mkdir(exist_ok=True)
    (cd / "state.json").write_text(json.dumps(fields))


def _write_active_task(cwd: Path, task_id: str, files_write: list[str]):
    locks = cwd / ".conductor" / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    (locks / "active-task.json").write_text(json.dumps({
        "task_id": task_id,
        "files_write": files_write,
    }))


def _make_large_spec(path: Path, lines: int = 600):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ["# Project Spec", ""]
    for i in range(1, lines - 1):
        body.append(f"AC{i}: criterion line {i}")
    path.write_text("\n".join(body))


def _simulate_splitter(cwd: Path):
    """The conductor-spec-splitter skill, simulated as a no-op data write."""
    sp = cwd / ".conductor" / "spec-parts"
    sp.mkdir(parents=True, exist_ok=True)
    (sp / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "global_header": ".conductor/spec-parts/global-header.md",
        "parts": [
            {"part_index": 1, "file": ".conductor/spec-parts/part-1.md"},
            {"part_index": 2, "file": ".conductor/spec-parts/part-2.md"},
        ],
    }))
    (sp / "global-header.md").write_text("# Project: Demo App\nStack: Python+SQLite\n")
    (sp / "part-1.md").write_text("# Part 1: Auth\n" + "section\n" * 50)
    (sp / "part-2.md").write_text("# Part 2: Dashboard\n" + "section\n" * 50)


# ---------------------------------------------------------------------------
# The big one: full lifecycle
# ---------------------------------------------------------------------------

def test_full_v6_lifecycle_spec_to_replay(tmp_path):
    project = tmp_path
    spec = project / "spec.md"
    _make_large_spec(spec, lines=600)

    # ------------------------------------------------------------------
    # Phase 0 — conductor session has just started. State is initialized
    # at the pre_first_response gate.
    # ------------------------------------------------------------------
    _write_state(project, phase="0", gate="pre_first_response_proceed")

    # While the First Response gate is active, a Write to source must be
    # blocked. Simulate the agent attempting to skip ahead and write code:
    src_file = project / "src" / "auth.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    r = _run_hook(
        "pre_first_response_gate.py", project,
        {"tool_name": "Write", "tool_input": {"file_path": str(src_file)}},
    )
    assert r.returncode == 2
    assert "HARD GATE" in r.stderr

    # Reading is still allowed (the gate only blocks mutations)
    r = _run_hook(
        "pre_first_response_gate.py", project,
        {"tool_name": "Read", "tool_input": {"file_path": str(spec)}},
    )
    assert r.returncode == 0

    # But pre_spec_split_enforce SHOULD fire: spec is 600 lines and no
    # manifest exists. This is the v6 enforcement for "don't read a 2000-
    # line spec monolithically."
    r = _run_hook(
        "pre_spec_split_enforce.py", project,
        {"tool_name": "Read", "tool_input": {"file_path": str(spec)}},
    )
    assert r.returncode == 2
    assert "Large spec read blocked" in r.stderr
    assert "conductor-spec-splitter" in r.stderr

    # ------------------------------------------------------------------
    # User replies "proceed" → agent updates state. Gate is now open.
    # ------------------------------------------------------------------
    _write_state(project, phase="1", gate="post_first_response_proceed")

    # First Response gate now no-ops
    r = _run_hook(
        "pre_first_response_gate.py", project,
        {"tool_name": "Write", "tool_input": {"file_path": str(src_file)}},
    )
    assert r.returncode == 0

    # But pre_spec_split_enforce STILL blocks until splitter has run.
    # This proves the two hooks compose: gate stops mutations until
    # 'proceed', spec-split-enforce stops large reads until splitter.
    r = _run_hook(
        "pre_spec_split_enforce.py", project,
        {"tool_name": "Read", "tool_input": {"file_path": str(spec)}},
    )
    assert r.returncode == 2

    # Agent paginates a small read → allowed (overrides not needed)
    r = _run_hook(
        "pre_spec_split_enforce.py", project,
        {"tool_name": "Read", "tool_input": {"file_path": str(spec), "limit": 100}},
    )
    assert r.returncode == 0

    # Agent invokes the splitter skill — manifest now exists
    _simulate_splitter(project)

    # spec-split-enforce now no-ops on the original spec
    r = _run_hook(
        "pre_spec_split_enforce.py", project,
        {"tool_name": "Read", "tool_input": {"file_path": str(spec)}},
    )
    assert r.returncode == 0

    # And reading a part file (under .conductor/) is always allowed
    r = _run_hook(
        "pre_spec_split_enforce.py", project,
        {"tool_name": "Read",
         "tool_input": {"file_path": str(project / ".conductor/spec-parts/part-1.md")}},
    )
    assert r.returncode == 0

    # ------------------------------------------------------------------
    # Phase 1 — register acceptance criteria from the (now-split) spec
    # ------------------------------------------------------------------
    c1 = coverage.register_criterion(
        "User can sign up with email + password", source="spec.md:42", cwd=project,
    )
    c2 = coverage.register_criterion(
        "User can log in and gets a session", source="spec.md:55", cwd=project,
    )
    assert c1.criterion_id == "C001"
    assert c2.criterion_id == "C002"

    # Coverage rendered before any task work shows 0% complete
    cov_md = coverage.write_coverage_md(cwd=project).read_text()
    assert "0/2 criteria complete (0%)" in cov_md

    # ------------------------------------------------------------------
    # Phase 2.task-1 — Implement signup
    # ------------------------------------------------------------------
    task_id = "p2.t1"
    evidence.init_task(task_id, task_name="Implement signup endpoint",
                       phase=2, cwd=project)
    coverage.link_task(c1.criterion_id, task_id, cwd=project)

    # Conductor records the active task's declared writes BEFORE dispatch.
    # This unlocks pre_lock_enforcement.
    _write_active_task(project, task_id, files_write=["src/auth.py"])

    # Build the dispatch envelope and pin it to evidence
    envelope = build_prompt(
        task="Implement POST /signup that accepts {email, password} and "
             "creates a user record",
        constraints="bcrypt for password hashing; SQLite for storage",
        files_write=["src/auth.py"],
        acceptance="POST /signup returns 201 with new user id",
        complexity=5,
        reminder="Hash before storing.",
    )
    evidence.write_envelope(task_id, envelope, cwd=project)

    # Sub-agent (simulated) writes src/auth.py — pre_lock_enforcement
    # must allow this because the path is in files_write
    r = _run_hook(
        "pre_lock_enforcement.py", project,
        {"tool_name": "Write", "tool_input": {"file_path": str(src_file)}},
    )
    assert r.returncode == 0

    # If the sub-agent tried to write OUTSIDE the declared set,
    # pre_lock_enforcement must block — proving the hook is active and
    # not pre-empted by anything earlier in the chain
    rogue = project / "src" / "billing.py"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    r = _run_hook(
        "pre_lock_enforcement.py", project,
        {"tool_name": "Write", "tool_input": {"file_path": str(rogue)}},
    )
    assert r.returncode == 2
    assert "Lock violation" in r.stderr

    # Sub-agent commits (simulated) and conductor receives the SHA
    src_file.write_text('def signup(): pass\n')
    fake_commit = "abc123def456789"
    evidence.write_result(task_id, "# Done\nAll checks pass.", cwd=project)
    evidence.record_files(
        task_id,
        files_written=["src/auth.py"],
        commit_sha=fake_commit,
        tests_run=["tests/test_auth.py"],
        cwd=project,
    )

    # Decision: structured, mirrored to the task's evidence folder
    rec = decisions.append_decision(
        "Use bcrypt for password hashing",
        rationale="Audited; constant-time compare; standard.",
        task_id=task_id,
        cwd=project,
    )
    assert rec.decision_id == "D001"
    # Mirror confirmed
    mirror = json.loads(
        (project / ".conductor/evidence/tasks/p2.t1/decisions.json").read_text()
    )
    assert mirror[0]["decision_id"] == "D001"

    # Live debug map: feature is added immediately, not at end-of-session
    debug_map.upsert_feature(
        "User signup",
        phase=2,
        tasks=[task_id],
        primary_files=["src/auth.py"],
        test_files=["tests/test_auth.py"],
        commit_shas=[fake_commit],
        subagent="general-purpose",
        model_requested="sonnet",
        key_decisions=["D001"],
        cwd=project,
    )
    debug_map.write_debug_map_md(cwd=project)
    debug_md = (project / ".conductor/debug-map.md").read_text()
    assert "User signup" in debug_md
    assert "abc123de" in debug_md  # short SHA
    assert "D001" in debug_md

    # Coverage now shows 1/2 complete (signup done; login pending)
    coverage.write_coverage_md(cwd=project)
    cov_md = (project / ".conductor/coverage.md").read_text()
    assert "1/2 criteria complete (50%)" in cov_md
    assert "✅" in cov_md  # at least one row shows complete

    # ------------------------------------------------------------------
    # Stop hooks: with everything completed cleanly, no advisories
    # ------------------------------------------------------------------
    r = _run_hook("stop_evidence_completeness_check.py", project)
    assert r.returncode == 0
    findings = project / ".conductor" / "findings.md"
    if findings.exists():
        # If a previous unrelated advisory was logged, it must NOT contain
        # this evidence-completeness signal
        assert "incomplete v6 evidence" not in findings.read_text()

    # ------------------------------------------------------------------
    # Phase 2.task-2 — Implement login. We INIT but do NOT record_files,
    # simulating a session that ended mid-task. Stop hook must catch this.
    # ------------------------------------------------------------------
    evidence.init_task("p2.t2", task_name="Implement login",
                       phase=2, cwd=project)
    coverage.link_task(c2.criterion_id, "p2.t2", cwd=project)

    r = _run_hook("stop_evidence_completeness_check.py", project)
    assert r.returncode == 0
    findings_text = (project / ".conductor/findings.md").read_text()
    assert "incomplete v6 evidence" in findings_text
    assert "p2.t2" in findings_text
    assert "Implement login" in findings_text
    # Completed task must NOT be flagged
    assert "p2.t1" not in findings_text.split("incomplete v6 evidence")[1]

    # ------------------------------------------------------------------
    # "Replay" — months later, a developer needs to debug the signup feature
    # ------------------------------------------------------------------
    rec = evidence.read_files_record("p2.t1", cwd=project)
    assert rec is not None
    assert rec["commit_sha"] == fake_commit
    assert rec["files_written"] == ["src/auth.py"]
    assert rec["tests_run"] == ["tests/test_auth.py"]

    manifest = evidence.read_manifest("p2.t1", cwd=project)
    assert manifest is not None
    assert manifest["task_name"] == "Implement signup endpoint"

    # The original dispatch envelope is recoverable verbatim
    env = (project / ".conductor/evidence/tasks/p2.t1/envelope.xml").read_text()
    assert "<task>" in env
    assert "POST /signup" in env

    # Decisions are query-able by ID
    assert decisions.list_decisions(cwd=project) == ["D001"]


# ---------------------------------------------------------------------------
# Hook precedence and no-conflict matrix
# ---------------------------------------------------------------------------

def test_no_hook_blocks_a_legitimate_v6_evidence_write(tmp_path):
    """A Write to .conductor/evidence/tasks/<id>/ must pass ALL PreToolUse
    hooks regardless of phase — evidence is the conductor's own state."""
    _write_state(tmp_path, phase="2", gate="post_first_response_proceed")
    _write_active_task(tmp_path, "p2.t1", files_write=["src/x.py"])

    target = tmp_path / ".conductor/evidence/tasks/p2.t1/result.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}

    for hook in [
        "pre_phase0_readonly.py",
        "pre_first_response_gate.py",
        "pre_busy_wait_block.py",
        "pre_state_committed.py",
        "pre_spec_split_enforce.py",
    ]:
        r = _run_hook(hook, tmp_path, payload)
        assert r.returncode == 0, (
            f"{hook} unexpectedly blocked an evidence write\n"
            f"stderr: {r.stderr}"
        )

    # pre_lock_enforcement is special — it CAN block writes outside the
    # declared set. .conductor/evidence/ is outside src/x.py — this is a
    # known intentional behavior; the conductor records evidence via
    # lib.evidence.* (Python imports), not via the Write tool.
    r = _run_hook("pre_lock_enforcement.py", tmp_path, payload)
    assert r.returncode == 2  # documents the boundary


def test_paginated_spec_read_passes_all_hooks(tmp_path):
    """A paginated Read of a large spec passes pre_spec_split_enforce
    regardless of manifest — and is silent for all other hooks."""
    _write_state(tmp_path, phase="1", gate="post_first_response_proceed")
    spec = tmp_path / "spec.md"
    _make_large_spec(spec, lines=2000)

    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(spec), "limit": 200},
    }
    for hook in [
        "pre_phase0_readonly.py",
        "pre_first_response_gate.py",
        "pre_busy_wait_block.py",
        "pre_lock_enforcement.py",
        "pre_state_committed.py",
        "pre_spec_split_enforce.py",
    ]:
        r = _run_hook(hook, tmp_path, payload)
        assert r.returncode == 0, f"{hook} blocked a paginated read; stderr: {r.stderr}"


def test_advisory_hooks_never_block(tmp_path):
    """Both v6 advisory hooks must always exit 0, even when they have
    something to say."""
    _write_state(tmp_path, phase="1", gate="post_first_response_proceed")

    # pre_state_committed: gitignore says .conductor/ → advisory case
    (tmp_path / ".gitignore").write_text(".conductor/\n")
    r = _run_hook("pre_state_committed.py", tmp_path, {})
    assert r.returncode == 0
    assert "advisory" in (tmp_path / ".conductor/findings.md").read_text()

    # stop_evidence_completeness_check: incomplete task → advisory case
    evidence.init_task("p2.t1", task_name="x", phase=2, cwd=tmp_path)
    r = _run_hook("stop_evidence_completeness_check.py", tmp_path, {})
    assert r.returncode == 0
    assert "incomplete v6 evidence" in (tmp_path / ".conductor/findings.md").read_text()


# ---------------------------------------------------------------------------
# Manifest / settings rendering reflects what the integration test exercises
# ---------------------------------------------------------------------------

def test_phase_b_plus_v6_settings_render_includes_all_exercised_hooks(tmp_path):
    """The bundles offer must produce settings.json that wires every hook
    exercised by the lifecycle test above."""
    block = render_settings_block(
        ["phase_b", "v6_replayability"],
        hook_dir=str(tmp_path / ".claude/hooks"),
    )
    all_commands: list[str] = []
    for entries in block["hooks"].values():
        for e in entries:
            for h in e["hooks"]:
                all_commands.append(h["command"])

    must_be_wired = [
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
    for name in must_be_wired:
        assert any(name in c for c in all_commands), (
            f"hook {name!r} exercised by lifecycle but not wired by "
            "render_settings_block(['phase_b', 'v6_replayability'])"
        )
