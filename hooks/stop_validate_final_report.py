#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

_FINDINGS = os.path.join(os.getcwd(), ".conductor", "findings.md")

REQUIRED_SECTIONS = [
    "executive summary",
    "plan vs",
    "material changes",
    "routing notes",
    "safety mechanism",
    "debug map",
    "outstanding items",
    "evidence index",
    "next steps",
]

_REPORT_CANDIDATES = [
    os.path.join(os.getcwd(), "FINAL_REPORT.md"),
    os.path.join(os.getcwd(), ".conductor", "FINAL_REPORT.md"),
]


def _append_findings(msg: str) -> None:
    try:
        with open(_FINDINGS, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main():
    try:
        sys.stdin.read()
    except Exception:
        pass

    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        sys.exit(0)

    if state.get("phase") != "complete":
        sys.exit(0)

    report_path = next(
        (c for c in _REPORT_CANDIDATES if os.path.exists(c)), None
    )

    if report_path is None:
        _append_findings(
            "stop_validate_final_report: phase==complete but FINAL_REPORT.md not found. "
            "Run conductor-debug-map skill to generate it."
        )
        sys.exit(0)

    try:
        content = Path(report_path).read_text(encoding="utf-8", errors="replace").lower()
    except Exception:
        _append_findings(
            f"stop_validate_final_report: FINAL_REPORT.md found at {report_path} "
            "but could not be read."
        )
        sys.exit(0)

    missing = [s for s in REQUIRED_SECTIONS if s not in content]
    if missing:
        _append_findings(
            f"stop_validate_final_report: FINAL_REPORT.md missing sections: "
            f"{missing}. Report may be incomplete."
        )


if __name__ == "__main__":
    main()
    sys.exit(0)
