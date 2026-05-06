# Phase B — Hooks (Backstops) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 deterministic backstop hooks that enforce rules the conductor body previously relied on text-only discipline for, plus the state-reader library they all share.

**Architecture:** Each hook reads `.conductor/state.json` via a shared `lib/conductor_state.py` reader. All PreToolUse hooks start with a universal no-op guard (exit 0 if state.json absent — not a conductor session) and a user-global write blocker (exit 2 if target is under `~/.claude/`). Blocking hooks exit 2 with a clear stderr message; PostToolUse/Stop hooks are non-blocking (always exit 0, write findings.md). The install.sh canary tests every hook with synthetic stdin before declaring it installable.

**Tech Stack:** Python 3, subprocess (tests), pytest, bash (install.sh canary). No new dependencies beyond stdlib.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `lib/conductor_state.py` | **Create** | Read/migrate state.json; `validate_scaffold_delegate()` |
| `lib/lock_check.py` | **Modify** | Add `path_within_declaration(target, declared, base)` |
| `hooks/pre_phase0_readonly.py` | **Create** | Block Write/Edit/mutating-Bash in phase 0 |
| `hooks/pre_first_response_gate.py` | **Create** | Block mutations while gate == pre_first_response_proceed |
| `hooks/pre_busy_wait_block.py` | **Create** | Block busy-wait Bash patterns |
| `hooks/pre_lock_enforcement.py` | **Create** | Block out-of-declaration writes (tolerant pre-Phase-D) |
| `hooks/post_output_quality.py` | **Create** | Check CSV/JSON completeness; write findings.md (non-blocking) |
| `hooks/stop_validate_final_report.py` | **Create** | Verify FINAL_REPORT exists when phase==complete (non-blocking) |
| `tests/test_hooks_integration.py` | **Create** | Subprocess integration tests for all 6 hooks |
| `install.sh` | **Modify** | Add hook canary section; print settings.json snippet in next-steps |
| `project-conductor.md` | **Modify** | Add bundle 4 entry for the 6 new hooks (+~8 lines) |

---

## Task 1: Create `lib/conductor_state.py`

**Files:**
- Create: `lib/conductor_state.py`

- [ ] **Step 1: Write the failing test** (in a new file `tests/test_conductor_state.py`)

```python
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
import conductor_state

def make_state(tmpdir, fields):
    d = Path(tmpdir) / ".conductor"
    d.mkdir()
    (d / "state.json").write_text(json.dumps(fields))

def test_read_state_returns_none_when_absent(tmp_path):
    assert conductor_state.read_state(str(tmp_path)) is None

def test_read_state_returns_dict(tmp_path):
    make_state(tmp_path, {"phase": "1", "gate": "post_first_response_proceed"})
    s = conductor_state.read_state(str(tmp_path))
    assert s["phase"] == "1"
    assert s["gate"] == "post_first_response_proceed"

def test_get_phase_returns_none_when_absent(tmp_path):
    assert conductor_state.get_phase(str(tmp_path)) is None

def test_get_phase_returns_value(tmp_path):
    make_state(tmp_path, {"phase": "0"})
    assert conductor_state.get_phase(str(tmp_path)) == "0"

def test_get_gate_returns_value(tmp_path):
    make_state(tmp_path, {"phase": "1", "gate": "pre_first_response_proceed"})
    assert conductor_state.get_gate(str(tmp_path)) == "pre_first_response_proceed"

def test_migrate_adds_gate_and_scaffold_written(tmp_path):
    make_state(tmp_path, {"phase": "2"})
    conductor_state.migrate_state_if_needed(str(tmp_path))
    s = conductor_state.read_state(str(tmp_path))
    assert "gate" in s
    assert "scaffold_written" in s
    assert s["gate"] == "post_first_response_proceed"
    assert s["scaffold_written"] is False

def test_migrate_is_idempotent(tmp_path):
    make_state(tmp_path, {"phase": "2", "gate": "my_gate", "scaffold_written": True})
    conductor_state.migrate_state_if_needed(str(tmp_path))
    s = conductor_state.read_state(str(tmp_path))
    assert s["gate"] == "my_gate"
    assert s["scaffold_written"] is True

def test_validate_scaffold_delegate_pass():
    fm = {"skills": ["conductor-scaffold-ai-director-os"], "tools": ["Read", "Write", "Edit", "Bash"]}
    assert conductor_state.validate_scaffold_delegate(fm) is True

def test_validate_scaffold_delegate_missing_skill():
    fm = {"skills": [], "tools": ["Read", "Write", "Edit", "Bash"]}
    assert conductor_state.validate_scaffold_delegate(fm) is False

def test_validate_scaffold_delegate_missing_tool():
    fm = {"skills": ["conductor-scaffold-ai-director-os"], "tools": ["Read", "Write", "Edit"]}
    assert conductor_state.validate_scaffold_delegate(fm) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_conductor_state.py -v
```
Expected: ImportError or ModuleNotFoundError (`No module named 'conductor_state'`)

- [ ] **Step 3: Write `lib/conductor_state.py`**

