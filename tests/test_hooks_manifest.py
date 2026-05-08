"""Tests for lib/hooks_manifest.py and hooks/MANIFEST.json consistency."""

import json

import pytest

from lib import hooks_manifest


# ---------------------------------------------------------------------------
# load_manifest — happy path + validation
# ---------------------------------------------------------------------------

def test_real_manifest_loads():
    m = hooks_manifest.load_manifest()
    assert m["schema_version"] == 1
    assert isinstance(m["hooks"], list)
    assert len(m["hooks"]) >= 9  # 6 phase_b + 3 v6 = 9 minimum


def test_real_manifest_consistent_with_disk():
    """Every entry in MANIFEST.json has a matching file in hooks/, and
    every .py in hooks/ is declared in MANIFEST.json."""
    errors = hooks_manifest.validate_against_disk()
    assert errors == [], f"manifest/disk inconsistency:\n  " + "\n  ".join(errors)


def test_load_rejects_wrong_schema_version(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": 99, "hooks": []}))
    with pytest.raises(ValueError, match="schema_version"):
        hooks_manifest.load_manifest(p)


def test_load_rejects_empty_hooks_list(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": 1, "hooks": []}))
    with pytest.raises(ValueError, match="non-empty"):
        hooks_manifest.load_manifest(p)


def test_load_rejects_missing_required_field(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "hooks": [{"name": "x.py", "event": "PreToolUse"}],  # missing fields
    }))
    with pytest.raises(ValueError, match="missing fields"):
        hooks_manifest.load_manifest(p)


def test_load_rejects_invalid_event(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "hooks": [{
            "name": "x.py", "event": "WrongEvent", "bundle": "phase_b",
            "blocking": True, "since_version": "v1", "description": "x",
        }],
    }))
    with pytest.raises(ValueError, match="event"):
        hooks_manifest.load_manifest(p)


def test_load_rejects_invalid_bundle(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "hooks": [{
            "name": "x.py", "event": "Stop", "bundle": "wat",
            "blocking": False, "since_version": "v1", "description": "x",
        }],
    }))
    with pytest.raises(ValueError, match="bundle"):
        hooks_manifest.load_manifest(p)


def test_load_rejects_duplicate_name(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "hooks": [
            {"name": "x.py", "event": "Stop", "bundle": "phase_b",
             "blocking": False, "since_version": "v1", "description": "a"},
            {"name": "x.py", "event": "PreToolUse", "bundle": "v6_replayability",
             "blocking": True, "since_version": "v6", "description": "b"},
        ],
    }))
    with pytest.raises(ValueError, match="duplicate"):
        hooks_manifest.load_manifest(p)


# ---------------------------------------------------------------------------
# list_hooks / list_bundles
# ---------------------------------------------------------------------------

def test_list_bundles_includes_phase_b_and_v6():
    bundles = hooks_manifest.list_bundles()
    assert "phase_b" in bundles
    assert "v6_replayability" in bundles


def test_list_hooks_filters_by_bundle():
    v6 = hooks_manifest.list_hooks("v6_replayability")
    names = {h["name"] for h in v6}
    assert "pre_state_committed.py" in names
    assert "pre_spec_split_enforce.py" in names
    assert "stop_evidence_completeness_check.py" in names
    # phase_b hooks should NOT appear
    assert "pre_phase0_readonly.py" not in names


def test_list_hooks_unknown_bundle_returns_empty():
    assert hooks_manifest.list_hooks("nonexistent") == []


# ---------------------------------------------------------------------------
# render_settings_block
# ---------------------------------------------------------------------------

def test_render_phase_b_groups_by_event():
    block = hooks_manifest.render_settings_block(
        ["phase_b"], hook_dir="/proj/.claude/hooks"
    )
    hooks = block["hooks"]
    assert "PreToolUse" in hooks
    assert "Stop" in hooks
    assert "PostToolUse" in hooks
    # Each event has the {hooks: [...]} wrapper that Claude Code expects
    assert "hooks" in hooks["PreToolUse"][0]
    pre_cmds = hooks["PreToolUse"][0]["hooks"]
    # 4 PreToolUse hooks in phase_b
    assert len(pre_cmds) == 4


def test_render_includes_v6_hooks_when_bundle_selected():
    block = hooks_manifest.render_settings_block(
        ["v6_replayability"], hook_dir="/proj/.claude/hooks"
    )
    hooks = block["hooks"]
    pre_commands = [h["command"] for h in hooks["PreToolUse"][0]["hooks"]]
    assert any("pre_spec_split_enforce.py" in c for c in pre_commands)
    assert any("pre_state_committed.py" in c for c in pre_commands)
    stop_commands = [h["command"] for h in hooks["Stop"][0]["hooks"]]
    assert any("stop_evidence_completeness_check.py" in c for c in stop_commands)


