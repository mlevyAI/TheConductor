"""Regression tests for install.sh skill-count handling.

History:
  Until v6.0.2 the installer hardcoded "expected 7 skills" in three places
  (header comment, usage text, error message + numeric guard). When the
  spec-splitter skill was added in v5-D the count went to 8 but those
  strings were never updated, producing a spurious warning on every run.
  v6.0.3 removed the hardcoded count; the installer now operates on
  whatever conductor-*/ skills are present at install time.

These tests pin the new behavior so a future contributor can't reintroduce
the same constant.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def _read_install_sh() -> str:
    return (REPO_ROOT / "install.sh").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# install.sh contains no stale skill-count constants
# ---------------------------------------------------------------------------

def test_install_sh_does_not_hardcode_seven_skills():
    text = _read_install_sh()
    forbidden = [
        "7 skill directories",
        "7 skills",
        "expected 7",
        "Expected 7 skill",
        "-ne 7",
        "Found 7",
    ]
    found = [s for s in forbidden if s in text]
    assert not found, (
        f"install.sh contains stale skill-count constants: {found}\n"
        "The installer should operate on whatever conductor-*/ skills "
        "are present at install time, not a hardcoded number."
    )


def test_install_sh_does_not_hardcode_eight_skills():
    """Same protection in the other direction — if someone 'fixes' 7→8,
    we'd be back to the same fragility the next time a skill is added."""
    text = _read_install_sh()
    forbidden = [
        "8 skill directories",
        "8 skills",
        "expected 8",
        "-ne 8",
        "Found 8",
    ]
    found = [s for s in forbidden if s in text]
    assert not found, (
        f"install.sh re-hardcodes skill count: {found}. "
        "Use a dynamic check instead — see SKILL_DIRS counting block."
    )


# ---------------------------------------------------------------------------
# All present skills are picked up by the glob
# ---------------------------------------------------------------------------

def test_every_skill_dir_has_a_skill_md():
    """install.sh's loop requires SKILL.md in each conductor-*/ directory.
    If a skill is added without a SKILL.md, the installer silently skips it.
    Catch that here at test time."""
    skills_root = REPO_ROOT / "skills"
    assert skills_root.is_dir(), "skills/ directory missing from repo"

    skill_dirs = sorted(d for d in skills_root.iterdir()
                         if d.is_dir() and d.name.startswith("conductor-"))
    assert skill_dirs, "no conductor-*/ skills found in skills/"

    missing_skill_md = [d.name for d in skill_dirs
                         if not (d / "SKILL.md").is_file()]
    assert not missing_skill_md, (
        f"skill directories missing SKILL.md: {missing_skill_md}. "
        "install.sh requires SKILL.md in every conductor-*/ to copy it."
    )


# ---------------------------------------------------------------------------
# Empty skills directory still produces a clean error path
# ---------------------------------------------------------------------------

def test_install_sh_still_errors_on_zero_skills():
    """The empty case must still error — that's a real installation problem."""
    text = _read_install_sh()
    # The block we kept after removing the -ne 7 check
    assert '"${#SKILL_DIRS[@]}" -eq 0' in text, (
        "install.sh should still error when zero skills are found"
    )
    assert "No skill directories found" in text
