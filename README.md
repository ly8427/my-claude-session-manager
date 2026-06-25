# cs — Claude Sessions

A shell command that lists all Claude Code sessions across every project directory and resumes any of them with one keystroke — automatically switching the terminal's working directory.

```
cs              # list all sessions (numbered, newest first)
cs -f myproject  # filter list by keyword (global numbers preserved)
cs -d 3          # delete session 3 (with confirmation)
cs 3            # cd into session 3's working dir and claude --resume
cs ipmifru      # match by cwd/summary substring, then resume
cs b2bcff98     # match by UUID prefix, then resume
```

## Quick install

```bash
curl -sSL https://raw.githubusercontent.com/ly8427/my-claude-session-manager/main/install.sh | bash
```

Or clone and run locally:

```bash
git clone https://github.com/ly8427/my-claude-session-manager.git
cd my-claude-session-manager && bash install.sh
```

Then restart your terminal (or `source ~/.bashrc` / `source ~/.zshrc`) and run `cs`.

## Requirements

- Python 3.6+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI (`claude --version`)
- `~/.claude/projects/` exists (run `claude` at least once)

## What it does

`cs` scans `~/.claude/projects/*/*.jsonl` to discover all Claude Code sessions, regardless of which project directory they were started in. Each session gets a stable index number (newest first) and a one-line summary drawn from the AI-generated title or first user message.

### Commands

| Command | Effect |
|---|---|
| `cs` | List all sessions, newest first |
| `cs -f <kw>` | Filter list by keyword (no resume, global numbers preserved) |
| `cs -d <sel>` | Delete session by number/UUID/keyword (asks for confirmation) |
| `cs <N>` | Resume session N (cd + `claude --resume`) |
| `cs <text>` | Resume by cwd/summary substring (must be unambiguous) |
| `cs <prefix>` | Resume by UUID prefix (must be unambiguous) |

### Tab completion

Press `Tab` after `cs` to complete session cwd names, UUID prefixes, and the `-f` / `--filter` / `-d` / `--delete` flags.

## How it works

- **`cs.py`** — A Python backend that parses session `.jsonl` files and handles listing, filtering, resolution, and tab-completion candidate generation. Installed to `~/.claude/scripts/cs.py`.
- **Shell function** — A `cs()` function appended to `~/.bashrc` or `~/.zshrc` that wraps the backend with argument routing, directory switching, and session resumption.
- **Tab completion** — Bash: `complete -F _cs_complete cs`. Zsh: `compdef _cs_complete cs` with `_arguments`.

## If you already have a `cs` command

The installer detects any pre-existing `cs` — an executable on your `PATH`, or a `cs` function/alias already in your shell rc — and asks for confirmation before installing, because the new shell function would shadow it in interactive shells. To skip the prompt (e.g. in automation):

```bash
CS_FORCE=1 bash install.sh
```

A pre-existing `cs` binary on `PATH` is **never deleted** — it is only shadowed in interactive shells. Reach it any time via `command cs`, `\cs`, or its full path.

## Uninstall

Remove the managed block from your shell rc — everything from (and including) the `# >>> cs (Claude Sessions) BEGIN` line down to the `# <<< cs (Claude Sessions) END` line. Then:

```bash
rm ~/.claude/scripts/cs.py
```

Re-running the installer also refreshes the block in place (it removes the old block before writing the new one), so you don't need to hand-edit your rc to upgrade.

## License

MIT
