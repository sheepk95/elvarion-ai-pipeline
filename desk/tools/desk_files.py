"""Shared helpers for the desk chat's desk files.

Lane chats append [DESK UPDATE] and [DESK Q] lines to updates/<session id>.md. The desk chat keeps one byte offset per
file in tools/state/read-offsets.json: desk_read.py prints and consumes what is new, desk_watch.py only looks.
Only whole lines (up to the last newline) count, so a half-written line waits for its newline.
"""
import json
import os

DESK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def paths(root=None):
    root = os.path.abspath(root or DESK)
    return {
        'root': root,
        'updates': os.path.join(root, 'updates'),
        'state': os.path.join(root, 'tools', 'state'),
        'offsets': os.path.join(root, 'tools', 'state', 'read-offsets.json'),
        'alive': os.path.join(root, 'tools', 'state', 'watch.alive'),
        'stop': os.path.join(root, 'tools', 'state', 'STOP-WATCH'),
    }


def load_offsets(p):
    try:
        with open(p['offsets'], encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_offsets(p, offsets):
    os.makedirs(p['state'], exist_ok=True)
    tmp = p['offsets'] + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(offsets, f, indent=1, sort_keys=True)
    os.replace(tmp, p['offsets'])


def lane_files(p):
    if not os.path.isdir(p['updates']):
        return []
    return sorted(n for n in os.listdir(p['updates'])
                  if n.endswith('.md') and n.lower() != 'readme.md' and not n.startswith('.'))


def new_lines(p, name, offsets):
    """Return (lines, new_offset, note) for the whole lines added to one lane file since its offset."""
    path = os.path.join(p['updates'], name)
    size = os.path.getsize(path)
    start = offsets.get(name, 0)
    note = ''
    if start > size:
        note = 'file shrank from %d to %d bytes (rewritten?): reading it again from the start' % (start, size)
        start = 0
    with open(path, 'rb') as f:
        f.seek(start)
        data = f.read(size - start)
    cut = data.rfind(b'\n')
    if cut < 0:
        return [], start, note
    chunk = data[:cut + 1]
    text = chunk.decode('utf-8', errors='replace')
    return [l.rstrip('\r') for l in text.split('\n')[:-1]], start + len(chunk), note


def kind(line):
    """'Q' or 'U' when the line starts with [DESK Q] or [DESK UPDATE] (after a BOM or spaces), else ''.
    A line that only mentions "[DESK Q]" in its text, such as an update about an earlier question, is not one."""
    s = line.lstrip('\ufeff \t')
    return 'Q' if s.startswith('[DESK Q]') else 'U' if s.startswith('[DESK UPDATE]') else ''
