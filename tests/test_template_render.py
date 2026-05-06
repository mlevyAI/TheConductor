"""Tests for lib/template_render.py — covers spec §7.2 cases 1-10 plus dedup contract."""
import pytest
from pathlib import Path

from lib.template_render import render


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_template(tmp_path: Path, content: str) -> str:
    """Write content to a temp file and return its path string."""
    p = tmp_path / "template.md"
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# §7.2 case 1 — Basic substitution
# ---------------------------------------------------------------------------

def test_basic_substitution(tmp_path):
    t = make_template(tmp_path, "Hello, {{PROJECT_NAME}}!")
    rendered, missing = render(t, {"PROJECT_NAME": "Conductor"}, "/tmp/out.md")
    assert rendered == "Hello, Conductor!"
    assert missing == []


# ---------------------------------------------------------------------------
# §7.2 case 2 — Missing var → TODO: VAR + appears in missing list
# ---------------------------------------------------------------------------

def test_missing_var(tmp_path):
    t = make_template(tmp_path, "Owner: {{UNKNOWN}}")
    rendered, missing = render(t, {}, "/tmp/out.md")
    assert rendered == "Owner: TODO: UNKNOWN"
    assert "UNKNOWN" in missing


# ---------------------------------------------------------------------------
# §7.2 case 3 — Escape sequence: {{{{ → {{ (not treated as var)
# ---------------------------------------------------------------------------

def test_escape_sequence(tmp_path):
    t = make_template(tmp_path, "Use {{{{ for literal braces.")
    rendered, missing = render(t, {}, "/tmp/out.md")
    assert rendered == "Use {{ for literal braces."
    assert missing == []


# ---------------------------------------------------------------------------
# §7.2 case 4 — Non-recursive: substituted value is NOT re-scanned
# ---------------------------------------------------------------------------

def test_non_recursive(tmp_path):
    t = make_template(tmp_path, "Value: {{X}}")
    rendered, missing = render(t, {"X": "{{Y}}"}, "/tmp/out.md")
    # The output should contain the literal string "{{Y}}", not expand Y
    assert rendered == "Value: {{Y}}"
    assert missing == []


# ---------------------------------------------------------------------------
# §7.2 case 5 — target under ~/.claude/ → ValueError with exact message
# ---------------------------------------------------------------------------

def test_target_under_claude_rejected(tmp_path):
    target = str(Path.home() / ".claude" / "skills" / "foo.md")
    with pytest.raises(ValueError, match=r"refusing to write under ~/\.claude/"):
        render("/dev/null", {}, target)


# ---------------------------------------------------------------------------
# §7.2 case 6 — Path traversal that resolves into ~/.claude/ → rejected
# ---------------------------------------------------------------------------

def test_path_traversal_into_claude_rejected(tmp_path):
    # ~/.claude/../.claude/foo.md still resolves to ~/.claude/foo.md
    target = str(Path.home() / ".claude" / ".." / ".claude" / "foo.md")
    with pytest.raises(ValueError, match=r"refusing to write under ~/\.claude/"):
        render("/dev/null", {}, target)


# ---------------------------------------------------------------------------
# §7.2 case 7 — Traversal that resolves OUTSIDE ~/.claude/ is allowed
# ---------------------------------------------------------------------------

def test_traversal_outside_claude_allowed(tmp_path):
    # /tmp/some/../../other/file.md → /tmp/other/file.md (outside ~/.claude/)
    target = "/tmp/some/../../other/file.md"
    t = make_template(tmp_path, "ok")
    # Should not raise; we don't care about return value here
    rendered, missing = render(t, {}, target)
    assert rendered == "ok"


# ---------------------------------------------------------------------------
# §7.2 case 8 — All vars present → empty missing list
# ---------------------------------------------------------------------------

def test_all_vars_present(tmp_path):
    t = make_template(tmp_path, "{{A}} and {{B}}")
    rendered, missing = render(t, {"A": "alpha", "B": "beta"}, "/tmp/out.md")
    assert rendered == "alpha and beta"
    assert missing == []


# ---------------------------------------------------------------------------
# §7.2 case 9 — Multiple vars in one template
# ---------------------------------------------------------------------------

def test_multiple_vars(tmp_path):
    t = make_template(tmp_path, "{{FIRST}} {{SECOND}} {{THIRD}}")
    rendered, missing = render(t, {"FIRST": "one", "SECOND": "two", "THIRD": "three"}, "/tmp/out.md")
    assert rendered == "one two three"
    assert missing == []


# ---------------------------------------------------------------------------
# §7.2 case 10 — Template with no vars → returned as-is, empty missing list
# ---------------------------------------------------------------------------

def test_no_vars(tmp_path):
    content = "Just plain text, nothing to substitute."
    t = make_template(tmp_path, content)
    rendered, missing = render(t, {}, "/tmp/out.md")
    assert rendered == content
    assert missing == []


# ---------------------------------------------------------------------------
# Dedup contract — same missing var used twice → one entry in missing list
# ---------------------------------------------------------------------------

def test_duplicate_missing_var_deduplicated(tmp_path):
    t = make_template(tmp_path, "{{FOO}} and {{FOO}} again")
    rendered, missing = render(t, {}, "/tmp/out.md")
    assert rendered == "TODO: FOO and TODO: FOO again"
    assert missing == ["FOO"]  # deduplicated, not ["FOO", "FOO"]
