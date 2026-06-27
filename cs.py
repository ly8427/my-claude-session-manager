#!/usr/bin/env python3
"""cs - Claude Sessions browser/resumer backend.

Scans ~/.claude/projects/*/*.jsonl and either:
  --list             print a numbered table (cwd, UUID, summary)
  --resolve <sel>    resolve a selector to "<cwd>\t<uuid>" on stdout
  --delete <sel>     resolve a selector and print "<path>\t<uuid>\t<cwd>\t<summary>"
  --cost [-c]        per-session token usage (+ optional USD), with optional time range
  --complete         emit tab-completion candidates

Selector may be:
  - an index from the most recent --list (1-based, modified desc)
  - a session UUID or unique UUID prefix
  - a case-insensitive substring matching exactly one session's cwd or summary
On ambiguity/no-match, prints candidates to stderr and exits non-zero.

Cost is computed from the `message.usage` token block on each assistant line
(uniform across all model backends). USD is shown only when a per-model rates
file exists at ~/.claude/cs-pricing.json (USD per 1M tokens).
"""
import json
import os
import re
import sys
import glob
import argparse
from datetime import datetime, timedelta, timezone

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
PRICING_FILE = os.path.expanduser("~/.claude/cs-pricing.json")
NAMES_FILE = os.path.expanduser("~/.claude/cs-names.json")

# ANSI color for the human-facing --list view only. Auto-disabled when stdout
# is not a TTY (e.g. `cs -f x | grep`); never used by --resolve/--delete/
# --complete, whose stdout is parsed by the shell function.
_USE_COLOR = sys.stdout.isatty()


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def _clr_name(t):
    return _c("1;96", t)   # bold bright cyan — stable session name


def _clr_cwd(t):
    return _c("92", t)     # bright green     — cwd


def _clr_desc(t):
    return _c("93", t)     # bright yellow    — ai_title (volatile)


def _clr_tok(t):
    return _c("94", t)     # bright blue      — token breakdown


def _clr_meta(t):
    return _c("2;37", t)   # dim              — index/date/msgs/uuid/branch


def _text_from_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return ""


def parse_session(path):
    uuid = os.path.splitext(os.path.basename(path))[0]
    cwd = git_branch = ai_title = first_user = None
    msg_count = 0
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cwd is None and o.get("cwd"):
                    cwd = o["cwd"]
                if git_branch is None and o.get("gitBranch"):
                    git_branch = o["gitBranch"]
                if o.get("type") == "ai-title" and o.get("aiTitle"):
                    ai_title = o["aiTitle"]
                if o.get("type") == "user":
                    msg_count += 1
                    if first_user is None:
                        msg = o.get("message", {})
                        if isinstance(msg, dict):
                            txt = _text_from_content(msg.get("content", "")).strip()
                            if txt and not txt.startswith("<"):
                                first_user = txt
    except OSError:
        pass
    summary = " ".join((ai_title or first_user or "(no summary)").split())
    return {
        "uuid": uuid,
        "cwd": cwd or "(unknown)",
        "summary": summary,
        "git_branch": git_branch,
        "messages": msg_count,
        "modified": os.path.getmtime(path),
        "path": path,
        "first_user": first_user,
        "ai_title": ai_title,
    }


