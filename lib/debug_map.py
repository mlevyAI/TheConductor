"""debug_map.py — Live surgical debug map.

§v6 of the TheConductor spec.

Generates `.conductor/debug-map.md` *incrementally* as features complete,
rather than only at the end of the session. The existing
`conductor-debug-map` skill remains the authoritative source for the
post-flight synthesis appended to `FINAL_REPORT.md`; this module is the
live, mid-run counterpart.

Persistence:

  .conductor/debug-map.json  — authoritative structured state (one record
                                per feature)
  .conductor/debug-map.md    — rendered markdown (overwritten on update)

The phrase "KNOWN LIMITATION" is banned per §v4 anti-patterns. Limitations
must use the form `unverified — N approaches tried: [list]`. This module
enforces that constraint at write time.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_BANNED_PHRASE = "KNOWN LIMITATION"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Limitation:
    description: str
    approaches_tried: list[str] = field(default_factory=list)

    def render(self) -> str:
        n = len(self.approaches_tried)
        approaches = ", ".join(self.approaches_tried) if self.approaches_tried else "—"
        return (
            f"unverified — {n} approaches tried: {approaches}. "
            f"Outstanding: {self.description}"
        )


@dataclass
class Feature:
    name: str
    phase: str
    tasks: list[str] = field(default_factory=list)
    primary_files: list[str] = field(default_factory=list)
    database_tables: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    commit_shas: list[str] = field(default_factory=list)
    subagent: str | None = None
    model_requested: str | None = None
    key_decisions: list[str] = field(default_factory=list)
    emergent_fixes: list[str] = field(default_factory=list)
    limitations: list[Limitation] = field(default_factory=list)
    recorded_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Feature":
        f = cls(
            name=d["name"],
            phase=str(d.get("phase", "")),
            tasks=list(d.get("tasks", [])),
            primary_files=list(d.get("primary_files", [])),
            database_tables=list(d.get("database_tables", [])),
            test_files=list(d.get("test_files", [])),
            commit_shas=list(d.get("commit_shas", [])),
            subagent=d.get("subagent"),
            model_requested=d.get("model_requested"),
            key_decisions=list(d.get("key_decisions", [])),
            emergent_fixes=list(d.get("emergent_fixes", [])),
            recorded_at=d.get("recorded_at", ""),
        )
        for raw in d.get("limitations", []):
            if isinstance(raw, dict):
                f.limitations.append(Limitation(
                    description=raw.get("description", ""),
                    approaches_tried=list(raw.get("approaches_tried", [])),
                ))
        return f

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def debug_map_json_path(cwd: str | os.PathLike | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".conductor" / "debug-map.json"


def debug_map_md_path(cwd: str | os.PathLike | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".conductor" / "debug-map.md"


def _load(cwd: str | os.PathLike | None) -> list[Feature]:
    p = debug_map_json_path(cwd)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("features", []) if isinstance(data, dict) else []
    return [Feature.from_dict(f) for f in raw if isinstance(f, dict)]


def _save(features: list[Feature], cwd: str | os.PathLike | None) -> None:
    p = debug_map_json_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": _utc_now(),
        "features": [f.to_dict() for f in features],
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _check_no_banned_phrase(*texts: str) -> None:
    for t in texts:
        if t and _BANNED_PHRASE in t:
            raise ValueError(
                f"banned phrase {_BANNED_PHRASE!r} detected; use the form "
                "'unverified — N approaches tried: [list]' instead "
                "(per §v4 anti-patterns)"
            )


def upsert_feature(
    name: str,
    *,
    phase: str | int,
    tasks: list[str] | None = None,
    primary_files: list[str] | None = None,
    database_tables: list[str] | None = None,
    test_files: list[str] | None = None,
    commit_shas: list[str] | None = None,
    subagent: str | None = None,
    model_requested: str | None = None,
    key_decisions: list[str] | None = None,
    emergent_fixes: list[str] | None = None,
    cwd: str | os.PathLike | None = None,
) -> Feature:
    """Insert or update a feature record. Identity is by `name`.

    Re-calling with the same name updates the existing record (idempotent
    upsert). Limitations are NOT modified here — use `add_limitation()`.
    """
    if not name or not name.strip():
        raise ValueError("feature name must be non-empty")

    _check_no_banned_phrase(
        name,
        *(tasks or []),
        *(primary_files or []),
        *(key_decisions or []),
        *(emergent_fixes or []),
    )

    features = _load(cwd)
    found: Feature | None = None
    for f in features:
        if f.name == name.strip():
            found = f
            break

    if found is None:
        found = Feature(name=name.strip(), phase=str(phase))
        features.append(found)
    else:
        found.phase = str(phase)

    if tasks is not None:
        found.tasks = list(tasks)
    if primary_files is not None:
        found.primary_files = list(primary_files)
    if database_tables is not None:
        found.database_tables = list(database_tables)
    if test_files is not None:
        found.test_files = list(test_files)
    if commit_shas is not None:
        found.commit_shas = list(commit_shas)
    if subagent is not None:
        found.subagent = subagent
    if model_requested is not None:
        found.model_requested = model_requested
    if key_decisions is not None:
        found.key_decisions = list(key_decisions)
    if emergent_fixes is not None:
        found.emergent_fixes = list(emergent_fixes)

    found.recorded_at = _utc_now()
    _save(features, cwd)
    return found


def add_limitation(
    feature_name: str,
    *,
    description: str,
    approaches_tried: list[str],
    cwd: str | os.PathLike | None = None,
) -> Feature:
    """Add a limitation to a feature.

    Enforces:
      - The banned phrase 'KNOWN LIMITATION' is not used.
      - approaches_tried has at least 3 entries (per §v4 Anti-Premature-
        Failure rule).
    """
    if len(approaches_tried) < 3:
        raise ValueError(
            f"limitations require ≥3 approaches tried; got {len(approaches_tried)} "
            "(per §v4 Anti-Premature-Failure)"
        )
    _check_no_banned_phrase(description, *approaches_tried)

    features = _load(cwd)
    for f in features:
        if f.name == feature_name:
            f.limitations.append(Limitation(
                description=description,
                approaches_tried=list(approaches_tried),
            ))
            f.recorded_at = _utc_now()
            _save(features, cwd)
            return f
    raise KeyError(f"feature {feature_name!r} not found")


def list_features(cwd: str | os.PathLike | None = None) -> list[Feature]:
    return _load(cwd)


def render_markdown(cwd: str | os.PathLike | None = None) -> str:
    features = _load(cwd)
    out = []
    out.append("## 🔧 Surgical Debug Map")
    out.append("")
    out.append("**Use this to fix bugs found after delivery.**")
    out.append("")
    out.append("### How to use")
    out.append(
        "> \"Bug in [feature]. Per debug map: phase [P], files [list], "
        "commit [SHA]. Fix surgically without touching unrelated code.\""
    )
    out.append("")
    if not features:
        out.append("_No features recorded yet. Features are added "
                   "incrementally as they complete._")
        out.append("")
        return "\n".join(out)

    out.append("### Feature → Debug Context map")
    out.append("")

    for f in features:
        out.append(f"#### Feature: {f.name}")
        out.append(f"- **Built in**: Phase {f.phase}, Tasks {_fmt_list(f.tasks)}")
        out.append(f"- **Primary files**: {_fmt_files(f.primary_files)}")
        if f.database_tables:
            out.append(f"- **Database**: {_fmt_files(f.database_tables)}")
        out.append(f"- **Tests**: {_fmt_files(f.test_files)}")
        out.append(f"- **Key commits**: {_fmt_shas(f.commit_shas)}")
        if f.subagent:
            sub = f.subagent
            if f.model_requested:
                sub = f"{sub} ({f.model_requested})"
            out.append(f"- **Subagent used**: {sub}")
        if f.key_decisions:
            out.append(f"- **Key decisions**: {', '.join(f.key_decisions)}")
        if f.emergent_fixes:
            out.append(f"- **Emergent fixes**: {', '.join(f.emergent_fixes)}")
        if f.limitations:
            out.append("- **Known limitations**:")
            for lim in f.limitations:
                out.append(f"  - {lim.render()}")
        out.append("")

    return "\n".join(out)


def _fmt_list(items: list[str]) -> str:
    return ", ".join(items) if items else "—"


def _fmt_files(items: list[str]) -> str:
    return ", ".join(f"`{i}`" for i in items) if items else "—"


def _fmt_shas(items: list[str]) -> str:
    return ", ".join(f"`{s[:8]}`" for s in items) if items else "—"


def write_debug_map_md(cwd: str | os.PathLike | None = None) -> Path:
    p = debug_map_md_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = render_markdown(cwd=cwd)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
    return p
