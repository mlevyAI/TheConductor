"""Tests for hooks/bootstrap_phase_0a.py — v6.0.3 SessionStart enforcement bootstrap.

The hook is wired ONCE in user-global ~/.claude/settings.json (by install.sh
Step 8). It fires for every Claude Code session and decides — based on
multiple conservative signals — whether to auto-install the 9 enforcement
hooks into <cwd>/.claude/settings.json.

These tests cover:
  - Conservative no-op for non-conductor sessions
  - Idempotency: doesn't re-install when hooks are already wired
  - Correctness: when it does install, the right hooks land, atomically
  - Failure-safety: never blocks Claude Code (always exits 0)
  - The detection signals (existing .conductor/, payload mention, existing
    hooks reference, spec.md + CLAUDE.md combination)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "bootstrap_phase_0a.py"
PYTHON = sys.executable


def _run(cwd: Path, *, payload: str = "{}", fake_home: Path | None = None):
    env = os.environ.copy()
    if fake_home is not None:
        env["HOME"] = str(fake_home)
    return subprocess.run(
        [PYTHON, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def _make_conductor_installed(fake_home: Path) -> None:
    """Create the user-global agent file that signals the conductor is installed."""
    agents = fake_home / ".claude" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "project-conductor.md").write_text(
        "---\nname: project-conductor\n---\nbody\n", encoding="utf-8"
    )


def _read_settings(cwd: Path) -> dict:
    p = cwd / ".claude" / "settings.json"
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Conservative no-op when not a conductor session
# ---------------------------------------------------------------------------

def test_noop_when_conductor_not_installed(tmp_path, tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home_no_conductor")
    # No agent file in fake_home → conductor not installed
    r = _run(tmp_path, fake_home=fake_home)
    assert r.returncode == 0
    assert not (tmp_path / ".claude" / "settings.json").exists()


def test_noop_when_conductor_installed_but_no_signals(tmp_path, tmp_path_factory):
    """Conductor agent file exists, but cwd has no .conductor/, no spec.md,
    no payload mention. Hook should still no-op (conservative)."""
    fake_home = tmp_path_factory.mktemp("home_with_conductor")
    _make_conductor_installed(fake_home)
    r = _run(tmp_path, payload="{}", fake_home=fake_home)
    assert r.returncode == 0
    assert not (tmp_path / ".claude" / "settings.json").exists()


# ---------------------------------------------------------------------------
# 2. Detection signals — each one alone triggers install
# ---------------------------------------------------------------------------

def test_signal_existing_conductor_dir_triggers_install(tmp_path, tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home_signal_conductor_dir")
    _make_conductor_installed(fake_home)
    (tmp_path / ".conductor").mkdir()  # signal: resumed conductor session
    r = _run(tmp_path, fake_home=fake_home)
    assert r.returncode == 0
    settings = _read_settings(tmp_path)
    assert "hooks" in settings
    assert "PreToolUse" in settings["hooks"]


def test_signal_payload_mention_triggers_install(tmp_path, tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home_signal_payload")
    _make_conductor_installed(fake_home)
    payload = json.dumps({"agent": "project-conductor"})
    r = _run(tmp_path, payload=payload, fake_home=fake_home)
    assert r.returncode == 0
    settings = _read_settings(tmp_path)
    assert "hooks" in settings


def test_signal_spec_plus_claude_md_triggers_install(tmp_path, tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home_signal_spec")
    _make_conductor_installed(fake_home)
    (tmp_path / "spec.md").write_text("# Spec\n")
    (tmp_path / "CLAUDE.md").write_text("Use project-conductor for builds.")
    r = _run(tmp_path, fake_home=fake_home)
    assert r.returncode == 0
    settings = _read_settings(tmp_path)
    assert "hooks" in settings


def test_signal_spec_alone_does_not_trigger(tmp_path, tmp_path_factory):
    """spec.md alone is NOT enough — many projects have a spec.md without
    using the conductor. CLAUDE.md or another signal must align."""
    fake_home = tmp_path_factory.mktemp("home_spec_alone")
    _make_conductor_installed(fake_home)
    (tmp_path / "spec.md").write_text("# Generic Spec\n")
    r = _run(tmp_path, fake_home=fake_home)
    assert r.returncode == 0
    assert not (tmp_path / ".claude" / "settings.json").exists()


# ---------------------------------------------------------------------------
# 3. What gets installed
# ---------------------------------------------------------------------------

def test_install_wires_all_nine_enforcement_hooks(tmp_path, tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home_full_install")
    _make_conductor_installed(fake_home)
    (tmp_path / ".conductor").mkdir()
    r = _run(tmp_path, fake_home=fake_home)
    assert r.returncode == 0
    settings = _read_settings(tmp_path)
    blob = json.dumps(settings)

    expected_hooks = [
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
    for name in expected_hooks:
        assert name in blob, f"enforcement hook {name!r} not wired by bootstrap"


def test_install_groups_hooks_by_event(tmp_path, tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home_groups")
    _make_conductor_installed(fake_home)
    (tmp_path / ".conductor").mkdir()
    _run(tmp_path, fake_home=fake_home)
    settings = _read_settings(tmp_path)
    assert "PreToolUse" in settings["hooks"]
    assert "PostToolUse" in settings["hooks"]
    assert "Stop" in settings["hooks"]


def test_install_logs_to_decisions_md(tmp_path, tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home_decisions")
    _make_conductor_installed(fake_home)
    (tmp_path / ".conductor").mkdir()
    _run(tmp_path, fake_home=fake_home)
    decisions = (tmp_path / ".conductor" / "decisions.md").read_text(encoding="utf-8")
    assert "bootstrap auto-install" in decisions
    assert "phase_b" in decisions
    assert "v6_replayability" in decisions


def test_install_adds_permissions_allow_entries(tmp_path, tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home_perms")
    _make_conductor_installed(fake_home)
    (tmp_path / ".conductor").mkdir()
    _run(tmp_path, fake_home=fake_home)
    settings = _read_settings(tmp_path)
    perms = settings.get("permissions", {}).get("allow", [])
    # 6 phase_b + 3 v6 = 9 entries
    assert len(perms) >= 9
    assert all(isinstance(p, str) and p.startswith("Bash(") for p in perms)


# ---------------------------------------------------------------------------
# 4. Idempotency
# ---------------------------------------------------------------------------

def test_does_not_double_wire(tmp_path, tmp_path_factory):
    fake_home = tmp_path_factory.mktemp("home_idempotent")
    _make_conductor_installed(fake_home)
    (tmp_path / ".conductor").mkdir()
    _run(tmp_path, fake_home=fake_home)
    s1 = _read_settings(tmp_path)
    pre1 = len(s1["hooks"]["PreToolUse"][0]["hooks"])

    _run(tmp_path, fake_home=fake_home)
    _run(tmp_path, fake_home=fake_home)
    s2 = _read_settings(tmp_path)
    pre2 = len(s2["hooks"]["PreToolUse"][0]["hooks"])

    # Same number of hooks — second run detected existing wiring and no-op'd
    assert pre1 == pre2


def test_preserves_user_authored_hook_entries(tmp_path, tmp_path_factory):
    """If the user already has their own hooks in settings.json, the bootstrap
    must merge — not clobber."""
    fake_home = tmp_path_factory.mktemp("home_merge")
    _make_conductor_installed(fake_home)
    (tmp_path / ".conductor").mkdir()
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    user_hook = {
        "hooks": {
            "PreToolUse": [
                {"hooks": [{"type": "command", "command": "echo my-custom-hook"}]}
            ],
        },
        "model": "claude-opus-4-7",
        "env": {"MY_VAR": "value"},
    }
    settings_path.write_text(json.dumps(user_hook), encoding="utf-8")

    _run(tmp_path, fake_home=fake_home)
    merged = _read_settings(tmp_path)

    # User-authored entries preserved
    assert merged["model"] == "claude-opus-4-7"
    assert merged["env"]["MY_VAR"] == "value"
    pre_commands = [
        h["command"]
        for entry in merged["hooks"]["PreToolUse"]
        for h in entry.get("hooks", [])
    ]
    assert any("my-custom-hook" in c for c in pre_commands)
    # And our enforcement hooks are wired alongside
    assert any("pre_phase0_readonly.py" in c for c in pre_commands)


# ---------------------------------------------------------------------------
# 5. Failure-safety
# ---------------------------------------------------------------------------

def test_handles_corrupted_settings_json_gracefully(tmp_path, tmp_path_factory):
    """A corrupt existing settings.json must NOT crash the hook or clobber
    the file. Hook exits 0; original content preserved."""
    fake_home = tmp_path_factory.mktemp("home_corrupt")
    _make_conductor_installed(fake_home)
    (tmp_path / ".conductor").mkdir()
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt = "this is not { valid json }}}"
    settings_path.write_text(corrupt, encoding="utf-8")

    r = _run(tmp_path, fake_home=fake_home)
    assert r.returncode == 0
    assert settings_path.read_text() == corrupt  # untouched


def test_always_exits_zero_even_on_unexpected_error(tmp_path):
    """Empty stdin, no conductor agent, weird state — exit must always be 0
    so we never block a Claude Code session."""
    r = _run(tmp_path, payload="not even valid json", fake_home=tmp_path / "no-home")
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# 6. Quick reject on non-conductor sessions (performance / safety check)
# ---------------------------------------------------------------------------

def test_does_not_modify_settings_in_non_conductor_session(tmp_path, tmp_path_factory):
    """The hook fires for ALL Claude Code sessions globally. In non-conductor
    sessions it must be a strict no-op — no file creation, no log spam."""
    fake_home = tmp_path_factory.mktemp("home_no_conductor")
    # Conductor not installed → fast-path no-op
    r = _run(tmp_path, fake_home=fake_home)
    assert r.returncode == 0
    # Nothing under .claude/, .conductor/ created
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".conductor").exists()
