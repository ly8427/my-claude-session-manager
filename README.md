# cs — Claude Sessions

A shell command that lists all Claude Code sessions across every project directory and resumes any of them with one keystroke — automatically switching the terminal's working directory.

```
cs              # list all sessions (numbered, newest first)
cs -f myproject  # filter list by keyword (global numbers preserved)
cs -n 3 "login fix"  # give session 3 a stable name (shown in color)
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

`cs` scans `~/.claude/projects/*/*.jsonl` to discover all Claude Code sessions, regardless of which project directory they were started in. Each session gets a stable index number (newest first) and a **stable name** — the first user message by default, or a name you set yourself (`cs -n`). The list is color-coded (name, cwd, and the AI-generated description each get their own color) with a blank line between sessions for easy scanning. Colors auto-disable when piped.

### Commands

| Command | Effect |
|---|---|
| `cs` | List all sessions, newest first |
| `cs -f <kw>` | Filter list by keyword (no resume, global numbers preserved) |
| `cs -d <sel>` | Delete session by number/UUID/keyword (asks for confirmation) |
| `cs -c [opts]` | Per-session token usage + total (+USD if configured); see [Session cost](#session-cost--usage) |
| `cs -n <sel> <name>` | Set a stable custom name for a session (`cs -n <sel> --clear` to remove) |
| `cs <N>` | Resume session N (cd + `claude --resume`) |
| `cs <text>` | Resume by cwd/summary substring (must be unambiguous) |
| `cs <prefix>` | Resume by UUID prefix (must be unambiguous) |

### Session names

Each session shows a **name** that stays put (unlike Claude Code's AI-generated title, which gets regenerated and changes every run):

- **Default** = the session's first user message (stable — that line never changes).
- **Custom** = `cs -n 3 "login fix"` sets your own; it overrides the default and is stored in `~/.claude/cs-names.json` (keyed by session UUID). Remove it with `cs -n 3 --clear`.

The list shows three color-coded lines per session — the **name** (cyan), the **cwd** (green), and the AI **description** (yellow) — plus dim meta (branch, message count, UUID prefix, time), with a blank line between sessions.

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
| `claude-opus-*` | 5.0 | 25.0 | 0.5 | 6.25 |
| `claude-sonnet-*` | 3.0 | 15.0 | 0.3 | 3.75 |
| `claude-haiku-*` | 1.0 | 5.0 | 0.1 | 1.25 |
| `deepseek-*` | 1.74 | 3.48 | 0.035 | 1.74 |
| `glm-5.*` | 1.11 | 3.89 | 0.0 | 1.11 |
| `glm-4.*` | 0.11 | 0.28 | 0.014 | 0.11 |

Unmatched models get `$0`. The estimate uses the 5-minute cache-write rate (1h cache writes actually cost 2×). **Override or add any model** via `~/.claude/cs-pricing.json` — entries there win over the built-ins (`cs -c --print-pricing` prints a template of your models):

```json
{"glm-5.2": {"input": 1.5, "output": 5.0, "cache_read": 0.1, "cache_creation": 1.5}}
```

Remember: it's `tokens × rates`, not real billing (that's `/usage`'s cloud feed, which a local tool can't read). DeepSeek/GLM rates are the least certain — verify against your provider.

### Keeping old sessions (auto-cleanup notice)

Claude Code **deletes session transcripts older than 30 days** by default (`cleanupPeriodDays`) — that's why sessions quietly vanish from the list over time. Cleanup is a discrete event (on instance start / periodically), not a continuous process, so "it was here yesterday, gone today" is normal.

On its first interactive run, `cs` notices when that default is still in force and offers to switch it off:

```
cs: notice: Claude Code auto-deletes session transcripts older than 30 days
    (default cleanupPeriodDays). That's why old sessions vanish from this list.
    Keep sessions for 10 years instead (set cleanupPeriodDays=3650)? [y/N]
```

- **`y`** — adds `"cleanupPeriodDays": 3650` to `~/.claude/settings.json` via a surgical one-line insert: every other line stays byte-identical. A timestamped backup is saved first (`~/.claude/settings.json.cs-bak-<ts>`; the 5 newest are kept, older ones rotate away).
- **`N` / Enter** — keeps the 30-day default, and the question is never asked again. To change your mind later, ask Claude: *"set cleanupPeriodDays to 3650 in ~/.claude/settings.json"*.

The offer fires **at most once per machine** (the answer is remembered in `~/.claude/cs-state.json`), only when both stdout and stderr are terminals — piped output, tab completion, and `cs <N>` resume never prompt and never block. If something goes wrong mid-edit, the original file is left untouched and you're told to set the key manually.

**If you've already set `cleanupPeriodDays` yourself (any value), this feature never triggers** — it exists for fresh installs and new machines, so don't be surprised if you never see the question.

Why 3650 and not 0: `cleanupPeriodDays: 0` does not mean "keep forever" — it's reported to silently stop transcript persistence entirely ([anthropics/claude-code#23710](https://github.com/anthropics/claude-code/issues/23710)). A large number is the only safe way to say "keep them".

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
