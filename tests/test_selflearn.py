"""Tests for the Layer 2 self-learning hook (agent-monitor/selflearn.py)
and the memory.json writer in agent-monitor/reporter.py."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AM_DIR = REPO / "agent-monitor"


def _load_module(name: str, path: Path):
    """Load a module fresh with module-level constants pointing at the given dir.

    reporter.py and selflearn.py both compute LOG_DIR from `__file__`, so
    importing them and then mutating constants is the simplest way to redirect
    them at a temp directory under test.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _redirect(mod, tmp: Path) -> None:
    mod.LOG_DIR = str(tmp)
    if hasattr(mod, "MEMORY_FILE"):
        mod.MEMORY_FILE = str(tmp / "memory.json")
    if hasattr(mod, "LAST_INJECTION_FILE"):
        mod.LAST_INJECTION_FILE = str(tmp / "last_injection.md")
    if hasattr(mod, "DISABLED_FLAG"):
        mod.DISABLED_FLAG = str(tmp / "selflearn.disabled")
    if hasattr(mod, "HOOK_ERRORS_FILE"):
        mod.HOOK_ERRORS_FILE = str(tmp / "hook-errors.log")
    if hasattr(mod, "LOG_FILE"):
        mod.LOG_FILE = str(tmp / "activity.jsonl")
    if hasattr(mod, "REPORTS_DIR"):
        mod.REPORTS_DIR = str(tmp / "reports")


# ---------------------------------------------------------------------------
# memory.json writer (reporter.update_memory)
# ---------------------------------------------------------------------------


def test_update_memory_creates_file_on_first_run(tmp_path):
    rep = _load_module("rep1", AM_DIR / "reporter.py")
    _redirect(rep, tmp_path)

    rep.update_memory([["probe_sprawl", "repeat_bash"]], "2026-05-10T10:00:00")
    mem = json.loads((tmp_path / "memory.json").read_text())

    assert mem["schema_version"] == 1
    assert mem["sessions_observed"] == 1
    assert mem["window_size"] == 20
    assert len(mem["session_history"]) == 1
    assert sorted(mem["patterns"].keys()) == ["probe_sprawl", "repeat_bash"]
    assert mem["patterns"]["probe_sprawl"]["hits"] == 1


def test_update_memory_increments_recurring_pattern(tmp_path):
    rep = _load_module("rep2", AM_DIR / "reporter.py")
    _redirect(rep, tmp_path)

    rep.update_memory([["probe_sprawl"]], "2026-05-09T10:00:00")
    rep.update_memory([["probe_sprawl"]], "2026-05-10T10:00:00")
    rep.update_memory([["probe_sprawl", "repeat_bash"]], "2026-05-11T10:00:00")

    mem = json.loads((tmp_path / "memory.json").read_text())
    assert mem["sessions_observed"] == 3
    assert mem["patterns"]["probe_sprawl"]["hits"] == 3
    assert mem["patterns"]["repeat_bash"]["hits"] == 1
    assert mem["patterns"]["probe_sprawl"]["first_seen"] == "2026-05-09T10:00:00"
    assert mem["patterns"]["probe_sprawl"]["last_seen"] == "2026-05-11T10:00:00"


def test_update_memory_window_ages_out_old_sessions(tmp_path):
    rep = _load_module("rep3", AM_DIR / "reporter.py")
    _redirect(rep, tmp_path)
    rep.MEMORY_WINDOW_SIZE = 3  # tighten for the test

    # 5 sessions, only first 2 had probe_sprawl
    for i, patterns in enumerate([
        ["probe_sprawl"], ["probe_sprawl"],
        ["repeat_bash"], ["repeat_bash"], ["repeat_bash"],
    ]):
        rep.update_memory([patterns], f"2026-05-{10 + i:02d}T10:00:00")

    # Reload memory and check window pruned
    mem = json.loads((tmp_path / "memory.json").read_text())
    assert len(mem["session_history"]) == 3, "window should hold only last 3 sessions"
    # probe_sprawl fell out of the window — should not appear at all
    assert "probe_sprawl" not in mem["patterns"]
    assert mem["patterns"]["repeat_bash"]["hits"] == 3


def test_load_memory_returns_empty_on_corrupted_file(tmp_path):
    rep = _load_module("rep4", AM_DIR / "reporter.py")
    _redirect(rep, tmp_path)
    (tmp_path / "memory.json").write_text("{not valid json")

    mem = rep.load_memory()
    assert mem["sessions_observed"] == 0
    assert mem["patterns"] == {}