def _load_names():
    """Load {uuid: custom_name} from NAMES_FILE (empty dict if missing/bad)."""
    try:
        with open(NAMES_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_names(names):
    try:
        with open(NAMES_FILE, "w") as fh:
            json.dump(names, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


def load_sessions():
    files = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
    sessions = [parse_session(p) for p in files]
    sessions.sort(key=lambda s: s["modified"], reverse=True)
    names = _load_names()
    for s in sessions:
        s["custom_name"] = names.get(s["uuid"])
    return sessions


def fmt_when(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def do_list(sessions, width, filt=None):
    if not sessions:
        print("No sessions found.")
        return
    n = len(sessions)
    iw = len(str(n))
    fl = filt.lower() if filt else None
    shown = 0
    first = True
    # Global index (i) is preserved even when filtering, so `cs <i>` stays valid.
    for i, s in enumerate(sessions, 1):
        if (fl and fl not in s["cwd"].lower() and fl not in s["summary"].lower()
                and fl not in (s["custom_name"] or "").lower()):
            continue
        if not first:
            print()  # blank line between sessions
        first = False
        shown += 1
        # Stable name: custom name → first user message → fallback. Never the
        # volatile ai_title (that's shown separately, as desc).
        name = " ".join((s["custom_name"] or s["first_user"] or "(no name)").split())
        if len(name) > width:
            name = name[: width - 1] + "…"
        idx = _clr_meta(f"[{str(i).rjust(iw)}]")
        branch = f" {_clr_meta('[' + s['git_branch'] + ']')}" if s["git_branch"] else ""
        meta = _clr_meta(f"· {s['messages']} msgs · {s['uuid'][:8]} · {fmt_when(s['modified'])}")
        print(f"{idx} {_clr_name(name)}")
        print(f"    {_clr_cwd(s['cwd'])}{branch}  {meta}")
        if s["ai_title"]:
            d = " ".join(s["ai_title"].split())
            if len(d) > width:
                d = d[: width - 1] + "…"
            print(f"    {_clr_desc(d)}")
    if fl:
        print(f"\n{_clr_meta('Shown:')} {shown}/{n} matching '{filt}'   |   "
              f"{_clr_meta('resume with:')} cs <number>")
    else:
        print(f"\n{_clr_meta('Total:')} {n} session(s)   |   "
              f"{_clr_meta('resume with:')} cs <number>")


def do_complete(sessions):
    """Emit completion candidates: cwd basenames and UUID prefixes.

    Only "safe" basenames (alnum, dash, underscore, dot) are emitted, because
    shells split completion candidates on whitespace and choke on characters
    like ( ) ' " in the candidate lists built by compgen / _arguments.
    """
    seen = set()
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    for s in sessions:
        base = os.path.basename(s["cwd"].rstrip("/")) or s["cwd"]
        if base and base not in seen and all(c in safe for c in base):
            seen.add(base)
            print(base)
    for s in sessions:
        print(s["uuid"][:8])


def _match_session(sessions, sel):
    """Resolve a selector to a single session, printing diagnostics to stderr.

    Returns (session, errcode):
      - (session, 0)   unique match
      - (None, 1)      no match (message already printed)
      - (None, 2)      ambiguous (candidates already printed)
    Diagnostics are emitted here so do_resolve / do_delete can't drift apart.
    """
    # 1) numeric index into the modified-desc list
    if sel.isdigit():
        idx = int(sel)
        if 1 <= idx <= len(sessions):
            return (sessions[idx - 1], 0)
        print(f"cs: index {idx} out of range (1..{len(sessions)})", file=sys.stderr)
        return (None, 1)

    sl = sel.lower()
    # 2) exact UUID or UUID prefix
    uuid_hits = [s for s in sessions if s["uuid"] == sel or s["uuid"].startswith(sl)]
    if len(uuid_hits) == 1:
        return (uuid_hits[0], 0)
    if len(uuid_hits) > 1:
        _print_candidates(uuid_hits, f"ambiguous UUID prefix '{sel}'")
        return (None, 2)

    # 3) substring match on cwd or summary
    hits = [s for s in sessions if sl in s["cwd"].lower() or sl in s["summary"].lower()]
    if len(hits) == 1:
        return (hits[0], 0)
    if len(hits) == 0:
        print(f"cs: no session matches '{sel}'", file=sys.stderr)
        return (None, 1)
    _print_candidates(hits, f"'{sel}' matches {len(hits)} sessions — refine, or use the number")
    return (None, 2)


def do_resolve(sessions, sel):
    s, err = _match_session(sessions, sel)
    if err:
        return err
    print(f"{s['cwd']}\t{s['uuid']}")
    return 0


def do_delete(sessions, sel):
    s, err = _match_session(sessions, sel)
    if err:
        return err
    # Unique match — print tab-separated line for shell function to parse
    print(f"{s['path']}\t{s['uuid']}\t{s['cwd']}\t{s['summary']}")
    return 0


def do_set_name(sessions, sel, name):
    s, err = _match_session(sessions, sel)
    if err:
        return err
    name = " ".join(name.split())
    names = _load_names()
    names[s["uuid"]] = name
    _save_names(names)
    print(f"cs: name set for {s['uuid'][:8]} ({s['cwd']}) -> {name}", file=sys.stderr)
    return 0


def do_clear_name(sessions, sel):
    s, err = _match_session(sessions, sel)
    if err:
        return err
    names = _load_names()
    if s["uuid"] in names:
        del names[s["uuid"]]
        _save_names(names)
        print(f"cs: custom name cleared for {s['uuid'][:8]}", file=sys.stderr)
    else:
        print(f"cs: no custom name set for {s['uuid'][:8]}", file=sys.stderr)
    return 0


# --- cost analytics ---------------------------------------------------------
# Isolated from the session-navigation functions above: --cost does its own
# per-message scan of message.usage + line-level timestamp. parse_session and
# the list/resolve/delete/complete paths are not touched.

def _parse_ts(s):
    """Parse an ISO-8601 timestamp (trailing 'Z' allowed) to an aware UTC
    datetime, or None if unparseable."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_bound(s, end_of_day=False):
    """Parse a --since/--until bound to an aware LOCAL datetime, or None.
    Accepts YYYY-MM-DD (midnight, or 23:59:59 when end_of_day), an explicit
    YYYY-MM-DDTHH:MM:SS, or a relative Nd/Nh/Nm window from now."""
    if not s:
        return None
    s = s.strip()
    rel = re.match(r"^(\d+)([dhm])$", s)
    if rel:
        n = int(rel.group(1))
        field = {"d": "days", "h": "hours", "m": "minutes"}[rel.group(2)]
        return datetime.now(timezone.utc).astimezone() - timedelta(**{field: n})
    dt = None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    if end_of_day and len(s) == 10:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.astimezone()  # naive -> assumed local


def _human(n):
    """Compact int formatting: 12 / 1.2k / 3.4M."""
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _load_pricing():
    """Load per-model rates (USD per 1M tokens) from PRICING_FILE, or None.
    The file only needs entries that OVERRIDE the built-in estimates below."""
    try:
        with open(PRICING_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _builtin_rate(model):
    """Built-in USD-per-1M-token rates (ESTIMATES). Anthropic = published list
    price; DeepSeek/GLM = approximate, converted from provider list prices.
    Returns None for unknown models. Verify against your actual billing."""
    m = (model or "").lower()
    if "opus" in m:            # Anthropic Opus 4.5+ ($5/$25; cache read $0.50, 5m write $6.25)
        return {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_creation": 6.25}
    if "sonnet" in m:          # Anthropic Sonnet 4 family ($3/$15)
        return {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_creation": 3.75}
    if "haiku" in m:           # Anthropic Haiku 4.5 ($1/$5)
        return {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_creation": 1.25}
    if "deepseek" in m:        # DeepSeek V4-Pro tier (cache write ≈ input)
        return {"input": 1.74, "output": 3.48, "cache_read": 0.035, "cache_creation": 1.74}
    if m.startswith("glm-5"):  # ZhiPu GLM-5.2: ¥8/¥28 per 1M (cache hit promo-free)
        return {"input": 1.11, "output": 3.89, "cache_read": 0.0, "cache_creation": 1.11}
    if m.startswith("glm"):    # ZhiPu GLM-4.x: ¥0.8/¥2 per 1M
        return {"input": 0.11, "output": 0.28, "cache_read": 0.014, "cache_creation": 0.11}
    return None


def _effective_rate(pricing, model):
    """Config-file override wins; else the built-in estimate; else None."""
    if isinstance(pricing, dict) and isinstance(pricing.get(model), dict):
        return pricing[model]
    return _builtin_rate(model)


def _usd_for(u, rate):
    """USD cost of one (model) token-total dict given a rate dict (per 1M tokens)."""
    if not isinstance(rate, dict):
        return 0.0
    return (
        u["in"] / 1_000_000 * rate.get("input", 0)
        + u["out"] / 1_000_000 * rate.get("output", 0)
        + u["cache_read"] / 1_000_000 * rate.get("cache_read", 0)
        + u["cache_creation"] / 1_000_000 * rate.get("cache_creation", 0)
    )


def _scan_usage(path, since_dt=None, until_dt=None):
    """Scan one session's assistant messages; sum usage tokens per model.

    Returns (per_model, counted, total): per_model maps model -> {in, out,
    cache_read, cache_creation, msgs}; counted is messages inside [since_dt,
    until_dt] (all when no range); total is all messages regardless of range.

    A single assistant message is written as MULTIPLE .jsonl lines — one per
    content block (thinking / text / tool_use) — each carrying the SAME
    message.id and the SAME usage. Dedup by message.id so each logical message
    is counted exactly once (otherwise usage is inflated ~2-3x)."""
    per_model = {}
    counted = 0
    total = 0
    seen_ids = set()
    try:
        fh = open(path, "r", errors="replace")
    except OSError:
        return per_model, 0, 0
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") != "assistant":
                continue
            msg = o.get("message") or {}
            mid = msg.get("id")
            if mid:
                if mid in seen_ids:
                    continue  # duplicate block of an already-counted message
                seen_ids.add(mid)
            total += 1
            if since_dt or until_dt:
                ts = _parse_ts(o.get("timestamp"))
                if ts is None:
                    continue
                local = ts.astimezone()
                if since_dt and local < since_dt:
                    continue
                if until_dt and local > until_dt:
                    continue
            u = msg.get("usage")
            if not isinstance(u, dict):
                continue
            model = msg.get("model") or "unknown"
            b = per_model.setdefault(
                model, {"in": 0, "out": 0, "cache_read": 0, "cache_creation": 0, "msgs": 0}
            )
            b["in"] += int(u.get("input_tokens") or 0)
            b["out"] += int(u.get("output_tokens") or 0)
            b["cache_read"] += int(u.get("cache_read_input_tokens") or 0)
            b["cache_creation"] += int(u.get("cache_creation_input_tokens") or 0)
            b["msgs"] += 1
            counted += 1
    return per_model, counted, total


def _print_pricing_template(sessions, since_dt=None, until_dt=None):
    """Print a JSON pricing template of the models seen, for redirecting to
    PRICING_FILE. Returns 0."""
    models = set()
    for s in sessions:
        per_model, _, _ = _scan_usage(s["path"], since_dt, until_dt)
        models.update(per_model)
    template = {
        m: {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_creation": 0.0}
        for m in sorted(models)
    }
    print(json.dumps(template, indent=2, ensure_ascii=False))
    print(
        f"\n# USD per 1,000,000 tokens. Fill in your real rates and save to:\n#   {PRICING_FILE}",
        file=sys.stderr,
    )
    return 0


def do_cost(sessions, since_dt=None, until_dt=None, filt=None, by_model=False, print_pricing=False, width=72):
    """Print per-session token usage (+ optional USD) and totals, optionally
    restricted to messages within [since_dt, until_dt] (local time)."""
    if not sessions:
        print("No sessions found.")
        return 0
    if print_pricing:
        return _print_pricing_template(sessions, since_dt, until_dt)

    fl = filt.lower() if filt else None
    pricing = _load_pricing()
    have_usd = True  # built-in estimates always provide a $ column
    iw = len(str(len(sessions)))

    if since_dt or until_dt:
        lo = since_dt.strftime("%Y-%m-%d %H:%M") if since_dt else "begin"
        hi = until_dt.strftime("%Y-%m-%d %H:%M") if until_dt else "now"
        print(f"Cost  {lo}  →  {hi}  (local)\n")
    else:
        print("Session cost (all time)\n")

    grand = {"in": 0, "out": 0, "cache_read": 0, "cache_creation": 0, "msgs": 0}
    grand_usd = 0.0
    grand_total = 0
    model_totals = {}

    first = True
    for i, s in enumerate(sessions, 1):
        if (fl and fl not in s["cwd"].lower() and fl not in s["summary"].lower()
                and fl not in (s["custom_name"] or "").lower()):
            continue
        per_model, counted, total = _scan_usage(s["path"], since_dt, until_dt)
        grand_total += total
        if not per_model:
            continue
        su = {"in": 0, "out": 0, "cache_read": 0, "cache_creation": 0, "msgs": 0}
        usd = 0.0
        for model, u in per_model.items():
            for k in su:
                su[k] += u[k]
            if have_usd:
                usd += _usd_for(u, _effective_rate(pricing, model))
            mt = model_totals.setdefault(
                model, {"in": 0, "out": 0, "cache_read": 0, "cache_creation": 0, "msgs": 0, "usd": 0.0}
            )
            for k in ("in", "out", "cache_read", "cache_creation", "msgs"):
                mt[k] += u[k]
            if have_usd:
                mt["usd"] += _usd_for(u, _effective_rate(pricing, model))
        for k in grand:
            grand[k] += su[k]
        grand_usd += usd
        if not first:
            print()  # blank line between sessions
        first = False
        # Mirrors do_list (name / cwd+meta / desc), plus a token line + USD.
        name = " ".join((s["custom_name"] or s["first_user"] or "(no name)").split())
        if len(name) > width:
            name = name[: width - 1] + "…"
        usd_str = f"${usd:.2f}"
        usd_s = f"  {_c('1;92', usd_str)}" if have_usd else ""
        idx = _clr_meta(f"[{str(i).rjust(iw)}]")
        print(f"{idx} {_clr_name(name)}{usd_s}")
        branch = " " + _clr_meta("[" + s["git_branch"] + "]") if s["git_branch"] else ""
        meta = _clr_meta(f"· {su['msgs']} msg · {s['uuid'][:8]} · {fmt_when(s['modified'])}")
        print(f"    {_clr_cwd(s['cwd'])}{branch}  {meta}")
        cache = su["cache_read"] + su["cache_creation"]
        modelname = "mixed" if len(per_model) > 1 else next(iter(per_model))
        toks = f"{_human(su['in'])} in · {_human(su['out'])} out · {_human(cache)} cache"
        print(f"    {_clr_tok(toks)}  {_clr_meta(modelname[:24])}")
        if s["ai_title"]:
            d = " ".join(s["ai_title"].split())
            if len(d) > width:
                d = d[: width - 1] + "…"
            print(f"    {_clr_desc(d)}")

    cache = grand["cache_read"] + grand["cache_creation"]
    toks = f"{_human(grand['in'])} in · {_human(grand['out'])} out · {_human(cache)} cache"
    grand_usd_str = f"${grand_usd:.2f}"
    usd_s = f"  {_c('1;92', grand_usd_str)}" if have_usd else ""
    grand_msg = f"({grand['msgs']} msg)"
    print(f"\n{_clr_meta('TOTAL')}  {_clr_tok(toks)}  {_clr_meta(grand_msg)}{usd_s}")
    if (since_dt or until_dt) and grand_total:
        print(_clr_meta(f"({grand['msgs']} of {grand_total} assistant messages in range)"))

    if by_model and model_totals:
        print(f"\n{_clr_meta('By model:')}")
        for model in sorted(model_totals):
            mt = model_totals[model]
            cache = mt["cache_read"] + mt["cache_creation"]
            toks = f"{_human(mt['in'])} in · {_human(mt['out'])} out · {_human(cache)} cache"
            mt_usd_str = f"${mt['usd']:.2f}"
            usd_s = f"  {_c('1;92', mt_usd_str)}" if have_usd else ""
            msgbit = _clr_meta(f"({mt['msgs']} msg)")
            print(f"  {_clr_meta(model[:24])}  {_clr_tok(toks)}  {msgbit}{usd_s}")

    print(
        f"\n($) estimate = tokens × rates. Anthropic = list price; DeepSeek/GLM "
        f"= approximate (verify your provider). cache write uses the 5m rate. "
        f"Override per-model in {PRICING_FILE}."
    )
    return 0


def _print_candidates(sessions, msg):
    print(f"cs: {msg}:", file=sys.stderr)
    for s in sessions[:15]:
        sm = s["summary"]
        if len(sm) > 60:
            sm = sm[:59] + "…"
        print(f"    {s['uuid'][:8]}  {s['cwd']}  — {sm}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--resolve", metavar="SEL")
    g.add_argument("--complete", action="store_true")
    g.add_argument("--delete", "-d", metavar="SEL")
    g.add_argument("--cost", "-c", action="store_true")
    g.add_argument("--set-name", nargs=2, metavar=("SEL", "NAME"))
    g.add_argument("--clear-name", metavar="SEL")
    ap.add_argument("--filter", metavar="KW")
    ap.add_argument("--width", type=int, default=72)
    ap.add_argument("--since", metavar="DATE")
    ap.add_argument("--until", metavar="DATE")
    ap.add_argument("--by-model", action="store_true")
    ap.add_argument("--print-pricing", action="store_true")
    args = ap.parse_args()

    sessions = load_sessions()
    if args.complete:
        do_complete(sessions)
        return 0
    if args.list:
        do_list(sessions, args.width, args.filter)
        return 0
    if args.cost:
        since_dt = _parse_bound(args.since) if args.since else None
        until_dt = _parse_bound(args.until, end_of_day=True) if args.until else None
        if args.since and since_dt is None:
            print(f"cs: bad --since '{args.since}' (use YYYY-MM-DD or Nd/Nh)", file=sys.stderr)
            return 1
        if args.until and until_dt is None:
            print(f"cs: bad --until '{args.until}' (use YYYY-MM-DD or Nd/Nh)", file=sys.stderr)
            return 1
        return do_cost(sessions, since_dt, until_dt, args.filter, args.by_model, args.print_pricing, width=args.width)
    if args.set_name:
        return do_set_name(sessions, args.set_name[0], args.set_name[1])
    if args.clear_name:
        return do_clear_name(sessions, args.clear_name)
    if args.delete:
        return do_delete(sessions, args.delete)
    return do_resolve(sessions, args.resolve)


if __name__ == "__main__":
    sys.exit(main())
