"""Tests for desk_watch.py's two pipeline exits (5: dead waiter, 6: self-clear not resumed).

Usage: python -B -I test_desk_watch_exits.py [TOOLS_DIR]    (default: this folder; a neutered copy is passed for born-red runs)
Everything runs in one new run-* folder under the system temp folder (or under $DW_TEST_TMP); no live inbox or desk is touched.
The run folder is removed at the end when every check passed (leftover temp folders once filled the disk's file
records); after a FAIL it is kept and its path printed, for inspection.
Times are built from the clock (time.time()) minus minutes, never typed.
"""
import hashlib, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else HERE
TMP_ROOT = os.environ.get('DW_TEST_TMP') or os.path.join(tempfile.gettempdir(), 'desk-watch-tests')   # a mutation runner may give each mutant its own
os.makedirs(TMP_ROOT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix='run-', dir=TMP_ROOT)
fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ' :: ' + detail))
    if not cond:
        fails.append(name)


def fstamp(minutes_ago):
    return time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(time.time() - minutes_ago * 60))


def stamp(minutes_ago):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - minutes_ago * 60))


class Env:
    def __init__(self, tag):
        self.root = os.path.join(TMP, tag + '-desk')
        self.elv = os.path.join(TMP, tag + '-elv')
        for d in (self.root, self.elv):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(os.path.join(self.root, 'updates'))
        os.makedirs(os.path.join(self.root, 'tools', 'state'))
        self.inbox = os.path.join(self.elv, 'lanes', 'alpha', 'inbox')
        os.makedirs(self.inbox)
        self.since(60 * 24 * 3)   # exit 6's go-live cutoff 3 days back, so the old cases see their handovers

    def since(self, minutes_ago):
        with open(os.path.join(self.root, 'tools', 'state', 'exit6-since.txt'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(stamp(minutes_ago) + '\n')

    def put(self, rel, text, minutes_ago=0):
        path = os.path.join(self.inbox, rel)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        t = time.time() - minutes_ago * 60
        os.utime(path, (t, t))
        return path

    def arm(self, arm_id='arm-1'):
        self.put('.waiter-arm', 'chat=chat-alpha pid=4242 arm=%s\n' % arm_id)

    def heartbeat(self, minutes_ago, arm_id='arm-1'):
        self.put('.waiter-heartbeat', '%s %s\n' % (stamp(minutes_ago), arm_id))

    def item(self, iid='lead-T1-1', minutes_ago=20):
        self.put('%s-lead-1.md' % fstamp(minutes_ago), 'id: %s\nkind: Q\nfrom: lead\nto: alpha\nrefs:\nblocking: yes\n' % iid, minutes_ago)

    def desk(self, text, name='chat-alpha.md'):
        with open(os.path.join(self.root, 'updates', name), 'a', encoding='utf-8', newline='\n') as f:
            f.write(text)

    def recovery(self, line):
        with open(os.path.join(self.root, 'recovery-sent.md'), 'a', encoding='utf-8', newline='\n') as f:
            f.write(line + '\n')

    def watch(self, *extra, again='0'):
        """again: --report-again-s. '0' (the default here) turns the rate limit off, so the older cases test only
        their own rule; None leaves the tool's default (1800 s)."""
        args = list(extra) + (['--report-again-s', again] if again is not None else [])
        r = subprocess.run([sys.executable, '-B', '-I', os.path.join(TOOLS, 'desk_watch.py'), '--root', self.root,
                            '--pipeline-root', self.elv, '--interval', '0.2', '--max-seconds', '1'] + args,
                           capture_output=True, text=True, encoding='utf-8', timeout=60)
        return r.returncode, r.stdout.strip()

    def read(self):
        subprocess.run([sys.executable, '-B', '-I', os.path.join(TOOLS, 'desk_read.py'), '--root', self.root],
                       capture_output=True, text=True, encoding='utf-8', timeout=60)


def add_cleared(e, chat='chat-alpha', minutes_ago=3):
    e.put('.waiter-arm', 'cleared %s\nchat: %s\n' % (stamp(minutes_ago), chat))


def key_of(out):
    return out.split('key=', 1)[1].split()[0] if 'key=' in out else ''


# ---- exit 5: dead waiter + an item that has waited ----
e = Env('a')
e.arm(); e.heartbeat(11); e.item(minutes_ago=20)
code, out = e.watch()
check('A1 heartbeat 11 min old + item waiting 20 min -> exit 5', code == 5 and 'lead-T1-1' in out and 'alpha' in out, '%s %s' % (code, out))

e = Env('a2')
e.arm(); e.heartbeat(11); e.item(minutes_ago=20)
e.put('ACKS.md', 'lead-T1-1 delivered\nlead-T1-1 done\n', 11)   # 11 min old: outside the busy window
check('A2 same, item marked done -> no exit 5', e.watch()[0] == 2, str(e.watch()))
e.put('ACKS.md', 'lead-T1-1 parked waiting on the owner\n', 11)
check('A2b parked counts like done', e.watch()[0] == 2)
e.put('ACKS.md', 'lead-T1-1 acting commit abc\n', 11)
check('A2c acting is not done -> exit 5', e.watch()[0] == 5)

e = Env('a3')
e.arm(); e.heartbeat(11); e.item(minutes_ago=5)
check('A3 item only 5 min old -> no exit', e.watch()[0] == 2)

e = Env('a4')
e.arm(); e.heartbeat(1); e.item(minutes_ago=60)
check('A4 live waiter (heartbeat 1 min, same arm id) -> no exit', e.watch()[0] == 2)

e = Env('a5')
e.arm('arm-2'); e.heartbeat(1, 'arm-1'); e.item(minutes_ago=20)
code, out = e.watch()
check('A5 fresh heartbeat but a stale arm id -> exit 5', code == 5 and 'stale arm id' in out, '%s %s' % (code, out))

e = Env('a6')
e.put('.waiter-arm', 'cleared %s\nchat: chat-alpha\n' % stamp(3)); e.heartbeat(1); e.item(minutes_ago=20)
code, out = e.watch()
check('A6 cleared -> exit 5', code == 5 and 'cleared' in out, '%s %s' % (code, out))
check('A6b the cleared key has no space and names the chat id', ' ' not in key_of(out) and key_of(out).startswith('waiter:chat-alpha:cleared-'), key_of(out))

e = Env('a7')
e.item(minutes_ago=20)
check('A7 no arm record and no heartbeat -> exit 5', e.watch()[0] == 5)

e = Env('a8')
e.arm(); e.heartbeat(11)
check('A8 dead waiter but empty inbox -> no exit', e.watch()[0] == 2)

# existing [DESK Q] exit wins and keeps code 0
e = Env('a9')
e.arm(); e.heartbeat(11); e.item(minutes_ago=20)
e.desk('[DESK Q] alpha | blocking: no | question\n')
check('A9 a [DESK Q] still exits 0 first', e.watch()[0] == 0)

# ---- exit 6: self-clear handover, no RESUMED 15 minutes later ----
HO = '[DESK HANDOVER] Alpha | self-clear, same chat chat-alpha | %s | compactions: 5 | /x/handover.md\n'
e = Env('b')
e.desk(HO % stamp(20))
code, out = e.watch()
check('B0 the fresh handover line still wakes with exit 0 (unchanged)', code == 0 and 'self-clear' in out, '%s %s' % (code, out))
e.read()
code, out = e.watch()
check('B1 read, 20 min, no RESUMED line -> exit 6', code == 6 and 'NOT RESUMED' in out, '%s %s' % (code, out))
e.desk('[DESK UPDATE] Alpha RESUMED %s\n' % stamp(1))
e.read()
check('B2 a RESUMED line for that title -> no exit 6', e.watch()[0] == 2)

e = Env('b3')
e.desk(HO % stamp(5)); e.read()
check('B3 handover only 5 min old -> no exit 6', e.watch()[0] == 2)

e = Env('b4')
e.desk(HO % stamp(20)); e.desk('[DESK UPDATE] Other lane RESUMED %s\n' % stamp(1)); e.read()
check('B4 a RESUMED line of another title does not count', e.watch()[0] == 6)

e = Env('b5')
e.desk('[DESK HANDOVER] Alpha | new chat for old | %s | x\n' % stamp(20)); e.read()
check('B5 a handover that is not a self-clear is ignored', e.watch()[0] == 2)

e = Env('b6')
e.desk(HO % stamp(60 * 30)); e.read()
check('B6 a handover 30 h old (after the cutoff) is still raised: no default age limit', e.watch()[0] == 6)
check('B6b ... unless --handover-max-age-hours 24 is given (opt-in)', e.watch('--handover-max-age-hours', '24')[0] == 2)

# ---- recovery-sent.md: skip a key already there, except once, 15 minutes after the message ----
e = Env('c')
e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
code, out = e.watch()
key = key_of(out)
check('C0 the alert names a key', code == 5 and key.startswith('waiter:chat-alpha:') and ' ' not in key, '%s %s' % (code, out))
code2, out2 = e.watch()
check('C1 without the key in recovery-sent.md (and the rate limit off), the alert repeats', code2 == 5 and key_of(out2) == key, '%s %s' % (code2, out2))
e.recovery('%s %s' % (stamp(5), key))
check('C2 key sent 5 min ago -> second alert suppressed', e.watch()[0] == 2)
e = Env('c3')
e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
e.recovery('%s %s' % (stamp(20), key))
code, out = e.watch()
check('C3 key sent 20 min ago, still down -> one STUCK line', code == 5 and 'STUCK' in out and key in out, '%s %s' % (code, out))
code, out = e.watch()
check('C4 the stuck line comes only once', code == 2, '%s %s' % (code, out))
e.heartbeat(0)
check('C5 a revived waiter raises nothing', e.watch()[0] == 2)

e = Env('c6')
e.desk(HO % stamp(40)); e.read()
code, out = e.watch()
hkey = key_of(out)
check('C6 handover alert names a key', code == 6 and hkey.startswith('handover:chat-alpha:'), '%s %s' % (code, out))
e.recovery('%s %s' % (stamp(5), hkey))
check('C7 handover key sent 5 min ago -> suppressed', e.watch()[0] == 2)
e = Env('c8')
e.desk(HO % stamp(40)); e.read()
hkey = key_of(e.watch()[1])
e.recovery('%s %s' % (stamp(20), hkey))
code, out = e.watch()
check('C8 handover key sent 20 min ago, no RESUMED -> one STUCK line', code == 6 and 'STUCK' in out, '%s %s' % (code, out))
check('C9 ... and only once', e.watch()[0] == 2)

# ---- R1 additions: the waiter's real file text, item filter, keys, crash paths, coordinator ----
RF = 'chat: chat-alpha\npid: 4242\narm: ab12cd34\nstarted: %s\n'   # the inbox waiter's arm file layout
HF = 'utc: %s\narm: ab12cd34\n'                                    # the inbox waiter's heartbeat file layout
e = Env('a10')
e.put('.waiter-arm', RF % stamp(1)); e.put('.waiter-heartbeat', HF % stamp(1)); e.item(minutes_ago=20)
code, out = e.watch()
check('A10 inbox waiter file text, live heartbeat -> alive, no exit', code == 2, '%s %s' % (code, out))
e = Env('a10b')
e.put('.waiter-arm', RF % stamp(12)); e.put('.waiter-heartbeat', HF % stamp(11)); e.item(minutes_ago=20)
code, out = e.watch()
check('A10b inbox waiter file text, heartbeat 11 min old -> exit 5 (heartbeat)', code == 5 and 'heartbeat' in out and 'waiter:chat-alpha:ab12cd34' in out, '%s %s' % (code, out))

e = Env('a11')
e.arm(); e.heartbeat(11)
e.put('README.md', 'notes\n', 60); e.put('sent.md', 'x\n', 60)
check('A11 README.md and sent.md are not items -> no exit', e.watch()[0] == 2)
e = Env('a11b')
e.arm(); e.heartbeat(11); e.item(minutes_ago=20)
e.put('ACKS.md', 'lead-T1-1 Done\n', 11)
check('A11b ACKS status is case-insensitive (Done) -> no exit', e.watch()[0] == 2)

e = Env('a15')
cin = os.path.join(e.elv, 'coordinator', 'inbox'); os.makedirs(cin)
e.inbox = cin
e.arm(); e.heartbeat(11); e.item(minutes_ago=20)
code, out = e.watch()
check('A15 coordinator inbox with a dead waiter + waiting item -> exit 5', code == 5 and 'coordinator' in out, '%s %s' % (code, out))

# unit-style: a file that vanishes between listdir and stat must not kill the watcher
sys.path.insert(0, TOOLS)
import desk_watch as DW  # noqa: E402
e = Env('a14')
e.item('lead-T1-1', 20); e.put('%s-lead-2.md' % fstamp(30), 'id: lead-T1-2\n', 30)
real = os.path.getmtime
def flaky(path):
    if path.endswith('-lead-2.md'):
        raise FileNotFoundError(path)
    return real(path)
os.path.getmtime = flaky
try:
    got = DW.waiting_items(e.inbox, time.time())
    check('A14 a vanished item is skipped, the others still reported', got == ['lead-T1-1'], str(got))
except OSError as exc:
    check('A14 a vanished item is skipped, the others still reported', False, repr(exc))
finally:
    os.path.getmtime = real

# new episode: a recovered-then-re-armed waiter that dies again has a different key
e = Env('c11')
e.put('.waiter-arm', RF % stamp(12)); e.put('.waiter-heartbeat', HF % stamp(11)); e.item(minutes_ago=40)
k1 = key_of(e.watch()[1])
e.recovery('%s %s' % (stamp(5), k1))
check('C10a first episode suppressed once recorded', e.watch()[0] == 2)
e.put('.waiter-arm', (RF % stamp(11)).replace('ab12cd34', 'ef56ab78')); e.put('.waiter-heartbeat', (HF % stamp(11)).replace('ab12cd34', 'ef56ab78'))
code, out = e.watch()
check('C11 re-armed with a new arm id and dead again -> exit 5 with a new key', code == 5 and key_of(out) != k1 and 'ef56ab78' in key_of(out), '%s %s' % (code, out))

e = Env('c10')
add_cleared(e); e.item(minutes_ago=20)
code, out = e.watch()
ck = key_of(out)
e.recovery('%s %s' % (stamp(5), ck))
check('C10 cleared inbox: the whole key copied into recovery-sent.md suppresses it', code == 5 and e.watch()[0] == 2, '%s %s' % (code, out))
e = Env('c12')
e.arm('ab12'); e.heartbeat(11, 'ab12'); e.item(minutes_ago=40)
e.recovery('%s waiter:chat-alpha:ab12cd34' % stamp(5))
check('C12 a longer key in recovery-sent.md does not suppress a shorter one (whole-word match)', e.watch()[0] == 5)

# ---- additions from review: cutoff, rate limit, busy window, age limit, whole-word keys, impossible dates ----
import calendar  # noqa: E402
e = Env('a12')
e.arm(); e.heartbeat(11); e.item(minutes_ago=20); e.put('ACKS.md', 'lead-T1-1 acknowledged\n', 2)
check('A12 dead heartbeat but ACKS.md written 2 min ago (receiver busy on the item) -> no exit 5', e.watch()[0] == 2)
e.put('ACKS.md', 'lead-T1-1 acknowledged\n', 11)
check('A12b same with ACKS.md 11 min old -> exit 5 (the busy window is bounded)', e.watch()[0] == 5)

e = Env('a13')
add_cleared(e, minutes_ago=21); e.item(minutes_ago=20); e.desk(HO % stamp(20)); e.read()
code, out = e.watch()
check('A13 cleared chat with an open self-clear handover -> one exit, code 6, no exit-5 line', code == 6 and 'DEAD WAITER' not in out and 'NOT RESUMED' in out, '%s %s' % (code, out))
e.desk('[DESK UPDATE] Alpha RESUMED %s\n' % stamp(1)); e.read()
code, out = e.watch()
check('A13b resumed but still cleared and an item waiting -> exit 5 (cleared key)', code == 5 and 'waiter:chat-alpha:cleared-' in out, '%s %s' % (code, out))

e = Env('a16')
e.put('.waiter-arm', RF % stamp(12)); e.put('.waiter-heartbeat', 'utc: 2026-02-30T10:00:00Z\narm: ab12cd34\n'); e.item(minutes_ago=20)
code, out = e.watch()
check('A16 an impossible heartbeat date reads as no heartbeat, not a crash -> exit 5', code == 5 and 'no heartbeat' in out, '%s %s' % (code, out))
e = Env('a16b')
e.desk('[DESK HANDOVER] Other | self-clear, same chat local_other | 2026-13-45T10:00:00Z | x\n', 'local_other.md')
e.desk(HO % stamp(20)); e.read()
code, out = e.watch()
check('A16b an impossible handover date is skipped and the valid handover still raises exit 6', code == 6 and 'handover:chat-alpha:' in out, '%s %s' % (code, out))
try:   # in-process: a raise here must be a FAIL line, not a crash that hides every later check
    got = DW.parse_ts('x 2026-02-30T10:00:00Z y 2026-10-28T10:00:00Z')
    check('A16c parse_ts skips an impossible stamp and returns the next valid one',
          got == calendar.timegm((2026, 10, 28, 10, 0, 0, 0, 0, 0)), str(got))
except ValueError as exc:
    check('A16c parse_ts skips an impossible stamp and returns the next valid one', False, repr(exc))

e = Env('a17')
e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
e.recovery('%s waiter:chat-alpha:arm-1' % stamp(20))
with open(os.path.join(e.root, 'tools', 'state', 'stuck-raised.json'), 'w', encoding='utf-8') as f:
    f.write('[1, 2]\n')
code, out = e.watch()
check('A17 stuck-raised.json holding a JSON list: STUCK still raised with a WARNING, no crash', code == 5 and 'STUCK' in out and 'WARNING stuck-raised.json' in out, '%s %s' % (code, out))
check('A17a ... and the rewritten file then holds the key (no second STUCK)', e.watch()[0] == 2)
e = Env('a17b')
e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
with open(os.path.join(e.root, 'tools', 'state', 'reported.json'), 'w', encoding='utf-8') as f:
    f.write('{bad\n')
code, out = e.watch()
check('A17b a corrupt reported.json is reported as a WARNING with the alert', code == 5 and 'WARNING reported.json' in out, '%s %s' % (code, out))

e = Env('a18')
e.arm(); e.heartbeat(11); e.put('%s-lead-9.md' % fstamp(20), 'ID: lead-T1-9\nkind: Q\n', 20); e.put('ACKS.md', 'lead-T1-9 done\n', 30)
check('A18 an upper-case ID: line is read as the inbox waiter reads it (done -> no exit)', e.watch()[0] == 2)
e = Env('a18b')
e.arm(); e.heartbeat(11); e.item(minutes_ago=20); e.put('ACKS.md', 'foo lead-T1-1 done\n', 30)
check('A18b an ACKS line not shaped [<UTC>] <id> <status> settles nothing (as the inbox waiter) -> exit 5', e.watch()[0] == 5)

e = Env('b7')
e.since(10); e.desk(HO % stamp(20)); e.read()
check('B7 a handover stamped before the exit6-since.txt cutoff -> no exit 6', e.watch()[0] == 2)
check('B7b --since 30 min back puts the same handover after the cutoff -> exit 6', e.watch('--since', stamp(30))[0] == 6)

e = Env('b8')
e.desk(HO % stamp(20)); e.desk('[DESK UPDATE] Alpha loop 3 | x\n'); e.read()
check('B8 a later plain update is not RESUMED by default -> exit 6', e.watch()[0] == 6)
check('B8b with --resumed-any-update it counts -> no exit 6', e.watch('--resumed-any-update')[0] == 2)

e = Env('b9')
os.remove(os.path.join(e.root, 'tools', 'state', 'exit6-since.txt'))
e.desk(HO % stamp(20)); e.read()
code, out = e.watch()
sp = os.path.join(e.root, 'tools', 'state', 'exit6-since.txt')
st = DW.parse_ts(open(sp, encoding='utf-8').read()) if os.path.exists(sp) else None
check('B9 the first run writes exit6-since.txt (about now) and ignores the older handover', code == 2 and st is not None and abs(time.time() - st) < 120, '%s %s %s' % (code, out, st))
check('B9b a second run keeps that cutoff', e.watch()[0] == 2 and DW.parse_ts(open(sp, encoding='utf-8').read()) == st)
check('B9w the first run says the cutoff was set, on its exit-2 output', 'WARNING exit6-since.txt was missing' in out, out)
check('B9bw a later run prints no such WARNING', 'exit6-since.txt was missing' not in e.watch()[1])
e = Env('b9c')
os.remove(os.path.join(e.root, 'tools', 'state', 'exit6-since.txt'))
e.desk(HO % stamp(20)); e.read()
check('B9c a first run with --since 30 min back raises the 20-min-old handover (first-deployment route) -> exit 6', e.watch('--since', stamp(30))[0] == 6)

e = Env('b10')
e.desk(HO % stamp(20)); e.desk('[DESK UPDATE] Alpha RESUMEDNESS x\n'); e.read()
check('B10 RESUMEDNESS is not a RESUMED line -> exit 6', e.watch()[0] == 6)
e.desk('[DESK UPDATE] Alpha RESUMED-AFTER-CLEAR %s | x\n' % stamp(1)); e.read()
check('B10b RESUMED-AFTER-CLEAR counts -> no exit 6', e.watch()[0] == 2)

e = Env('b11')
e.desk('%s %s' % (stamp(20), HO % stamp(20))); e.read()
code, out = e.watch()
check('B11 a handover line led by a UTC stamp (as on the live desk) is seen -> exit 6', code == 6, '%s %s' % (code, out))
e.desk('%s [DESK UPDATE] Alpha RESUMED %s\n' % (stamp(1), stamp(1))); e.read()
check('B11b a RESUMED line led by a UTC stamp counts -> no exit 6', e.watch()[0] == 2)

e = Env('c13')
e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
c1 = e.watch(again=None)[0]
c2 = e.watch(again=None)[0]
time.sleep(1.2)
c3 = e.watch(again='1')[0]
check('C13 an alert nobody recorded is not raised again within --report-again-s (default 1800), then is', (c1, c2, c3) == (5, 2, 5), str((c1, c2, c3)))

e = Env('c14')
add_cleared(e, minutes_ago=30); e.item(minutes_ago=40)
code, out = e.watch()
k = key_of(out)
e.recovery(k)   # the key alone, no message stamp: the cleared stamp inside the key is not the message time
check('C14 a key-only recovery line is timed by the file, not by the stamp inside the key -> suppressed, no STUCK', 'cleared-' in k and e.watch()[0] == 2, '%s %s' % (k, out))

e = Env('c15')
e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
k = key_of(e.watch()[1])
e.recovery('%s key=%s' % (stamp(5), k))
check('C15 a recovery line copied as key=<key> suppresses the alert', e.watch()[0] == 2)

# ---- second review round: expectations come from the design, not from the tool's own output ----
import builtins  # noqa: E402


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))


