"""Wait until a lane chat writes a new [DESK Q] line into desk/updates/, then exit so the desk chat wakes.

Usage (the desk chat, a background shell job, run_in_background, timeout 7200000):
  python -B -I <DESK_ROOT>/tools/desk_watch.py [--interval 15] [--max-seconds 6900]
Exit 0: a new [DESK Q] is waiting (run desk_read.py, handle it, re-arm). Exit 2: max-seconds passed with none
(re-arm). Exit 3: the STOP-WATCH file exists (tools/state/STOP-WATCH; delete it before re-arming).
Exit 4: another watcher touched watch.alive within the last 3 intervals. It never moves the read offsets.
Exit 5: a pipeline inbox has a dead waiter and an item waiting >15 min. Watched: coordinator/inbox, each
lanes/<slug>/inbox and each role folder lanes/<slug>/inbox/<role>. With the shipped waiter
(pipeline/tools/wait_inbox.py) a waiter is considered unavailable when its PID and creation identity do not match, or identity is unknown. A
waiter that writes .waiter-arm and .waiter-heartbeat is dead when the heartbeat is >10 min old, the arm id is stale
or the arm says 'cleared'. An item is handled once its file name is in the inbox's .seen, or its id is done or
parked in ACKS.md. Skipped while the receiver wrote ACKS.md or .seen in the last 10 min (busy on the item its
waiter woke it for), and for a cleared chat whose self-clear handover is still open (exit 6 owns that episode).
A chat that works on one item for over 15 min without touching .seen or ACKS.md also trips exit 5: the recovery
message then just waits in its queue.
Exit 6: a self-clear [DESK HANDOVER] line, stamped at or after the go-live cutoff, has no
'[DESK UPDATE] <title> RESUMED' line 15 min later. The cutoff is --since, else tools/state/exit6-since.txt, which the
first run writes once, so self-clears from before go-live never fire.
Every exit 5/6 line ends 'key=<key>' (no spaces). The desk chat writes that key in recovery-sent.md before it sends
its recovery message. Both exits skip a key already there, except once 15 min after its message (a STUCK line). A key
that was alerted but is not in recovery-sent.md is raised again only after --report-again-s (default 1800), so an
alert nobody records cannot wake the desk chat in a loop.
Options: --pipeline-root DIR (default: the PIPELINE_ROOT environment variable), --since UTC, --handover-max-age-hours H (opt-in, no
default limit), --resumed-any-update (opt-in), --report-again-s S.
The first line of exits 0, 2, 5 and 6 ends '(desk_watch <sha256[:12]>; exit5 inboxes=<n> ...; exit6 since <UTC>)', and
every WARNING found in the last poll (plus the run's one-off exit6-since.txt note) follows the hits, so a wrong root,
an unlistable folder or an unreadable file is never a silent all-clear, and a problem that has cleared is not reported
hours later. A file that exists but cannot be read is never read as absent: that inbox (or, for
recovery-sent.md, exits 5 and 6) is skipped for the poll with a WARNING, never alerted on.
A background exit wakes an idle chat; the harness caps background jobs at 2 h,
hence max-seconds 6900. Not a timer for anything else: it only looks at desk files.
"""
import argparse
import calendar
import importlib.util
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desk_files  # noqa: E402


# ---- Pipeline exits 5 and 6. Each rule is one small function. ----
DEAD_HEARTBEAT_S = 600   # heartbeat older than 10 minutes counts as dead
WAITED_S = 900           # an item not done/parked for more than 15 minutes has waited
HANDOVER_S = 900         # a self-clear with no RESUMED line 15 minutes later
STUCK_S = 900            # one stuck line 15 minutes after the recovery message
REPORT_AGAIN_S = 1800    # an alert not recorded in recovery-sent.md is raised again only after this
TS_RE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z|\d{8}T\d{6}Z')
LEAD_TS = re.compile(r'^(?:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z|\d{8}T\d{6}Z)\s+')   # '<UTC> [DESK ...' (live desk)
# An item is <UTC>-<from>-<n>.md (pipeline/tools/wait_inbox.py ITEM). NOT_ITEMS and HANDLED serve waiters that
# keep an ACKS.md; the shipped pipeline marks handled items in <inbox>/.seen instead (both are read).
ITEM_RE = re.compile(r'^\d[^/\\]*\.md$')
ANSWERED_COPY = re.compile(r'\(answered(?:[ \t]+DQ-\d+|:[ \t]*[^()\s][^()\r\n]*)\)[ \t]*$')
NOT_ITEMS = {'acks.md', 'sent.md', 'readme.md'}
HANDLED = ('done', 'parked')
WARN = set()             # unreadable files, unlistable folders, a missing root: printed with exits 0, 2, 5 and 6
READ_TRIES, READ_SLEEP = 40, 0.05   # about 2 s, as the inbox waiter's read_text rides out a writer's os.replace
CLOSED = ('ok', 'failed')           # a key with one of these lines has ended


