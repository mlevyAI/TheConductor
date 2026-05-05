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
FORBIDDEN_WRITE_TARGETS = [
    "~/.claude/CLAUDE.md",
    "~/.claude/imports",
    "~/.claude/settings.json",
    "~/.claude/memory",
    "~/.claude/commands",
    "~/.claude/output-styles",
    "${HOME}/.claude/CLAUDE.md",
    "${HOME}/.claude/imports",
    "${HOME}/.claude/settings.json",
    "${HOME}/.claude/memory",
    "${HOME}/.claude/commands",
    "${HOME}/.claude/output-styles",
]

# Paths the installer IS allowed to write to.
ALLOWED_WRITE_TARGETS = [
    "~/.claude/agents",
    "~/.claude/skills",
    "${HOME}/.claude/agents",
    "${HOME}/.claude/skills",
    "${HOME}/.claude",  # for `mkdir -p ~/.claude` parent creation
]


def test_install_sh_exists():
    assert INSTALL_SH.is_file(), f"install.sh missing at {INSTALL_SH}"


def test_install_sh_does_not_write_to_forbidden_user_global_paths():
    """Grep install.sh source for any line that would write to a forbidden path.

    A 'write context' targets the forbidden path AS THE WRITE TARGET — not as
    string content inside a printf/echo. Specifically:
      - `cp <src> <forbidden>`
      - `mv <src> <forbidden>`
      - `> <forbidden>` or `>> <forbidden>` (redirect)
      - `sed -i ... <forbidden>`
      - `rm <forbidden>` / `rmdir <forbidden>`
      - `mkdir <forbidden>` / `touch <forbidden>`
      - `tee <forbidden>` / `tee -a <forbidden>`
      - `cat > <forbidden>` (technically caught by the redirect rule above)

    We do NOT flag printf/echo lines that merely include the path as a quoted
    string (those are documentation/disclosure messages, not writes).
    """
    source = INSTALL_SH.read_text(encoding="utf-8")
    forbidden_alt = "(?:" + "|".join(re.escape(p) for p in FORBIDDEN_WRITE_TARGETS) + ")"

    write_target_patterns = [
        # cp/mv with forbidden as the LAST argument (target)
        re.compile(rf"^\s*(?:cp|mv)\b[^\n]*?\s{forbidden_alt}(?:[\"\s]|$)"),
        # > or >> redirect to forbidden
        re.compile(rf">>\s*{forbidden_alt}|>(?<!2>)\s*{forbidden_alt}"),
        # sed -i operating on forbidden file
        re.compile(rf"^\s*sed\s+-i\b[^\n]*\s{forbidden_alt}"),
        # rm/rmdir/mkdir/touch/tee at the start of a shell statement
        # (anchored so words inside quoted strings like "does not touch ~/..." don't match)
        re.compile(rf"^\s*(?:rm|rmdir|mkdir|touch|tee)(?:\s+-[^\s]+)*\s+{forbidden_alt}"),
    ]

    def _strip_quoted_strings(text: str) -> str:
        """Remove the *contents* of printf/echo/cat-heredoc string literals so
        that prose inside them (e.g., "does not touch ~/.claude/...") doesn't
        trigger command-name regexes."""
        # Strip the body of double-quoted strings while keeping the quotes
        # (preserves redirects and other syntax outside strings).
        return re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', text)

    violations = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        # Strip shell comments (but only when # starts a token, not inside ${VAR#...})
        no_comment = re.sub(r"(?<![\$\\\{])#.*$", "", line)
        # Strip the contents of double-quoted strings — printf/echo prose is not a write
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
    """Positive assertion: every cp/mv targeting ~/.claude/ goes to skills or agents."""
    source = INSTALL_SH.read_text(encoding="utf-8")

    # Match assignments and writes referencing ~/.claude/ or ${HOME}/.claude/
    # Specifically pull out cp/mv/cat-redirect targets.
    cp_mv_pattern = re.compile(
        r"\b(?:cp|mv)\b\s+[^\n]*?(\"?(~|\$\{HOME\}|\$HOME)/\.claude[^\s\"]*\"?)"
    )

    findings = cp_mv_pattern.findall(source)
    for full_target, _root in findings:
        target = full_target.strip('"')
        # Must contain /skills or /agents
        assert "/skills" in target or "/agents" in target, (
            f"install.sh writes to disallowed user-global path: {target}"
        )


def test_install_sh_does_not_read_forbidden_user_global_paths():
    """The installer never reads ~/.claude/CLAUDE.md, imports/, settings.json, memory/.

    Comments are allowed to MENTION these paths (and we deliberately do — the
    comments document the boundary). What's forbidden is a read context: cat,
    grep, sed without -i, awk reading the file, source/., or shell redirection
    < from the file.
    """
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
            # Heuristic: `sed -i` IS a write — already covered above.
            # Allow plain `sed s/.../.../` patches when target is a tmp file.
            violations.append(f"  install.sh:{lineno}: {line.rstrip()}")

    assert not violations, (
        "install.sh appears to READ from forbidden ~/.claude/ paths:\n"
        + "\n".join(violations)
    )