def compact(t):
    return time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(t))


def first_line(out):
    return out.splitlines()[0] if out else ''


# B12: two self-clears in a row, the first RESUMED: the SECOND is flagged, keyed by its own line UTC.
e = Env('b12')
t2 = time.time() - 30 * 60   # one clock read for the second clear's stamp and its expected key
e.desk(HO % stamp(120))
e.desk('[DESK UPDATE] Alpha RESUMED %s after handover %s\n' % (stamp(110), stamp(120)))
e.desk(HO % iso(t2)); e.read()
code, out = e.watch()
check('B12 two self-clears, the first RESUMED: the second is flagged, key handover:<chat>:<its UTC as YYYYMMDDTHHMMSSZ>',
      code == 6 and key_of(out) == 'handover:chat-alpha:' + compact(t2), '%s %s' % (code, out))
e.desk('[DESK UPDATE] Alpha RESUMED %s after handover %s\n' % (stamp(0), iso(t2))); e.read()
check('B12b a RESUMED line after the second clear ends it -> no exit 6', e.watch()[0] == 2)

# A19: each cleared stamp is its own episode ("a new cleared stamp").
s1 = time.time() - 30 * 60
s2 = s1 + 5 * 60
keys19 = []
for tag, t in (('a19', s1), ('a19b', s2)):
    e = Env(tag)
    e.put('.waiter-arm', 'cleared %s\nchat: chat-alpha\n' % iso(t)); e.item(minutes_ago=20)
    keys19.append(key_of(e.watch()[1]))
