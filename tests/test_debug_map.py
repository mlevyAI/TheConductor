"""Tests for lib/debug_map.py — v6 live surgical debug map."""

import json

import pytest

from lib import debug_map


# ---------------------------------------------------------------------------
# upsert_feature — basic
# ---------------------------------------------------------------------------

def test_upsert_creates_feature(tmp_path):
    f = debug_map.upsert_feature(
        "User signup",
        phase=2,
        tasks=["p2.t1"],
        primary_files=["src/api/signup.ts"],
        commit_shas=["abc123def"],
        subagent="general-purpose",
        model_requested="sonnet",
        cwd=tmp_path,
    )
    assert f.name == "User signup"
    assert f.phase == "2"
    assert f.subagent == "general-purpose"


def test_upsert_persists_json(tmp_path):
    debug_map.upsert_feature("F1", phase=2, cwd=tmp_path)
    data = json.loads((tmp_path / ".conductor" / "debug-map.json").read_text())
    assert data["schema_version"] == 1
    assert data["features"][0]["name"] == "F1"


def test_upsert_is_idempotent_by_name(tmp_path):
    debug_map.upsert_feature("F1", phase=2, primary_files=["a.py"], cwd=tmp_path)
    debug_map.upsert_feature("F1", phase=2, primary_files=["a.py", "b.py"], cwd=tmp_path)
    feats = debug_map.list_features(cwd=tmp_path)
    assert len(feats) == 1
    assert feats[0].primary_files == ["a.py", "b.py"]


def test_upsert_updates_phase_on_re_upsert(tmp_path):
    debug_map.upsert_feature("F1", phase=2, cwd=tmp_path)
    debug_map.upsert_feature("F1", phase=3, cwd=tmp_path)
    feats = debug_map.list_features(cwd=tmp_path)
    assert feats[0].phase == "3"


def test_upsert_rejects_empty_name(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        debug_map.upsert_feature("", phase=2, cwd=tmp_path)


def test_upsert_rejects_banned_phrase_in_decisions(tmp_path):
    with pytest.raises(ValueError, match="banned phrase"):
        debug_map.upsert_feature(
            "F1", phase=2,
            key_decisions=["this is a KNOWN LIMITATION decision"],
            cwd=tmp_path,
        )


def test_upsert_partial_update_preserves_other_fields(tmp_path):
    debug_map.upsert_feature(
        "F1",
        phase=2,
        primary_files=["a.py"],
        commit_shas=["abc"],
        subagent="general",
        cwd=tmp_path,
    )
    # Update only primary_files; subagent and commits should remain
    debug_map.upsert_feature("F1", phase=2, primary_files=["b.py"], cwd=tmp_path)
    feats = debug_map.list_features(cwd=tmp_path)
    assert feats[0].primary_files == ["b.py"]
    assert feats[0].commit_shas == ["abc"]
    assert feats[0].subagent == "general"


# ---------------------------------------------------------------------------
# add_limitation
# ---------------------------------------------------------------------------

def test_add_limitation_requires_three_approaches(tmp_path):
    debug_map.upsert_feature("F1", phase=2, cwd=tmp_path)
    with pytest.raises(ValueError, match="≥3 approaches"):
        debug_map.add_limitation(
            "F1",
            description="cannot use Stripe in offline mode",
            approaches_tried=["a", "b"],
            cwd=tmp_path,
        )


def test_add_limitation_rejects_banned_phrase(tmp_path):
    debug_map.upsert_feature("F1", phase=2, cwd=tmp_path)
    with pytest.raises(ValueError, match="banned phrase"):
        debug_map.add_limitation(
            "F1",
            description="KNOWN LIMITATION: not implemented",
            approaches_tried=["a", "b", "c"],
            cwd=tmp_path,
        )


def test_add_limitation_succeeds_with_three_approaches(tmp_path):
    debug_map.upsert_feature("F1", phase=2, cwd=tmp_path)
    f = debug_map.add_limitation(
        "F1",
        description="cannot run offline",
        approaches_tried=["mock1", "mock2", "stub3"],
        cwd=tmp_path,
    )
    assert len(f.limitations) == 1


def test_add_limitation_unknown_feature_raises(tmp_path):
    with pytest.raises(KeyError):
        debug_map.add_limitation(
            "Ghost",
            description="x",
            approaches_tried=["a", "b", "c"],
            cwd=tmp_path,
        )


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

def test_render_empty_includes_preamble(tmp_path):
    md = debug_map.render_markdown(cwd=tmp_path)
    assert "## 🔧 Surgical Debug Map" in md
    assert "How to use" in md
    assert "No features recorded yet" in md


def test_render_includes_feature_block(tmp_path):
    debug_map.upsert_feature(
        "User signup",
        phase=2,
        tasks=["p2.t1", "p2.t2"],
        primary_files=["src/api/signup.ts"],
        test_files=["tests/signup.test.ts"],
        commit_shas=["abcdef1234567890"],
        subagent="general-purpose",
        model_requested="sonnet",
        cwd=tmp_path,
    )
    md = debug_map.render_markdown(cwd=tmp_path)
    assert "#### Feature: User signup" in md
    assert "Phase 2" in md
    assert "p2.t1, p2.t2" in md
    assert "`src/api/signup.ts`" in md
    assert "`abcdef12`" in md  # short SHA
    assert "general-purpose (sonnet)" in md


def test_render_includes_database_when_present(tmp_path):
    debug_map.upsert_feature(
        "X",
        phase=2,
        database_tables=["users", "sessions"],
        cwd=tmp_path,
    )
    md = debug_map.render_markdown(cwd=tmp_path)
    assert "**Database**" in md
    assert "`users`" in md


def test_render_omits_database_when_absent(tmp_path):
    debug_map.upsert_feature("X", phase=2, cwd=tmp_path)
    md = debug_map.render_markdown(cwd=tmp_path)
    assert "**Database**" not in md


def test_render_limitations_use_unverified_form(tmp_path):
    debug_map.upsert_feature("X", phase=2, cwd=tmp_path)
    debug_map.add_limitation(
        "X",
        description="cannot do offline",
        approaches_tried=["a1", "a2", "a3"],
        cwd=tmp_path,
    )
    md = debug_map.render_markdown(cwd=tmp_path)
    assert "unverified — 3 approaches tried" in md
    assert "a1, a2, a3" in md
    assert "KNOWN LIMITATION" not in md


# ---------------------------------------------------------------------------
# write_debug_map_md
# ---------------------------------------------------------------------------

def test_write_debug_map_md_writes_file(tmp_path):
    debug_map.upsert_feature("X", phase=2, cwd=tmp_path)
    p = debug_map.write_debug_map_md(cwd=tmp_path)
    assert p.exists()
    assert "Surgical Debug Map" in p.read_text()


def test_write_debug_map_md_overwrites(tmp_path):
    debug_map.upsert_feature("F1", phase=2, cwd=tmp_path)
    debug_map.write_debug_map_md(cwd=tmp_path)
    debug_map.upsert_feature("F2", phase=3, cwd=tmp_path)
    debug_map.write_debug_map_md(cwd=tmp_path)
    md = (tmp_path / ".conductor" / "debug-map.md").read_text()
    assert "F1" in md
    assert "F2" in md
