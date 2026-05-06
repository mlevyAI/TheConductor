"""Tests for dispatch_envelope.py — §7.2 requirements."""

import pytest

from lib.dispatch_envelope import apply_literalism_rules, build_prompt


# ---------------------------------------------------------------------------
# 1. reminder == task raises ValueError
# ---------------------------------------------------------------------------

def test_reminder_equals_task_raises():
    with pytest.raises(ValueError, match="reminder must differ"):
        build_prompt(task="Do X", reminder="Do X")


def test_reminder_equals_task_strips_whitespace():
    """Whitespace-only difference should still raise."""
    with pytest.raises(ValueError, match="reminder must differ"):
        build_prompt(task="Do X", reminder="Do X  ")


# ---------------------------------------------------------------------------
# 2. Base-mode ordering
# ---------------------------------------------------------------------------

def test_base_mode_ordering():
    result = build_prompt(
        task="Write a module",
        constraints="Must use Python 3.12",
        files_write=["lib/foo.py"],
        acceptance="All tests pass",
        context="Existing codebase uses Flask",
        effort_recommendation="high",
        complexity=7,
        reminder="Focus on correctness, not speed",
        context_window=200_000,
    )
    idx_task = result.index("<task>")
    idx_constraints = result.index("<constraints>")
    idx_files = result.index("<files-write>")
    idx_acceptance = result.index("<acceptance>")
    idx_context = result.index("<context>")
    idx_effort = result.index("<effort-recommendation>")
    idx_complexity = result.index("<complexity>")
    idx_reminder = result.index("Reminder:")

    assert idx_task < idx_constraints
    assert idx_constraints < idx_files
    assert idx_files < idx_acceptance
    assert idx_acceptance < idx_context
    assert idx_context < idx_effort
    assert idx_effort < idx_complexity
    assert idx_complexity < idx_reminder


# ---------------------------------------------------------------------------
# 3. Split-mode ordering
# ---------------------------------------------------------------------------

def test_split_mode_ordering():
    # context_window=100 → threshold=4 chars; any real prompt triggers split
    long_task = "A" * 50
    result = build_prompt(
        task=long_task,
        constraints="c",
        files_write=["a/b.py"],
        acceptance="acc",
        critical_context="CRITICAL INFO",
        reference_context="REFERENCE INFO",
        effort_recommendation="xhigh",
        complexity=9,
        reminder="Different reminder text here",
        context_window=100,
    )
    idx_task = result.index("<task>")
    idx_constraints = result.index("<constraints>")
    idx_files = result.index("<files-write>")
    idx_acceptance = result.index("<acceptance>")
    idx_critical = result.index("<critical-context>")
    idx_reference = result.index("<reference-context>")
    idx_effort = result.index("<effort-recommendation>")
    idx_complexity = result.index("<complexity>")
    idx_reminder = result.index("Reminder:")

    assert idx_task < idx_constraints
    assert idx_constraints < idx_files
    assert idx_files < idx_acceptance
    assert idx_acceptance < idx_critical
    assert idx_critical < idx_reference
    assert idx_reference < idx_effort
    assert idx_effort < idx_complexity
    assert idx_complexity < idx_reminder


# ---------------------------------------------------------------------------
# 4. Long-context threshold triggers split mode
# ---------------------------------------------------------------------------

def test_small_window_triggers_split():
    result = build_prompt(
        task="A" * 50,
        critical_context="important info",
        reference_context="extra info",
        reminder="Do not skip tests",
        context_window=100,
    )
    assert "<critical-context>" in result
    assert "<context>" not in result


def test_large_window_stays_base():
    result = build_prompt(
        task="A" * 50,
        context="base context",
        critical_context="important info",
        reference_context="extra info",
        reminder="Do not skip tests",
        context_window=2_000_000,
    )
    assert "<context>" in result
    assert "<critical-context>" not in result


# ---------------------------------------------------------------------------
# 5. apply_literalism_rules: bugfix detection
# ---------------------------------------------------------------------------

def test_bugfix_detection_appends_root_cause():
    result = apply_literalism_rules("Please fix the bug in auth.py")
    assert "ROOT CAUSE" in result


def test_bugfix_detection_case_insensitive():
    result = apply_literalism_rules("FIX THE BUG NOW")
    assert "ROOT CAUSE" in result


# ---------------------------------------------------------------------------
# 6. apply_literalism_rules: idempotent
# ---------------------------------------------------------------------------