check('A19 two cleared stamps give two keys, waiter:<chat>:cleared-<that stamp>',
      keys19 == ['waiter:chat-alpha:cleared-' + compact(s1), 'waiter:chat-alpha:cleared-' + compact(s2)], str(keys19))

# A4b: a LIVE waiter whose key was recorded 20 min ago, no stuck line yet -> nothing.
e = Env('a4b')
e.arm(); e.heartbeat(1); e.item(minutes_ago=40)
e.recovery('%s waiter:chat-alpha:arm-1' % stamp(20))
check('A4b live waiter, key recorded 20 min ago, STUCK not yet raised -> no exit (liveness, not the record, decides)', e.watch()[0] == 2)

# C16: a stampless 'sending <key>' line is timed from its first sight, not the file mtime.
e = Env('c16')
k16 = 'waiter:chat-alpha:arm-16'
rs = os.path.join(e.root, 'recovery-sent.md')
e.recovery('sending ' + k16); e.recovery('sent ' + k16)
t0 = time.time()
os.utime(rs, (t0 - 300, t0 - 300))
p16 = DW.desk_files.paths(e.root)
try:
    first = DW.recovery_state(p16, k16, t0)
    e.recovery('sending waiter:local_other:arm-9')   # another episode's line moves the file mtime to now
    later = DW.recovery_state(p16, k16, t0 + 11 * 60)
    check('C16 stampless key first seen 5 min old, another key appended, 11 min later -> STUCK due (16 min after its first line)',
          (first, later) == ('sent', 'stuck-due'), str((first, later)))
