#!/usr/bin/env bash
#
# install.sh -- Install project-conductor + 7 skill directories into your Claude Code.
#
# What this script does:
#   1. Detects the repository root (wherever you git-cloned TheConductor).
#   2. Surfaces a single disclosure prompt with explicit Y/n consent for any write under ~/.claude/.
#   3. Patches project-conductor.md so every "/path/to/TheConductor" placeholder
#      is replaced with the real absolute path on this machine.
#   4. Copies the patched project-conductor.md to ~/.claude/agents/.
#   5. Copies skills/conductor-*/ directories to ~/.claude/skills/ (default) OR to
#      <project>/.claude/skills/ when --for-project <path> is passed (advanced).
#
# §3.1 boundary (load-bearing): the installer ONLY writes to:
#   - ~/.claude/skills/conductor-*/SKILL.md
#   - ~/.claude/agents/project-conductor.md
#   (or, with --for-project, the corresponding project-scope locations)
# It NEVER reads, scans, or modifies ~/.claude/CLAUDE.md, ~/.claude/imports/,
# ~/.claude/settings.json, or ~/.claude/memory/. This is enforced by
# tests/test_user_global_readonly.py.
#
# Re-running this script is safe and idempotent: if the deployed files already
# match what we'd write, the script exits without prompting.
#
# Usage:
#   ./install.sh [--force] [--for-project <path>] [--help]
#
#   --force                Overwrite existing deployed files without prompting (for automation
#                          / scripted updates after `git pull`).
#   --for-project <path>   Advanced: install skills to <path>/.claude/skills/ instead of
#                          ~/.claude/skills/. Agent file still goes to ~/.claude/agents/.
#                          For users with strong project-isolation requirements.
#
# Platform support:
#   Linux, macOS (bash 3.2+), Windows Git Bash / WSL

set -euo pipefail

