#!/usr/bin/env bash
set -euo pipefail

# cs — Claude Sessions installer
# One-command install:  curl -sSL <raw-url>/install.sh | bash

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

say()  { printf "${GREEN}→${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}⚠${NC} %s\n" "$1"; }
die()  { printf "${RED}✗${NC} %s\n" "$1"; exit 1; }

# --- Managed-block markers (replaces the fragile 'grep cs()' dedup) ----------
# A stable BEGIN/END comment pair wraps our cs() block in the shell rc, so we can
# detect / update / uninstall reliably regardless of how an existing 'cs' is
# formatted.
CS_BLOCK_BEGIN="# >>> cs (Claude Sessions) BEGIN"
CS_BLOCK_END="# <<< cs (Claude Sessions) END"

# Detect any pre-existing 'cs' the user may already have: a PATH executable, or a
# function/alias defined in the target rc (excluding our own managed block).
# Prints each finding to stdout; empty output means "nothing found".
detect_existing_cs() {
    local p
    # command -v in this non-interactive shell finds PATH binaries only (rc not
    # sourced); a loaded function would print bare "cs", which we ignore.
    p="$(command -v cs 2>/dev/null || true)"
    if [ -n "$p" ] && [ "$p" != "cs" ] && [ -x "$p" ]; then
        echo "  - existing executable on PATH: $p"
    fi
    if [ -f "$SHELL_RC" ]; then
        # Strip our own managed block first, then scan the rest for foreign defs.
        local stripped
        stripped="$(awk '/# >>> cs \(Claude Sessions\) BEGIN/{f=1} !f{print} /# <<< cs \(Claude Sessions\) END/{f=0}' "$SHELL_RC" 2>/dev/null)"
        if printf '%s' "$stripped" | grep -Eq '(^|[^[:alnum:]_])cs[[:space:]]*\(\)|function[[:space:]]+cs([[:space:]]*\(\)|[[:space:]]*\{)|alias[[:space:]]+cs[[:space:]]*='; then
            echo "  - existing cs function/alias in $SHELL_RC (not from this tool)"
        fi
    fi
}

# y/N prompt that reads from /dev/tty so it works under `curl | bash` (where stdin
# is the script itself). Returns 0 for yes, 1 for no.
prompt_yesno() {
    local resp=""
    if [ -c /dev/tty ]; then
        printf "%s [y/N] " "$1" >&2
        read -r resp </dev/tty 2>/dev/null || resp=""
    fi
    case "$(printf '%s' "$resp" | tr '[:upper:]' '[:lower:]')" in
        y|yes) return 0 ;;
        *) return 1 ;;
    esac
}

# Remove our managed block from the rc (clean update / uninstall). Portable awk,
# no GNU-vs-BSD `sed -i` differences.
remove_managed_block() {
    [ -f "$SHELL_RC" ] || return 0
    local tmp="${SHELL_RC}.cs.tmp.$$"
    awk '/# >>> cs \(Claude Sessions\) BEGIN/{f=1} !f{print} /# <<< cs \(Claude Sessions\) END/{f=0}' \
        "$SHELL_RC" > "$tmp" 2>/dev/null || return 0
    mv "$tmp" "$SHELL_RC"
}

echo ""
echo "  cs — Claude Sessions installer"
echo "  -------------------------------"
echo ""

# --- Detect shell -----------------------------------------------------------
SHELL_RC=""
SHELL_NAME=""
case "$(basename "${SHELL:-}")" in
    zsh)
        SHELL_RC="$HOME/.zshrc"
        SHELL_NAME="zsh"
        ;;
    bash)
        SHELL_RC="$HOME/.bashrc"
        SHELL_NAME="bash"
        ;;
    *)
        # Fallback: check parent process
        detected="$(ps -p $$ -o comm= 2>/dev/null || true)"
        case "$detected" in
            *zsh*)
                SHELL_RC="$HOME/.zshrc"
                SHELL_NAME="zsh"
                ;;
            *)
                SHELL_RC="$HOME/.bashrc"
                SHELL_NAME="bash"
                warn "Could not detect shell; defaulting to bash (~/.bashrc)"
                ;;
        esac
        ;;
esac
say "Detected shell: $SHELL_NAME  →  $SHELL_RC"

# --- Prerequisites -----------------------------------------------------------
say "Checking prerequisites…"

if ! python3 --version >/dev/null 2>&1; then
    die "python3 is required (3.6+). Install it:  sudo apt-get install -y python3"
fi

if ! command -v claude >/dev/null 2>&1; then
    die "claude CLI not found. Install Claude Code first:  npm install -g @anthropic-ai/claude-code"
fi

if [ ! -d "$HOME/.claude/projects" ]; then
    warn "~/.claude/projects/ does not exist. Run 'claude' at least once before installing cs."
    exit 1
fi

# --- Install backend script --------------------------------------------------
SCRIPTS_DIR="$HOME/.claude/scripts"
mkdir -p "$SCRIPTS_DIR"

SCRIPT_SRC="$(dirname "$0")/cs.py"
if [ -f "$SCRIPT_SRC" ]; then
    cp "$SCRIPT_SRC" "$SCRIPTS_DIR/cs.py"
    say "Installed cs.py from local source"
else
    die "cs.py not found alongside install.sh. Run from the cs repo directory."
fi

chmod +x "$SCRIPTS_DIR/cs.py"