except Exception as exc:   # noqa: BLE001
    check('C16 stampless key first seen 5 min old, another key appended, 11 min later -> STUCK due (16 min after its first line)', False, repr(exc))
e = Env('c16b')
e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
e.recovery('sending waiter:chat-alpha:arm-1'); e.recovery('sent waiter:chat-alpha:arm-1')
t0 = time.time()
os.utime(os.path.join(e.root, 'recovery-sent.md'), (t0 - 16 * 60, t0 - 16 * 60))
code, out = e.watch()
check('C16b design-shaped sending/sent lines untouched 16 min, still down -> one STUCK (known-good)', code == 5 and 'STUCK' in out, '%s %s' % (code, out))
check('C16c ... only once', e.watch()[0] == 2)

# C17: STUCK is timed from the key's FIRST line, not a later retry line.
e = Env('c17')
e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
e.recovery('%s waiter:chat-alpha:arm-1' % stamp(20)); e.recovery('retry waiter:chat-alpha:arm-1 %s' % stamp(1))
code, out = e.watch()
check('C17 first line 20 min old, a retry line 1 min old -> STUCK (timed from the first line)', code == 5 and 'STUCK' in out, '%s %s' % (code, out))

# C18: 'failed' / 'ok' end the key even when tools/state has no stuck-raised entry (after failed, nothing more).
for tag, last in (('c18', 'failed'), ('c18b', 'ok')):
    e = Env(tag)
    e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
    k = 'waiter:chat-alpha:arm-1'
    for l in ('sending ' + k, 'sent ' + k, 'retry %s %s' % (k, stamp(35)), '%s %s %s' % (last, k, stamp(5))):
        e.recovery(l)
    t0 = time.time()
    os.utime(os.path.join(e.root, 'recovery-sent.md'), (t0 - 40 * 60, t0 - 40 * 60))
    code, out = e.watch()
    check('%s a key ended by a %s line, no stuck-raised.json, file 40 min old -> no exit' % ('C18' if tag == 'c18' else 'C18b', last), code == 2, '%s %s' % (code, out))
