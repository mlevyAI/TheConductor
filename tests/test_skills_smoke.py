"""
Phase A smoke tests for the conductor skills.

These tests are structural — they validate that each skill file is well-formed
markdown with the required frontmatter fields and section headings per the
common skill body shape (spec §5.1). Phase A skills are content-only (no
executable behavior); Phase B+ adds runtime behavior tests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

# Per spec §5.1: skills #3 and #4 require ## Examples; others don't.
SKILLS_REQUIRING_EXAMPLES = {
    "conductor-routing-rubric",
    "conductor-classification",
}

REQUIRED_SECTIONS = [
    "## When to invoke",
    "## Inputs",
    "## Outputs",
    "## Procedure",
    "## Failure modes",
]

EXPECTED_SKILLS = [
    "conductor-phase-0-discovery",
    "conductor-spec-enrichment",
    "conductor-spec-splitter",
    "conductor-routing-rubric",
    "conductor-classification",
    "conductor-output-quality",
    "conductor-debug-map",
    "conductor-scaffold-ai-director-os",
    "conductor-first-response",
]


def _read_skill(skill_name: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_str) for the named skill."""
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")

    # Extract YAML frontmatter between --- markers
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, f"{skill_path}: missing or malformed frontmatter"
    frontmatter = yaml.safe_load(match.group(1))
    body = match.group(2)
    return frontmatter, body


def test_skills_directory_exists():
    assert SKILLS_DIR.is_dir(), f"skills/ directory missing at {SKILLS_DIR}"


def test_all_expected_skills_present():
    """Each expected skill exists as <name>/SKILL.md per Claude Code docs."""
    found = sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir())
    found_with_skill = [n for n in found if (SKILLS_DIR / n / "SKILL.md").is_file()]
    assert sorted(EXPECTED_SKILLS) == sorted(found_with_skill), (
        f"Expected skills {sorted(EXPECTED_SKILLS)}, found {sorted(found_with_skill)}"
    )


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_has_valid_frontmatter(skill_name: str):
    frontmatter, _ = _read_skill(skill_name)

    # Required: name field matches directory name
    assert frontmatter.get("name") == skill_name, (
        f"{skill_name}: frontmatter.name={frontmatter.get('name')!r} != directory={skill_name!r}"
    )

    # Required: description (per Claude Code docs, "recommended" but always present in this codebase)
    description = frontmatter.get("description", "")
    assert description, f"{skill_name}: frontmatter.description is empty or missing"
    assert isinstance(description, str), f"{skill_name}: description must be a string"

    # Required: allowed-tools (with hyphen, per Claude Code docs)
    allowed_tools = frontmatter.get("allowed-tools")
    assert allowed_tools is not None, (
        f"{skill_name}: frontmatter is missing 'allowed-tools' (note: hyphen, not underscore)"
    )

    # name must match Claude Code constraint: lowercase letters, numbers, hyphens, max 64
    assert re.fullmatch(r"[a-z0-9-]{1,64}", skill_name), (
        f"{skill_name}: skill name must be lowercase letters/numbers/hyphens, max 64 chars"
    )


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_has_required_sections(skill_name: str):
    _, body = _read_skill(skill_name)

    for section in REQUIRED_SECTIONS:
        assert section in body, (
            f"{skill_name}: missing required section heading {section!r}"
        )


@pytest.mark.parametrize("skill_name", sorted(SKILLS_REQUIRING_EXAMPLES))
def test_skill_has_examples_section(skill_name: str):
    """Skills #3 (routing-rubric) and #4 (classification) require ## Examples."""
    _, body = _read_skill(skill_name)
    assert "## Examples" in body, (
        f"{skill_name}: spec §5.1 requires ## Examples for this skill"
    )


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_has_no_unescaped_template_literals(skill_name: str):
    """No literal '{{VAR}}' strings — those would be unrendered template placeholders.

    The skill bodies should describe templates conceptually but not contain
    literal {{...}} syntax that would suggest unfinished rendering.
    """
    _, body = _read_skill(skill_name)
    # We allow {{VAR}} when it appears inside a code-fence example or backticks.
    # Strip those, then check for residual {{...}} in plain prose.
    stripped = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    stripped = re.sub(r"`[^`]*`", "", stripped)
    matches = re.findall(r"\{\{[A-Z_][A-Z0-9_]*\}\}", stripped)
    assert not matches, (
        f"{skill_name}: found unescaped template literals in plain prose: {matches}"
    )


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_file_ends_with_newline(skill_name: str):
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    raw = skill_path.read_bytes()
    assert raw.endswith(b"\n"), f"{skill_name}: file must end with a newline"


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_description_is_concise(skill_name: str):
    """Per Claude Code docs, combined description+when_to_use is capped at 1536 chars
    in the skill listing. We don't need a fixed limit but ensure descriptions are
    structured prose, not multi-paragraph dumps."""
    frontmatter, _ = _read_skill(skill_name)
    description = frontmatter["description"]
    # Soft check: descriptions are typically 1-3 sentences. Flag if a description
    # exceeds 800 characters as that's likely too verbose.
    assert len(description) <= 800, (
        f"{skill_name}: description is {len(description)} chars; spec §5.1 expects "
        "a concise one-line trigger description. Consider moving detail into the body."
    )