```python
import json
import os
import shutil
from pathlib import Path


def read_state(cwd=None):
    """Read .conductor/state.json. Returns dict or None if absent/invalid."""
    if cwd is None:
        cwd = os.getcwd()
    path = Path(cwd) / ".conductor" / "state.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def get_phase(cwd=None):
    s = read_state(cwd)
    return s.get("phase") if s else None


def get_gate(cwd=None):
    s = read_state(cwd)
    return s.get("gate") if s else None


def migrate_state_if_needed(cwd=None):
    """Add gate and scaffold_written to state.json if absent (v4.1→v5 migration).

    Creates a .v4.1.bak backup before modifying. Safe to call on every startup.
    """
    if cwd is None:
        cwd = os.getcwd()
    path = Path(cwd) / ".conductor" / "state.json"
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    needs_migration = "gate" not in state or "scaffold_written" not in state
    if not needs_migration:
        return

    bak = path.with_suffix(".json.v4.1.bak")
    if not bak.exists():
        shutil.copy2(path, bak)

    state.setdefault("gate", "post_first_response_proceed")
    state.setdefault("scaffold_written", False)

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def validate_scaffold_delegate(frontmatter: dict) -> bool:
    """Return True if agent frontmatter qualifies as a scaffold delegate.

    Requires: skills includes conductor-scaffold-ai-director-os AND
    tools includes all of Read, Write, Edit, Bash.
    """
    skills = frontmatter.get("skills", [])
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",")]
    tools = frontmatter.get("tools", [])
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",")]

    has_skill = "conductor-scaffold-ai-director-os" in skills
    has_tools = {"Read", "Write", "Edit", "Bash"}.issubset(set(tools))
    return has_skill and has_tools
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_conductor_state.py -v
```
Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/conductor_state.py tests/test_conductor_state.py
git commit -m "feat(phase-b): add conductor_state.py — state reader, migration, scaffold validation"
```

---

## Task 2: Add `path_within_declaration` to `lib/lock_check.py`

**Files:**
- Modify: `lib/lock_check.py` (insert after imports, before `SCHEMA_VERSION`)
- Create: `tests/test_lock_check_path.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from lock_check import path_within_declaration

def test_exact_match(tmp_path):
    f = tmp_path / "src" / "app.py"
    d = tmp_path / "src"
    assert path_within_declaration(str(f), str(d), str(tmp_path)) is True

def test_deep_nesting(tmp_path):
    f = tmp_path / "src" / "api" / "routes" / "user.ts"
    d = tmp_path / "src" / "api"
    assert path_within_declaration(str(f), str(d), str(tmp_path)) is True

def test_regression_api_vs_api_keys(tmp_path):
    # src/api must NOT match src/api-keys/secrets.ts
    f = tmp_path / "src" / "api-keys" / "secrets.ts"
    d = tmp_path / "src" / "api"
    assert path_within_declaration(str(f), str(d), str(tmp_path)) is False

def test_sibling_dir_not_matched(tmp_path):
    f = tmp_path / "tests" / "test_routes.py"
    d = tmp_path / "src"
    assert path_within_declaration(str(f), str(d), str(tmp_path)) is False

def test_declared_equals_target(tmp_path):
    f = tmp_path / "src" / "app.py"
    assert path_within_declaration(str(f), str(f), str(tmp_path)) is True

def test_relative_paths_resolved(tmp_path):
    # Relative declared path resolved against base
    f = tmp_path / "src" / "api" / "user.ts"
    assert path_within_declaration(str(f), "src/api", str(tmp_path)) is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_lock_check_path.py -v
```
Expected: ImportError (`cannot import name 'path_within_declaration'`)

- [ ] **Step 3: Insert `path_within_declaration` into `lib/lock_check.py`**

Insert the following block after the imports section (after `from pathlib import Path`, before `SCHEMA_VERSION = 1`):

```python
def path_within_declaration(target: str, declared: str, base: str = None) -> bool:
    """True if target is at or inside the declared path using segment-exact prefix match.

    Regression: src/api does NOT match src/api-keys/secrets.ts — the api-keys segment
    differs from api at position 3, so the check correctly returns False.

    Args:
        target: absolute or relative path being written
        declared: path from files_write[] (absolute or relative)
        base: directory for resolving relative paths (default: cwd)
    """
    if base is None:
        base = os.getcwd()
    base_p = Path(base)

    t_p = Path(target) if Path(target).is_absolute() else base_p / target
    d_p = Path(declared) if Path(declared).is_absolute() else base_p / declared

    try:
        t_parts = t_p.resolve().parts
        d_parts = d_p.resolve().parts
    except Exception:
        return False

    return len(d_parts) <= len(t_parts) and t_parts[: len(d_parts)] == d_parts
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_lock_check_path.py -v
```
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/lock_check.py tests/test_lock_check_path.py
git commit -m "feat(phase-b): add path_within_declaration to lock_check.py"
```

---

## Task 3: Create `hooks/pre_phase0_readonly.py`

**Files:**
- Create: `hooks/pre_phase0_readonly.py`

This hook fires on Write/Edit/Bash. Two enforcements:
1. **Always** (regardless of phase): user-global write blocker — exit 2 if target resolves under `~/.claude/`.
2. **Phase 0 only**: block Write/Edit outside `.conductor/**`; block Bash not in read-only allowlist.

- [ ] **Step 1: Write the hook**

