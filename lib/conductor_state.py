import json
import os
import shutil
from pathlib import Path


def read_state(cwd=None):
    """Read .conductor/state.json. Returns dict or None if absent/invalid."""
    if cwd is None:
        cwd = os.getcwd()
    path = Path(cwd) / ".conductor" / "state.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def get_phase(cwd=None):
    s = read_state(cwd)
    return s.get("phase") if s else None


def get_gate(cwd=None):
    s = read_state(cwd)
    return s.get("gate") if s else None


def migrate_state_if_needed(cwd=None):
    """Add gate and scaffold_written to state.json if absent (v4.1→v5 migration).

    Creates a .v4.1.bak backup before modifying. Safe to call on every startup.
    """
    if cwd is None:
        cwd = os.getcwd()
    path = Path(cwd) / ".conductor" / "state.json"
    if not path.exists():
        return

    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    needs_migration = "gate" not in state or "scaffold_written" not in state
    if not needs_migration:
        return

    bak = path.with_suffix(".json.v4.1.bak")
    if not bak.exists():
        bak_tmp = path.with_suffix(".json.v4.1.bak.tmp")
        shutil.copy2(path, bak_tmp)
        os.replace(bak_tmp, bak)

    state.setdefault("gate", "post_first_response_proceed")
    state.setdefault("scaffold_written", False)

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def validate_scaffold_delegate(frontmatter: dict) -> bool:
    """Return True if agent frontmatter qualifies as a scaffold delegate.

    Requires: skills includes conductor-scaffold-ai-director-os AND
    tools includes all of Read, Write, Edit, Bash.
    """
    if not isinstance(frontmatter, dict):
        return False
    skills = frontmatter.get("skills", [])
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",")]
    tools = frontmatter.get("tools", [])
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",")]

    has_skill = "conductor-scaffold-ai-director-os" in skills
    has_tools = {"Read", "Write", "Edit", "Bash"}.issubset(set(tools))
    return has_skill and has_tools