# ---------------------------------------------------------------------------
# Colours -- only when stdout supports color
# ---------------------------------------------------------------------------
if [[ -t 1 && -z "${NO_COLOR:-}" && "${TERM:-}" != "dumb" ]]; then
  C_GREEN=$'\033[0;32m'
  C_YELLOW=$'\033[1;33m'
  C_RED=$'\033[0;31m'
  C_CYAN=$'\033[0;36m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_RESET=$'\033[0m'
else
  C_GREEN=''; C_YELLOW=''; C_RED=''; C_CYAN=''; C_BOLD=''; C_DIM=''; C_RESET=''
fi

ok()     { printf "${C_GREEN}[OK]${C_RESET}  %s\n" "$*"; }
warn()   { printf "${C_YELLOW}[!!]${C_RESET}  %s\n" "$*"; }
err()    { printf "${C_RED}[ERR]${C_RESET} %s\n" "$*" >&2; }
header() { printf "\n${C_BOLD}%s${C_RESET}\n" "$*"; }
dim()    { printf "${C_DIM}%s${C_RESET}\n" "$*"; }

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  cat <<'EOF'
Usage: ./install.sh [--force] [--for-project <path>] [--help]

Installs project-conductor + 7 skill directories into Claude Code.

What happens:
  1. Detects this repository's path (the git clone root).
  2. Asks for explicit Y/n consent before writing under ~/.claude/.
  3. Patches /path/to/TheConductor placeholders in project-conductor.md.
  4. Copies project-conductor.md → ~/.claude/agents/.
  5. Copies skills/conductor-*/ → ~/.claude/skills/ (default).

Boundary (§3.1 of the design spec): the installer ONLY writes to
~/.claude/skills/ and ~/.claude/agents/. It NEVER reads, scans, or modifies
~/.claude/CLAUDE.md, ~/.claude/imports/, ~/.claude/settings.json, or
~/.claude/memory/.

Flags:
  --force                Overwrite existing deployed files without prompting.
                         Use in automated update flows (git pull && ./install.sh).
  --for-project <path>   Advanced: install skills to <path>/.claude/skills/
                         instead of ~/.claude/skills/. Agent file still goes
                         to ~/.claude/agents/.
  --help                 Show this message.

Re-running without --force on an unchanged install is a silent no-op.
EOF
  exit 0
}

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
FORCE=0
FOR_PROJECT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force|-f) FORCE=1; shift ;;
    --help|-h)  usage ;;
    --for-project)
      shift
      if [[ $# -eq 0 || "$1" == --* ]]; then
        err "--for-project requires a path argument"
        exit 2
      fi
      FOR_PROJECT="$1"
      shift
      ;;
    *)
      err "Unknown argument: $1"
      err "Run './install.sh --help' for usage."
      exit 2
      ;;
  esac
done

# Validate --for-project path
if [[ -n "$FOR_PROJECT" ]]; then
  if [[ ! -d "$FOR_PROJECT" ]]; then
    err "--for-project: directory does not exist: $FOR_PROJECT"
    exit 2
  fi
  # Normalize to absolute path
  FOR_PROJECT="$(cd "$FOR_PROJECT" && pwd)"
fi

# ---------------------------------------------------------------------------
# Step 1 — Detect repository root
# ---------------------------------------------------------------------------
header "TheConductor Installer"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

printf "  Repo root : ${C_CYAN}%s${C_RESET}\n" "$REPO_ROOT"

# Verify expected files exist
if [[ ! -f "$REPO_ROOT/project-conductor.md" ]]; then
  err "project-conductor.md not found at $REPO_ROOT"
  err "Make sure you run this script from inside the TheConductor repository."
  exit 1
fi

if [[ ! -d "$REPO_ROOT/skills" ]]; then
  err "skills/ directory not found at $REPO_ROOT — install cannot proceed without skill bodies."
  err "Make sure you're on a v5+ checkout of TheConductor."
  exit 1
fi

if [[ ! -d "$REPO_ROOT/templates" ]]; then
  warn "templates/ directory not found at $REPO_ROOT — scaffold feature will not work."
  warn "Run: git pull to get the latest templates."
fi

if [[ ! -f "$REPO_ROOT/lib/template_render.py" ]]; then
  warn "lib/template_render.py not found at $REPO_ROOT — scaffold feature will not work."
fi

# Count skill directories
SKILL_DIRS=()
for d in "$REPO_ROOT"/skills/conductor-*/; do
  if [[ -d "$d" && -f "$d/SKILL.md" ]]; then
    SKILL_DIRS+=("$d")
  fi
done

if [[ "${#SKILL_DIRS[@]}" -eq 0 ]]; then
  err "No skill directories found at $REPO_ROOT/skills/conductor-*/"
  err "Expected 7 skill directories, each containing a SKILL.md."
  exit 1
fi

if [[ "${#SKILL_DIRS[@]}" -ne 7 ]]; then
  warn "Found ${#SKILL_DIRS[@]} skill directories (expected 7) — installer will proceed with what's present."
fi

# Optional bundle dir checks (warning only)
if [[ ! -d "$REPO_ROOT/hooks" ]]; then
  warn "hooks/ directory not found at $REPO_ROOT — bundle paths may be incomplete."
fi

if [[ ! -d "$REPO_ROOT/agent-monitor" ]]; then
  warn "agent-monitor/ directory not found at $REPO_ROOT — bundle paths may be incomplete."
fi

if [[ ! -f "$REPO_ROOT/lib/lock_check.py" ]]; then
  warn "lib/lock_check.py not found at $REPO_ROOT — the conductor will fall back to legacy time-based stale-lock cleanup."
fi

# ---------------------------------------------------------------------------
# Step 2 — Find Claude Code agents folder + decide skills target
# ---------------------------------------------------------------------------

find_claude_agents_dir() {
  local primary="${HOME}/.claude/agents"
  if [[ -d "$primary" ]]; then echo "$primary"; return 0; fi
  if [[ -d "${HOME}/.claude" ]]; then echo "$primary"; return 0; fi
  if [[ -n "${USERPROFILE:-}" ]]; then
    local win_path
    win_path="$(cygpath -u "$USERPROFILE" 2>/dev/null || echo "$USERPROFILE")"
    if [[ -d "${win_path}/.claude" ]]; then
      echo "${win_path}/.claude/agents"; return 0
    fi
  fi
  if [[ -f /proc/version ]] && grep -qi microsoft /proc/version 2>/dev/null; then
    local wsl_home
    wsl_home="$(wslpath "$(cmd.exe /C "echo %USERPROFILE%" 2>/dev/null | tr -d '\r')" 2>/dev/null || true)"
    if [[ -n "$wsl_home" && -d "${wsl_home}/.claude" ]]; then
      echo "${wsl_home}/.claude/agents"; return 0
    fi
  fi
  echo "$primary"
}

AGENTS_DIR="$(find_claude_agents_dir)"
USER_GLOBAL_DIR="$(dirname "$AGENTS_DIR")"

# Decide skills target
if [[ -n "$FOR_PROJECT" ]]; then
  SKILLS_DIR="$FOR_PROJECT/.claude/skills"
  SKILLS_DESC="$SKILLS_DIR (--for-project)"
else
  SKILLS_DIR="$USER_GLOBAL_DIR/skills"
  SKILLS_DESC="$SKILLS_DIR (global default)"
fi

printf "  Agents dir: ${C_CYAN}%s${C_RESET}\n" "$AGENTS_DIR"
printf "  Skills dir: ${C_CYAN}%s${C_RESET}\n" "$SKILLS_DESC"

if [[ ! -d "${HOME}/.claude" ]] && [[ ! -d "$(dirname "$AGENTS_DIR")" ]]; then
  err "Claude Code does not appear to be installed on this machine."
  err "Expected ~/.claude/ to exist. Install Claude Code first, then re-run."
  err "See: https://docs.claude.com/en/docs/claude-code"
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 3 — User-global footprint disclosure (§3.1.2 + §7.5 #6)
# ---------------------------------------------------------------------------

# Idempotency pre-check: if everything is already up-to-date, skip the prompt.
ALREADY_UP_TO_DATE=1

# Patch agent in memory for compare
CONDUCTOR_SRC="$REPO_ROOT/project-conductor.md"
CONDUCTOR_TMP="$(mktemp "${TMPDIR:-/tmp}/project-conductor-patched.XXXXXX.md")"
trap 'rm -f "$CONDUCTOR_TMP"' EXIT

if command -v perl >/dev/null 2>&1; then
  perl -pe "s|/path/to/TheConductor|${REPO_ROOT}|g" "$CONDUCTOR_SRC" > "$CONDUCTOR_TMP"
else
  REPO_ROOT_ESC=$(printf '%s\n' "$REPO_ROOT" | sed 's/[\&|]/\\&/g')
  sed "s|/path/to/TheConductor|${REPO_ROOT_ESC}|g" "$CONDUCTOR_SRC" > "$CONDUCTOR_TMP"
fi

if [[ ! -s "$CONDUCTOR_TMP" ]]; then
  err "Patching produced an empty file — aborting."
  exit 1
fi

# Compare agent file
DEST_AGENT="$AGENTS_DIR/project-conductor.md"
if [[ ! -f "$DEST_AGENT" ]] || ! cmp -s "$CONDUCTOR_TMP" "$DEST_AGENT"; then
  ALREADY_UP_TO_DATE=0
fi

# Compare each skill directory
for skill_src in "${SKILL_DIRS[@]}"; do
  skill_name="$(basename "$skill_src")"
  skill_dest="$SKILLS_DIR/$skill_name/SKILL.md"
  skill_src_md="$skill_src/SKILL.md"
  if [[ ! -f "$skill_dest" ]] || ! cmp -s "$skill_src_md" "$skill_dest"; then
    ALREADY_UP_TO_DATE=0
    break
  fi
done

if [[ "$ALREADY_UP_TO_DATE" -eq 1 ]]; then
  ok "Already up to date — agent and all skills match. No changes."
  exit 0
fi

# Disclosure prompt — explicit Y/n consent
header "About to write to ~/.claude/:"
if [[ -n "$FOR_PROJECT" ]]; then
  printf "  - %d skill directories → %s/conductor-*/SKILL.md\n" "${#SKILL_DIRS[@]}" "$SKILLS_DIR"
else
  printf "  - %d skill directories → ~/.claude/skills/conductor-*/SKILL.md\n" "${#SKILL_DIRS[@]}"
fi
printf "  - 1 agent file → ~/.claude/agents/project-conductor.md\n"
printf "\n"
printf "  ${C_DIM}No other files under ~/.claude/ will be modified.${C_RESET}\n"
printf "  ${C_DIM}(Boundary §3.1: the installer does not touch ~/.claude/CLAUDE.md,${C_RESET}\n"
printf "  ${C_DIM} ~/.claude/imports/, ~/.claude/settings.json, or ~/.claude/memory/.)${C_RESET}\n"
printf "\n"

if [[ "$FORCE" -ne 1 ]]; then
  printf "  Proceed? [Y/n] "
  read -r answer </dev/tty
  case "$answer" in
    n|N|no|NO)
      ok "Aborted — conductor not installed; re-run when ready."
      exit 0
      ;;
    *) : ;;
  esac
