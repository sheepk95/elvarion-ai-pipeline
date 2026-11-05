"""Inbox waiter (11-lane pipeline). Run in the background as the last step of a waiting turn; it exits when a new
item lands, which wakes the idle chat.

Usage: python -I -B wait_inbox.py <inbox folder> [--timeout 7200]
Exit 0: prints NEW ITEMS and their paths; it does NOT write <inbox>/.seen: the chat appends each item's file name there
once it has handled the item, so an item is "unread" (switch_census.py) and wakes a restarted waiter until then. Exit 2: timeout, nothing new: start it
again. Only items count: files named <UTC>-<from>-<n>.md (writers publish a closed temporary file atomically). Notes such as ACKS.md
never wake the chat (an early trial woke on its own ack file).
"""
import argparse
import atexit
import os
import re
import sys
import time
import importlib.util

spec = importlib.util.spec_from_file_location("waiter_identity", os.path.join(os.path.dirname(__file__), "waiter_identity.py"))
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)

ITEM = re.compile(r"^\d{8}T\d{6}Z-.+-\d+\.md$")
ap = argparse.ArgumentParser()
ap.add_argument("inbox")
ap.add_argument("--timeout", type=int, default=7200)
a = ap.parse_args()
seen_path = os.path.join(a.inbox, ".seen")
seen = set(open(seen_path, encoding="utf-8-sig").read().splitlines()) if os.path.exists(seen_path) else set()
pid_path = os.path.join(a.inbox, ".waiter.pid")
with identity.registration_lock(a.inbox):
    previous = identity.status(a.inbox)
    if previous == "UNKNOWN":
        # A legacy/malformed registration may still name a live process; only
        # replace it when the OS can prove that PID is gone.
        try:
            with open(pid_path) as fh:
                old_pid = int(fh.read().strip())
            if not 0 < old_pid <= 0xffffffff or identity.creation(old_pid)[0] != "DEAD":
                sys.exit("wait_inbox: existing waiter identity unknown; resolve it before re-arming")
        except (OSError, ValueError):
            sys.exit("wait_inbox: existing waiter identity unknown; resolve it before re-arming")
    elif previous == "ARMED":
        sys.exit("wait_inbox: an existing waiter is still armed")
    with open(pid_path, "w") as fh:
        fh.write(str(os.getpid()))
    record = identity.register(a.inbox)

def cleanup():
    with identity.registration_lock(a.inbox):
        try:
            with open(pid_path) as fh:
                own = fh.read().strip() == str(os.getpid())
            if own:
                os.remove(pid_path)
                if record is not None:
                    identity_path = os.path.join(a.inbox, ".waiter.identity")
                    try:
                        import json
                        with open(identity_path, encoding="utf-8") as fh:
                            same = json.load(fh) == record
                        if same:
                            os.remove(identity_path)
                    except (OSError, ValueError):
                        pass
        except OSError:
            pass
atexit.register(cleanup)
end = time.time() + a.timeout
while time.time() < end:
    new = sorted(f for f in os.listdir(a.inbox) if ITEM.match(f) and f not in seen)
    if new:
        print("NEW ITEMS:")
        print("\n".join(os.path.join(a.inbox, f) for f in new))
        sys.exit(0)
    time.sleep(2)
print("TIMEOUT: no new items; start the waiter again")
sys.exit(2)