```python
#!/usr/bin/env python3
# This regex/prefix check catches the common cases. It will NOT catch `bash -c '…'`,
# aliases, double-spaced commands, or chained `cd && rm`. Truth is
# .conductor/state.json + the conductor's own discipline. The hook is a safety net,
# not a fence.

import json
import os
import sys
from pathlib import Path

# --- Universal no-op guard ---
state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

USER_GLOBAL = str(Path.home() / ".claude")

BASH_READONLY_PREFIXES = (
    "ls", "find", "cat", "head", "tail", "grep", "rg", "ag",
    "git status", "git diff", "git log", "git branch", "git show",
    "git ls-files", "git rev-parse", "git stash list",
    "which", "type", "echo", "printf", "wc", "jq", "stat",
    "python3 lib/lock_check", "python3 -c",
)


def _is_bash_allowed(cmd: str) -> bool:
    s = cmd.strip()
    for prefix in BASH_READONLY_PREFIXES:
        if s == prefix or s.startswith(prefix + " ") or s.startswith(prefix + "\n"):
            return True
    return False


def _block(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    target = tool_input.get("file_path", "")

    # User-global write blocker — applies regardless of phase
    if target:
        try:
            resolved = str(Path(target).resolve())
            ug = USER_GLOBAL
            if resolved == ug or resolved.startswith(ug + os.sep):
                _block(
                    "refusing to write under ~/.claude/ — "
                    "user-global is read-only at runtime per §3.1"
                )
        except Exception:
            pass

    # Phase 0 enforcement
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        sys.exit(0)

    if state.get("phase") != "0":
        sys.exit(0)

    conductor_dir = str(Path(os.getcwd()) / ".conductor")

    if tool in ("Write", "Edit"):
        if not target:
            sys.exit(0)
        resolved_target = str(Path(target).resolve())
        resolved_cdir = str(Path(conductor_dir).resolve())
        if not (resolved_target == resolved_cdir
                or resolved_target.startswith(resolved_cdir + os.sep)):
            _block(
                f"🚧 Phase 0 is READ-ONLY — Write/Edit outside .conductor/ is blocked "
                f"(target: {target}). Phase 0 is environment discovery only."
            )

    if tool == "Bash":
        cmd = tool_input.get("command", "")
        if not _is_bash_allowed(cmd):
            _block(
                f"🚧 Phase 0 is READ-ONLY — Bash command not in read-only allowlist "
                f"(command: {cmd[:120]!r}). Use Read/Grep/Glob for discovery."
            )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x hooks/pre_phase0_readonly.py
```

- [ ] **Step 3: Smoke-test manually**

```bash
# No-op guard (no state.json in cwd): should exit 0
echo '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' \
  | python3 hooks/pre_phase0_readonly.py; echo "exit: $?"
# Expected: exit: 0
```

- [ ] **Step 4: Commit**

```bash
git add hooks/pre_phase0_readonly.py
git commit -m "feat(phase-b): add pre_phase0_readonly hook"
```

---

## Task 4: Create `hooks/pre_first_response_gate.py`

**Files:**
- Create: `hooks/pre_first_response_gate.py`

Blocks Write (outside .conductor), ALL Edit, ALL Task, and mutating Bash while `gate == "pre_first_response_proceed"`.

- [ ] **Step 1: Write the hook**

```python
#!/usr/bin/env python3
# This regex catches the common mutating patterns. It will NOT catch all possible
# shell constructs. The hook is a safety net, not a fence.

import json
import os
import sys
from pathlib import Path

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

USER_GLOBAL = str(Path.home() / ".claude")

MUTATING_BASH_FRAGMENTS = (
    "mkdir", "touch ", "rm ", "cp ", "mv ", "pip install",
    "npm install", "pnpm install", "yarn install", "playwright install",
    "git add", "git commit", "git push", "git checkout",
    "curl ", "wget ", "tee ",
)


def _is_mutating_bash(cmd: str) -> bool:
    for frag in MUTATING_BASH_FRAGMENTS:
        if frag in cmd:
            return True
    return False


def _block(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    target = tool_input.get("file_path", "")

    # User-global write blocker — always
    if target:
        try:
            resolved = str(Path(target).resolve())
            ug = USER_GLOBAL
            if resolved == ug or resolved.startswith(ug + os.sep):
                _block(
                    "refusing to write under ~/.claude/ — "
                    "user-global is read-only at runtime per §3.1"
                )
        except Exception:
            pass

    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        sys.exit(0)

    if state.get("gate") != "pre_first_response_proceed":
        sys.exit(0)

    conductor_dir = str(Path(os.getcwd()) / ".conductor")
    gate_msg = (
        "🛑 HARD GATE — waiting for user to reply 'proceed' before execution begins. "
        "This overrides accept-edits mode."
    )

    if tool == "Write":
        if target:
            resolved_target = str(Path(target).resolve())
            resolved_cdir = str(Path(conductor_dir).resolve())
            if not (resolved_target == resolved_cdir
                    or resolved_target.startswith(resolved_cdir + os.sep)):
                _block(f"{gate_msg} (Write outside .conductor/ blocked)")

    elif tool == "Edit":
        _block(f"{gate_msg} (Edit blocked)")

    elif tool == "Task":
        _block(f"{gate_msg} (Task dispatch blocked)")

    elif tool == "Bash":
        cmd = tool_input.get("command", "")
        if _is_mutating_bash(cmd):
            _block(f"{gate_msg} (mutating Bash blocked: {cmd[:80]!r})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x hooks/pre_first_response_gate.py
```

- [ ] **Step 3: Commit**

```bash
git add hooks/pre_first_response_gate.py
git commit -m "feat(phase-b): add pre_first_response_gate hook"
```

---

## Task 5: Create `hooks/pre_busy_wait_block.py`

**Files:**
- Create: `hooks/pre_busy_wait_block.py`

Blocks Bash busy-wait patterns: `until ... do sleep N; done`, `while ... do sleep N; done`, leading `sleep NNN` (3+ digit seconds).

- [ ] **Step 1: Write the hook**

