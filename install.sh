#!/usr/bin/env bash
#
# install.sh -- Install project-conductor into your Claude Code agents folder.
#
# What this script does:
#   1. Detects the repository root (wherever you git-cloned TheConductor).
#   2. Patches project-conductor.md so every "/path/to/TheConductor" placeholder
#      is replaced with the real absolute path of this repo, and the hooks/
#      and agent-monitor/ paths resolve correctly on this machine.
#   3. Finds the Claude Code agents folder on this machine (~/.claude/agents/).
#   4. Copies the patched project-conductor.md into that agents folder.
#
# Re-running this script is safe and idempotent: if the deployed file already
# matches what we'd write, the script exits without prompting.
#
# Usage:
#   ./install.sh [--force] [--help]
#
#   --force   Overwrite existing deployed file without prompting (for automation
#             / scripted updates after `git pull`).
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
Usage: ./install.sh [--force] [--help]

Installs project-conductor into your Claude Code agents folder.

What happens:
  1. Detects the location of this repository (the git clone root).
  2. Patches project-conductor.md so "/path/to/TheConductor" placeholders
     are replaced with the real absolute path on this machine.
  3. Finds your Claude Code agents folder (~/.claude/agents/).
  4. Copies the patched file there as project-conductor.md.

The original project-conductor.md in this repo is NEVER modified in place.
A patched copy is written to a temp file, then installed.

Flags:
  --force   Overwrite an existing deployed file without prompting.
            Use this in automated update flows (git pull && ./install.sh).
  --help    Show this message.

Re-running without --force on an unchanged install is a silent no-op.
EOF
  exit 0
}

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    --help|-h)  usage ;;
    *)
      err "Unknown argument: $arg"
      err "Run './install.sh --help' for usage."
      exit 2
      ;;
  esac
done

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
# Step 2 — Find Claude Code agents folder
# ---------------------------------------------------------------------------

find_claude_agents_dir() {
  # Primary: standard location used by Claude Code on all platforms
  local primary="${HOME}/.claude/agents"
  if [[ -d "$primary" ]]; then
    echo "$primary"
    return 0
  fi

  # Fallback: ~/.claude exists but agents/ sub-dir hasn't been created yet
  if [[ -d "${HOME}/.claude" ]]; then
    echo "$primary"   # will be created below
    return 0
  fi

  # Windows Git Bash: USERPROFILE may differ from HOME
  if [[ -n "${USERPROFILE:-}" ]]; then
    local win_path
    # Convert Windows path to Unix-style if running under Git Bash
    win_path="$(cygpath -u "$USERPROFILE" 2>/dev/null || echo "$USERPROFILE")"
    if [[ -d "${win_path}/.claude" ]]; then
      echo "${win_path}/.claude/agents"
      return 0
    fi
  fi

  # WSL: check the Windows-side home if inside WSL
  if [[ -f /proc/version ]] && grep -qi microsoft /proc/version 2>/dev/null; then
    local wsl_home
    wsl_home="$(wslpath "$(cmd.exe /C "echo %USERPROFILE%" 2>/dev/null | tr -d '\r')" 2>/dev/null || true)"
    if [[ -n "$wsl_home" && -d "${wsl_home}/.claude" ]]; then
      echo "${wsl_home}/.claude/agents"
      return 0
    fi
  fi

  # Not found — return the standard path; caller will create it or warn
  echo "$primary"
}

AGENTS_DIR="$(find_claude_agents_dir)"
printf "  Agents dir: ${C_CYAN}%s${C_RESET}\n" "$AGENTS_DIR"

if [[ ! -d "${HOME}/.claude" ]] && [[ ! -d "$(dirname "$AGENTS_DIR")" ]]; then
  err "Claude Code does not appear to be installed on this machine."
  err "Expected ~/.claude/ to exist. Install Claude Code first, then re-run."
  err "See: https://docs.anthropic.com/claude-code"
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 3 — Patch project-conductor.md with real repo paths
# ---------------------------------------------------------------------------

CONDUCTOR_SRC="$REPO_ROOT/project-conductor.md"
CONDUCTOR_TMP="$(mktemp "${TMPDIR:-/tmp}/project-conductor-patched.XXXXXX.md")"

# Always clean up the temp file on exit (success, error, or signal).
trap 'rm -f "$CONDUCTOR_TMP"' EXIT

# Replace every occurrence of the generic placeholder "/path/to/TheConductor"
# (used in examples and bundle install prompts inside the file) with the real path.
#
# We use perl for robust in-memory substitution that works on both Linux and macOS
# without needing GNU sed's -i ''.
if command -v perl >/dev/null 2>&1; then
  perl -pe "s|/path/to/TheConductor|${REPO_ROOT}|g" "$CONDUCTOR_SRC" > "$CONDUCTOR_TMP"
else
  # Fallback: sed (GNU on Linux; BSD on macOS both support this form).
  # Escape characters that have special meaning in sed's replacement string.
  REPO_ROOT_ESC=$(printf '%s\n' "$REPO_ROOT" | sed 's/[\&|]/\\&/g')
  sed "s|/path/to/TheConductor|${REPO_ROOT_ESC}|g" "$CONDUCTOR_SRC" > "$CONDUCTOR_TMP"
fi

# Verify the patch produced output
if [[ ! -s "$CONDUCTOR_TMP" ]]; then
  err "Patching produced an empty file — aborting to avoid overwriting with garbage."
  exit 1
fi

ok "Patched placeholders → real paths in temp copy"
dim "  /path/to/TheConductor  →  $REPO_ROOT"

# ---------------------------------------------------------------------------
# Step 4 — Copy patched file into Claude Code agents folder
# ---------------------------------------------------------------------------

mkdir -p "$AGENTS_DIR"

DEST="$AGENTS_DIR/project-conductor.md"

if [[ -f "$DEST" ]]; then
  # Idempotency: if the deployed file is byte-identical to what we'd write, no-op.
  if cmp -s "$CONDUCTOR_TMP" "$DEST"; then
    ok "Already up to date — no changes."
    dim "  $DEST"
    exit 0
  fi

  if [[ "$FORCE" -ne 1 ]]; then
    warn "project-conductor.md already exists at $DEST (content differs)."
    printf "  Overwrite? [y/N] (or use --force to skip this prompt) "
    read -r answer </dev/tty
    case "$answer" in
      y|Y|yes|YES) : ;;
      *)
        ok "Aborted — existing file left unchanged."
        exit 0
        ;;
    esac
  else
    dim "  --force: overwriting existing deployed file"
  fi
fi

cp "$CONDUCTOR_TMP" "$DEST"

ok "Installed → $DEST"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
printf "\n"
printf "  +------------------------------------------------+\n"
printf "  | ${C_GREEN}${C_BOLD}  project-conductor installed successfully!${C_RESET}     |\n"
printf "  +------------------------------------------------+\n"
printf "\n"
dim "  Agents folder : $AGENTS_DIR"
dim "  Installed file: $DEST"
dim "  Source repo   : $REPO_ROOT"
printf "\n"
printf "  ${C_CYAN}Next steps:${C_RESET}\n"
printf "  1. Open a project in Claude Code.\n"
printf "  2. Type: ${C_BOLD}Use project-conductor to build from [your-spec-file]${C_RESET}\n"
printf "  3. When prompted for optional bundles, the paths to\n"
printf "     ${C_BOLD}hooks/${C_RESET} and ${C_BOLD}agent-monitor/${C_RESET} are already baked in.\n"
printf "\n"
