"""Tests for lib/effort_router.py — §7.2 of the TheConductor v5 spec."""

import pytest

from lib.effort_router import (
    ALWAYS_XHIGH,
    XHIGH_FLOOR,
    resolve_effort,
    resolve_model,
)


# ---------------------------------------------------------------------------
# resolve_effort — spec §7.2 named cases
# ---------------------------------------------------------------------------


def test_always_xhigh_below_floor_mapping_wins():
    """Case 1: ALWAYS_XHIGH category below floor → normal mapping wins."""
    assert resolve_effort("security_audit", 2) == "low"


def test_security_audit_at_floor_is_xhigh():
    """Case 2: complexity=4 (floor) in security category → xhigh."""
    assert resolve_effort("security_audit", 4) == "xhigh"


def test_schema_design_below_floor_is_low():
    """Case 3: complexity=2 in schema category → low."""
    assert resolve_effort("schema_design", 2) == "low"


def test_non_special_category_at_floor_is_medium():
    """Case 4: Non-ALWAYS_XHIGH at complexity 4 → medium, not xhigh."""
    assert resolve_effort("feature", 4) == "medium"


def test_non_special_high_complexity():
    """Case 5: complexity=7 non-special category → high."""
    assert resolve_effort("feature", 7) == "high"


def test_non_special_xhigh_complexity():
    """Case 6: complexity=9 → xhigh regardless of category."""
    assert resolve_effort("feature", 9) == "xhigh"


# ---------------------------------------------------------------------------
# Case 7: All 4 ALWAYS_XHIGH categories at floor → xhigh
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", sorted(ALWAYS_XHIGH))
def test_all_always_xhigh_categories_at_floor(category):
    """All 4 ALWAYS_XHIGH categories at XHIGH_FLOOR return xhigh."""
    assert resolve_effort(category, XHIGH_FLOOR) == "xhigh"


# ---------------------------------------------------------------------------
# Case 8: XHIGH_FLOOR boundary
# ---------------------------------------------------------------------------


def test_security_below_floor_is_low():
    """complexity=3 (one below floor) in security → low."""
    assert resolve_effort("security_audit", XHIGH_FLOOR - 1) == "low"


def test_security_at_floor_is_xhigh():
    """complexity=4 (at floor) in security → xhigh."""
    assert resolve_effort("security_audit", XHIGH_FLOOR) == "xhigh"


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------


def test_resolve_model_low_complexity():
    """Case 9: complexity=3 → sonnet."""
    assert resolve_model(3) == "sonnet"


def test_resolve_model_mid_complexity_is_none():
    """Case 10: complexity=5 → None (agent default)."""
    assert resolve_model(5) is None


def test_resolve_model_high_complexity():
    """Case 11: complexity=8 → opus."""
    assert resolve_model(8) == "opus"


# ---------------------------------------------------------------------------
# Case 12: Invalid complexity raises ValueError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, 11, -1, 100])
def test_resolve_effort_invalid_complexity(bad):
    with pytest.raises(ValueError, match="complexity must be 1-10"):
        resolve_effort("x", bad)


@pytest.mark.parametrize("bad", [0, 11, -1, 100])
def test_resolve_model_invalid_complexity(bad):
    with pytest.raises(ValueError, match="complexity must be 1-10"):
        resolve_model(bad)


# ---------------------------------------------------------------------------
# Full EFFORT_MAP coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("complexity,expected", [
    (1, "low"), (2, "low"), (3, "low"),
    (4, "medium"), (5, "medium"), (6, "medium"),
    (7, "high"), (8, "high"),
    (9, "xhigh"), (10, "xhigh"),
])
def test_effort_map_full_coverage(complexity, expected):
    """Non-special category respects EFFORT_MAP at every complexity level."""
    assert resolve_effort("generic", complexity) == expected


# ---------------------------------------------------------------------------
# Full MODEL_MAP coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("complexity,expected", [
    (1, "sonnet"), (2, "sonnet"), (3, "sonnet"),
    (4, None), (5, None), (6, None),
    (7, "opus"), (8, "opus"),
    (9, "opus"), (10, "opus"),
])
def test_model_map_full_coverage(complexity, expected):
    assert resolve_model(complexity) == expected