```python
#!/usr/bin/env python3
# This regex catches the common busy-wait forms. It will NOT catch `bash -c '…'`,
# aliases, or creatively split commands. The hook is a safety net, not a fence.

import json
import os
import re
import sys

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

_BUSY_WAIT = [
    re.compile(r"until\s+.+?;\s*do\s+sleep\s+\d+", re.DOTALL),
    re.compile(r"while\s+.+?;\s*do\s+sleep\s+\d+", re.DOTALL),
    re.compile(r"^\s*sleep\s+\d{3,}", re.MULTILINE),
]


def _is_busy_wait(cmd: str) -> bool:
    return any(p.search(cmd) for p in _BUSY_WAIT)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    cmd = data.get("tool_input", {}).get("command", "")
    if _is_busy_wait(cmd):
        sys.stderr.write(
            "🚫 Forbidden busy-wait pattern — use ScheduleWakeup (time-based) or "
            "file-mtime polling (event-based) instead of sleep loops.\n"
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x hooks/pre_busy_wait_block.py
```

- [ ] **Step 3: Commit**

```bash
git add hooks/pre_busy_wait_block.py
git commit -m "feat(phase-b): add pre_busy_wait_block hook"
```

---

## Task 6: Create `hooks/pre_lock_enforcement.py`

**Files:**
- Create: `hooks/pre_lock_enforcement.py`

Blocks Write/Edit to paths not in `active-task.json::files_write[]`. **Tolerant fallback (pre-Phase-D):** if active-task.json missing or `files_write` absent/empty, exit 0 and write ONE findings.md row per session.

- [ ] **Step 1: Write the hook**

```python
#!/usr/bin/env python3
# This path check catches the common cases using segment-exact prefix matching.
# It will NOT catch all possible write paths (symlinks, /proc, etc.).
# The hook is a safety net, not a fence.

import json
import os
import sys
from pathlib import Path

REPO_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
sys.path.insert(0, REPO_LIB)
from lock_check import path_within_declaration  # noqa: E402

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

USER_GLOBAL = str(Path.home() / ".claude")
ACTIVE_TASK_PATH = os.path.join(os.getcwd(), ".conductor", "locks", "active-task.json")
FINDINGS_PATH = os.path.join(os.getcwd(), ".conductor", "findings.md")
FALLBACK_MARKER = os.path.join(os.getcwd(), ".conductor", ".lock_enforcement_fallback_logged")


def _append_findings(msg: str) -> None:
    try:
        with open(FINDINGS_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _block(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit"):
        sys.exit(0)

    target = data.get("tool_input", {}).get("file_path", "")

    # User-global write blocker — always
    if target:
        try:
            resolved = str(Path(target).resolve())
            ug = USER_GLOBAL
            if resolved == ug or resolved.startswith(ug + os.sep):
                _block(
                    "refusing to write under ~/.claude/ — "
                    "user-global is read-only at runtime per §3.1"
                )
        except Exception:
            pass

    # Read active-task.json
    active_task = None
    if os.path.exists(ACTIVE_TASK_PATH):
        try:
            with open(ACTIVE_TASK_PATH, encoding="utf-8") as f:
                active_task = json.load(f)
        except Exception:
            pass

    files_write = active_task.get("files_write", []) if active_task else []

    # Tolerant fallback: no declaration available yet (pre-Phase-D)
    if not files_write:
        if not os.path.exists(FALLBACK_MARKER):
            _append_findings(
                "pre_lock_enforcement: no active-task.json::files_write[] yet "
                "(pre-Phase-D); not enforcing this session"
            )
            try:
                open(FALLBACK_MARKER, "w").close()
            except Exception:
                pass
        sys.exit(0)

    if not target:
        sys.exit(0)

    cwd = os.getcwd()
    for declared in files_write:
        if path_within_declaration(target, declared, cwd):
            sys.exit(0)

    _block(
        f"🔒 Lock violation — {target!r} is outside the declared files_write set "
        f"for the active task. Declared: {files_write}. "
        "Log the deviation and surface to user before continuing."
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x hooks/pre_lock_enforcement.py
```

- [ ] **Step 3: Commit**

```bash
git add hooks/pre_lock_enforcement.py
git commit -m "feat(phase-b): add pre_lock_enforcement hook with pre-Phase-D tolerant fallback"
```

---

## Task 7: Create `hooks/post_output_quality.py`

**Files:**
- Create: `hooks/post_output_quality.py`

PostToolUse hook. Non-blocking (always exit 0). Checks CSV/JSON files for empty columns. Appends findings to `.conductor/findings.md`.

- [ ] **Step 1: Write the hook**

```python
#!/usr/bin/env python3

import csv
import io
import json
import os
import sys
from pathlib import Path

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

FINDINGS_PATH = os.path.join(os.getcwd(), ".conductor", "findings.md")

WATCHED_EXTENSIONS = {".csv", ".json", ".jsonl", ".parquet", ".xlsx"}

SQLITE_KEYWORDS = ("sqlite3", "INSERT INTO", "CREATE TABLE", ".import")


def _append_findings(msg: str) -> None:
    try:
        with open(FINDINGS_PATH, "a", encoding="utf-8") as f:
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
        for col in (rows[0].keys() if rows else []):
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
            content = f.read(1_000_000)  # cap at 1 MB
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
        # parquet/xlsx: skip gracefully (require third-party libs)

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
```

- [ ] **Step 2: Make executable**

```bash
chmod +x hooks/post_output_quality.py
```

- [ ] **Step 3: Commit**

```bash
git add hooks/post_output_quality.py
git commit -m "feat(phase-b): add post_output_quality hook"
```

---

## Task 8: Create `hooks/stop_validate_final_report.py`

**Files:**
- Create: `hooks/stop_validate_final_report.py`

Stop hook. Non-blocking (always exit 0). When `phase == "complete"`, checks that FINAL_REPORT.md exists and has required sections. Writes findings.md row if incomplete.

- [ ] **Step 1: Write the hook**

