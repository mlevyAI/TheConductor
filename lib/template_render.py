import re
from pathlib import Path


def render(template_path: str, payload: dict, target_path: str) -> tuple[str, list[str]]:
    """Render a template file with variable substitution.

    Args:
        template_path: Path to the UTF-8 template file.
        payload: Dict mapping variable names to their values.
        target_path: Destination path (used for path-safety check only; not written here).

    Returns:
        (rendered_content, list_of_missing_var_names)

    Raises:
        ValueError: If target_path resolves to a path under ~/.claude/.
    """
    # --- Path safety check ---
    resolved_target = Path(target_path).resolve()
    resolved_claude = Path("~/.claude").expanduser().resolve()

    # Manual parts-prefix comparison (Python 3.8 compat; avoids is_relative_to)
    target_parts = resolved_target.parts
    claude_parts = resolved_claude.parts
    if target_parts[: len(claude_parts)] == claude_parts:
        raise ValueError(
            "refusing to write under ~/.claude/ — user-global is read-only at runtime per §3.1"
        )

    # --- Read template ---
    with open(template_path, encoding="utf-8") as f:
        content = f.read()

    # --- Substitution ---
    missing: list = []

    # Pattern: {{{{ (escape) OR {{VAR}} (variable)
    pattern = re.compile(r"\{\{\{\{|\{\{([^{}]*)\}\}")

    def replacer(match: re.Match) -> str:
        if match.group(0) == "{{{{":
            return "{{"
        var_name = match.group(1)
        if var_name in payload:
            return str(payload[var_name])
        missing.append(var_name)
        return f"TODO: {var_name}"

    rendered = pattern.sub(replacer, content)
    return rendered, missing