def _self_sha():
    """Every run names the file it ran (first 12 hex digits of its sha256)."""
    try:
        with open(os.path.abspath(__file__), 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except OSError:
        return 'unknown'


SELF_SHA = _self_sha()


class Unreadable(Exception):
    """A file that exists but could not be read (held with no read sharing, a folder of that name, ...)."""


def parse_ts(text):
    """First valid UTC stamp in text (2026-01-01T17:00:00Z or 20260101T170000Z) as epoch seconds, else None.
    A stamp-shaped but impossible date (2026-02-30T...) is skipped, never raised."""
    for m in TS_RE.finditer(text or ''):
        t = m.group(0)
        fmt = '%Y-%m-%dT%H:%M:%SZ' if '-' in t else '%Y%m%dT%H%M%SZ'
        try:
            return calendar.timegm(time.strptime(t, fmt))
        except ValueError:
            continue
    return None


def utc(t):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))


def read_text(path):
    """The file's text; None only when it does not exist. One that exists but stays unreadable for about 2 s (a
    sharing violation, a folder of that name) raises Unreadable: a held file is never read as a missing one."""
    for i in range(READ_TRIES):
        try:
            with open(path, encoding='utf-8-sig', errors='replace') as f:
                return f.read()
        except FileNotFoundError:
            return None
        except OSError as e:
            if os.path.isdir(path) or i == READ_TRIES - 1:
                raise Unreadable('%s unreadable (%s)' % (os.path.basename(path), type(e).__name__))
            time.sleep(READ_SLEEP)


def read_json(path):
    """A state dict; {} when absent. Unreadable, corrupt or non-object content is also {}, noted in WARN."""
    try:
        with open(path, encoding='utf-8') as f:
            obj = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        WARN.add('WARNING %s unreadable (%s): treated as empty' % (os.path.basename(path), type(e).__name__))
        return {}
    if not isinstance(obj, dict):
        WARN.add('WARNING %s is not a JSON object: treated as empty' % os.path.basename(path))
        return {}
    return obj


