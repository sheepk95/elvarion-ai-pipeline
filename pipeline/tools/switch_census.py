"""After an account switch (or any app restart): which pipeline chats lost their inbox waiter, and which to wake.

A pipeline may need to survive rotating to a different account. A switch restarts the app, which kills
every chat's background waiter (wait_inbox.py) without running its exit code, so its .waiter.pid stays behind with a
dead process. The chat then sleeps and new items pile up until a message reaches it.

Windows only (ctypes process checks); the chat list is read from the Claude desktop app's session folder under
%LOCALAPPDATA%.

Usage: python -I -B switch_census.py [--root <pipeline root; default = the parent of tools/>] [--all]
                                     [--account-pairs <json file>] [--cwd-marker <text>]
  --account-pairs: optional JSON file mapping an account e-mail (the CLAUDE_CODE_USER_EMAIL environment variable)
  to the folder name of that account's session pair; without it, the pair written last is used.
  --cwd-marker: a chat counts as a pipeline chat when its working folder contains this text (default: the name
  of the pipeline root folder).
  One line per inbox: chat title, session id (from this account's sidebar list), waiter ARMED (matching PID and
  process creation time), DEAD (process exited or identity differs), UNKNOWN (identity unavailable or legacy PID-only),
  or NONE (no pid file: the chat is mid-turn, or was stopped mid-turn), unread items and the oldest age.
  WAKE lines: chats whose waiter is DEAD, UNKNOWN or NONE and that have unread items (--all: every such chat). Send each
  one SendMessage to its id: "wake: account switch; re-read RULES.md 'Account switch', then your inbox; re-arm your
  waiter; if PAUSED, note new items in your HANDOVER note and .seen, and do not re-arm". Exit 0: nothing to wake; 4:
  WAKE lines printed; 5: unread items have no matching chat (takes precedence over 4).
"""
import argparse
import glob
import json
import os
import re
import sys
import time

ITEM = re.compile(r"^\d{8}T\d{6}Z-.+-\d+\.md$")
ap = argparse.ArgumentParser()
ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ap.add_argument("--all", action="store_true")
ap.add_argument("--account-pairs", default="")
ap.add_argument("--cwd-marker", default="")
a = ap.parse_args()
if os.name != "nt":
    sys.exit("switch_census.py: Windows and the Claude desktop app only (it reads the app's session folder and "
             "checks waiter processes with Windows APIs); wake CLI chats by hand")
import importlib.util
spec = importlib.util.spec_from_file_location("waiter_identity", os.path.join(os.path.dirname(__file__), "waiter_identity.py"))
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)
CWD_MARKER = a.cwd_marker or os.path.basename(os.path.normpath(a.root))


def waiter(inbox):
    return identity.status(inbox)


