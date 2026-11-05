"""Print what lane chats added to desk/updates/ since the desk chat's last read, then mark it read.

Usage: python -B -I desk_read.py [--peek] [--root DIR]
  --peek   print without moving the read offsets
Run it on every wake, log each new [DESK Q] in QUEUE.md and each [DESK UPDATE] in your own state file's lane table,
then re-arm desk_watch.py. Exit 0 always; the last line counts new questions and updates.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desk_files  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--peek', action='store_true')
    ap.add_argument('--root')
    a = ap.parse_args()
    p = desk_files.paths(a.root)
    offsets = desk_files.load_offsets(p)
    questions = updates = 0
    for name in desk_files.lane_files(p):
        lines, end, note = desk_files.new_lines(p, name, offsets)
        if note:
            print('!! %s: %s' % (name, note))
        if lines:
            print('== %s (%d new lines)' % (name, len(lines)))
            for line in lines:
                print(line)
                questions += desk_files.kind(line) == 'Q'
                updates += desk_files.kind(line) == 'U'
        offsets[name] = end
    if not a.peek:
        desk_files.save_offsets(p, offsets)
    print('desk_read: %d new [DESK Q], %d new [DESK UPDATE]%s' % (questions, updates, ' (peek)' if a.peek else ''))


if __name__ == '__main__':
    main()
