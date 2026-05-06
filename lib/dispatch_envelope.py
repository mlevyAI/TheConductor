"""dispatch_envelope.py — Build structured prompt envelopes for agent dispatch.

§5.3 of the TheConductor v5 spec.
"""


def build_prompt(
    task: str,
    *,
    constraints: str = "",
    files_write: list[str] | None = None,
    acceptance: str = "",
    context: str = "",
    critical_context: str = "",
    reference_context: str = "",
    effort_recommendation: str = "",
    complexity: int = 0,
    reminder: str,
    context_window: int = 200_000,
) -> str:
    """Build a structured prompt envelope for agent dispatch.

    Assembles elements in §5.3 order, separated by double newlines.
    Switches from base (8-element) to split (9-element) format when the
    assembled prompt exceeds 4% of context_window.

    Raises ValueError if reminder == task or complexity is out of range.
    """
    if reminder.strip() == task.strip():
        raise ValueError("reminder must differ from task")
    if complexity != 0 and complexity not in range(1, 11):
        raise ValueError(f"complexity must be 1-10 (or 0 for unspecified), got {complexity}")

    threshold = int(context_window * 0.04)

    # --- helpers ---
    def fmt_files(paths: list[str]) -> str:
        return "\n".join(f"- {p}" for p in paths)

    # --- build base prompt ---
    base_prompt = _assemble(
        task=task,
        constraints=constraints,
        files_write=files_write,
        acceptance=acceptance,
        context=context,
        critical_context=None,
        reference_context=None,
        effort_recommendation=effort_recommendation,
        complexity=complexity,
        reminder=reminder,
        split=False,
        fmt_files=fmt_files,
    )

    if len(base_prompt) > threshold:
        return _assemble(
            task=task,
            constraints=constraints,
            files_write=files_write,
            acceptance=acceptance,
            context=None,
            critical_context=critical_context,
            reference_context=reference_context,
            effort_recommendation=effort_recommendation,
            complexity=complexity,
            reminder=reminder,
            split=True,
            fmt_files=fmt_files,
        )

    return base_prompt


def _assemble(
    *,
    task: str,
    constraints: str,
    files_write: list[str] | None,
    acceptance: str,
    context: str | None,
    critical_context: str | None,
    reference_context: str | None,
    effort_recommendation: str,
    complexity: int,
    reminder: str,
    split: bool,
    fmt_files,
) -> str:
    elements: list[str] = []

    # 1. task — always present
    elements.append(f"<task>\n{task}\n</task>")

    # 2. constraints — omit if empty
    if constraints:
        elements.append(f"<constraints>\n{constraints}\n</constraints>")

    # 3. files-write — omit if empty/None
    if files_write:
        elements.append(f"<files-write>\n{fmt_files(files_write)}\n</files-write>")

    # 4. acceptance — omit if empty
    if acceptance:
        elements.append(f"<acceptance>\n{acceptance}\n</acceptance>")

    if not split:
        # 5 (base). context — omit if empty
        if context:
            elements.append(f"<context>\n{context}\n</context>")
    else:
        # 5 (split). critical-context — omit if empty
        if critical_context:
            elements.append(f"<critical-context>\n{critical_context}\n</critical-context>")
        # 6 (split). reference-context — omit if empty
        if reference_context:
            elements.append(f"<reference-context>\n{reference_context}\n</reference-context>")

    # 6/7. effort-recommendation — omit if empty
    if effort_recommendation:
        elements.append(f"<effort-recommendation>{effort_recommendation}</effort-recommendation>")

    # 7/8. complexity — omit if 0
    if complexity != 0:
        elements.append(f"<complexity>{complexity}</complexity>")

    # 8/9. reminder — always present, plain text
    elements.append(f"Reminder: {reminder}")

    return "\n\n".join(elements)


def apply_literalism_rules(prompt: str) -> str:
    """Transform a prompt string to improve Opus compliance per §5.3.

    1. Replaces vague API/endpoint references with explicit file globs.
    2. Appends root-cause instruction for bugfix prompts (idempotent).
    """
    import re as _re

    # Rule 1a: "all API routes" → explicit glob (case-insensitive)
    prompt = _re.sub(
        r"all\s+api\s+routes",
        "all files matching `src/api/**/*`. Process each file independently and confirm each one.",
        prompt,
        flags=_re.IGNORECASE,
    )

    # Rule 1b: "all endpoints" → explicit glob (case-insensitive)
    prompt = _re.sub(
        r"all\s+endpoints",
        "all files matching `src/**/*.ts`. Process each file independently and confirm each one.",
        prompt,
        flags=_re.IGNORECASE,
    )

    # Rule 2: root-cause instruction for bugfix prompts (idempotent)
    root_cause_instruction = (
        "\n\nFix the ROOT CAUSE, not just the symptom. "
        "If the obvious fix is line-local, surface why and ask before patching only that line."
    )
    if ("fix" in prompt.lower() or "bug" in prompt.lower()) and root_cause_instruction not in prompt:
        prompt += root_cause_instruction

    return prompt