def sessions():
    """Open chats in THIS account's sidebar list: title -> local id. The account's pair comes from the optional
    --account-pairs map (account e-mail -> pair folder), else the pair written last."""
    # Undocumented desktop-app storage: the layout may change between app versions, and CLI sessions are not listed.
    base = os.environ.get("LOCALAPPDATA", "")
    roots = glob.glob(os.path.join(base, "Claude-Data", "claude_*", "claude-code-sessions")) if base else []
    if len(roots) != 1:
        return {}, "(no single session root)"
    pairs = [d for d in glob.glob(os.path.join(roots[0], "*", "*")) if glob.glob(os.path.join(d, "local_*.json"))]
    if not pairs:
        return {}, "(no session pair holds any chat)"
    amap_p = a.account_pairs
    amap = {}
    if amap_p and os.path.exists(amap_p):
        try:
            with open(amap_p, encoding="utf-8-sig") as fh:
                amap = json.load(fh)
            if not isinstance(amap, dict) or not all(isinstance(v, str) for v in amap.values()):
                raise ValueError("not a JSON object of e-mail -> folder name strings")
        except (OSError, ValueError) as e:
            print("WARNING: --account-pairs %s unreadable (%s); ignoring it" % (amap_p, e))
            amap = {}
    email = os.environ.get("CLAUDE_CODE_USER_EMAIL", "")
    pair = next((d for d in pairs if email in amap and os.path.normpath(d).endswith(os.path.normpath(amap[email]))), None)
    pair = pair or max(pairs, key=lambda d: max(os.path.getmtime(f) for f in glob.glob(os.path.join(d, "local_*.json"))))
    idx_p = os.path.join(pair, "archived-sessions.idx")
    arch = set()
    if os.path.exists(idx_p):
        try:
            with open(idx_p, encoding="utf-8-sig") as fh:
                listed = json.load(fh)["archived"]
            if not isinstance(listed, list) or not all(isinstance(x, str) for x in listed):
                raise ValueError("'archived' is not a list of session ids")
            arch = set(listed)
        except (OSError, ValueError, KeyError, TypeError) as e:
            print("WARNING: %s unreadable (%s); archived chats are not filtered out" % (idx_p, e))
    out = {}
    for f in glob.glob(os.path.join(pair, "local_*.json")):
        cid = os.path.basename(f)[:-5]
        try:
            with open(f, encoding="utf-8") as fh:
                j = json.load(fh)
            if not isinstance(j, dict):
                raise ValueError("not a JSON object")
            for key in ("title", "cwd"):
                if j.get(key) is not None and not isinstance(j[key], str):
                    raise ValueError("%r is %s, not a string" % (key, type(j[key]).__name__))
        except (OSError, ValueError) as e:   # one unreadable session file must not hide every other chat
            print("WARNING: skipped unreadable session file %s: %s" % (f, e))
            continue
        if cid not in arch and not j.get("isArchived") and CWD_MARKER in (j.get("cwd") or ""):
            out[j.get("title") or ""] = cid
    return out, os.path.relpath(pair, roots[0])


chats, pair = sessions()
rows = [(os.path.join(a.root, "coordinator", "inbox"), ["Coordinator"])]
for lane in sorted(glob.glob(os.path.join(a.root, "lanes", "*"))):
    head = ""
    if os.path.exists(os.path.join(lane, "LANE.md")):
        with open(os.path.join(lane, "LANE.md"), encoding="utf-8-sig", errors="replace") as fh:
            head = fh.readline()
    m = re.match(r"#\s*LANE:\s*(.+?)\s*\(", head)
    title = m.group(1) if m else os.path.basename(lane)
    for inbox in sorted(glob.glob(os.path.join(lane, "inbox", "*"))):
        role = os.path.basename(inbox)
        rows.append((inbox, ["%s %s" % (title, role), title]))
now, wake, unresolved = time.time(), [], False
print("account pair %s | %d open pipeline chats in its sidebar list" % (pair, len(chats)))
for inbox, names in rows:
    if not os.path.isdir(inbox):
        continue
    seen_p = os.path.join(inbox, ".seen")
    seen = set()
    if os.path.exists(seen_p):
        with open(seen_p, encoding="utf-8-sig", errors="replace") as fh:
            seen = set(fh.read().splitlines())
    unread = [f for f in os.listdir(inbox) if ITEM.match(f) and f not in seen]
    age = (now - min(os.path.getmtime(os.path.join(inbox, f)) for f in unread)) / 60 if unread else 0
    title = next((n for n in names if n in chats), None)
    sid = chats.get(title, "-") if title else "-"
    w = waiter(inbox)
    print("%-36s %-44s waiter %-5s unread %d%s" % ((title or names[0])[:36], sid, w, len(unread),
                                                   " (oldest %.0f min)" % age if unread else ""))
    if w != "ARMED" and title and (unread or a.all):
        wake.append((title, sid, len(unread)))
    if unread and not title:
        print("   NO CHAT: %s has %d unread items and no open chat titled %s" % (inbox, len(unread), " / ".join(names)))
        unresolved = True
for title, sid, n in wake:
    print("WAKE %s %s (%d unread): SendMessage \"wake: account switch; re-read RULES.md 'Account switch', then your inbox;"
          " re-arm your waiter; if PAUSED, note new items in your HANDOVER note and .seen, and do not re-arm\""
          % (sid, title, n))
sys.exit(5 if unresolved else 4 if wake else 0)
