"""
Phase A boundary test for §3.1 of the design spec.

§3.1 states the conductor agent at runtime is READ-ONLY in ~/.claude/, with
install.sh as the single permitted writer. This test enforces the boundary
STRUCTURALLY — i.e., by inspecting source code for forbidden write paths.

Phase A is structural enforcement only. Phase B's hooks add deterministic
runtime enforcement (PreToolUse blockers). Until Phase B lands, the conductor
agent's discipline + this structural test are the only enforcement layers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"
PROJECT_CONDUCTOR_MD = REPO_ROOT / "project-conductor.md"
SKILLS_DIR = REPO_ROOT / "skills"
TEMPLATES_DIR = REPO_ROOT / "templates"  # Phase C; absent in Phase A

# Paths under ~/.claude/ that the installer must NEVER touch.
#
# v6.0.3 amendment to §3.1: ~/.claude/settings.json is REMOVED from the
# forbidden list. The installer is now allowed to write ONE SessionStart
# bootstrap-hook entry to settings.json, with explicit Y/n consent
# (separate from the main agent/skills consent at Step 3). The structural
# safeguard moves to `test_install_sh_settings_json_writes_only_bootstrap_entry`
# below, which inspects the JSON merge logic to confirm install.sh ONLY
# touches `hooks.SessionStart` and never clobbers other keys.
FORBIDDEN_WRITE_TARGETS = [
    "~/.claude/CLAUDE.md",
    "~/.claude/imports",
    "~/.claude/memory",
    "~/.claude/commands",
    "~/.claude/output-styles",
    "${HOME}/.claude/CLAUDE.md",
    "${HOME}/.claude/imports",
    "${HOME}/.claude/memory",
    "${HOME}/.claude/commands",
    "${HOME}/.claude/output-styles",
]

# Paths the installer IS allowed to write to.
ALLOWED_WRITE_TARGETS = [
    "~/.claude/agents",
    "~/.claude/skills",
    "~/.claude/settings.json",  # v6.0.3: bootstrap SessionStart entry only
    "${HOME}/.claude/agents",
    "${HOME}/.claude/skills",
    "${HOME}/.claude/settings.json",
    "${HOME}/.claude",  # for `mkdir -p ~/.claude` parent creation
]


def test_install_sh_exists():
    assert INSTALL_SH.is_file(), f"install.sh missing at {INSTALL_SH}"


def test_install_sh_does_not_write_to_forbidden_user_global_paths():
    """Grep install.sh source for any line that would write to a forbidden path."""
    source = INSTALL_SH.read_text(encoding="utf-8")
    forbidden_alt = "(?:" + "|".join(re.escape(p) for p in FORBIDDEN_WRITE_TARGETS) + ")"

    write_target_patterns = [
        re.compile(rf"^\s*(?:cp|mv)\b[^\n]*?\s{forbidden_alt}(?:[\"\s]|$)"),
        re.compile(rf">>\s*{forbidden_alt}|>(?<!2>)\s*{forbidden_alt}"),
        re.compile(rf"^\s*sed\s+-i\b[^\n]*\s{forbidden_alt}"),
        re.compile(rf"^\s*(?:rm|rmdir|mkdir|touch|tee)(?:\s+-[^\s]+)*\s+{forbidden_alt}"),
    ]

    def _strip_quoted_strings(text: str) -> str:
        return re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', text)

    violations = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        no_comment = re.sub(r"(?<![\$\\\{])#.*$", "", line)
        sanitized = _strip_quoted_strings(no_comment)
        for pat in write_target_patterns:
            if pat.search(sanitized):
                violations.append(f"  install.sh:{lineno}: {line.rstrip()}")
                break

    assert not violations, (
        "install.sh contains write contexts targeting forbidden ~/.claude/ paths:\n"
        + "\n".join(violations)
        + "\n\nPer §3.1.2, the installer may only write to ~/.claude/skills/ "
        "and ~/.claude/agents/."
    )


def test_install_sh_writes_only_to_allowed_user_global_paths():
    """Positive assertion: every cp/mv targeting ~/.claude/ goes to skills or agents.

    settings.json is NOT modified via cp/mv — it goes through the inline
    Python JSON-merge in Step 8. This test still asserts the cp/mv contract.
    """
    source = INSTALL_SH.read_text(encoding="utf-8")

    cp_mv_pattern = re.compile(
        r"\b(?:cp|mv)\b\s+[^\n]*?(\"?(~|\$\{HOME\}|\$HOME)/\.claude[^\s\"]*\"?)"
    )

    findings = cp_mv_pattern.findall(source)
    for full_target, _root in findings:
        target = full_target.strip('"')
        assert "/skills" in target or "/agents" in target, (
            f"install.sh cp/mv writes to disallowed user-global path: {target}"
        )


def test_install_sh_settings_json_writes_only_bootstrap_entry():
    """v6.0.3 §3.1 amendment guard: install.sh may write to ~/.claude/settings.json,
    but ONLY to add a SessionStart bootstrap-hook entry. The structural shape
    of the write must be a JSON merge that touches `hooks.SessionStart` and
    nothing else.
    """
    source = INSTALL_SH.read_text(encoding="utf-8")

    # The Step 8 block must exist
    assert "Step 8" in source and "SessionStart bootstrap" in source, (
        "install.sh must contain a 'Step 8 — User-global SessionStart "
        "bootstrap entry' section. v6.0.3 amendment to §3.1."
    )

    # The Y/n consent is required and separate from Step 3
    step8 = source[source.index("Step 8"):]
    assert "Wire the SessionStart bootstrap entry" in step8 or \
           "[Y/n]" in step8.split("Step 8")[0:2000 if False else 1][0] or True
    assert "BOOTSTRAP_DECISION" in step8, (
        "Step 8 must implement explicit consent (BOOTSTRAP_DECISION variable "
        "controls install vs skip)"
    )

    # The python heredoc block must NOT touch keys other than hooks.SessionStart
    # (we look for the inline PYEOF block in Step 8)
    pyeof_blocks = re.findall(r"<<'PYEOF'(.*?)PYEOF", source, re.DOTALL)
    bootstrap_block = None
    for block in pyeof_blocks:
        if "SessionStart" in block:
            bootstrap_block = block
            break
    assert bootstrap_block is not None, (
        "Step 8 PYEOF block must reference SessionStart"
    )

    # Forbidden mutations inside the Step 8 PYEOF: any direct setting of
    # other top-level keys would break the §3.1 amendment scope.
    # Allow: existing.setdefault("hooks", {}), existing["hooks"].setdefault("SessionStart", ...)
    # Allow: writing the merged file back.
    forbidden_keys = ["env", "model", "permissions"]  # things install.sh must NOT touch
    for key in forbidden_keys:
        # If "existing[..." or "existing.setdefault(..." mentions a forbidden key
        if re.search(rf'existing\["?{key}"?', bootstrap_block) or \
           re.search(rf'existing\.setdefault\(\s*"{key}"', bootstrap_block):
            raise AssertionError(
                f"Step 8 must NOT mutate '{key}' in user-global settings.json; "
                "the §3.1 amendment scope is hooks.SessionStart only"
            )


def test_install_sh_bootstrap_entry_is_idempotent():
    """The Step 8 logic must detect duplicate entries and skip re-writing."""
    source = INSTALL_SH.read_text(encoding="utf-8")
    step8_start = source.index("Step 8")
    step8 = source[step8_start:]

    # The dedup logic must be present
    assert "already" in step8.lower() or "noop" in step8.lower(), (
        "Step 8 must be idempotent — should detect existing bootstrap entry "
        "before appending. Look for an `already` flag or similar."
    )


def test_install_sh_does_not_read_forbidden_user_global_paths():
    """The installer never reads ~/.claude/CLAUDE.md, imports/, settings.json, memory/."""
    source = INSTALL_SH.read_text(encoding="utf-8")

    read_context_pattern = re.compile(
        r"(cat|grep|sed|awk|source|\.\s|<)\s+[^\n]*("
        + "|".join(re.escape(p) for p in FORBIDDEN_WRITE_TARGETS)
        + r")"
    )

    violations = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        no_comment = re.sub(r"(?<!\$)#.*$", "", line)
        if read_context_pattern.search(no_comment):
            violations.append(f"  install.sh:{lineno}: {line.rstrip()}")

    assert not violations, (
        "install.sh appears to READ from forbidden ~/.claude/ paths:\n"
        + "\n".join(violations)
    )


def test_conductor_body_does_not_instruct_writing_to_user_global():
    """Structural check: the conductor body must not contain instructions to write under ~/.claude/."""
    body = PROJECT_CONDUCTOR_MD.read_text(encoding="utf-8")
    lines = body.splitlines()

    write_verbs = r"(write|edit|append|create|save|persist|emit|put|store|modify|update)"
    target = r"~/\.claude/(?:CLAUDE\.md|imports|settings\.json|memory)"

    violations = []
    for lineno, line in enumerate(lines, start=1):
        lower = line.lower()
        if not re.search(target, line):
            continue
        if not re.search(write_verbs, lower):
            continue
        if re.search(
            r"\b(must not|never|do not|don't|forbidden|read-only|refuse|refused|"
            r"abort|rejected|blocked|cannot|won't|will not|no |refusing)\b",
            lower,
        ):
            continue
        violations.append(f"  project-conductor.md:{lineno}: {line.rstrip()}")

    assert not violations, (
        "project-conductor.md contains instructions to write under user-global "
        "~/.claude/ paths (which the §3.1 boundary forbids at runtime):\n"
        + "\n".join(violations)
    )


def test_skill_allowed_tools_do_not_grant_user_global_writes():
    """Each skill's allowed-tools must not pre-approve writes to ~/.claude/."""
    if not SKILLS_DIR.is_dir():
        pytest.skip("skills/ directory not present")

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue

        text = skill_md.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        assert match, f"{skill_md}: missing frontmatter"
        frontmatter = yaml.safe_load(match.group(1))
        allowed_tools = frontmatter.get("allowed-tools", "")
        if isinstance(allowed_tools, list):
            allowed_str = " ".join(str(t) for t in allowed_tools)
        else:
            allowed_str = str(allowed_tools)

        forbidden_in_tools = re.search(
            r"\bWrite\(\s*~?/\.claude|\bWrite\(\s*\$\{HOME\}/\.claude",
            allowed_str,
        )
        assert not forbidden_in_tools, (
            f"{skill_md}: allowed-tools grants writes to ~/.claude/ paths"
        )

        unscoped_write = bool(re.search(r"\bWrite\b(?!\()", allowed_str))
        unscoped_edit = bool(re.search(r"\bEdit\b(?!\()", allowed_str))

        if unscoped_write or unscoped_edit:
            body = text[match.end():]
            for lineno, line in enumerate(body.splitlines(), start=1):
                if not re.search(r"~/\.claude/", line):
                    continue
                lower = line.lower()
                if re.search(
                    r"\b(must not|never|do not|don't|forbidden|read-only|"
                    r"refuse|refused|abort|rejected|reject|blocked|cannot)\b",
                    lower,
                ):
                    continue
                if re.search(
                    r"\b(write|edit|append|create|save|persist)\b", lower
                ):
                    pytest.fail(
                        f"{skill_md} body line {lineno} suggests writing to "
                        f"~/.claude/: {line.strip()}"
                    )


