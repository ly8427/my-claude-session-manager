#!/usr/bin/env python3
"""cs - Claude Sessions browser/resumer backend.

Scans ~/.claude/projects/*/*.jsonl and either:
  --list             print a numbered table (cwd, UUID, summary)
  --resolve <sel>    resolve a selector to "<cwd>\t<uuid>" on stdout
  --delete <sel>     resolve a selector and print "<path>\t<uuid>\t<cwd>\t<summary>"
  --complete         emit tab-completion candidates

Selector may be:
  - an index from the most recent --list (1-based, modified desc)
  - a session UUID or unique UUID prefix
  - a case-insensitive substring matching exactly one session's cwd or summary
On ambiguity/no-match, prints candidates to stderr and exits non-zero.
"""
import json
import os
import sys
import glob
import argparse
from datetime import datetime, timezone

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


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
    }


def load_sessions():
    files = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
    sessions = [parse_session(p) for p in files]
    sessions.sort(key=lambda s: s["modified"], reverse=True)
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
    # Global index (i) is preserved even when filtering, so `cs <i>` stays valid.
    for i, s in enumerate(sessions, 1):
        if fl and fl not in s["cwd"].lower() and fl not in s["summary"].lower():
            continue
        shown += 1
        summary = s["summary"]
        if len(summary) > width:
            summary = summary[: width - 1] + "…"
        branch = f"  [{s['git_branch']}]" if s["git_branch"] else ""
        print(f"[{str(i).rjust(iw)}] {fmt_when(s['modified'])}  {s['uuid']}")
        print(f"{' ' * (iw + 3)}cwd : {s['cwd']}{branch}  ({s['messages']} msgs)")
        print(f"{' ' * (iw + 3)}desc: {summary}")
    if fl:
        print(f"\nShown: {shown}/{n} matching '{filt}'   |   resume with:  cs <number>")
    else:
        print(f"\nTotal: {n} session(s)   |   resume with:  cs <number>")


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
    ap.add_argument("--filter", metavar="KW")
    ap.add_argument("--width", type=int, default=72)
    args = ap.parse_args()

    sessions = load_sessions()
    if args.complete:
        do_complete(sessions)
        return 0
    if args.list:
        do_list(sessions, args.width, args.filter)
        return 0
    if args.delete:
        return do_delete(sessions, args.delete)
    return do_resolve(sessions, args.resolve)


if __name__ == "__main__":
    sys.exit(main())