def test_render_combines_multiple_bundles():
    block = hooks_manifest.render_settings_block(
        ["phase_b", "v6_replayability"], hook_dir="/proj/.claude/hooks"
    )
    pre_count = len(block["hooks"]["PreToolUse"][0]["hooks"])
    # 4 phase_b PreToolUse + 2 v6 PreToolUse = 6
    assert pre_count == 6


def test_render_blocking_hooks_omit_async_field():
    block = hooks_manifest.render_settings_block(
        ["phase_b"], hook_dir="/x"
    )
    for entry in block["hooks"]["PreToolUse"][0]["hooks"]:
        # blocking hooks should not be async (must wait for exit code 2)
        assert "async" not in entry


def test_render_non_blocking_hooks_set_async_true():
    block = hooks_manifest.render_settings_block(
        ["monitoring"], hook_dir="/x"
    )
    if "PostToolUse" in block["hooks"]:
        for entry in block["hooks"]["PostToolUse"][0]["hooks"]:
            assert entry.get("async") is True


def test_render_uses_provided_hook_dir():
    block = hooks_manifest.render_settings_block(
        ["v6_replayability"], hook_dir="/myproject/.claude/hooks"
    )
    cmd = block["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "/myproject/.claude/hooks/" in cmd


def test_render_uses_provided_python_cmd():
    block = hooks_manifest.render_settings_block(
        ["v6_replayability"], hook_dir="/x", python_cmd="/usr/bin/python3.12"
    )
    cmd = block["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd.startswith("/usr/bin/python3.12 ")


def test_render_empty_when_no_bundles():
    block = hooks_manifest.render_settings_block([], hook_dir="/x")
    assert block == {"hooks": {}}


def test_render_unknown_bundle_yields_empty():
    block = hooks_manifest.render_settings_block(
        ["does_not_exist"], hook_dir="/x"
    )
    assert block == {"hooks": {}}


def test_render_event_order_is_deterministic():
    """Output should always order events: SessionStart, PreToolUse, PostToolUse, Stop."""
    block = hooks_manifest.render_settings_block(
        ["phase_b", "v6_replayability"], hook_dir="/x"
    )
    keys = list(block["hooks"].keys())
    expected = ["PreToolUse", "PostToolUse", "Stop"]
    assert keys == expected


# ---------------------------------------------------------------------------
# render_permissions
# ---------------------------------------------------------------------------

def test_render_permissions_phase_b():
    perms = hooks_manifest.render_permissions(
        ["phase_b"], hook_dir="/proj/.claude/hooks"
    )
    assert len(perms) == 6
    for p in perms:
        assert p.startswith('Bash(python3 "/proj/.claude/hooks/')
        assert p.endswith('.py")')


def test_render_permissions_uses_python_cmd():
    perms = hooks_manifest.render_permissions(
        ["v6_replayability"], hook_dir="/x", python_cmd="/usr/local/bin/py"
    )
    for p in perms:
        assert p.startswith('Bash(/usr/local/bin/py')


# ---------------------------------------------------------------------------
# Bundle membership sanity
# ---------------------------------------------------------------------------

def test_phase_b_bundle_has_six_hooks():
    """Phase B bundle must have exactly 6 hooks (the original v3-v5 set)."""
    phase_b = hooks_manifest.list_hooks("phase_b")
    names = sorted(h["name"] for h in phase_b)
    assert names == sorted([
        "pre_phase0_readonly.py",
        "pre_first_response_gate.py",
        "pre_busy_wait_block.py",
        "pre_lock_enforcement.py",
        "post_output_quality.py",
        "stop_validate_final_report.py",
    ])


def test_v6_bundle_has_three_hooks():
    v6 = hooks_manifest.list_hooks("v6_replayability")
    names = sorted(h["name"] for h in v6)
    assert names == sorted([
        "pre_state_committed.py",
        "pre_spec_split_enforce.py",
        "stop_evidence_completeness_check.py",
    ])


def test_blocking_hooks_are_pretooluse():
    """Sanity: only PreToolUse hooks may be blocking; Stop/PostToolUse advisory."""
    m = hooks_manifest.load_manifest()
    for h in m["hooks"]:
        if h["blocking"]:
            assert h["event"] == "PreToolUse", (
                f"hook {h['name']} is blocking but event is {h['event']!r}; "
                "blocking is only valid for PreToolUse"
            )