def write_atomic(path, text):
    """tmp + os.replace, retried: Windows refuses a replace while a reader holds the target open."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = '%s.%d.tmp' % (path, os.getpid())
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    for i in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 39:
                raise
            time.sleep(0.05)


def inbox_dirs(elv):
    """The inbox layout of pipeline/RULES.md (Items): lanes/<slug>/inbox/<role>/ for each role folder,
    lanes/<slug>/inbox/ itself, and coordinator/inbox/. Returns [(label, dir)]; a role folder's label is
    <slug>/<role> (no spaces: it goes into alert keys).
    A missing root, an unlistable lanes/ folder or an empty watch set adds a WARNING (never a silent zero)."""
    out = []
    if not elv or not os.path.isdir(elv):
        WARN.add('WARNING exit 5 off: pipeline root %s not found' % elv)
        return out
    lanes = os.path.join(elv, 'lanes')
    if os.path.isdir(lanes):
        try:
            slugs = sorted(os.listdir(lanes))
        except OSError as e:
            WARN.add('WARNING cannot list %s (%s): its lane inboxes are not watched' % (lanes, type(e).__name__))
            slugs = []
        for slug in slugs:
            d = os.path.join(lanes, slug, 'inbox')
            if os.path.isdir(d):
                out.append((slug, d))
                try:
                    roles = sorted(r for r in os.listdir(d)
                                   if not r.startswith('.') and os.path.isdir(os.path.join(d, r)))
                except OSError as e:
                    WARN.add('WARNING cannot list %s (%s): its role inboxes are not watched' % (d, type(e).__name__))
                    roles = []
                for role in roles:
                    out.append(('%s/%s' % (slug, role.replace(' ', '_')), os.path.join(d, role)))
    d = os.path.join(elv, 'coordinator', 'inbox')
    if os.path.isdir(d):
        out.append(('coordinator', d))
    if not out:
        WARN.add('WARNING exit 5 watches 0 inboxes under %s' % elv)
    return out


KV_LINE = re.compile(r'^\s*(chat|pid|arm|started|utc)\s*:\s*(\S+)', re.M)


def _kv(text):
    """The inbox waiter's 'key: value' lines; else today's key=value words."""
    found = dict(KV_LINE.findall(text or ''))
    if found:
        return found
    return dict(t.split('=', 1) for t in (text or '').split() if '=' in t)


def norm_stamp(text):
    """A UTC stamp in text as 20260101T170000Z (no colons, no spaces: safe inside a key), else '?'."""
    ts = parse_ts(text)
    return time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(ts)) if ts is not None else '?'


def pipeline_waiter_status(inbox, pipeline_root):
    """A missing identity helper is unknown, never evidence of an armed waiter."""
    path = os.path.join(pipeline_root, 'tools', 'waiter_identity.py')
    try:
        spec = importlib.util.spec_from_file_location('waiter_identity', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.status(inbox)
    except (OSError, ImportError, AttributeError):
        return 'UNKNOWN'


def waiter_state(inbox, now, pipeline_root=''):
    """Return (dead, reason, arm part of the key, chat id or None). Formats (the inbox waiter's 'key: value' lines, or
    key=value, or positional words):
    .waiter-arm = 'chat: <id>/pid: <pid>/arm: <armid>/started: <UTC>' or 'chat=<id> pid=<pid> arm=<armid>' or
    '<chat> <pid> <arm>'; after a clear its first line is 'cleared <UTC>' (a chat: line may follow);
    .waiter-heartbeat = 'utc: <UTC>/arm: <armid>' or '<UTC> arm=<armid>' or '<UTC> <armid>'.
    With neither file, the shipped waiter's .waiter.pid decides: alive while that process lives."""
    arm_txt = read_text(os.path.join(inbox, '.waiter-arm'))
    hb_txt = read_text(os.path.join(inbox, '.waiter-heartbeat'))
    if arm_txt is None and hb_txt is None:
        pid_txt = read_text(os.path.join(inbox, '.waiter.pid'))
        if pid_txt is not None:
            state = pipeline_waiter_status(inbox, pipeline_root)
            try:
                pid = int(pid_txt.strip())
                key = 'pid-%d' % pid if 0 < pid <= 0xffffffff else 'pid-bad'
                # Keep legacy/invalid identity episodes distinct from verified registrations.
                ident = read_json(os.path.join(inbox, '.waiter.identity'))
                if ident.get('pid') == pid and type(ident.get('creation')) is int:
                    key += '-creation-%d' % ident['creation']
                elif ident.get('pid') == pid and re.fullmatch(r'[0-9a-f]{32}', str(ident.get('generation', ''))):
                    key += '-generation-' + ident['generation']
                else:
                    # Legacy PID-only records: a rewrite changes file metadata, distinguishing
                    # episodes without changing the legacy on-disk format.
                    try:
                        st = os.stat(os.path.join(inbox, '.waiter.pid'))
                    except OSError as e:
                        raise Unreadable('waiter pid changed while reading (%s)' % type(e).__name__)
                    key += '-legacy-%d-%d-%d' % (st.st_mtime_ns, st.st_ctime_ns, st.st_size)
            except ValueError:
                key = 'pid-bad'
            if state == 'ARMED':
                return False, 'alive', key, None
            return True, ('waiter gone or replaced' if state == 'DEAD' else 'waiter identity unknown; re-arm'), key, None
    arm_tok = (arm_txt or '').split()
    kv = _kv(arm_txt)
    if arm_tok and arm_tok[0] == 'cleared':
        return True, 'cleared', 'cleared-' + norm_stamp(arm_tok[1] if len(arm_tok) > 1 else ''), kv.get('chat')
    arm = kv.get('arm') or (arm_tok[2] if len(arm_tok) >= 3 and not kv else None)
    chat = kv.get('chat') or (arm_tok[0] if len(arm_tok) >= 3 and not kv else None)
    if not arm:
        return True, ('no waiter file' if arm_txt is None and hb_txt is None else 'no arm record'), 'no-arm', chat
    hb_kv = _kv(hb_txt)
    hb_ts = parse_ts(hb_kv.get('utc') or hb_txt)
    if hb_ts is None:
        return True, 'no heartbeat', arm, chat
    hb_tok = (hb_txt or '').split()
    hb_arm = hb_kv.get('arm') or (next((t for t in hb_tok if not TS_RE.fullmatch(t) and '=' not in t and ':' not in t), None)
                                  if not hb_kv else None)
    if hb_arm != arm:
        return True, 'stale arm id', arm, chat
    if now - hb_ts > DEAD_HEARTBEAT_S:
        return True, 'heartbeat %.0f min old' % ((now - hb_ts) / 60), arm, chat
    return False, 'alive', arm, chat