```python
#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

state_path = os.path.join(os.getcwd(), ".conductor", "state.json")
if not os.path.exists(state_path):
    sys.exit(0)

FINDINGS_PATH = os.path.join(os.getcwd(), ".conductor", "findings.md")

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

REPORT_CANDIDATES = [
    os.path.join(os.getcwd(), "FINAL_REPORT.md"),
    os.path.join(os.getcwd(), ".conductor", "FINAL_REPORT.md"),
]


def _append_findings(msg: str) -> None:
    try:
        with open(FINDINGS_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main():
    # stdin can be ignored for Stop hooks; we only need state.json
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

    # Find the report
    report_path = None
    for candidate in REPORT_CANDIDATES:
        if os.path.exists(candidate):
            report_path = candidate
            break

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
```

- [ ] **Step 2: Make executable**

```bash
chmod +x hooks/stop_validate_final_report.py
```

- [ ] **Step 3: Commit**

```bash
git add hooks/stop_validate_final_report.py
git commit -m "feat(phase-b): add stop_validate_final_report hook"
```

---

## Task 9: Create `tests/test_hooks_integration.py`

**Files:**
- Create: `tests/test_hooks_integration.py`

Subprocess integration tests: every hook with allow-case (exit 0) and block-case (exit 2 for PreToolUse). Plus user-global write blocker, universal no-op guard, and tolerant fallback.

- [ ] **Step 1: Write the test file**