e = Env('c18c')
e.desk(HO % stamp(60)); e.read()
hk = key_of(e.watch()[1])
for l in ('sending ' + hk, 'sent ' + hk, 'retry %s %s' % (hk, stamp(35)), 'failed %s %s' % (hk, stamp(5))):
    e.recovery(l)
t0 = time.time()
os.utime(os.path.join(e.root, 'recovery-sent.md'), (t0 - 40 * 60, t0 - 40 * 60))
code, out = e.watch()
check('C18c after failed, no exit-6 line names the handover key again', code == 2 and hk.startswith('handover:'), '%s %s %s' % (hk, code, out))

# C19: the exit-6 STUCK line names the waiting item ids of that chat's inbox.
e = Env('c19')
add_cleared(e, minutes_ago=41); e.item('lead-T1-7', 40); e.desk(HO % stamp(40)); e.read()
code, out = e.watch()
hk = key_of(out)
e.recovery('%s %s' % (stamp(20), hk))
code, out = e.watch()
stuck = next((l for l in out.splitlines() if 'STUCK' in l), '')
check('C19 exit-6 STUCK line carries "waiting: lead-T1-7" and the key', code == 6 and 'waiting: lead-T1-7' in stuck and stuck.endswith('key=' + hk), '%s %s' % (code, out))

