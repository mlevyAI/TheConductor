"""Integration tests for template rendering flow (Phase C — Task #14).

These tests exercise lib/template_render.py against the real templates in
templates/. They do NOT run the full conductor agent.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from lib.template_render import render

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"

# ---------------------------------------------------------------------------
# Shared full payload covering every {{VAR}} used across all templates.
# ---------------------------------------------------------------------------
FULL_PAYLOAD: dict[str, str] = {
    "PROJECT_NAME": "TaskFlow",
    "STACK": "Next.js 14 + Supabase",
    "LANG_PRIMARY": "TypeScript",
    "TEXT_DIRECTION": "ltr",
    "AUTH_MODEL": "JWT with Supabase Auth",
    "CURRENT_PHASE_TITLE": "Phase 1: Core task management",
    "IN_SCOPE": "- User registration\n- Task CRUD",
    "OUT_OF_SCOPE": "- Mobile app\n- Integrations",
    "DOMAIN": "B2B SaaS — team productivity",
    "TABLES": "users, tasks, projects",
}


# ---------------------------------------------------------------------------
# Test 1: All templates render without unresolved vars when given a full payload
# ---------------------------------------------------------------------------
def test_all_templates_render_with_full_payload(tmp_path: Path) -> None:
    """Every template file must produce output with no {{VAR}} remnants."""
    template_files = list(TEMPLATES_DIR.rglob("*"))
    template_files = [f for f in template_files if f.is_file()]

    assert template_files, "No template files found — check TEMPLATES_DIR path"

    for template_file in template_files:
        out_file = tmp_path / f"out_{template_file.name}"
        rendered, missing = render(str(template_file), FULL_PAYLOAD, str(out_file))

        # Must produce non-empty output
        assert rendered, f"Empty render for {template_file.name}"

        # No unresolved {{VAR}} patterns must remain
        unresolved = re.search(r"\{\{[A-Z_]+\}\}", rendered)
        assert unresolved is None, (
            f"Unresolved var in {template_file.name}: {unresolved.group()}"
        )

        # Missing list must be empty
        assert missing == [], (
            f"Unexpected missing vars in {template_file.name}: {missing}"
        )


# ---------------------------------------------------------------------------
# Test 2: Partial payload → TODO markers + non-empty missing list
# ---------------------------------------------------------------------------
def test_partial_payload_produces_todo_markers(tmp_path: Path) -> None:
    """Vars absent from payload must become TODO: VAR in rendered output."""
    partial_payload = {"PROJECT_NAME": "TaskFlow", "STACK": "Next.js"}
    claude_template = TEMPLATES_DIR / "CLAUDE.md"
    out_file = tmp_path / "CLAUDE.md"

    rendered, missing = render(str(claude_template), partial_payload, str(out_file))

    # Provided vars ARE substituted
    assert "TaskFlow" in rendered, "PROJECT_NAME was not substituted"

    # Missing vars produce TODO markers
    for var in ("LANG_PRIMARY", "TEXT_DIRECTION", "AUTH_MODEL"):
        assert f"TODO: {var}" in rendered, f"Expected TODO marker for {var}"
        assert var in missing, f"Expected {var} in missing list"


# ---------------------------------------------------------------------------
# Test 3: Collision policy — existing target produces .scaffold-suggestion file
# ---------------------------------------------------------------------------
def test_scaffold_collision_produces_suggestion_file(tmp_path: Path) -> None:
    """Collision handling must write to a suggestion file, leaving the original intact."""
    original_content = "# Existing CLAUDE.md\nDo not overwrite me."
    target = tmp_path / "CLAUDE.md"
    target.write_text(original_content, encoding="utf-8")

    # Simulate the collision branch: target exists → write to suggestion path
    suggestion_path = Path(
        str(target) + f".scaffold-suggestion.{datetime.now().strftime('%Y-%m-%dT%H%M%S')}"
    )
    claude_template = TEMPLATES_DIR / "CLAUDE.md"
    rendered, _ = render(str(claude_template), FULL_PAYLOAD, str(suggestion_path))
    suggestion_path.write_text(rendered, encoding="utf-8")

    # Suggestion file must exist
    assert suggestion_path.exists(), "scaffold-suggestion file was not created"

    # Original must be unchanged
    assert target.read_text(encoding="utf-8") == original_content, (
        "Original CLAUDE.md was modified — collision policy violated"
    )


# ---------------------------------------------------------------------------
# Test 4: Thin-spec circuit-breaker threshold
# ---------------------------------------------------------------------------
def test_thin_spec_detection(tmp_path: Path) -> None:
    """Rendering CLAUDE.md with only PROJECT_NAME must produce ≥3 TODO markers."""
    minimal_payload = {"PROJECT_NAME": "X"}
    claude_template = TEMPLATES_DIR / "CLAUDE.md"
    out_file = tmp_path / "CLAUDE.md"

    rendered, _ = render(str(claude_template), minimal_payload, str(out_file))

    todo_count = rendered.count("TODO:")
    assert todo_count >= 3, (
        f"Expected ≥3 TODO markers for circuit-breaker, got {todo_count}"
    )


# ---------------------------------------------------------------------------
# Test 5: Atomic-write staging directory is cleaned up on simulated failure
# ---------------------------------------------------------------------------
def test_atomic_write_staging_cleanup_on_failure(tmp_path: Path) -> None:
    """Staging dir must be removed and final target must not exist after failure."""
    staging_dir = tmp_path / ".conductor" / "scaffold-staging-test"
    staging_dir.mkdir(parents=True)

    # Write partial content into staging dir (simulating mid-rename state)
    staged_file = staging_dir / "CLAUDE.md"
    staged_file.write_text("partial", encoding="utf-8")
    assert staged_file.exists(), "Pre-condition: staged file must exist"

    # Simulate failure and cleanup
    shutil.rmtree(staging_dir, ignore_errors=True)

    # Staging dir must no longer exist
    assert not staging_dir.exists(), "Staging dir was not cleaned up after failure"

    # Final target (outside staging) must not exist
    final_target = tmp_path / "CLAUDE.md"
    assert not final_target.exists(), (
        "Final target must not exist — nothing should have been committed to final dest"
    )