```python
"""Integration tests for Phase B hooks.

Each test runs the hook script via subprocess from a temp directory
that either has or lacks .conductor/state.json, simulating real invocations.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
PYTHON = sys.executable


def run_hook(hook_name: str, stdin_data: dict, state: dict = None,
             active_task: dict = None) -> subprocess.CompletedProcess:
    """Run hook_name from a temp dir; optionally seed .conductor/state.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        if state is not None:
            conductor_dir = Path(tmpdir) / ".conductor"
            conductor_dir.mkdir()
            (conductor_dir / "state.json").write_text(json.dumps(state))
            if active_task is not None:
                locks_dir = conductor_dir / "locks"
                locks_dir.mkdir()
                (locks_dir / "active-task.json").write_text(json.dumps(active_task))

        return subprocess.run(
            [PYTHON, str(HOOKS_DIR / hook_name)],
            input=json.dumps(stdin_data),
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )


# ---------------------------------------------------------------------------
# Universal no-op guard — all 6 hooks must exit 0 when state.json absent
# ---------------------------------------------------------------------------

HOOK_NAMES = [
    "pre_phase0_readonly.py",
    "pre_first_response_gate.py",
    "pre_busy_wait_block.py",
    "pre_lock_enforcement.py",
    "post_output_quality.py",
    "stop_validate_final_report.py",
]


def test_noop_guard_all_hooks_exit_0_when_no_state_json():
    payload = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x.py"}}
    for hook in HOOK_NAMES:
        r = run_hook(hook, payload, state=None)
        assert r.returncode == 0, f"{hook} should exit 0 (no-op) when state.json absent, got {r.returncode}\nstderr: {r.stderr}"


# ---------------------------------------------------------------------------
# User-global write blocker — all Write|Edit PreToolUse hooks
# ---------------------------------------------------------------------------

USER_GLOBAL_TARGET = str(Path.home() / ".claude" / "skills" / "foo.md")

PRETOOLUSE_WRITE_HOOKS = [
    "pre_phase0_readonly.py",
    "pre_first_response_gate.py",
    "pre_lock_enforcement.py",
]


def test_user_global_write_blocker():
    state = {"phase": "1", "gate": "post_first_response_proceed"}
    payload = {"tool_name": "Write", "tool_input": {"file_path": USER_GLOBAL_TARGET}}
    for hook in PRETOOLUSE_WRITE_HOOKS:
        r = run_hook(hook, payload, state=state)
        assert r.returncode == 2, (
            f"{hook} must exit 2 for ~/.claude/ target, got {r.returncode}\nstderr: {r.stderr}"
        )
        assert "refusing to write under ~/.claude/" in r.stderr, (
            f"{hook} must emit canonical stderr for ~/.claude/ block\nstderr: {r.stderr}"
        )


# ---------------------------------------------------------------------------
# pre_phase0_readonly
# ---------------------------------------------------------------------------

def test_pre_phase0_readonly_allows_write_in_phase1():
    state = {"phase": "1", "gate": "post_first_response_proceed"}
    r = run_hook("pre_phase0_readonly.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 0

def test_pre_phase0_readonly_blocks_write_outside_conductor_in_phase0():
    state = {"phase": "0", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_phase0_readonly.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 2
    assert "Phase 0 is READ-ONLY" in r.stderr

def test_pre_phase0_readonly_allows_write_to_conductor_dir_in_phase0(tmp_path):
    state = {"phase": "0", "gate": "pre_first_response_proceed"}
    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    target = str(conductor_dir / "findings.md")
    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "pre_phase0_readonly.py")],
        input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": target}}),
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0

def test_pre_phase0_readonly_blocks_mutating_bash_in_phase0():
    state = {"phase": "0", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_phase0_readonly.py",
                 {"tool_name": "Bash", "tool_input": {"command": "git add src/app.py"}},
                 state=state)
    assert r.returncode == 2
    assert "READ-ONLY" in r.stderr

def test_pre_phase0_readonly_allows_readonly_bash_in_phase0():
    state = {"phase": "0", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_phase0_readonly.py",
                 {"tool_name": "Bash", "tool_input": {"command": "git status"}},
                 state=state)
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# pre_first_response_gate
# ---------------------------------------------------------------------------

def test_first_response_gate_allows_when_gate_open():
    state = {"phase": "1", "gate": "post_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 0

def test_first_response_gate_blocks_write_outside_conductor():
    state = {"phase": "1", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 2
    assert "HARD GATE" in r.stderr

def test_first_response_gate_blocks_edit():
    state = {"phase": "1", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 2

def test_first_response_gate_blocks_task():
    state = {"phase": "1", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Task", "tool_input": {"description": "do something"}},
                 state=state)
    assert r.returncode == 2

def test_first_response_gate_blocks_mutating_bash():
    state = {"phase": "1", "gate": "pre_first_response_proceed"}
    r = run_hook("pre_first_response_gate.py",
                 {"tool_name": "Bash", "tool_input": {"command": "npm install"}},
                 state=state)
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# pre_busy_wait_block
# ---------------------------------------------------------------------------

def test_busy_wait_allows_normal_bash():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
                 state=state)
    assert r.returncode == 0

def test_busy_wait_blocks_until_sleep():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash",
                  "tool_input": {"command": "until check; do sleep 5; done"}},
                 state=state)
    assert r.returncode == 2
    assert "busy-wait" in r.stderr.lower()

def test_busy_wait_blocks_while_sleep():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash",
                  "tool_input": {"command": "while true; do sleep 30; done"}},
                 state=state)
    assert r.returncode == 2

def test_busy_wait_blocks_leading_long_sleep():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash", "tool_input": {"command": "sleep 300"}},
                 state=state)
    assert r.returncode == 2

def test_busy_wait_allows_short_sleep():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_busy_wait_block.py",
                 {"tool_name": "Bash", "tool_input": {"command": "sleep 5"}},
                 state=state)
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# pre_lock_enforcement
# ---------------------------------------------------------------------------

def test_lock_enforcement_tolerant_fallback_when_no_active_task():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("pre_lock_enforcement.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/anything.py"}},
                 state=state)
    # Tolerant fallback: allow, just log
    assert r.returncode == 0

def test_lock_enforcement_allows_declared_path(tmp_path):
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    active_task = {"task_id": "t1", "files_write": [str(tmp_path / "src")]}
    target = str(tmp_path / "src" / "app.py")

    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    locks_dir = conductor_dir / "locks"
    locks_dir.mkdir()
    (locks_dir / "active-task.json").write_text(json.dumps(active_task))

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "pre_lock_enforcement.py")],
        input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": target}}),
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0

def test_lock_enforcement_blocks_undeclared_path(tmp_path):
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    active_task = {"task_id": "t1", "files_write": [str(tmp_path / "src")]}
    target = str(tmp_path / "config" / "secret.env")

    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    locks_dir = conductor_dir / "locks"
    locks_dir.mkdir()
    (locks_dir / "active-task.json").write_text(json.dumps(active_task))

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "pre_lock_enforcement.py")],
        input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": target}}),
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 2
    assert "Lock violation" in r.stderr


# ---------------------------------------------------------------------------
# post_output_quality
# ---------------------------------------------------------------------------

def test_output_quality_allows_non_structured_file():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("post_output_quality.py",
                 {"tool_name": "Write", "tool_input": {"file_path": "/tmp/app.py"}},
                 state=state)
    assert r.returncode == 0

def test_output_quality_writes_finding_for_empty_csv_column(tmp_path):
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    csv_path = tmp_path / "output.csv"
    csv_path.write_text("name,age,email\nAlice,30,\nBob,25,\n")

    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "post_output_quality.py")],
        input=json.dumps({"tool_name": "Write",
                          "tool_input": {"file_path": str(csv_path)}}),
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0  # non-blocking
    findings = (conductor_dir / "findings.md").read_text()
    assert "email" in findings
    assert "empty" in findings.lower()


# ---------------------------------------------------------------------------
# stop_validate_final_report
# ---------------------------------------------------------------------------

def test_stop_validator_noop_when_phase_not_complete():
    state = {"phase": "2", "gate": "post_first_response_proceed"}
    r = run_hook("stop_validate_final_report.py", {}, state=state)
    assert r.returncode == 0

def test_stop_validator_writes_finding_when_report_missing(tmp_path):
    state = {"phase": "complete", "gate": "post_first_response_proceed"}
    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "stop_validate_final_report.py")],
        input="{}",
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    findings = (conductor_dir / "findings.md").read_text()
    assert "FINAL_REPORT.md not found" in findings

def test_stop_validator_writes_finding_when_sections_missing(tmp_path):
    state = {"phase": "complete", "gate": "post_first_response_proceed"}
    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    # Write a report missing most required sections
    (tmp_path / "FINAL_REPORT.md").write_text("# Report\n\n## Summary\nDone.\n")

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "stop_validate_final_report.py")],
        input="{}",
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    findings = (conductor_dir / "findings.md").read_text()
    assert "missing sections" in findings

def test_stop_validator_passes_complete_report(tmp_path):
    state = {"phase": "complete", "gate": "post_first_response_proceed"}
    conductor_dir = tmp_path / ".conductor"
    conductor_dir.mkdir()
    (conductor_dir / "state.json").write_text(json.dumps(state))
    (tmp_path / "FINAL_REPORT.md").write_text(
        "# Report\n## Executive Summary\n## Plan vs Actual\n"
        "## Material Changes Log\n## Routing Notes\n## Safety Mechanism Outcomes\n"
        "## Surgical Debug Map\n## Outstanding Items\n## Evidence Index\n"
        "## Recommended Next Steps\n"
    )

    r = subprocess.run(
        [PYTHON, str(HOOKS_DIR / "stop_validate_final_report.py")],
        input="{}",
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0
    findings_path = conductor_dir / "findings.md"
    # No findings written for complete report
    assert not findings_path.exists() or "missing sections" not in findings_path.read_text()
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_hooks_integration.py -v
```
Expected: All tests PASS (or PASS with any previously-failing tests for hooks already written)

