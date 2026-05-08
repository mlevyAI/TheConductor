"""Pin tests for project-conductor.md v6.0.3 wiring.

The Phase 0a auto-install + bundle reduction are described purely in the
agent's prompt (no executable code drives them — the agent reads the
prompt and acts on it). These tests pin the prose so a future edit can't
silently revert the v6.0.3 contract.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def _read_prompt() -> str:
    return (REPO_ROOT / "project-conductor.md").read_text(encoding="utf-8")


def _read_hooks_readme() -> str:
    return (REPO_ROOT / "hooks" / "README.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 0a section is present and self-consistent
# ---------------------------------------------------------------------------

def test_prompt_contains_phase_0a_section():
    text = _read_prompt()
    assert "## Phase 0a" in text, (
        "project-conductor.md must contain a `## Phase 0a` section that "
        "describes the first-session enforcement-hooks auto-install. "
        "See v6.0.3 contract."
    )


def test_phase_0a_runs_before_phase_0():
    """Phase 0a must appear in the document BEFORE Phase 0 — order matters
    because pre_phase0_readonly.py would block the settings.json write
    once it's wired."""
    text = _read_prompt()
    idx_0a = text.find("## Phase 0a")
    idx_0 = text.find("## Phase 0 — Environment Discovery")
    assert idx_0a >= 0 and idx_0 >= 0
    assert idx_0a < idx_0, (
        "## Phase 0a must precede ## Phase 0 — auto-install must complete "
        "before the read-only hook becomes active"
    )


def test_phase_0a_references_manifest_and_render():
    text = _read_prompt()
    assert "hooks/MANIFEST.json" in text
    assert "render_settings_block" in text
    assert '"phase_b", "v6_replayability"' in text or \
           "phase_b" in text and "v6_replayability" in text


def test_phase_0a_documents_canary_sanity_test():
    """The §3 settings-write contract requires a canary; Phase 0a must
    invoke it just like the bundles offer historically did."""
    text = _read_prompt()
    # Look in the Phase 0a section specifically
    idx = text.find("## Phase 0a")
    section = text[idx:text.find("## Phase 0", idx + 1)] if idx >= 0 else ""
    assert "canary" in section.lower(), (
        "Phase 0a must invoke a canary sanity test before activating the "
        "settings.json merge — same gate as the existing bundles install."
    )


def test_phase_0a_no_user_prompt_required():
    text = _read_prompt()
    idx = text.find("## Phase 0a")
    section = text[idx:text.find("## Phase 0", idx + 1)] if idx >= 0 else ""
    assert "No prompt to the user" in section, (
        "Phase 0a must explicitly state that no user prompt is required "
        "(this is what differentiates auto-install from the historical "
        "bundles flow)."
    )


def test_phase_0a_documents_removal():
    """Per user choice: 'Always install, document removal'."""
    text = _read_prompt()
    idx = text.find("## Phase 0a")
    section = text[idx:text.find("## Phase 0", idx + 1)] if idx >= 0 else ""
    assert "Removal" in section or "remove" in section.lower(), (
        "Phase 0a must document how a user can remove the auto-installed "
        "hooks (per the v6.0.3 'always install, document removal' choice)."
    )


# ---------------------------------------------------------------------------
# Bundles offer was reduced to 3
# ---------------------------------------------------------------------------

def test_bundles_offer_no_longer_includes_4_or_5():
    text = _read_prompt()
    # The bundles offer used to list (4) Phase B and (5) v6 replayability.
    # After v6.0.3 those move to Phase 0a, so the offer text should NOT
    # contain "**(4)" or "**(5)" entries within the Optional Bundles Offer.
    idx_offer = text.find("### 📦 Optional bundles offer")
    if idx_offer < 0:
        # Try alternate header style
        idx_offer = text.find("Optional Bundles Offer")
    assert idx_offer >= 0, "Optional Bundles Offer section not found"

    # Look at next ~2000 chars (the offer block)
    block = text[idx_offer:idx_offer + 2000]
    assert "**(4)" not in block, (
        "Optional Bundles Offer still mentions bundle (4); per v6.0.3 the "
        "Phase B + v6 enforcement hooks are auto-installed in Phase 0a "
        "and should NOT appear in the offer."
    )
    assert "**(5)" not in block, (
        "Optional Bundles Offer still mentions bundle (5); per v6.0.3 the "
        "v6 replayability hooks move to Phase 0a auto-install."
    )


def test_bundles_offer_install_command_uses_three_indices():
    text = _read_prompt()
    # The install command should now read "install 1,2,3" not "install 1,2,3,4,5"
    assert "install 1,2,3 from /path/to/TheConductor" in text or \
           "install 1,2,3 from" in text, (
        "Bundles offer install command should reference 1,2,3 only "
        "(monitoring + recovery + agent-monitor). Found something else."
    )
    # Stale 1,2,3,4,5 must not be in the bundles offer area
    assert "install 1,2,3,4,5" not in text, (
        "Stale bundle install command 'install 1,2,3,4,5' still in prompt"
    )


# ---------------------------------------------------------------------------
# hooks/README.md tracks the new install model
# ---------------------------------------------------------------------------

def test_hooks_readme_documents_two_install_paths():
    text = _read_hooks_readme()
    # Must describe BOTH paths
    assert "Auto-installed" in text or "auto-installed" in text.lower()
    assert "Opt-in" in text or "opt-in" in text.lower()


def test_hooks_readme_mentions_phase_0a():
    text = _read_hooks_readme()
    assert "Phase 0a" in text, (
        "hooks/README.md should reference Phase 0a so users know where "
        "the enforcement hooks come from."
    )


def test_hooks_readme_mentions_manifest():
    text = _read_hooks_readme()
    assert "MANIFEST.json" in text, (
        "hooks/README.md should point users to MANIFEST.json as the "
        "canonical source of which hooks ship."
    )


def test_hooks_readme_documents_removal_path():
    text = _read_hooks_readme()
    assert "Removing" in text or "removing" in text.lower()
    assert "settings.json" in text
