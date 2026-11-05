"""Sleep until a UTC time, then exit with a WAKE line, so a Claude chat that ran this as a background Bash job wakes up.

A pipeline needs a script that wakes the desk chat after the 5-hour usage limit resets, so it can carry on with the
lane chats and then set another waker for the next window.

Why it works: a background Bash job's exit wakes an idle Claude chat. A chat that hit
the 5-hour limit sits idle after its failed turn; this job exits after the reset, the chat gets a new turn and the API
works again.

Usage (Bash tool, run_in_background true, timeout a little longer than the wait):
    python -B -I <DESK_ROOT>/tools/limit_waker.py --at 2026-01-01T15:05:00Z --label "desk chat"
    python -B -I ... --in-minutes 300 --label "next window"
Prints its plan at start, a heartbeat line every 30 min, and "WAKE <label> <UTC>" at the end. Exit 0 on time; exit 2 if
the target is already past (it still prints WAKE, so the chat wakes at once).
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone


def parse_utc(s):
    s = s.strip().replace("Z", "+00:00")
    t = datetime.fromisoformat(s)
    if t.tzinfo is None:
        raise SystemExit("--at needs a UTC time with Z or an offset, e.g. 2026-01-01T15:05:00Z")
    return t.astimezone(timezone.utc)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--at", help="UTC time to wake, e.g. 2026-01-01T15:05:00Z")
    g.add_argument("--in-minutes", type=float, help="wake this many minutes from now")
    ap.add_argument("--label", default="waker")
    ap.add_argument("--heartbeat-min", type=float, default=30)
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    target = parse_utc(a.at) if a.at else now + timedelta(minutes=a.in_minutes)
    print(f"limit_waker {a.label}: now {now:%Y-%m-%dT%H:%M:%SZ}, wake at {target:%Y-%m-%dT%H:%M:%SZ} "
          f"({(target - now).total_seconds() / 60:.1f} min)", flush=True)
    if target <= now:
        print(f"WAKE {a.label} {now:%Y-%m-%dT%H:%M:%SZ} (target already past)", flush=True)
        sys.exit(2)
    next_beat = time.time() + a.heartbeat_min * 60
    while True:
        left = (target - datetime.now(timezone.utc)).total_seconds()
        if left <= 0:
            break
        time.sleep(min(left, 60))
        if time.time() >= next_beat:
            print(f"  waiting, {left / 60:.0f} min left", flush=True)
            next_beat += a.heartbeat_min * 60
    print(f"WAKE {a.label} {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}", flush=True)


if __name__ == "__main__":
    main()