def test_conductor_body_does_not_instruct_writing_to_user_global():
    """Structural check: the conductor body must not contain instructions that
    direct itself or any sub-agent to write under ~/.claude/.

    We look for prose like:
      - "write to ~/.claude/..."
      - "edit ~/.claude/..."
      - "create a file under ~/.claude/..."
    Comments about NOT writing are explicitly allowed (they document the boundary).
    """
    body = PROJECT_CONDUCTOR_MD.read_text(encoding="utf-8")
    lines = body.splitlines()

    # Phrases that suggest writing TO user-global. We exclude phrases that also
    # contain a NOT-related word ("not", "never", "MUST NOT", "do not", "forbidden",
    # "read-only", "REFUSED", "blocked", "abort", "rejected").
    write_verbs = r"(write|edit|append|create|save|persist|emit|put|store|modify|update)"
    target = r"~/\.claude/(?:CLAUDE\.md|imports|settings\.json|memory)"

    violations = []
    for lineno, line in enumerate(lines, start=1):
        lower = line.lower()
        if not re.search(target, line):
            continue
        if not re.search(write_verbs, lower):
            continue
        # Negation context: anything that flips the meaning to "don't write"
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
    """Each skill's allowed-tools must not pre-approve writes to ~/.claude/.

    Skills can declare Write/Edit, but they should be path-scoped (e.g.,
    `Write(.conductor/**)`) when the skill writes anywhere. Skill #2
    explicitly scopes to .conductor/. Skills #3-#6 should not grant
    Write/Edit at all (they read or run inspection commands).
    """
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

        # If the skill declares unscoped Write or Edit, ensure the body's
        # procedure does not target ~/.claude/.
        unscoped_write = bool(re.search(r"\bWrite\b(?!\()", allowed_str))
        unscoped_edit = bool(re.search(r"\bEdit\b(?!\()", allowed_str))

        # No skill should pre-approve writes to ~/.claude/ paths.
        forbidden_in_tools = re.search(
            r"\bWrite\(\s*~?/\.claude|\bWrite\(\s*\$\{HOME\}/\.claude",
            allowed_str,
        )
        assert not forbidden_in_tools, (
            f"{skill_md}: allowed-tools grants writes to ~/.claude/ paths"
        )

        # Body must not say "write under ~/.claude/" without negation.
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
                # If the line discusses ~/.claude/ in a procedure step that
                # writes, flag it.
                if re.search(
                    r"\b(write|edit|append|create|save|persist)\b", lower
                ):
                    pytest.fail(
                        f"{skill_md} body line {lineno} suggests writing to "
                        f"~/.claude/: {line.strip()}"
                    )


def test_templates_dir_does_not_target_user_global():
    """Phase A precondition: templates/ doesn't exist yet (Phase C adds it).
    When it does exist, no template path should resolve under ~/.claude/.
    """
    if not TEMPLATES_DIR.is_dir():
        pytest.skip("templates/ directory not yet present (Phase C)")

    for path in TEMPLATES_DIR.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(TEMPLATES_DIR)
        # No template path component may be ~/.claude/ — templates resolve
        # relative to the user's project cwd, never to the user's home.
        rel_str = str(rel)
        assert not rel_str.startswith("~/"), (
            f"templates/{rel_str}: template paths must be project-relative, "
            "never user-home-relative"
        )
        assert "/.claude/" not in str(path).replace(str(TEMPLATES_DIR), ""), (
            # The .claude/ subdir is fine when relative to project; what's
            # forbidden is a path that starts at the user's home.
            f"templates/{rel_str}: unexpected ~/.claude/ in template path"
        )


# ---------------------------------------------------------------------------
# Phase C: template_render boundary assertions
# ---------------------------------------------------------------------------

from lib.template_render import render  # noqa: E402


def test_no_template_resolves_into_user_global_with_realistic_payload():
    """Assert lib/template_render.py::render() does not produce a ~/.claude/ target
    when called with a realistic payload and any template from templates/.
    """
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
    # Path.home() / ".claude" / "imports" / ".." / "skills" / "foo.md" resolves to
    # ~/.claude/skills/foo.md — still under ~/.claude/ → ValueError.
    # The path safety check runs before the template is read, so /dev/null is safe to pass.
    target = str(Path.home() / ".claude" / "imports" / ".." / "skills" / "foo.md")
    with pytest.raises(ValueError, match="refusing to write under ~/.claude/"):
        render("/dev/null", {}, target)