def acks_settled(inbox):
    """Ids marked done or parked in inbox/ACKS.md, read as the inbox waiter reads them: '[<UTC>] <id> <status> ...'."""
    settled = set()
    for line in (read_text(os.path.join(inbox, 'ACKS.md')) or '').splitlines():
        tok = line.split()
        if tok and TS_RE.fullmatch(tok[0]):
            tok = tok[1:]
        if len(tok) >= 2 and tok[1].lower() in HANDLED:
            settled.add(tok[0])
    return settled


def item_id(path, name):
    """The 'id:' line within the first 15 lines, as the inbox waiter reads it; else the file stem."""
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for _, ln in zip(range(15), f):
            if ln.lower().startswith('id:'):
                v = ln.split(':', 1)[1].strip()
                if v:
                    return v
    return name[:-3]


def waiting_items(inbox, now):
    """Item ids (or file stems) older than 15 minutes that are neither in .seen nor done/parked in ACKS.md."""
    settled = acks_settled(inbox)   # an unreadable ACKS.md raises Unreadable: done items are never re-raised blind
    seen = {s.strip() for s in (read_text(os.path.join(inbox, '.seen')) or '').splitlines()}   # likewise .seen
    out = []
    try:
        names = sorted(os.listdir(inbox))
    except FileNotFoundError:
        return out
    except OSError as e:
        raise Unreadable('inbox listing %s (%s)' % (inbox, type(e).__name__))
    for n in names:
        path = os.path.join(inbox, n)
        if not ITEM_RE.match(n) or n.lower() in NOT_ITEMS:
            continue
        try:   # a sender may rename or remove the file between the listing and the stat
            if not os.path.isfile(path):
                continue
            iid = item_id(path, n)
            if n not in seen and iid not in settled and now - os.path.getmtime(path) > WAITED_S:
                out.append(iid)
        except FileNotFoundError:
            continue
        except OSError as e:   # one bad item never silences the rest, and is named
            WARN.add('WARNING item %s unreadable (%s): skipped this poll' % (n, type(e).__name__))
            continue
    return out


def receiver_active(inbox, now):
    """The receiver wrote its ACKS.md or .seen within the heartbeat window, so it is
    working on the item its waiter woke it for (the waiter ends when an item lands), not dead."""
    for name in ('ACKS.md', '.seen'):
        try:
            if now - os.path.getmtime(os.path.join(inbox, name)) <= DEAD_HEARTBEAT_S:
                return True
        except OSError:
            continue
    return False


def key_pat(key):
    """The key as a whole word: after a start, space, '=', quote, backtick or '('; before an end, space or . , ; ) quote
    backtick. A colon never ends a key, so a longer key never matches a shorter one."""
    return re.compile(r'(^|[\s=`"\'(])' + re.escape(key) + r'([\s.,;)`"\']|$)')