fi

# ---------------------------------------------------------------------------
# Step 4 — Install agent
# ---------------------------------------------------------------------------

mkdir -p "$AGENTS_DIR"

if [[ -f "$DEST_AGENT" ]] && ! cmp -s "$CONDUCTOR_TMP" "$DEST_AGENT"; then
  if [[ "$FORCE" -ne 1 ]]; then
    warn "$DEST_AGENT exists with different content."
    printf "  Overwrite agent file? [y/N] "
    read -r answer </dev/tty
    case "$answer" in
      y|Y|yes|YES) cp "$CONDUCTOR_TMP" "$DEST_AGENT" ;;
      *) warn "Skipped agent overwrite."; AGENT_SKIPPED=1 ;;
    esac
  else
    cp "$CONDUCTOR_TMP" "$DEST_AGENT"
  fi
else
  cp "$CONDUCTOR_TMP" "$DEST_AGENT"
fi

if [[ -z "${AGENT_SKIPPED:-}" ]]; then
  ok "Installed agent → $DEST_AGENT"
fi

# ---------------------------------------------------------------------------
# Step 5 — Install skills
# ---------------------------------------------------------------------------

mkdir -p "$SKILLS_DIR"

INSTALLED_SKILLS=0
SKIPPED_SKILLS=0