def test_load_memory_archives_incompatible_schema(tmp_path):
    rep = _load_module("rep5", AM_DIR / "reporter.py")
    _redirect(rep, tmp_path)
    (tmp_path / "memory.json").write_text(json.dumps({
        "schema_version": 99,
        "patterns": {"probe_sprawl": {"hits": 5}},
    }))
    mem = rep.load_memory()
    assert mem["schema_version"] == 1
    assert mem["sessions_observed"] == 0
    # The old file should have been archived, not silently overwritten
    assert (tmp_path / "memory.json.v99.bak").exists()


def test_update_memory_atomic_no_partial_file(tmp_path):
    rep = _load_module("rep6", AM_DIR / "reporter.py")
    _redirect(rep, tmp_path)
    rep.update_memory([["probe_sprawl"]], "2026-05-10T10:00:00")
    # No .tmp leftover
    assert not (tmp_path / "memory.json.tmp").exists()


# ---------------------------------------------------------------------------
# selflearn.py — build_injection
# ---------------------------------------------------------------------------


def test_build_injection_empty_memory_returns_empty(tmp_path):
    sl = _load_module("sl1", AM_DIR / "selflearn.py")
    _redirect(sl, tmp_path)
    assert sl.build_injection({"sessions_observed": 0, "patterns": {}}) == ""


def test_build_injection_single_pattern(tmp_path):
    sl = _load_module("sl2", AM_DIR / "selflearn.py")
    _redirect(sl, tmp_path)
    memory = {
        "sessions_observed": 5,
        "patterns": {
            "probe_sprawl": {"hits": 3, "last_seen": "2026-05-10T10:00:00"},
        },
    }
    out = sl.build_injection(memory)
    assert "probe_sprawl" in out
    assert "3 of last 5" in out
    assert "throwaway research scripts" in out
    assert "selflearn.disabled" in out  # opt-out hint included


def test_build_injection_orders_by_hits(tmp_path):
    sl = _load_module("sl3", AM_DIR / "selflearn.py")
    _redirect(sl, tmp_path)
    memory = {
        "sessions_observed": 10,
        "patterns": {
            "scope_shrink": {"hits": 1, "last_seen": "2026-05-10T10:00:00"},
            "probe_sprawl": {"hits": 9, "last_seen": "2026-05-09T10:00:00"},
            "repeat_bash":  {"hits": 4, "last_seen": "2026-05-08T10:00:00"},
        },
    }
    out = sl.build_injection(memory)
    # probe_sprawl (9) should come before repeat_bash (4) before scope_shrink (1)
    assert out.index("probe_sprawl") < out.index("repeat_bash") < out.index("scope_shrink")


def test_build_injection_caps_at_max_patterns(tmp_path):
    sl = _load_module("sl4", AM_DIR / "selflearn.py")
    _redirect(sl, tmp_path)
    sl.MAX_PATTERNS = 2
    memory = {
        "sessions_observed": 10,
        "patterns": {
            "probe_sprawl":        {"hits": 9, "last_seen": "2026-05-09T10:00:00"},
            "repeat_bash":         {"hits": 8, "last_seen": "2026-05-09T10:00:00"},
            "no_forward_progress": {"hits": 7, "last_seen": "2026-05-09T10:00:00"},
            "scope_shrink":        {"hits": 6, "last_seen": "2026-05-09T10:00:00"},
        },
    }
    out = sl.build_injection(memory)
    # Only top-2 (probe_sprawl, repeat_bash) should appear in advice list
    advice_lines = [l for l in out.splitlines() if l.startswith("- ")]
    assert len(advice_lines) == 2
    assert "probe_sprawl" in advice_lines[0]
    assert "repeat_bash" in advice_lines[1]


def test_build_injection_skips_unknown_pattern_ids(tmp_path):
    sl = _load_module("sl5", AM_DIR / "selflearn.py")
    _redirect(sl, tmp_path)
    memory = {
        "sessions_observed": 3,
        "patterns": {
            "future_pattern_we_dont_know_about_yet": {"hits": 99, "last_seen": "2026-05-10T10:00:00"},
            "probe_sprawl": {"hits": 1, "last_seen": "2026-05-10T10:00:00"},
        },
    }
    out = sl.build_injection(memory)
    # We surface probe_sprawl (known) and skip the unknown id silently.
    assert "probe_sprawl" in out
    assert "future_pattern" not in out