# --- Pre-install detection: any pre-existing 'cs'? ---------------------------
say "Checking for an existing 'cs' command…"
CS_EXISTING="$(detect_existing_cs || true)"
if [ -n "$CS_EXISTING" ]; then
    warn "An existing 'cs' was detected:"
    printf '%s\n' "$CS_EXISTING"
    warn "Continuing will let this tool's cs() function shadow the above in interactive shells."
    warn "(A PATH binary is never deleted — still reachable via 'command cs' or its full path.)"
    if [ "${CS_FORCE:-0}" = "1" ]; then
        say "CS_FORCE=1 set; continuing."
    elif ! prompt_yesno "Continue?"; then
        die "Cancelled. To override, set CS_FORCE=1 and re-run:  CS_FORCE=1 bash install.sh"
    fi
fi

# --- Install shell function --------------------------------------------------
# Update path: if our managed block already exists, drop it first so re-running
# the installer refreshes the function/completion code instead of skipping.
if grep -q "$CS_BLOCK_BEGIN" "$SHELL_RC" 2>/dev/null; then
    say "Found a previous install of this tool; removing the old block to update."
    remove_managed_block
fi

say "Adding cs() shell function to $SHELL_RC …"
{
    echo ""
    printf '%s\n' "$CS_BLOCK_BEGIN"
    if [ "$SHELL_NAME" = "zsh" ]; then
        cat << 'EOF'

# cs - Claude Sessions: list all sessions, or resume one (switches cwd too)
#   cs              list every session across all project dirs (numbered)
#   cs -f <kw>      filter list by keyword (global numbers preserved; no resume)
#   cs <number>     cd into that session's working dir and `claude --resume`
#   cs <text>       match by UUID prefix / cwd / summary substring, then resume
cs() {
    local py="$HOME/.claude/scripts/cs.py"
    if [[ $# -eq 0 ]]; then
        python3 "$py" --list
        return
    fi
    if [[ "$1" == "-f" || "$1" == "--filter" ]]; then
        python3 "$py" --list --filter "${2:-}"
        return
    fi
    local out dir uuid
    out=$(python3 "$py" --resolve "$1") || return $?
    dir=${out%%$'\t'*}
    uuid=${out##*$'\t'}
    print "cd $dir && claude --resume $uuid"
    cd "$dir" || return 1
    claude --resume "$uuid"
}

# Tab completion for cs
autoload -Uz compinit
compinit
_cs_complete() {
    local -a cands
    cands=("${(@f)$(python3 "$HOME/.claude/scripts/cs.py" --complete 2>/dev/null)}")
    _arguments \
        '(-f --filter)'{-f,--filter}'[filter by keyword]:keyword:( )' \
        '1:session:($cands)'
}
compdef _cs_complete cs
EOF
    else
        cat << 'EOF'

# cs - Claude Sessions: list all sessions, or resume one (switches cwd too)
#   cs              list every session across all project dirs (numbered)
#   cs -f <kw>      list only sessions matching <kw> (keeps global numbers; no resume)
#   cs <number>     cd into that session's working dir and `claude --resume`
#   cs <text>       match a session by UUID prefix / cwd / summary substring, then resume
cs() {
    local py="$HOME/.claude/scripts/cs.py"
    if [ "$#" -eq 0 ]; then
        python3 "$py" --list
        return
    fi
    if [ "$1" = "-f" ] || [ "$1" = "--filter" ]; then
        python3 "$py" --list --filter "${2:-}"
        return
    fi
    local out rc dir uuid
    out=$(python3 "$py" --resolve "$1")
    rc=$?
    if [ "$rc" -ne 0 ]; then
        return "$rc"
    fi
    dir=${out%%$'\t'*}
    uuid=${out##*$'\t'}
    printf 'cd %s && claude --resume %s\n' "$dir" "$uuid"
    cd "$dir" || return 1
    claude --resume "$uuid"
}

# Tab completion for cs
_cs_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local cands
    cands="$(python3 "$HOME/.claude/scripts/cs.py" --complete 2>/dev/null)"
    COMPREPLY=( $(compgen -W "-f --filter ${cands}" -- "$cur") )
}
complete -F _cs_complete cs
EOF
    fi
    printf '%s\n' "$CS_BLOCK_END"
} >> "$SHELL_RC"
say "Shell integration added."

# --- Verify ------------------------------------------------------------------
echo ""
say "Verifying installation…"
echo ""

python3 "$SCRIPTS_DIR/cs.py" --list >/dev/null 2>&1 || {
    warn "Backend script check failed — cs.py may have an issue."
    exit 1
}

# Verification in a fresh shell
if [ "$SHELL_NAME" = "zsh" ]; then
    if zsh -i -c 'type cs' >/dev/null 2>&1; then
        say "cs function loaded OK"
    else
        warn "cs function not found in fresh zsh — restart your terminal or run: source $SHELL_RC"
    fi
else
    if bash -i -c 'type cs' >/dev/null 2>&1; then
        say "cs function loaded OK"
    else
        warn "cs function not found in fresh bash — restart your terminal or run: source $SHELL_RC"
    fi
fi

echo ""
echo "  ${GREEN}Done!${NC}  Run ${YELLOW}source $SHELL_RC${NC} (or open a new terminal), then try:"
echo ""
echo "    ${YELLOW}cs${NC}              # list all sessions"
echo "    ${YELLOW}cs -f <kw>${NC}      # filter by keyword"
echo "    ${YELLOW}cs <number>${NC}     # resume session by number"
echo "    ${YELLOW}cs <text>${NC}       # resume by cwd/summary substring"
echo ""
echo "  Uninstall: remove the block between ${CS_BLOCK_BEGIN} and ${CS_BLOCK_END}"
echo "  in $SHELL_RC, then 'rm ~/.claude/scripts/cs.py' (or re-run the installer to update)."
echo ""