- [ ] **Step 3: Commit**

```bash
git add tests/test_hooks_integration.py
git commit -m "feat(phase-b): add integration tests for all 6 hooks"
```

---

## Task 10: Add hook canary to `install.sh`

**Files:**
- Modify: `install.sh` (append before the final `Done` block)

The canary runs each hook from a temp dir with synthetic state and stdin. `CANARY_PASS`/`CANARY_FAIL` counters. Failures print a warning but do not abort install.

- [ ] **Step 1: Read install.sh to find the insertion point**

The canary section inserts between `Step 5 — Install skills` and the final `Done` block. Find the line with `# ---- Done ----` (or `printf "\n"` just before the success banner).

- [ ] **Step 2: Insert canary section into install.sh**

Insert the following block immediately before the final `printf "\n"  printf "  +--------..."` banner (around line 377):

```bash
# ---------------------------------------------------------------------------
# Step 6 — Hook canary (Phase B)
# ---------------------------------------------------------------------------
if [[ -d "$REPO_ROOT/hooks" ]]; then
  header "Hook canary"

  CANARY_PASS=0
  CANARY_FAIL=0
  CANARY_TMP="$(mktemp -d)"
  trap 'rm -rf "$CANARY_TMP"' EXIT

  _canary() {
    local hook_file="$1"
    local case_label="$2"
    local state_json="$3"
    local stdin_json="$4"
    local expected_exit="$5"

    mkdir -p "$CANARY_TMP/.conductor"
    if [[ -n "$state_json" ]]; then
      printf '%s' "$state_json" > "$CANARY_TMP/.conductor/state.json"
    else
      rm -f "$CANARY_TMP/.conductor/state.json"
    fi

    actual_exit=0
    (cd "$CANARY_TMP" && printf '%s' "$stdin_json" \
      | python3 "$hook_file" >/dev/null 2>&1) || actual_exit=$?

    if [[ "$actual_exit" -eq "$expected_exit" ]]; then
      CANARY_PASS=$((CANARY_PASS + 1))
    else
      warn "Canary FAIL: $(basename "$hook_file") ($case_label): expected exit $expected_exit, got $actual_exit"
      CANARY_FAIL=$((CANARY_FAIL + 1))
    fi
  }

  # pre_phase0_readonly
  HOOK="$REPO_ROOT/hooks/pre_phase0_readonly.py"
  if [[ -f "$HOOK" ]]; then
    _canary "$HOOK" "no-op (no state.json)" "" \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$HOOK" "allow (phase=1)" \
      '{"phase":"1","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$HOOK" "block write in phase=0" \
      '{"phase":"0","gate":"pre_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 2
  fi

  # pre_first_response_gate
  HOOK="$REPO_ROOT/hooks/pre_first_response_gate.py"
  if [[ -f "$HOOK" ]]; then
    _canary "$HOOK" "no-op (no state.json)" "" \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$HOOK" "allow (gate open)" \
      '{"phase":"1","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$HOOK" "block Edit (gate=pre_first_response_proceed)" \
      '{"phase":"1","gate":"pre_first_response_proceed"}' \
      '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/x.py"}}' 2
  fi

  # pre_busy_wait_block
  HOOK="$REPO_ROOT/hooks/pre_busy_wait_block.py"
  if [[ -f "$HOOK" ]]; then
    _canary "$HOOK" "no-op (no state.json)" "" \
      '{"tool_name":"Bash","tool_input":{"command":"ls"}}' 0
    _canary "$HOOK" "allow normal bash" \
      '{"phase":"2","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' 0
    _canary "$HOOK" "block busy-wait" \
      '{"phase":"2","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Bash","tool_input":{"command":"until check; do sleep 5; done"}}' 2
  fi

  # pre_lock_enforcement
  HOOK="$REPO_ROOT/hooks/pre_lock_enforcement.py"
  if [[ -f "$HOOK" ]]; then
    _canary "$HOOK" "no-op (no state.json)" "" \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$HOOK" "tolerant fallback (no active-task.json)" \
      '{"phase":"2","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
  fi

  # post_output_quality
  HOOK="$REPO_ROOT/hooks/post_output_quality.py"
  if [[ -f "$HOOK" ]]; then
    _canary "$HOOK" "no-op (no state.json)" "" \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$HOOK" "allow non-structured file" \
      '{"phase":"2","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
  fi

  # stop_validate_final_report
  HOOK="$REPO_ROOT/hooks/stop_validate_final_report.py"
  if [[ -f "$HOOK" ]]; then
    _canary "$HOOK" "no-op (no state.json)" "" '{}' 0
    _canary "$HOOK" "no-op (phase!=complete)" \
      '{"phase":"2","gate":"post_first_response_proceed"}' '{}' 0
  fi

  if [[ "$CANARY_FAIL" -gt 0 ]]; then
    warn "$CANARY_FAIL hook canary case(s) failed — hooks may not work correctly on this system."
  else
    ok "Hook canary: $CANARY_PASS/$CANARY_PASS cases passed."
  fi
fi
```

- [ ] **Step 3: Verify install.sh syntax**

```bash
bash -n install.sh
```
Expected: no output (syntax OK)

- [ ] **Step 4: Run install.sh in dry-run mode to see canary output**

```bash
./install.sh --help
```
Expected: no errors

- [ ] **Step 5: Verify boundary test still passes**