# C20: a key followed by punctuation, or inside backticks, is still the key.
for tag, fmt in (('c20', '%s refused %s.'), ('c20b', '%s `%s`')):
    e = Env(tag)
    e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
    e.recovery(fmt % (stamp(5), 'waiter:chat-alpha:arm-1'))
    check('%s a key recorded as %r suppresses the alert' % ('C20' if tag == 'c20' else 'C20b', fmt), e.watch()[0] == 2)

# A20: the watch set is visible; a wrong root, an empty root, an unlistable lanes/ or desk file is loud.
e = Env('a20')
code, out = e.watch('--pipeline-root', os.path.join(TMP, 'no-such-pipeline'))
check('A20 a missing pipeline root: exit-2 line says exit5 inboxes=0 (off: ...) and a WARNING follows',
      code == 2 and 'exit5 inboxes=0 (off:' in first_line(out) and 'WARNING exit 5 off' in out, '%s %s' % (code, out))
empty = os.path.join(TMP, 'a20-empty-elv'); os.makedirs(empty, exist_ok=True)
code, out = e.watch('--pipeline-root', empty)
check('A20b a root with no inboxes: WARNING exit 5 watches 0 inboxes, and the first line says degraded',
      code == 2 and 'WARNING exit 5 watches 0 inboxes' in out and 'degraded' in first_line(out), '%s %s' % (code, out))