def key_line(text, key):
    """The first recovery-sent.md line holding the key as a whole word ('<UTC> <key>', 'sending <key>', 'key=<key>')."""
    pat = key_pat(key)
    return next((l for l in (text or '').splitlines() if pat.search(l)), None)


def key_closed(text, key):
    """A key with an 'ok <key> <UTC>' or 'failed <key> <UTC>' line has ended and is never raised
    again, whatever tools/state holds (a lost or rebuilt state folder included). An optional leading UTC is skipped."""
    pat = key_pat(key)
    for l in (text or '').splitlines():
        if not pat.search(l):
            continue
        tok = [t for t in l.split() if t not in ('-', '*')]
        if tok and TS_RE.fullmatch(tok[0]):
            tok = tok[1:]
        if tok and tok[0].lower() in CLOSED:
            return True
    return False


def first_seen(p, key, path, now):
    """When this watcher first saw the key in recovery-sent.md. A 'sending <key>' line has no
    UTC, so the STUCK timer starts here, never at the file's mtime, which every later line of ANY key moves.
    tools/state/key-first-seen.json, one writer (desk_watch); first sight stores min(now, file mtime); 7-day prune."""
    spath = os.path.join(p['state'], 'key-first-seen.json')
    seen = read_json(spath)
    at = seen.get(key)
    if isinstance(at, (int, float)):
        return at
    try:
        at = min(now, os.path.getmtime(path))
    except OSError:
        at = now
    seen = {k: v for k, v in seen.items() if isinstance(v, (int, float)) and now - v < 7 * 86400}
    seen[key] = int(at)
    try:
        write_atomic(spath, json.dumps(seen, indent=1, sort_keys=True))
    except OSError as e:
        WARN.add('WARNING key-first-seen.json not written (%s): a stampless key is timed again next run' % type(e).__name__)
    return int(at)


def recovery_state(p, key, now):
    """'new', 'sent' or 'stuck-due' for a key against recovery-sent.md. A key already there is skipped, except
    once, 15 minutes after its FIRST line there, to raise the stuck line (tracked in tools/state/stuck-raised.json).
    An unreadable recovery-sent.md raises Unreadable (never read as 'no key')."""
    path = os.path.join(p['root'], 'recovery-sent.md')
    text = read_text(path)
    line = key_line(text, key)
    if line is None:
        return 'new'
    if key_closed(text, key):
        return 'sent'
    sent_at = parse_ts(line.replace(key, ' '))   # the message's stamp, never one inside the key
    if sent_at is None:
        sent_at = first_seen(p, key, path, now)
    raised = read_json(os.path.join(p['state'], 'stuck-raised.json'))
    if key not in raised and now - sent_at >= STUCK_S:
        return 'stuck-due'
    return 'sent'


def mark_stuck_raised(p, key, now):
    """Only desk_watch writes this file (one writer); atomic replace."""
    path = os.path.join(p['state'], 'stuck-raised.json')
    raised = read_json(path)
    raised[key] = int(now)
    write_atomic(path, json.dumps(raised, indent=1, sort_keys=True))


def recently_reported(p, key, now, again_s):
    """A key already alerted, but not written in recovery-sent.md, is not raised again for again_s seconds."""
    at = read_json(os.path.join(p['state'], 'reported.json')).get(key)
    return isinstance(at, (int, float)) and now - at < again_s


def mark_reported(p, keys, now):
    """Only desk_watch writes reported.json (one writer); atomic replace; entries older than 7 days are dropped."""
    path = os.path.join(p['state'], 'reported.json')
    rep = {k: v for k, v in read_json(path).items() if isinstance(v, (int, float)) and now - v < 7 * 86400}
    for k in keys:
        rep[k] = int(now)
    write_atomic(path, json.dumps(rep, indent=1, sort_keys=True))


def classify(p, key, now, again_s):
    """'raise', 'stuck' or None (skip) for one alert key: recovery-sent.md rules first, then the rate limit."""
    st = recovery_state(p, key, now)
    if st == 'sent':
        return None
    if st == 'stuck-due':
        return 'stuck'
    return None if recently_reported(p, key, now, again_s) else 'raise'


