"""effort_router.py — Map task complexity and category to effort level and model.

§5.4 of the TheConductor v5 spec.
"""

ALWAYS_XHIGH = frozenset({"security_audit", "schema_design", "root_cause_debug", "classification"})
XHIGH_FLOOR = 4  # complexity floor below which ALWAYS_XHIGH doesn't override

EFFORT_MAP = {
    1: "low", 2: "low", 3: "low",
    4: "medium", 5: "medium", 6: "medium",
    7: "high", 8: "high",
    9: "xhigh", 10: "xhigh",
}

MODEL_MAP = {
    1: "sonnet", 2: "sonnet", 3: "sonnet",
    4: None,  # agent default (no override)
    5: None, 6: None,
    7: "opus", 8: "opus",
    9: "opus", 10: "opus",
}


def resolve_effort(category: str, complexity: int) -> str:
    """Return effort level for a task.

    ALWAYS_XHIGH categories are xhigh at complexity >= XHIGH_FLOOR.
    Below floor, normal mapping wins regardless of category.

    Raises ValueError if complexity not in [1, 10].
    """
    if complexity not in range(1, 11):
        raise ValueError(f"complexity must be 1-10, got {complexity}")
    if complexity < XHIGH_FLOOR:
        return EFFORT_MAP[complexity]  # floor wins for trivial tasks
    if category in ALWAYS_XHIGH:
        return "xhigh"
    return EFFORT_MAP[complexity]


def resolve_model(complexity: int) -> str | None:
    """Return model override for a given complexity, or None for agent default.

    Raises ValueError if complexity not in [1, 10].
    """
    if complexity not in range(1, 11):
        raise ValueError(f"complexity must be 1-10, got {complexity}")
    return MODEL_MAP[complexity]
