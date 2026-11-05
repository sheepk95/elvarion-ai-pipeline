"""After an account switch (or any app restart): which pipeline chats lost their inbox waiter, and which to wake.

A pipeline may need to survive rotating to a different account. A switch restarts the app, which kills
every chat's background waiter (wait_inbox.py) without running its exit code, so its .waiter.pid stays behind with a
dead process. The chat then sleeps and new items pile up until a message reaches it.

Windows only (ctypes process checks); the chat list is read from the Claude desktop app's session folder under
%LOCALAPPDATA%.

Usage: python -I -B switch_census.py [--root <pipeline root; default = the parent of tools/>] [--all]
                                     [--account-pairs <json file>] [--cwd-marker <text>]
  --account-pairs: required JSON file mapping the CLAUDE_CODE_USER_EMAIL account to its relative pair path
  (e.g. account/org). Missing or unresolved mappings fail closed (exit 5). Duplicate titles and session IDs
  matching multiple inboxes are unresolved (exit 5).
  --cwd-marker: optional additional text filter; working folders must also be the canonical root or a descendant.
  One line per inbox: chat title, session id (from this account's sidebar list), waiter ARMED (matching PID and
  process creation time), DEAD (process exited or identity differs), UNKNOWN (identity unavailable or legacy PID-only),
  or NONE (no pid file: the chat is mid-turn, or was stopped mid-turn), unread items and the oldest age.
  WAKE lines: chats whose waiter is DEAD, UNKNOWN or NONE and that have unread items (--all: every such chat). Send each
  one SendMessage to its id: "wake: account switch; re-read RULES.md 'Account switch', then your inbox; re-arm your
  waiter; if PAUSED, note new items in your HANDOVER note and .seen, and do not re-arm". Exit 0: nothing to wake; 4:
  WAKE lines printed; 5: unresolved account, metadata, title or unread item (takes precedence over 4).
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
def in_root(cwd):
    if not cwd or not os.path.isabs(cwd):
        return False
    root = os.path.normcase(os.path.realpath(a.root))
    path = os.path.normcase(os.path.realpath(cwd))
    try:
        return os.path.commonpath([root, path]) == root and (not a.cwd_marker or a.cwd_marker in cwd)
    except ValueError:
        return False


def waiter(inbox):
    return identity.status(inbox)


def sessions():
    """Open chats in THIS account's sidebar list: title -> local id from the required account map."""
    # Undocumented desktop-app storage: the layout may change between app versions, and CLI sessions are not listed.
    base = os.environ.get("LOCALAPPDATA", "")
    roots = glob.glob(os.path.join(base, "Claude-Data", "claude_*", "claude-code-sessions")) if base else []
    if len(roots) != 1:
        return {}, "(no single session root)"
    pairs = [d for d in glob.glob(os.path.join(roots[0], "*", "*")) if glob.glob(os.path.join(d, "local_*.json"))]
    if not pairs:
        return {}, "(no session pair holds any chat)"
    amap_p = a.account_pairs
    if amap_p:
        try:
            with open(amap_p, encoding="utf-8-sig") as fh:
                amap = json.load(fh)
            if not isinstance(amap, dict) or not all(isinstance(v, str) for v in amap.values()):
                raise ValueError("not a JSON object of e-mail -> folder name strings")
            email = os.environ.get("CLAUDE_CODE_USER_EMAIL", "")
            if not email or email not in amap:
                raise ValueError("current account has no mapping")
            # Match a complete relative pair path, not a suffix of another account.
            mapped = os.path.normcase(os.path.normpath(amap[email]))
            matches = [d for d in pairs if os.path.normcase(os.path.normpath(os.path.relpath(d, roots[0]))) == mapped]
            if len(matches) != 1:
                raise ValueError("mapped pair has no sessions or is ambiguous")
            pair = matches[0]
        except (OSError, ValueError) as e:
            print("WARNING: --account-pairs %s unresolved (%s)" % (amap_p, e))
            return {}, "(account mapping unresolved)"
    else:
        return {}, "(account mapping unresolved)"
    idx_p = os.path.join(pair, "archived-sessions.idx")
    arch = set()
    damaged = False
    if os.path.exists(idx_p):
        try:
            with open(idx_p, encoding="utf-8-sig") as fh:
                listed = json.load(fh)["archived"]
            if not isinstance(listed, list) or not all(isinstance(x, str) for x in listed):
                raise ValueError("'archived' is not a list of session ids")
            arch = set(listed)
        except (OSError, ValueError, KeyError, TypeError) as e:
            print("WARNING: %s unreadable (%s); routing suppressed" % (idx_p, e))
            damaged = True
    out = {}
    for f in glob.glob(os.path.join(pair, "local_*.json")):
        cid = os.path.basename(f)[:-5]
        try:
            with open(f, encoding="utf-8") as fh:
                j = json.load(fh)
            if not isinstance(j, dict):
                raise ValueError("not a JSON object")
            for key in ("title", "cwd"):
                if not isinstance(j.get(key), str) or not j[key]:
                    raise ValueError("%r is missing, empty or not a string" % key)
            if "isArchived" in j and type(j["isArchived"]) is not bool:
                raise ValueError("isArchived is not a boolean")
        except (OSError, ValueError) as e:   # one unreadable session file must not hide every other chat
            print("WARNING: skipped unreadable session file %s: %s; routing suppressed" % (f, e))
            damaged = True
            continue
        if cid not in arch and not j.get("isArchived") and in_root(j.get("cwd") or ""):
            title = j.get("title") or ""
            if title in out:
                out[title] = None  # ambiguous: never select either session
            else:
                out[title] = cid
    if damaged:
        return {}, "(session metadata unresolved)"
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
# Resolve every inbox first, including empty ones. A chat may serve exactly one inbox.
resolved = {}
owners = {}
for inbox, names in rows:
    if not os.path.isdir(inbox):
        continue
    title = next((n for n in names if n in chats), None)
    sid = chats.get(title) if title else None
    resolved[inbox] = (title, sid)
    if sid:
        owners.setdefault(sid, []).append(inbox)

now, wake, unresolved = time.time(), [], pair in {"(account mapping unresolved)", "(no single session root)",
    "(no session pair holds any chat)", "(multiple populated account pairs; mapping required)",
    "(session metadata unresolved)"}
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
    title, sid = resolved[inbox]
    if sid and len(owners[sid]) > 1:
        print("   AMBIGUOUS INBOX: session %s maps to %d inboxes" % (sid, len(owners[sid])))
        unresolved = True
        title, sid = None, None
    elif title and sid is None:
        print("   AMBIGUOUS CHAT: %s has multiple open sessions" % title)
        unresolved = True
        title = None
    sid = sid or "-"
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