def dead_waiter_hits(p, elv, now, open_chats=(), again_s=REPORT_AGAIN_S):
    """Exit 5: an inbox whose waiter is dead while an item there has waited over 15 minutes.
    -> (lines, alerted keys, stuck keys)."""
    hits, keys, marks = [], [], []
    for slug, inbox in inbox_dirs(elv):
        try:   # one unreadable arm, heartbeat, ACKS.md or listing skips only this inbox, loudly, never as 'dead'
            dead, why, arm, chat = waiter_state(inbox, now, elv)
            ids = waiting_items(inbox, now)
        except Unreadable as e:
            WARN.add('WARNING inbox %s: %s; skipped this poll (not read as a dead waiter)' % (slug, e))
            continue
        if not dead:
            continue
        if why == 'cleared' and chat in open_chats:   # exit 6 owns a cleared chat with an open self-clear
            continue
        if not ids or receiver_active(inbox, now):
            continue
        if arm == 'no-arm':   # no record: one key per oldest waiting item, so a later outage is a new episode
            arm = 'no-arm-' + ids[0]
        key = 'waiter:%s:%s' % (chat or slug, arm)
        act = classify(p, key, now, again_s)
        if act is None:
            continue
        tag = 'STUCK (recovery message sent, waiter still down)' if act == 'stuck' else 'DEAD WAITER'
        hits.append('%s %s | waiter %s | waiting: %s | key=%s' % (tag, slug, why, ', '.join(ids), key))
        keys.append(key)
        if act == 'stuck':
            marks.append(key)
    return hits, keys, marks


def resumed_line(line, title, any_update=False):
    """'[DESK UPDATE] <title> RESUMED...' (RESUMED-AFTER-CLEAR counts, RESUMEDNESS does not). With
    any_update (opt-in, off by default) any later '[DESK UPDATE] <title> ...' line counts."""
    tail = r'(?=[\s|]|$)' if any_update else r' RESUMED(?![A-Za-z0-9])'
    return re.match(r'\[DESK UPDATE\] ' + re.escape(title) + tail, line) is not None


def open_handovers(p, now, since=None, max_age_h=None, any_update=False):
    """Self-clear [DESK HANDOVER] lines stamped at or after `since` (and within max_age_h when set) with no later
    RESUMED line for their title in the same desk file -> [(desk file, line, stamp, chat id)], any age.
    A leading '<UTC> ' before '[DESK ...' is tolerated on both lines (seen on the live desk)."""
    out = []
    for name in desk_files.lane_files(p):
        try:
            txt = read_text(os.path.join(p['updates'], name))
        except Unreadable as e:
            WARN.add('WARNING desk file %s: exit 6 skipped it this poll' % e)
            continue
        if txt is None:
            continue
        lines = [LEAD_TS.sub('', l.lstrip('\ufeff \t'), count=1) for l in txt.splitlines()]
        for i, s in enumerate(lines):
            if not (s.startswith('[DESK HANDOVER]') and 'self-clear' in s):
                continue
            fields = [f.strip() for f in s[len('[DESK HANDOVER]'):].split('|')]
            title = fields[0]
            at = parse_ts(fields[2] if len(fields) > 2 else '') or parse_ts(s)
            if at is None or (since is not None and at < since):
                continue
            if max_age_h is not None and now - at > max_age_h * 3600:
                continue
            if any(resumed_line(x, title, any_update) for x in lines[i + 1:]):
                continue
            m = re.search(r'same chat (\S+)', s)
            out.append((name, s, at, m.group(1) if m else name[:-3]))
    return out


def waiting_for_chat(elv, chat, now):
    """A stuck line names the waiting item ids. Those of the inbox whose .waiter-arm names this chat id;
    'none' when that inbox holds none; 'unknown (...)' when no inbox names the chat or it cannot be read."""
    for slug, inbox in inbox_dirs(elv):
        try:
            if waiter_state(inbox, now, elv)[3] == chat:
                return ', '.join(waiting_items(inbox, now)) or 'none'
        except Unreadable as e:
            WARN.add('WARNING inbox %s: %s; skipped this poll' % (slug, e))
    return 'unknown (no readable inbox names chat %s)' % chat