e = Env('a20c')
lanes_dir = os.path.join(e.elv, 'lanes')
real_listdir = os.listdir


def bad_listdir(path='.'):
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(lanes_dir)):
        raise PermissionError(13, 'denied (test)', path)
    return real_listdir(path)


DW.WARN.clear()
os.listdir = bad_listdir
try:
    DW.inbox_dirs(e.elv)
finally:
    os.listdir = real_listdir
check('A20c an unlistable lanes/ folder adds a WARNING (not a silent empty watch set)', any('cannot list' in w for w in DW.WARN), str(DW.WARN))
e = Env('a20d')
os.makedirs(os.path.join(e.root, 'updates', 'local_held.md'))   # a desk "file" that cannot be read
code, out = e.watch()
check('A20d an unreadable desk file: exit 2 says degraded and names it', code == 2 and 'WARNING desk file' in out and 'degraded' in first_line(out), '%s %s' % (code, out))

# A21: a sharing violation shorter than the retry budget is ridden out; one that lasts is never "dead".
real_open = builtins.open


def flaky_open(suffix, times):
    left = {'n': times}

    def fake(path, *a, **k):
        if str(path).endswith(suffix) and (left['n'] is None or left['n'] > 0):
            if left['n'] is not None:
                left['n'] -= 1
            raise PermissionError(13, 'held (test)', str(path))
        return real_open(path, *a, **k)
    return fake


e = Env('a21')
e.arm(); e.heartbeat(1); e.item(minutes_ago=40)
try:
    DW.open = flaky_open('.waiter-heartbeat', 2)
    got = DW.waiter_state(e.inbox, time.time())
    check('A21 heartbeat refused twice, then readable -> alive (a short hold is ridden out)', got[:2] == (False, 'alive'), str(got))
except Exception as exc:   # noqa: BLE001
    check('A21 heartbeat refused twice, then readable -> alive (a short hold is ridden out)', False, repr(exc))
finally:
    DW.__dict__.pop('open', None)
try:
    DW.WARN.clear()
    DW.open = flaky_open('.waiter-heartbeat', None)
    hits = DW.dead_waiter_hits(DW.desk_files.paths(e.root), e.elv, time.time())[0]
    check('A21b heartbeat refused every time: no exit-5 hit, a WARNING instead', hits == [] and any('unreadable' in w for w in DW.WARN), '%s %s' % (hits, DW.WARN))
except Exception as exc:   # noqa: BLE001
    check('A21b heartbeat refused every time: no exit-5 hit, a WARNING instead', False, repr(exc))
finally:
    DW.__dict__.pop('open', None)
t_in = os.path.join(e.elv, 'lanes', 'towers', 'inbox'); os.makedirs(t_in)
for n, body, ago in (('.waiter-arm', 'chat=local_towers pid=1 arm=t1\n', 0), ('.waiter-heartbeat', '%s t1\n' % stamp(11), 0),
                     ('%s-lead-1.md' % fstamp(20), 'id: lead-T2-1\n', 20)):
    with open(os.path.join(t_in, n), 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)
    tt = time.time() - ago * 60
    os.utime(os.path.join(t_in, n), (tt, tt))
try:
    DW.open = flaky_open(os.path.join('alpha', 'inbox', '.waiter-heartbeat'), None)
    hits = DW.dead_waiter_hits(DW.desk_files.paths(e.root), e.elv, time.time())[0]
    check('A21c one unreadable inbox does not hide another inbox\'s dead waiter', len(hits) == 1 and 'towers' in hits[0], str(hits))