```bash
python3 -m pytest tests/test_user_global_readonly.py -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add install.sh
git commit -m "feat(phase-b): add hook canary section to install.sh"
```

---

## Task 11: Add Phase B hooks as bundle 4 in `project-conductor.md`

**Files:**
- Modify: `project-conductor.md` (Optional Bundles Offer section only, ~+8 lines)

This surfaces the 6 new hooks to users so they can install and activate them.

- [ ] **Step 1: Find the insertion point**

In `project-conductor.md`, find the Optional Bundles Offer section. It ends with:

```
**(3) hooks/usage_limit_wakeup.py** — auto-resume after API rate / usage limit via ScheduleWakeup
```

- [ ] **Step 2: Insert bundle 4 after bundle 3**

Replace the closing ``` ``` ` of the Optional Bundles markdown block (after `ScheduleWakeup`) with:

```
**(4) Phase B backstop hooks** — 6 hooks that convert text-only rules to deterministic enforcement: Phase 0 read-only guard, First Response hard gate, busy-wait blocker, lock enforcement (tolerant until Phase D), output-quality checker, FINAL_REPORT validator. Wire into `.claude/settings.json` on install.
```

And update the install command line from:
```
**Install:** `install 1,2,3 from /path/to/TheConductor` (or any subset), or `skip bundles`.
```
to:
```
**Install:** `install 1,2,3,4 from /path/to/TheConductor` (or any subset), or `skip bundles`.
```

The settings.json block the conductor writes on `install 4` registration:
```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Write|Edit|Bash", "hooks": [{"type": "command", "command": "python3 /path/to/TheConductor/hooks/pre_phase0_readonly.py"}]},
      {"matcher": "Write|Edit|Task|Bash", "hooks": [{"type": "command", "command": "python3 /path/to/TheConductor/hooks/pre_first_response_gate.py"}]},
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 /path/to/TheConductor/hooks/pre_busy_wait_block.py"}]},
      {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "python3 /path/to/TheConductor/hooks/pre_lock_enforcement.py"}]}
    ],
    "PostToolUse": [
      {"matcher": "Write|Bash", "hooks": [{"type": "command", "command": "python3 /path/to/TheConductor/hooks/post_output_quality.py"}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "python3 /path/to/TheConductor/hooks/stop_validate_final_report.py"}]}
    ]
  }
}
```

Add this settings.json block to `project-conductor.md` **inside the Optional Bundles Offer code block** (after bundle 4's description).

- [ ] **Step 3: Verify line count stays under 500**

```bash
wc -l project-conductor.md
```
Expected: ≤ 500

- [ ] **Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -v
```
Expected: all tests pass (including existing smoke + boundary tests)

- [ ] **Step 5: Commit**

```bash
git add project-conductor.md
git commit -m "feat(phase-b): surface Phase B hooks as bundle 4 in Optional Bundles Offer"
```

---

## Final verification

- [ ] **Run full test suite and check line count**

```bash
python3 -m pytest tests/ -v && wc -l project-conductor.md
```
Expected: all tests pass, `project-conductor.md` line count ≤ 500

- [ ] **Run install.sh syntax check**

```bash
bash -n install.sh
```
Expected: no output

- [ ] **List all 6 new hooks exist**

```bash
ls hooks/pre_phase0_readonly.py hooks/pre_first_response_gate.py \
   hooks/pre_busy_wait_block.py hooks/pre_lock_enforcement.py \
   hooks/post_output_quality.py hooks/stop_validate_final_report.py
```
Expected: all 6 files listed

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Plan coverage |
|---|---|
| 6 new hooks (§5.2 table) | Tasks 3–8 |
| Universal no-op guard (§5.2) | All hook Tasks; Task 9 `test_noop_guard_*` |
| User-global write blocker in all Write\|Edit PreToolUse hooks (§5.2) | Tasks 3, 4, 6; Task 9 `test_user_global_write_blocker` |
| Bash regex hermeticity comment (§5.2) | Tasks 3, 4, 5 (header comment) |
| Lock enforcement: segment-exact match (§5.2) | Task 2 (`path_within_declaration`) |
| Regression test: `src/api` ≠ `src/api-keys/secrets.ts` (§5.2) | Task 2 `test_regression_api_vs_api_keys` |
| Pre-Phase-D tolerant fallback + single findings.md row (§5.2 + §6.2) | Task 6; Task 9 `test_lock_enforcement_tolerant_fallback` |
| `lib/conductor_state.py` (§4.1) | Task 1 |
| v4.1→v5 state migration (`gate`, `scaffold_written`) (§7.5 #3) | Task 1 `migrate_state_if_needed` |
| `validate_scaffold_delegate()` (§4.3) | Task 1 |
| Hook canary in install.sh (§5.2, §7.5 #5) | Task 10 |
| Phase B hooks surfaced to users via bundles offer | Task 11 |
| Integration tests: 12 cases for 6 hooks (§7.2) | Task 9 |
| User-global write blocker integration test with `~/.claude/skills/foo.md` target (§7.2) | Task 9 `test_user_global_write_blocker` |
| post_output_quality: CSV all-empty column → findings.md row (§7.2) | Task 9 `test_output_quality_writes_finding_for_empty_csv_column` |
| stop_validate_final_report: phase=complete + missing report → findings.md row (§7.2) | Task 9 `test_stop_validator_writes_finding_when_report_missing` |
| Universal no-op guard: all hooks → exit 0 with no state.json (§7.2) | Task 9 `test_noop_guard_all_hooks_exit_0_when_no_state_json` |
| `sub-agent gate inheritance` note in conductor body (§5.2) | Covered in Task 11 (bundle 4 install note) |