def unresumed_handover_hits(p, now, handovers, again_s=REPORT_AGAIN_S, elv=None):
    """Exit 6: an open self-clear handover 15+ minutes old. -> (lines, alerted keys, stuck keys)."""
    hits, keys, marks = [], [], []
    for name, s, at, chat in handovers:
        if now - at < HANDOVER_S:
            continue
        key = 'handover:%s:%s' % (chat, time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(at)))
        act = classify(p, key, now, again_s)
        if act is None:
            continue
        tag = 'STUCK (resume message sent, no RESUMED line)' if act == 'stuck' else 'NOT RESUMED'
        waiting = ' | waiting: %s' % waiting_for_chat(elv, chat, now) if act == 'stuck' else ''
        hits.append('%s: %s | %s%s | key=%s' % (name, tag, s[:200], waiting, key))
        keys.append(key)
        if act == 'stuck':
            marks.append(key)
    return hits, keys, marks


def extra_exit(p, elv, now, since=None, max_age_h=None, any_update=False, again_s=REPORT_AGAIN_S):
    """(exit code, lines, alerted keys, stuck keys) for the two pipeline exits, or None. An unreadable
    recovery-sent.md skips both exits for this poll with a WARNING: never an alert from a file it could not read."""
    try:
        handovers = open_handovers(p, now, since, max_age_h, any_update)
        open_chats = {h[3] for h in handovers}
        for code, fn in ((5, lambda: dead_waiter_hits(p, elv, now, open_chats, again_s)),
                         (6, lambda: unresumed_handover_hits(p, now, handovers, again_s, elv))):
            hits, keys, marks = fn()
            if hits:
                return code, hits, keys, marks
    except Unreadable as e:
        WARN.add('WARNING %s: exits 5 and 6 skipped this poll' % e)
    return None


def exit6_since(p, given, now):
    """The go-live cutoff for exit 6. --since, else the stamp in
    tools/state/exit6-since.txt, which the first run writes once; a stampless file counts from its mtime."""
    if given:
        ts = parse_ts(given)
        if ts is None:
            raise SystemExit('desk_watch: --since needs a UTC stamp such as 2026-01-01T17:00:00Z')
        return ts
    path = os.path.join(p['state'], 'exit6-since.txt')
    if not os.path.exists(path):
        write_atomic(path, utc(now) + '\n')
        WARN.add('WARNING exit6-since.txt was missing: exit 6 cutoff set to %s' % utc(now))
    try:
        ts = parse_ts(read_text(path))
    except Unreadable as e:
        WARN.add('WARNING %s' % e)
        ts = None
    if ts is None:
        WARN.add('WARNING exit6-since.txt holds no UTC stamp: its mtime is the cutoff')
        try:
            ts = os.path.getmtime(path)
        except OSError:
            ts = now
    return ts