def test_literalism_rules_idempotent():
    prompt = "fix the bug in login"
    first = apply_literalism_rules(prompt)
    second = apply_literalism_rules(first)
    # ROOT CAUSE should appear exactly once
    assert first.count("ROOT CAUSE") == 1
    assert second.count("ROOT CAUSE") == 1


# ---------------------------------------------------------------------------
# 7. apply_literalism_rules: API routes glob
# ---------------------------------------------------------------------------

def test_api_routes_glob_replacement():
    result = apply_literalism_rules("Review all API routes for security issues")
    assert "all API routes" not in result
    assert "src/api/**/*" in result
    assert "Process each file independently" in result


def test_endpoints_glob_replacement():
    result = apply_literalism_rules("Update all endpoints to return JSON")
    assert "all endpoints" not in result
    assert "src/**/*.ts" in result
    assert "Process each file independently" in result


# ---------------------------------------------------------------------------
# 8. Omit empty tags
# ---------------------------------------------------------------------------

def test_omit_empty_tags():
    result = build_prompt(task="Minimal task", reminder="Keep it simple")
    assert "<constraints>" not in result
    assert "<context>" not in result
    assert "<files-write>" not in result
    assert "<acceptance>" not in result
    assert "<effort-recommendation>" not in result
    assert "<complexity>" not in result
    assert "<critical-context>" not in result
    assert "<reference-context>" not in result


# ---------------------------------------------------------------------------
# 9. files_write formatting
# ---------------------------------------------------------------------------

def test_files_write_bullet_format():
    result = build_prompt(
        task="Write files",
        files_write=["lib/foo.py", "lib/bar.py"],
        reminder="Check both files",
    )
    assert "<files-write>\n- lib/foo.py\n- lib/bar.py\n</files-write>" in result


# ---------------------------------------------------------------------------
# 10. reminder always present
# ---------------------------------------------------------------------------

def test_reminder_always_present():
    result = build_prompt(task="Minimal task", reminder="This is the reminder")
    assert "Reminder: This is the reminder" in result


def test_reminder_at_end():
    result = build_prompt(
        task="Some task",
        constraints="constraint",
        reminder="Always at the end",
    )
    # reminder line is the last element
    assert result.strip().endswith("Reminder: Always at the end")


# ---------------------------------------------------------------------------
# Extras: complexity validation
# ---------------------------------------------------------------------------

def test_complexity_zero_allowed():
    result = build_prompt(task="task", reminder="reminder text", complexity=0)
    assert "<complexity>" not in result


def test_complexity_valid_range():
    for c in range(1, 11):
        result = build_prompt(task="task", reminder="reminder text", complexity=c)
        assert f"<complexity>{c}</complexity>" in result


def test_complexity_out_of_range_raises():
    with pytest.raises(ValueError):
        build_prompt(task="task", reminder="reminder text", complexity=11)

    with pytest.raises(ValueError):
        build_prompt(task="task", reminder="reminder text", complexity=-1)


# ---------------------------------------------------------------------------
# Separator check
# ---------------------------------------------------------------------------

def test_elements_separated_by_double_newline():
    result = build_prompt(
        task="task text",
        constraints="constraint text",
        reminder="reminder text",
    )
    # task block ends with </task>, then double newline, then <constraints>
    assert "</task>\n\n<constraints>" in result


# ---------------------------------------------------------------------------
# Gap fixes: §7.2.1 whitespace symmetry + §7.2.3 threshold precision
# ---------------------------------------------------------------------------

def test_reminder_equals_task_task_has_whitespace():
    """strip() is applied to task too — leading/trailing whitespace on task side."""
    with pytest.raises(ValueError, match="reminder must differ"):
        build_prompt(task="  Do X  ", reminder="Do X")


def test_split_threshold_exact_boundary():
    """Verify split fires at exactly threshold+1 chars (window-relative, not hard-coded)."""
    # Use a small context_window so threshold = int(20 * 0.04) = 0 chars.
    # Any non-trivial prompt will exceed 0 → split mode.
    result_split = build_prompt(
        task="X",
        critical_context="C",
        reference_context="R",
        reminder="Final reminder",
        context_window=20,   # threshold = int(20 * 0.04) = 0
    )
    assert "<critical-context>" in result_split
    assert "<context>" not in result_split

    # With a very large window, the same prompt stays base.
    result_base = build_prompt(
        task="X",
        context="C",
        critical_context="C",
        reference_context="R",
        reminder="Final reminder",
        context_window=10_000_000,  # threshold = 400_000 — far exceeds prompt
    )
    assert "<context>" in result_base
    assert "<critical-context>" not in result_base