# ---------------------------------------------------------------------------
# selflearn.py — main() as a SessionStart hook
# ---------------------------------------------------------------------------


def _run_selflearn(tmp_path: Path, payload: str = "") -> subprocess.CompletedProcess:
    """Invoke selflearn.py as a real Claude Code SessionStart hook would,
    with LOG_DIR redirected via env-passed PATH override. We pass the temp
    dir as cwd and rewrite the constants by importing-and-running in-process
    is too brittle for stdout JSON; subprocess invocation is the truth."""
    # Stage a copy of selflearn.py with constants pointing to tmp_path
    staged = tmp_path / "selflearn.py"
    src = (AM_DIR / "selflearn.py").read_text()
    # Replace the LOG_DIR computation so the script reads from tmp_path
    rewritten = src.replace(
        'LOG_DIR = os.path.dirname(os.path.abspath(__file__))',
        f'LOG_DIR = {str(tmp_path)!r}',
    )
    staged.write_text(rewritten)
    return subprocess.run(
        ["python3", str(staged)],
        input=payload, capture_output=True, text=True, timeout=10,
    )


def test_selflearn_cold_start_emits_nothing(tmp_path):
    r = _run_selflearn(tmp_path)
    assert r.returncode == 0
    assert r.stdout.strip() == ""
    assert r.stderr.strip() == ""


def test_selflearn_emits_additionalcontext_when_memory_present(tmp_path):
    (tmp_path / "memory.json").write_text(json.dumps({
        "schema_version": 1,
        "sessions_observed": 4,
        "window_size": 20,
        "session_history": [],
        "patterns": {
            "probe_sprawl": {"hits": 3, "last_seen": "2026-05-10T10:00:00"},
        },
    }))
    r = _run_selflearn(tmp_path)
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "probe_sprawl" in ctx
    assert "3 of last 4" in ctx
    # Side-effect: last_injection.md is written so reporter.py can show it later
    assert (tmp_path / "last_injection.md").exists()


def test_selflearn_disabled_flag_suppresses_output(tmp_path):
    (tmp_path / "memory.json").write_text(json.dumps({
        "schema_version": 1, "sessions_observed": 5, "window_size": 20,
        "session_history": [],
        "patterns": {"probe_sprawl": {"hits": 5, "last_seen": "2026-05-10T10:00:00"}},
    }))
    (tmp_path / "selflearn.disabled").touch()
    r = _run_selflearn(tmp_path)
    assert r.returncode == 0
    assert r.stdout.strip() == ""
    # Memory is still preserved — only injection is suppressed
    assert (tmp_path / "memory.json").exists()


def test_selflearn_corrupted_memory_returns_silent(tmp_path):
    (tmp_path / "memory.json").write_text("{not valid")
    r = _run_selflearn(tmp_path)
    assert r.returncode == 0  # never block a session
    assert r.stdout.strip() == ""


def test_selflearn_always_exits_zero_even_on_unexpected_error(tmp_path):
    # Write a memory.json that's a *list* (not a dict) — pathological case
    (tmp_path / "memory.json").write_text("[1, 2, 3]")
    r = _run_selflearn(tmp_path)
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# Integration: reporter.read_last_injection round-trips correctly
# ---------------------------------------------------------------------------


def test_reporter_picks_up_and_clears_last_injection(tmp_path):
    rep = _load_module("rep7", AM_DIR / "reporter.py")
    _redirect(rep, tmp_path)

    (tmp_path / "last_injection.md").write_text(
        "[Self-learning context]\n- probe_sprawl: avoid X\n"
    )
    text = rep.read_last_injection()
    assert "probe_sprawl" in text
    # File is consumed (cleared) after read — next session starts fresh
    assert not (tmp_path / "last_injection.md").exists()


def test_reporter_format_injection_section_empty_when_no_text():
    rep = _load_module("rep8", AM_DIR / "reporter.py")
    assert rep.format_injection_section("") == []


def test_reporter_format_injection_section_includes_text():
    rep = _load_module("rep9", AM_DIR / "reporter.py")
    out = rep.format_injection_section("hello-world")
    joined = "\n".join(out)
    assert "Self-learning context applied this session" in joined
    assert "hello-world" in joined