def status(a, since):
    """The tail of every exit's first line: which file ran, what exit 5 watches, the exit-6
    cutoff in force, and whether anything was degraded (the WARNING lines follow the hits)."""
    n = len(inbox_dirs(a.pipeline_root))
    off = '' if a.pipeline_root and os.path.isdir(a.pipeline_root) else ' (off: %s not found)' % a.pipeline_root
    degraded = '; degraded: %d warning(s) below' % len(WARN) if WARN else ''
    return '(desk_watch %s; exit5 inboxes=%d%s; exit6 since %s%s)' % (SELF_SHA, n, off, utc(since), degraded)


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', type=float, default=15)
    ap.add_argument('--max-seconds', type=float, default=6900)
    ap.add_argument('--root')
    ap.add_argument('--pipeline-root', default=os.environ.get('PIPELINE_ROOT', ''),
                    help='folder holding lanes/<slug>/inbox[/<role>] and coordinator/inbox (exit 5)')
    ap.add_argument('--since', help='exit 6 ignores self-clears stamped before this UTC (default: exit6-since.txt)')
    ap.add_argument('--handover-max-age-hours', type=float, default=None,
                    help='opt-in: also ignore self-clears older than this (default: no limit)')
    ap.add_argument('--resumed-any-update', action='store_true',
                    help='opt-in: any later [DESK UPDATE] <title> line counts as resumed')
    ap.add_argument('--report-again-s', type=float, default=REPORT_AGAIN_S,
                    help='an alert not recorded in recovery-sent.md is raised again only after this many seconds')
    a = ap.parse_args()
    p = desk_files.paths(a.root)
    os.makedirs(p['state'], exist_ok=True)
    try:
        age = time.time() - os.path.getmtime(p['alive'])
        with open(p['alive'], encoding='utf-8') as f:
            other = f.read().split()[0]
        if age < 3 * a.interval and other != str(os.getpid()):
            print('desk_watch: another watcher (pid %s) is alive, %.0f s ago; not starting' % (other, age))
            sys.exit(4)
    except (FileNotFoundError, IndexError):
        pass
    since = exit6_since(p, a.since, time.time())
    run_warn = set(WARN)   # once-per-run notes (exit6-since.txt was just written) go with every exit of this run
    start = time.time()
    while True:
        # Each poll reports only what is wrong in THIS poll: a file unreadable in hour 1 and fine since is not
        # 'degraded' on the exit-2 line two hours later.
        WARN.clear()
        WARN.update(run_warn)
        if os.path.exists(p['stop']):
            print('desk_watch: STOP-WATCH found; stopping')
            if os.path.exists(p['alive']):
                os.remove(p['alive'])
            sys.exit(3)
        with open(p['alive'], 'w', encoding='utf-8') as f:
            f.write('%d %s\n' % (os.getpid(), time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        offsets = desk_files.load_offsets(p, WARN)
        hits = []
        for name in desk_files.lane_files(p):
            try:
                lines, _, _ = desk_files.new_lines(p, name, offsets)
            except OSError as e:   # never a silent all-clear: its [DESK Q] lines went unchecked, so say so
                WARN.add('WARNING lane file %s unreadable (%s): its [DESK Q] lines were not checked this poll'
                         % (name, type(e).__name__))
                continue
            # Only an explicit suffix marks an answered copy; prose mentioning an answer still wakes the desk.
            hits += ['%s: %s' % (name, l[:300]) for l in lines
                     if desk_files.kind(l) == 'Q' and not ANSWERED_COPY.search(l)]
            # A self-clear handover also wakes the desk chat: the lane's own resume cron and waker die with the clear
            # (seen in practice), so the desk chat must send the resume message.
            hits += ['%s: %s' % (name, l[:300]) for l in lines
                     if l.lstrip('\ufeff \t').startswith('[DESK HANDOVER]') and 'self-clear' in l]
            # A chat can write SELF-CLEAR BLOCKED and still be cleared: check list_events and wake it if empty.
            hits += ['%s: %s' % (name, l[:300]) for l in lines
                     if desk_files.kind(l) == 'U' and 'SELF-CLEAR BLOCKED' in l]
        if hits:
            print('desk_watch: %d new [DESK Q] waiting %s' % (len(hits), status(a, since)))
            print('\n'.join(hits + sorted(WARN)))
            os.remove(p['alive'])
            sys.exit(0)
        extra = extra_exit(p, a.pipeline_root, time.time(), since, a.handover_max_age_hours,
                           a.resumed_any_update, a.report_again_s)
        if extra:
            code, ehits, keys, marks = extra
            print('desk_watch: %d %s %s' % (len(ehits), 'inbox(es) with a dead waiter and a waiting item (exit 5)'
                  if code == 5 else 'self-clear handover(s) not resumed after 15 min (exit 6)', status(a, since)))
            print('\n'.join(ehits + sorted(WARN)), flush=True)
            now = time.time()
            try:   # the alert is already printed; a state file that cannot be written must not turn it into exit 1
                for k in marks:
                    mark_stuck_raised(p, k, now)
                mark_reported(p, keys, now)
            except OSError as e:
                print('WARNING state not written (%s): this alert may be raised again' % type(e).__name__, flush=True)
            os.remove(p['alive'])
            sys.exit(code)
        if time.time() - start > a.max_seconds:
            print('desk_watch: no new [DESK Q] in %.0f s; re-arm %s' % (time.time() - start, status(a, since)))
            if WARN:
                print('\n'.join(sorted(WARN)))
            os.remove(p['alive'])
            sys.exit(2)
        time.sleep(a.interval)


if __name__ == '__main__':
    main()
