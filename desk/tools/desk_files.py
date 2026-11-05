"""Shared helpers for the desk chat's desk files.

Lane chats append [DESK UPDATE] and [DESK Q] lines to updates/<session id>.md. The desk chat keeps one byte offset per
file in tools/state/read-offsets.json: desk_read.py prints and consumes what is new, desk_watch.py only looks.
Only whole lines (up to the last newline) count, so a half-written line waits for its newline.
A corrupt read-offsets.json is warned about and read as "no offsets" (everything is shown again, nothing is skipped);
the next desk_read keeps it as read-offsets.json.corrupt-<UTC> before writing a good one.
"""
import json
import os
import shutil
import sys
import time

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


def _offsets_problem(path):
    """None when read-offsets.json is absent or a JSON object of byte offsets, else a short reason (unreadable or
    corrupt, not an object, holding a value that is not an offset)."""
    try:
        with open(path, encoding='utf-8') as f:
            obj = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError) as e:   # UnicodeDecodeError and JSONDecodeError are ValueErrors
        return 'unreadable (%s)' % type(e).__name__
    if not isinstance(obj, dict):
        return 'not a JSON object'
    return None if all(_good_offset(v) for v in obj.values()) else 'holding bad offsets'


def _good_offset(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def load_offsets(p, warn=None):
    """The byte offset per lane file; {} when the file is absent.
    A corrupt, unreadable or non-object read-offsets.json (or a bad entry in it) is warned about on stderr, naming the
    file, and counts as no offset: every lane file (or that entry's file) is read again from byte 0. That re-shows old
    questions and updates (noisy) but never skips one (lossy): a question the desk chat sees twice costs a QUEUE.md
    look-up, a question it never sees is lost. Nothing is written here; save_offsets keeps a copy of a corrupt file
    before it replaces it. warn: an optional set that gets the message instead of stderr (desk_watch's WARN, printed
    with every exit's output and counted as 'degraded', so a 15 s poll loop does not fill its log with copies)."""
    def say(msg):
        msg = 'WARNING %s %s' % (p['offsets'], msg)
        if warn is None:
            print(msg, file=sys.stderr, flush=True)
        else:
            warn.add(msg)
    try:
        with open(p['offsets'], encoding='utf-8') as f:
            obj = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError) as e:
        say('unreadable (%s): every lane file is read again from the start' % type(e).__name__)
        return {}
    if not isinstance(obj, dict):
        say('is not a JSON object: every lane file is read again from the start')
        return {}
    good = {k: v for k, v in obj.items() if _good_offset(v)}
    bad = sorted(set(obj) - set(good))
    if bad:
        say('has %d bad offset(s) (%s): those files are read again from the start' % (len(bad), ', '.join(bad)[:200]))
    return good


def save_offsets(p, offsets):
    os.makedirs(p['state'], exist_ok=True)
    why = _offsets_problem(p['offsets'])
    if why:   # never replace a corrupt file silently: keep it beside the new one
        keep = '%s.corrupt-%s' % (p['offsets'], time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
        try:
            shutil.copy2(p['offsets'], keep)
            print('WARNING %s was %s: kept as %s before writing new offsets' % (p['offsets'], why, keep),
                  file=sys.stderr, flush=True)
        except OSError as e:
            print('WARNING %s was %s and no copy could be kept (%s): it is replaced now' % (
                p['offsets'], why, type(e).__name__), file=sys.stderr, flush=True)
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
