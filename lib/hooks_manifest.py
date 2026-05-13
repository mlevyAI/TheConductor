"""hooks_manifest.py — Read hooks/MANIFEST.json and generate settings.json.

§v6.0.2 of the TheConductor spec.

The conductor's "Optional Bundles Offer" tells the user which hooks will
be wired into their project's `.claude/settings.json`. Until v6.0.2 the
list lived in prose inside `project-conductor.md` and the wiring was
re-derived ad hoc each session. This module makes the list a structured
artifact and the wiring deterministic:

  hooks/MANIFEST.json  — single source of truth (one entry per hook)
  lib.hooks_manifest    — load, validate, group by bundle, render settings

The settings snippet produced is the literal JSON the conductor writes
into the project's `.claude/settings.json` (via the existing canary +
sanity-test path described in `project-conductor.md`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

VALID_EVENTS = {"PreToolUse", "PostToolUse", "Stop", "SessionStart"}
VALID_BUNDLES = {"phase_b", "v6_replayability", "monitoring", "recovery", "bootstrap"}
REQUIRED_FIELDS = {"name", "event", "bundle", "blocking", "since_version", "description"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def manifest_path() -> Path:
    return _repo_root() / "hooks" / "MANIFEST.json"


def hooks_dir() -> Path:
    return _repo_root() / "hooks"


def load_manifest(path: str | os.PathLike | None = None) -> dict:
    """Load and validate the hooks manifest. Raises on malformed entries."""
    p = Path(path) if path is not None else manifest_path()
    if not p.is_file():
        raise FileNotFoundError(f"hooks manifest not found at {p}")
    data = json.loads(p.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    if data.get("schema_version") != 1:
        raise ValueError(
            f"unsupported manifest schema_version {data.get('schema_version')!r}"
        )
    hooks = data.get("hooks")
    if not isinstance(hooks, list) or not hooks:
        raise ValueError("manifest.hooks must be a non-empty list")

    seen_names: set[str] = set()
    for i, h in enumerate(hooks):
        if not isinstance(h, dict):
            raise ValueError(f"hooks[{i}] must be an object")
        missing = REQUIRED_FIELDS - h.keys()
        if missing:
            raise ValueError(f"hooks[{i}] missing fields: {sorted(missing)}")
        if h["event"] not in VALID_EVENTS:
            raise ValueError(
                f"hooks[{i}].event {h['event']!r} not in {sorted(VALID_EVENTS)}"
            )
        if h["bundle"] not in VALID_BUNDLES:
            raise ValueError(
                f"hooks[{i}].bundle {h['bundle']!r} not in {sorted(VALID_BUNDLES)}"
            )
        if not isinstance(h["blocking"], bool):
            raise ValueError(f"hooks[{i}].blocking must be bool")
        if h["name"] in seen_names:
            raise ValueError(f"duplicate hook name in manifest: {h['name']!r}")
        seen_names.add(h["name"])

    return data


def list_hooks(bundle: str | None = None, *, manifest: dict | None = None) -> list[dict]:
    """Return hook entries, optionally filtered by bundle."""
    m = manifest if manifest is not None else load_manifest()
    out = m["hooks"]
    if bundle is not None:
        out = [h for h in out if h["bundle"] == bundle]
    return out


def list_bundles(manifest: dict | None = None) -> list[str]:
    """Return all bundle names referenced in the manifest, sorted."""
    m = manifest if manifest is not None else load_manifest()
    return sorted({h["bundle"] for h in m["hooks"]})


def render_settings_block(
    bundles: list[str],
    *,
    hook_dir: str,
    python_cmd: str = "python3",
    manifest: dict | None = None,
) -> dict:
    """Render a top-level settings fragment containing the `hooks` key.

    Returns ``{"hooks": {...}}`` — a fragment you merge **at the top level**
    of your settings dict. Do NOT nest the return value under another
    ``hooks:`` key (that double-wraps and Claude Code silently ignores the
    inner block). Correct merge::

        settings["hooks"] = render_settings_block(...)["hooks"]
        # or, additive over any pre-existing entries:
        existing = settings.setdefault("hooks", {})
        for event, entries in render_settings_block(...)["hooks"].items():
            existing.setdefault(event, []).extend(entries)

    `hook_dir` should be the absolute directory in which hook scripts will
    be invoked (typically `<project>/.claude/hooks/` after the conductor
    has copied them there, or the in-repo `hooks/` for advanced users
    pointing directly at the source).

    Full return shape::

        {"hooks": {"PreToolUse": [{"hooks": [{...}, {...}]}], "Stop": [...]}}
    """
    m = manifest if manifest is not None else load_manifest()
    selected = [h for h in m["hooks"] if h["bundle"] in bundles]
    if not selected:
        return {"hooks": {}}

    hook_dir_path = Path(hook_dir)
    by_event: dict[str, list[dict]] = {}
    for h in selected:
        cmd = f'{python_cmd} "{(hook_dir_path / h["name"]).as_posix()}"'
        entry: dict = {"type": "command", "command": cmd}
        if not h["blocking"]:
            entry["async"] = True
        by_event.setdefault(h["event"], []).append(entry)

    out: dict[str, list[dict]] = {}
    # Preserve a deterministic event order for predictable JSON output
    for event in ("SessionStart", "PreToolUse", "PostToolUse", "Stop"):
        if event in by_event:
            out[event] = [{"hooks": by_event[event]}]

    return {"hooks": out}


def render_permissions(
    bundles: list[str],
    *,
    hook_dir: str,
    python_cmd: str = "python3",
    manifest: dict | None = None,
) -> list[str]:
    """Return the `Bash(...)` allow entries the user must add to permissions.

    Format mirrors `hooks/README.md` example block.
    """
    m = manifest if manifest is not None else load_manifest()
    selected = [h for h in m["hooks"] if h["bundle"] in bundles]
    hook_dir_path = Path(hook_dir)
    return [
        f'Bash({python_cmd} "{(hook_dir_path / h["name"]).as_posix()}")'
        for h in selected
    ]


def validate_against_disk(manifest: dict | None = None) -> list[str]:
    """Return a list of consistency errors between manifest and hooks/.

    Empty list = consistent. Each entry is a human-readable error.
    """
    m = manifest if manifest is not None else load_manifest()
    errors: list[str] = []

    declared = {h["name"] for h in m["hooks"]}

    # Every declared hook must have a matching .py file in hooks/
    for name in declared:
        if not (hooks_dir() / name).is_file():
            errors.append(f"manifest declares {name!r} but no such file in hooks/")

    # Every .py file in hooks/ must be declared (exclude private helpers)
    for f in hooks_dir().glob("*.py"):
        if f.name.startswith("_"):
            continue
        if f.name not in declared:
            errors.append(f"hooks/{f.name} exists but is not declared in MANIFEST.json")

    return errors
