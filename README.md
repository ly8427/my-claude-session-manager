# cs — Claude Sessions

A shell command that lists all Claude Code sessions across every project directory and resumes any of them with one keystroke — automatically switching the terminal's working directory.

```
cs              # list all sessions (numbered, newest first)
cs -f myproject  # filter list by keyword (global numbers preserved)
cs -c            # per-session token usage (+USD if configured)
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
| `cs -c [opts]` | Per-session token usage + total (+USD if configured); see [Session cost](#session-cost--usage) |
| `cs <N>` | Resume session N (cd + `claude --resume`) |
| `cs <text>` | Resume by cwd/summary substring (must be unambiguous) |
| `cs <prefix>` | Resume by UUID prefix (must be unambiguous) |

### Tab completion

Press `Tab` after `cs` to complete session cwd names, UUID prefixes, and the `-f` / `--filter` / `-d` / `--delete` / `-c` / `--cost` flags.

### Session cost & usage

`cs -c` prints per-session token usage (input / output / cache) plus a total, computed from the `message.usage` block on each assistant turn in the `.jsonl`. This works across **any model backend** — glm, deepseek, opus, etc. — because the usage format is Claude Code's own log format, not the model's.

```
cs -c                         # all sessions, all time
cs -c --since 2026-06-01      # only turns on/after June 1 (local time)
cs -c --since 7d              # last 7 days (also: 12h, 30m)
cs -c --by-model              # break the total down per model
cs -c -f myproject            # only sessions matching a keyword
```

**USD shows by default — but it's an estimate.** There's no stored cost anywhere, so `cs -c` multiplies tokens by built-in per-model rates (USD per 1M tokens): Anthropic models use published list prices; DeepSeek and GLM use approximate provider list prices. A footer reminds you it's only an estimate.

| Model pattern | input | output | cache_read | cache_creation |
|---|---|---|---|---|
| `claude-opus-*` | 15.0 | 75.0 | 1.5 | 18.75 |
| `claude-sonnet-*` | 3.0 | 15.0 | 0.3 | 3.75 |
| `claude-haiku-*` | 0.8 | 4.0 | 0.08 | 1.0 |
| `deepseek-*` | 1.74 | 3.48 | 0.035 | 1.74 |
| `glm-5.*` | 1.11 | 3.89 | 0.0 | 1.11 |
| `glm-4.*` | 0.11 | 0.28 | 0.014 | 0.11 |

Unmatched models get `$0`. The estimate uses the 5-minute cache-write rate (1h cache writes actually cost 2×). **Override or add any model** via `~/.claude/cs-pricing.json` — entries there win over the built-ins (`cs -c --print-pricing` prints a template of your models):

```json
{"glm-5.2": {"input": 1.5, "output": 5.0, "cache_read": 0.1, "cache_creation": 1.5}}
```

Remember: it's `tokens × rates`, not real billing (that's `/usage`'s cloud feed, which a local tool can't read). DeepSeek/GLM rates are the least certain — verify against your provider.

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