for skill_src in "${SKILL_DIRS[@]}"; do
  skill_name="$(basename "$skill_src")"
  skill_src_md="$skill_src/SKILL.md"
  skill_dest_dir="$SKILLS_DIR/$skill_name"
  skill_dest_md="$skill_dest_dir/SKILL.md"

  if [[ -f "$skill_dest_md" ]] && cmp -s "$skill_src_md" "$skill_dest_md"; then
    : # already up to date, no message
    continue
  fi

  if [[ -f "$skill_dest_md" ]] && ! cmp -s "$skill_src_md" "$skill_dest_md"; then
    if [[ "$FORCE" -ne 1 ]]; then
      warn "$skill_dest_md exists with different content."
      printf "  Overwrite this skill? [y/N] "
      read -r answer </dev/tty
      case "$answer" in
        y|Y|yes|YES) : ;;
        *) SKIPPED_SKILLS=$((SKIPPED_SKILLS + 1)); continue ;;
      esac
    fi
  fi

  mkdir -p "$skill_dest_dir"
  cp "$skill_src_md" "$skill_dest_md"
  INSTALLED_SKILLS=$((INSTALLED_SKILLS + 1))
done

if [[ "$INSTALLED_SKILLS" -gt 0 ]]; then
  ok "Installed $INSTALLED_SKILLS skill(s) → $SKILLS_DIR/conductor-*/"
fi

if [[ "$SKIPPED_SKILLS" -gt 0 ]]; then
  warn "Skipped $SKIPPED_SKILLS skill(s) (existing content differs; use --force to overwrite)"
