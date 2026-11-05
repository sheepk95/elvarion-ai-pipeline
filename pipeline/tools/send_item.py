"""Write one item into a chat's inbox (11-lane pipeline). Publishes a fully written temporary file without overwriting an existing item.

Usage: python -I -B send_item.py --to <inbox folder> --from <sender> --kind <JOB|REVIEW-ASK|FINDINGS|TEST-ASK|WORKS|NOT-WORKS|GO|READY|Q|UP|DONE|BUG|FAULT|RETEST|PLAY|MERGED|RESUME|PAUSE>
                                 [--refs "<ids>"] (--body "<text>" | --body-file <path>)
Prints the item id and path. The id is <from>-<UTC>-<n>; the file is <UTC>-<from>-<n>.md.
A relative --to is resolved against the pipeline root (the parent of tools/), not the current folder.
Exit 0 sent (a WAITER DEAD / NO WAITER FILE / WAITER STATUS UNKNOWN line is advice, not a failure);
non-zero: nothing was published (bad argument, missing inbox, or the publish itself failed).
"""
import argparse
import os
import re
import sys
import tempfile
import time

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--to", required=True)
ap.add_argument("--from", dest="frm", required=True)
ap.add_argument("--kind", required=True, choices="JOB REVIEW-ASK FINDINGS TEST-ASK WORKS NOT-WORKS GO READY Q UP DONE BUG FAULT RETEST PLAY MERGED RESUME PAUSE".split())
ap.add_argument("--refs", default="")
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--body")
g.add_argument("--body-file")
a = ap.parse_args()
if not re.fullmatch(r"[A-Za-z0-9 ._-]+", a.frm) or ".." in a.frm:    # --from becomes part of a file name
    sys.exit(f"ERROR: --from {a.frm!r}: use letters, digits, space, dot, dash and underscore only, and no '..'")
# --refs is one header line; a line break could forge another header. Readers split with str.splitlines(), which also
# breaks on \v \f \x1c-\x1e \x85 U+2028 U+2029, so refuse any separator splitlines() knows (the appended "x" makes a
# trailing one split too), and NUL.
if len((a.refs + "x").splitlines()) != 1 or "\x00" in a.refs:
    sys.exit("ERROR: --refs must be a single line (no line breaks or line separators, no NUL)")
if not os.path.isabs(a.to):     # a relative --to is relative to the pipeline root (parent of tools/), not the cwd
    a.to = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), a.to)
if not os.path.isdir(a.to):
    sys.exit(f"ERROR: no inbox folder {a.to}")
# An inbox holding role subfolders (e.g. lanes/integrator/inbox/builder) is not an inbox: an item there is never seen
# (a sender once wrote into lanes/integrator/inbox and the item sat unread).
subs = [d for d in os.listdir(a.to) if os.path.isdir(os.path.join(a.to, d)) and not d.startswith((".", "__"))]
if subs:
    sys.exit(f"ERROR: {a.to} holds role subfolders {sorted(subs)}: send to one of them")
body = a.body if a.body is not None else open(a.body_file, encoding="utf-8").read()
u = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
n = 1
while True:
    iid, name = f"{a.frm}-{u}-{n}", f"{u}-{a.frm}-{n}.md"
    text = f"id: {iid}\nkind: {a.kind}\nfrom: {a.frm}\nrefs: {a.refs}\n\n{body.rstrip()}\n"
    fd, tmp = tempfile.mkstemp(prefix=".send-item-", suffix=".tmp", dir=a.to)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        try:
            os.link(tmp, os.path.join(a.to, name))
        except FileExistsError:
            n += 1
            continue
        except OSError as e:    # e.g. FAT or some network drives: no hard links, so nothing can be published here
            sys.exit(f"ERROR: cannot publish into {a.to} ({e}); the inbox needs a filesystem with hard links")
        break
    finally:
        try:
            os.unlink(tmp)
        except OSError as exc:
            # Publication is already complete if link() succeeded. A cleanup failure
            # must not turn a delivered item into a failed send and invite a retry.
            print(f"WARNING: could not remove temporary file {tmp}: {exc}", file=sys.stderr)
print(f"sent {iid} -> {os.path.join(a.to, name)}")
# A .waiter.pid whose process is gone means the receiving chat is asleep (an app restart or account switch killed its
# waiter): this item will not wake it. tools/switch_census.py names the chat to wake (RULES.md "Account switch").
pid_p = os.path.join(a.to, ".waiter.pid")
if os.path.exists(pid_p) and os.name != "nt":
    print("WAITER STATUS UNKNOWN: process liveness check is supported on Windows only")
elif os.path.exists(pid_p):
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    try:
        h = k.OpenProcess(0x1000, False, int(open(pid_p).read().strip()))
    except (ValueError, OSError):  # the waiter may delete the file between exists and open
        h = 0
    code = wintypes.DWORD()
    up = bool(h) and k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259
    if up:      # as switch_census.py: the pid must be a python process, not a reused pid
        buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        up = not k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) or "python" in buf.value.lower()
    if h:
        k.CloseHandle(h)
    if not up:
        print("WAITER DEAD: the receiving chat is asleep; tell the Coordinator by Q (the desk chat wakes the Coordinator); tools/switch_census.py names the WAKE id")
else:
    print("NO WAITER FILE: chat not started or mid-turn")