except Exception as exc:   # noqa: BLE001
    check('A21c one unreadable inbox does not hide another inbox\'s dead waiter', False, repr(exc))
finally:
    DW.__dict__.pop('open', None)
e = Env('a21d')
e.item('lead-T1-1', 20); e.put('%s-lead-2.md' % fstamp(30), 'id: lead-T1-2\n', 30)
try:
    DW.WARN.clear()
    DW.open = flaky_open('-lead-2.md', None)
    got = DW.waiting_items(e.inbox, time.time())
    check('A21d an unreadable item is skipped and named in a WARNING; the others still count',
          got == ['lead-T1-1'] and any('lead-2.md unreadable' in w for w in DW.WARN), '%s %s' % (got, DW.WARN))
except Exception as exc:   # noqa: BLE001
    check('A21d an unreadable item is skipped and named in a WARNING; the others still count', False, repr(exc))
finally:
    DW.__dict__.pop('open', None)

# A22: recovery-sent.md held by a REAL second process with no sharing is not read as "no key".
HOLDER = os.path.join(TMP, 'hold_noshare.py')
with open(HOLDER, 'w', encoding='utf-8', newline='\n') as f:
    f.write('import ctypes, sys, time\n'
            'k = ctypes.windll.kernel32\n'
            'k.CreateFileW.restype = ctypes.c_void_p\n'
            'k.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]\n'
            'h = k.CreateFileW(sys.argv[1], 0xC0000000, 0, None, 3, 0x80, None)\n'
            'if h is None or h == ctypes.c_void_p(-1).value:\n'
            '    sys.exit(2)\n'
            'open(sys.argv[2], "w").write("held")\n'
            'time.sleep(float(sys.argv[3]))\n')
e = Env('a22')
e.arm(); e.heartbeat(11); e.item(minutes_ago=40)
k22 = key_of(e.watch()[1])
e.recovery('%s %s' % (stamp(5), k22))
check('A22a key recorded 5 min ago, file readable -> suppressed (control)', e.watch()[0] == 2)
ready = os.path.join(TMP, 'a22.ready')
hold = subprocess.Popen([sys.executable, '-B', '-I', HOLDER, os.path.join(e.root, 'recovery-sent.md'), ready, '120'])
try:
    for _ in range(300):
        if os.path.exists(ready) or hold.poll() is not None:
            break
        time.sleep(0.1)
    code, out = e.watch() if os.path.exists(ready) else (None, 'holder did not start (exit %s)' % hold.poll())
finally:
    hold.kill(); hold.wait()
check('A22 recovery-sent.md held with no sharing: no alert for the recorded key, a WARNING instead',
      code == 2 and 'WARNING recovery-sent.md unreadable' in out, '%s %s' % (code, out))

# A23: the first line of exits 0, 2, 5 and 6 names this file's sha256 and the exit-6 cutoff in force.
with open(os.path.join(TOOLS, 'desk_watch.py'), 'rb') as f:
    want_sha = hashlib.sha256(f.read()).hexdigest()[:12]
firsts = {}
e = Env('a23')
c, o = e.watch(); firsts[c] = first_line(o)
e.arm(); e.heartbeat(11); e.item(minutes_ago=20)
c, o = e.watch(); firsts[c] = first_line(o)
e.desk('[DESK Q] alpha | blocking: no | q\n')
c, o = e.watch(); firsts[c] = first_line(o)
e6 = Env('a23b')
e6.desk(HO % stamp(20)); e6.read()
c, o = e6.watch(); firsts[c] = first_line(o)
check('A23 exits 0, 2, 5 and 6 each name (desk_watch <the file\'s sha256[:12]>; ...) on their first line',
      sorted(firsts) == [0, 2, 5, 6] and all(('(desk_watch %s;' % want_sha) in v for v in firsts.values()), '%s %s' % (want_sha, firsts))
with open(os.path.join(e.root, 'tools', 'state', 'exit6-since.txt'), encoding='utf-8') as f:
    since_txt = f.read().strip()
check('A23s the exit-2 line names the exit-6 cutoff in force', ('exit6 since %s' % since_txt) in firsts.get(2, ''), '%s %s' % (since_txt, firsts.get(2)))

# A24: a state file that cannot be written after the alert is printed keeps the exit code.
e = Env('a24')
e.arm(); e.heartbeat(11); e.item(minutes_ago=20)
os.makedirs(os.path.join(e.root, 'tools', 'state', 'reported.json'))
code, out = e.watch()
check('A24 reported.json cannot be replaced: still exit 5, with a WARNING (not a crash, exit 1)', code == 5 and 'WARNING state not written' in out, '%s %s' % (code, out))

print('RESULT', 'FAIL' if fails else 'PASS', len(fails), 'failures')
if fails:
    print('kept for inspection:', TMP)
else:
    shutil.rmtree(TMP, ignore_errors=True)
    try:
        os.rmdir(TMP_ROOT)   # the shared parent too, but only when no other run is still using it (rmdir needs it empty)
    except OSError:
        pass
sys.exit(1 if fails else 0)