fi

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

    local actual_exit=0
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
  if [[ -f "$REPO_ROOT/hooks/pre_phase0_readonly.py" ]]; then
    _canary "$REPO_ROOT/hooks/pre_phase0_readonly.py" \
      "no-op (no state.json)" "" \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$REPO_ROOT/hooks/pre_phase0_readonly.py" \
      "allow (phase=1)" \
      '{"phase":"1","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$REPO_ROOT/hooks/pre_phase0_readonly.py" \
      "block write in phase=0" \
      '{"phase":"0","gate":"pre_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 2
  fi

  # pre_first_response_gate
  if [[ -f "$REPO_ROOT/hooks/pre_first_response_gate.py" ]]; then
    _canary "$REPO_ROOT/hooks/pre_first_response_gate.py" \
      "no-op (no state.json)" "" \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$REPO_ROOT/hooks/pre_first_response_gate.py" \
      "allow (gate open)" \
      '{"phase":"1","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$REPO_ROOT/hooks/pre_first_response_gate.py" \
      "block Edit (gate=pre_first_response_proceed)" \
      '{"phase":"1","gate":"pre_first_response_proceed"}' \
      '{"tool_name":"Edit","tool_input":{"file_path":"/tmp/x.py"}}' 2
  fi

  # pre_busy_wait_block
  if [[ -f "$REPO_ROOT/hooks/pre_busy_wait_block.py" ]]; then
    _canary "$REPO_ROOT/hooks/pre_busy_wait_block.py" \
      "no-op (no state.json)" "" \
      '{"tool_name":"Bash","tool_input":{"command":"ls"}}' 0
    _canary "$REPO_ROOT/hooks/pre_busy_wait_block.py" \
      "allow normal bash" \
      '{"phase":"2","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' 0
    _canary "$REPO_ROOT/hooks/pre_busy_wait_block.py" \
      "block busy-wait" \
      '{"phase":"2","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Bash","tool_input":{"command":"until check; do sleep 5; done"}}' 2
  fi

  # pre_lock_enforcement
  if [[ -f "$REPO_ROOT/hooks/pre_lock_enforcement.py" ]]; then
    _canary "$REPO_ROOT/hooks/pre_lock_enforcement.py" \
      "no-op (no state.json)" "" \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$REPO_ROOT/hooks/pre_lock_enforcement.py" \
      "tolerant fallback (no active-task.json)" \
      '{"phase":"2","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
  fi

  # post_output_quality
  if [[ -f "$REPO_ROOT/hooks/post_output_quality.py" ]]; then
    _canary "$REPO_ROOT/hooks/post_output_quality.py" \
      "no-op (no state.json)" "" \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
    _canary "$REPO_ROOT/hooks/post_output_quality.py" \
      "allow non-structured file" \
      '{"phase":"2","gate":"post_first_response_proceed"}' \
      '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x.py"}}' 0
  fi

  # stop_validate_final_report
  if [[ -f "$REPO_ROOT/hooks/stop_validate_final_report.py" ]]; then
    _canary "$REPO_ROOT/hooks/stop_validate_final_report.py" \
      "no-op (no state.json)" "" '{}' 0
    _canary "$REPO_ROOT/hooks/stop_validate_final_report.py" \
      "no-op (phase!=complete)" \
      '{"phase":"2","gate":"post_first_response_proceed"}' '{}' 0
  fi

  if [[ "$CANARY_FAIL" -gt 0 ]]; then
    warn "$CANARY_FAIL hook canary case(s) failed — hooks may not work correctly on this system."
  else
    ok "Hook canary: all $CANARY_PASS cases passed."
  fi
fi

# ---------------------------------------------------------------------------
# Step 7 — Template render canary (Phase C)
# ---------------------------------------------------------------------------
if [[ -f "$REPO_ROOT/lib/template_render.py" && -d "$REPO_ROOT/templates" ]]; then
  header "Template render canary"

  # Pick one template to test — CLAUDE.md has the most vars
  TEMPLATE_TO_TEST="$REPO_ROOT/templates/CLAUDE.md"
  RENDER_CANARY_TARGET="/tmp/conductor_canary_render_$(date +%s).md"
  RENDER_OK=0

  if python3 - <<PYEOF 2>/dev/null
import sys
sys.path.insert(0, "$REPO_ROOT/lib")
from template_render import render
payload = {
    "PROJECT_NAME": "CanaryProject",
    "STACK": "React",
    "LANG_PRIMARY": "TypeScript",
    "TEXT_DIRECTION": "ltr",
    "AUTH_MODEL": "JWT",
}
rendered, missing = render("$TEMPLATE_TO_TEST", payload, "$RENDER_CANARY_TARGET")
assert "CanaryProject" in rendered, "PROJECT_NAME not substituted"
PYEOF
  then
    ok "Template render canary: passed."
    RENDER_OK=1
  else
    warn "Template render canary: FAILED — lib/template_render.py may be broken."
  fi
  rm -f "$RENDER_CANARY_TARGET"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
printf "\n"
printf "  +------------------------------------------------+\n"
printf "  | ${C_GREEN}${C_BOLD}  TheConductor installed successfully!${C_RESET}         |\n"
printf "  +------------------------------------------------+\n"
printf "\n"
dim "  Agents folder : $AGENTS_DIR"
dim "  Skills folder : $SKILLS_DIR"
dim "  Source repo   : $REPO_ROOT"
printf "\n"
printf "  ${C_CYAN}Next steps — invoke the conductor as your main agent:${C_RESET}\n"
printf "\n"
printf "    1. Open a project in your terminal and ${C_BOLD}cd${C_RESET} into it.\n"
printf "    2. Run: ${C_BOLD}claude --agent project-conductor${C_RESET}\n"
printf "    3. In the session, ask it to build from your spec, e.g.:\n"
printf "       ${C_BOLD}build from spec.md${C_RESET}\n"
printf "\n"
dim "  The conductor runs as the MAIN agent (not a sub-agent). It spawns"
dim "  sub-agents and invokes skills on demand to execute your spec."
printf "\n"
dim "  Updating later: git pull && ./install.sh"
printf "\n"
