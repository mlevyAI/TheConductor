#!/usr/bin/env python3

import csv
import json
import os
import sys
from pathlib import Path

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

_FINDINGS = os.path.join(os.getcwd(), ".conductor", "findings.md")

SQLITE_KEYWORDS = ("sqlite3", "INSERT INTO", "CREATE TABLE", ".import")


def _append_findings(msg: str) -> None:
    try:
        with open(_FINDINGS, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _check_csv(filepath: str) -> list:
    issues = []
    try:
        with open(filepath, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return ["output-quality: empty CSV — no rows written"]
        for col in rows[0].keys():
            values = [r.get(col, "") or "" for r in rows]
            non_empty = [v for v in values if v.strip()]
            if not non_empty:
                issues.append(
                    f"output-quality: column '{col}' is entirely empty in {filepath}"
                )
            elif len(non_empty) / len(values) < 0.5:
                pct = int(100 * len(non_empty) / len(values))
                issues.append(
                    f"output-quality: column '{col}' has low fill rate ({pct}%) in {filepath}"
                )
    except Exception as e:
        issues.append(f"output-quality: could not check {filepath}: {e}")
    return issues


def _check_json(filepath: str) -> list:
    issues = []
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read(1_000_000)
        data = json.loads(content)
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return []
        for key in data[0]:
            values = [r.get(key) for r in data]
            non_empty = [v for v in values if v is not None and str(v).strip()]
            if not non_empty:
                issues.append(
                    f"output-quality: key '{key}' is entirely null/empty in {filepath}"
                )
    except Exception:
        pass
    return issues


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    issues = []

    if tool == "Write":
        fp = tool_input.get("file_path", "")
        ext = Path(fp).suffix.lower() if fp else ""
        if ext == ".csv":
            issues = _check_csv(fp)
        elif ext in (".json", ".jsonl"):
            issues = _check_json(fp)

    elif tool == "Bash":
        cmd = tool_input.get("command", "")
        if any(kw in cmd for kw in SQLITE_KEYWORDS):
            issues.append(
                "output-quality: sqlite write detected — verify row counts and "
                "schema match expectations (manual check recommended)"
            )

    for issue in issues:
        _append_findings(issue)

    sys.exit(0)


if __name__ == "__main__":
    main()