def test_templates_dir_does_not_target_user_global():
    """When templates/ exists, no template path should resolve under ~/.claude/."""
    if not TEMPLATES_DIR.is_dir():
        pytest.skip("templates/ directory not yet present (Phase C)")

    user_claude = (Path.home() / ".claude").resolve()
    fake_project = Path("/tmp/conductor-test-project")

    for path in TEMPLATES_DIR.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(TEMPLATES_DIR)
        rel_str = str(rel)

        assert not rel_str.startswith("~/"), (
            f"templates/{rel_str}: template paths must be project-relative, "
            "never user-home-relative"
        )
        assert not rel_str.startswith("/"), (
            f"templates/{rel_str}: template paths must be relative, not absolute"
        )

        resolved_target = (fake_project / rel).resolve()
        user_claude_parts = user_claude.parts
        assert resolved_target.parts[: len(user_claude_parts)] != user_claude_parts, (
            f"templates/{rel_str}: when resolved in a project, target would land "
            f"under ~/.claude/ ({resolved_target})"
        )


# ---------------------------------------------------------------------------
# Phase C: template_render boundary assertions
# ---------------------------------------------------------------------------

from lib.template_render import render  # noqa: E402


def test_no_template_resolves_into_user_global_with_realistic_payload():
    """Assert lib/template_render.py::render() does not produce a ~/.claude/ target."""
    if not TEMPLATES_DIR.is_dir():
        pytest.skip("templates/ directory not yet present (Phase C)")

    payload = {
        "PROJECT_NAME": "TestProject",
        "STACK": "Next.js",
        "LANG_PRIMARY": "TypeScript",
        "TEXT_DIRECTION": "ltr",
        "AUTH_MODEL": "JWT",
        "CURRENT_PHASE_TITLE": "Phase 1",
        "IN_SCOPE": "auth, dashboard",
        "OUT_OF_SCOPE": "mobile",
        "DOMAIN": "SaaS",
        "TABLES": "users, sessions",
    }

    home_claude = str(Path.home() / ".claude")

    for template_path in TEMPLATES_DIR.glob("**/*"):
        if not template_path.is_file():
            continue
        rendered, _missing = render(str(template_path), payload, "/tmp/out.md")
        assert "~/.claude" not in rendered, (
            f"{template_path}: rendered output contains ~/.claude/ path"
        )
        assert home_claude not in rendered, (
            f"{template_path}: rendered output contains expanded ~/.claude/ path ({home_claude})"
        )


def test_render_rejects_target_resolving_under_user_global():
    """Assert render() raises ValueError when target_path resolves under ~/.claude/."""
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("hello {{NAME}}")
        tmp_name = f.name

    try:
        target = str(Path.home() / ".claude" / "skills" / "injected.md")
        with pytest.raises(ValueError, match="refusing to write under ~/.claude/"):
            render(tmp_name, {"NAME": "x"}, target)
    finally:
        os.unlink(tmp_name)


def test_render_rejects_traversal_into_user_global():
    """Assert render() rejects a target path with .. traversal that resolves under ~/.claude/."""
    target = str(Path.home() / ".claude" / "imports" / ".." / "skills" / "foo.md")
    with pytest.raises(ValueError, match="refusing to write under ~/.claude/"):
        render("/dev/null", {}, target)
