"""Regression tests: desk_watch.py warnings are per poll, an unreadable lane file is named, and a corrupt
read-offsets.json neither crashes desk_read.py / desk_watch.py nor loses a question.

Usage: python -B -I test_desk_robustness.py [TOOLS_DIR]   (default: this folder; pass a neutered copy for born-red runs)
Stdlib only, offline. Everything runs in one temp folder that is removed at the end; no live desk or inbox is touched.
"""
import json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else HERE
TMP = tempfile.mkdtemp(prefix='desk-robust-')
fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ' :: ' + detail))
    if not cond:
        fails.append(name)


def stamp(minutes_ago):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - minutes_ago * 60))


def make_env(tag):
    """A desk root plus a pipeline root with one empty, waiter-less inbox (so exit 5 adds no WARNING of its own)."""
    root = os.path.join(TMP, tag + '-desk')
    elv = os.path.join(TMP, tag + '-elv')
    os.makedirs(os.path.join(root, 'updates'))
    os.makedirs(os.path.join(root, 'tools', 'state'))
    os.makedirs(os.path.join(elv, 'lanes', 'alpha', 'inbox'))
    with open(os.path.join(root, 'tools', 'state', 'exit6-since.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(stamp(60) + '\n')   # present, so the run's one-off "exit6-since.txt was missing" note is not printed
    return root, elv


def run(script, root, elv=None, *args):
    cmd = [sys.executable, '-B', '-I', os.path.join(TOOLS, script), '--root', root]
    if script == 'desk_watch.py':
        cmd += ['--pipeline-root', elv, '--report-again-s', '0']
    r = subprocess.run(cmd + list(args), capture_output=True, text=True, encoding='utf-8', timeout=60)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def first_line(out):
    return out.splitlines()[0] if out else ''


def write_lane(root, name, text):
    with open(os.path.join(root, 'updates', name), 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


# ---- 1. a warning from an early poll is not reported as 'degraded' at a later exit ----
root, elv = make_env('r1')
held = os.path.join(root, 'updates', 'local_held.md')
os.makedirs(held)   # a lane "file" that cannot be read (a folder of that name)
alive = os.path.join(root, 'tools', 'state', 'watch.alive')
w = subprocess.Popen([sys.executable, '-B', '-I', os.path.join(TOOLS, 'desk_watch.py'), '--root', root,
                      '--pipeline-root', elv, '--interval', '0.3', '--max-seconds', '4'],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
# watch.alive is rewritten at the start of every poll: its second distinct mtime means poll 1 has finished
seen, deadline = set(), time.time() + 20
while len(seen) < 2 and time.time() < deadline and w.poll() is None:
    try:
        seen.add(os.stat(alive).st_mtime_ns)
    except OSError:
        pass
    time.sleep(0.02)
check('R1 setup: the watcher completed a poll while the unreadable lane file existed', len(seen) >= 2,
      'mtimes seen %d, exit %s' % (len(seen), w.poll()))
os.rmdir(held)   # the problem clears; every later poll is clean
try:
    out, err = w.communicate(timeout=30)
except subprocess.TimeoutExpired:
    w.kill(); out, err = w.communicate()
out = out.strip()
check('R1 a lane file unreadable only in poll 1: the later exit 2 neither names it nor says degraded',
      w.returncode == 2 and 'local_held' not in out and 'degraded' not in first_line(out),
      '%s %r %r' % (w.returncode, out, err))

# ---- 2. an unreadable lane file is named (the Q scan never skips it silently), in the poll it happens ----
root, elv = make_env('r2')
os.makedirs(os.path.join(root, 'updates', 'local_held.md'))
code, out, err = run('desk_watch.py', root, elv, '--interval', '0.2', '--max-seconds', '0.5')
check('R2 an unreadable lane file: exit 2 says degraded and a WARNING says its [DESK Q] lines were not checked',
      code == 2 and 'degraded' in first_line(out) and 'WARNING lane file local_held.md unreadable' in out
      and 'not checked' in out, '%s %r %r' % (code, out, err))

# ---- 3. a corrupt read-offsets.json: warned about, read from 0 (no question lost), kept aside on rewrite ----
Q = '[DESK Q] G9 | blocking: no | survives a corrupt offsets file'
for tag, bad in (('r3', '{"local_a.md": 12,'), ('r3list', '[1, 2]'), ('r3val', '{"local_a.md": "x"}')):
    root, elv = make_env(tag)
    write_lane(root, 'local_a.md', '[DESK UPDATE] G9 loop 1 | old news\n' + Q + '\n')
    offs = os.path.join(root, 'tools', 'state', 'read-offsets.json')
    with open(offs, 'w', encoding='utf-8', newline='\n') as f:
        f.write(bad)
    code, out, err = run('desk_watch.py', root, elv, '--interval', '0.2', '--max-seconds', '0.5')
    check('%s desk_watch with read-offsets.json = %r: no crash, the question still wakes it (exit 0)' % (tag, bad),
          code == 0 and 'survives a corrupt offsets file' in out, '%s %r %r' % (code, out, err))
    check('%s desk_watch names read-offsets.json in a WARNING and says degraded' % tag,
          'WARNING' in out and 'read-offsets.json' in out and 'degraded' in first_line(out), '%r' % out)
    with open(offs, encoding='utf-8') as f:
        check('%s desk_watch (look-only) left the corrupt file untouched' % tag, f.read() == bad)
    code, out, err = run('desk_read.py', root)
    check('%s desk_read: no crash, shows the question again from byte 0' % tag,
          code == 0 and '1 new [DESK Q], 1 new [DESK UPDATE]' in out and 'survives a corrupt offsets file' in out,
          '%s %r %r' % (code, out, err))
    check('%s desk_read warns on stderr, naming the file' % tag, 'WARNING' in err and 'read-offsets.json' in err, err)
    kept = [n for n in os.listdir(os.path.dirname(offs)) if n.startswith('read-offsets.json.corrupt-')]
    body = None
    if len(kept) == 1:
        with open(os.path.join(os.path.dirname(offs), kept[0]), encoding='utf-8') as f:
            body = f.read()
    check('%s the corrupt file is kept as read-offsets.json.corrupt-<UTC> with its old content' % tag,
          len(kept) == 1 and body == bad, '%s %r' % (kept, body))
    try:
        with open(offs, encoding='utf-8') as f:
            good = json.load(f)
    except ValueError:
        good = None   # still the corrupt file: reported by the check below, not a crash of this test
    size = os.path.getsize(os.path.join(root, 'updates', 'local_a.md'))
    check('%s the new read-offsets.json is a JSON object with the whole lane file read' % tag,
          good == {'local_a.md': size}, '%r %d' % (good, size))
    code, out, err = run('desk_read.py', root)
    check('%s a second desk_read is quiet and keeps no second copy' % tag,
          '0 new [DESK Q], 0 new [DESK UPDATE]' in out and err == ''
          and len([n for n in os.listdir(os.path.dirname(offs)) if '.corrupt-' in n]) == 1, '%r %r' % (out, err))

# A closed output pipe must not acknowledge the question.
root, elv = make_env('closed-pipe')
write_lane(root, 'local_a.md', '[DESK Q] unread after broken pipe\n')
rfd, wfd = os.pipe()
os.close(rfd)
with os.fdopen(wfd, 'wb') as output:
    proc = subprocess.run([sys.executable, '-B', '-I', os.path.join(TOOLS, 'desk_read.py'), '--root', root],
                          stdout=output, stderr=subprocess.PIPE, timeout=20)
check('closed stdout fails', proc.returncode != 0)
code, out, err = run('desk_read.py', root)
check('closed stdout leaves question unread', code == 0 and 'unread after broken pipe' in out, out + err)
code, out, err = run('desk_read.py', root)
check('successful output advances offsets', code == 0 and '0 new [DESK Q]' in out, out + err)

# Same PID but different creation FILETIME is a different recovery episode.
import importlib.util
sys.path.insert(0, TOOLS)
spec = importlib.util.spec_from_file_location('watch_regression', os.path.join(TOOLS, 'desk_watch.py'))
watchmod = importlib.util.module_from_spec(spec); spec.loader.exec_module(watchmod)
inbox = os.path.join(TMP, 'identity-inbox'); os.makedirs(inbox)
with open(os.path.join(inbox, '.waiter.pid'), 'w') as f: f.write('1234')
watchmod.pipeline_waiter_status = lambda *args: 'DEAD'
keys = []
for creation in (111, 222):
    with open(os.path.join(inbox, '.waiter.identity'), 'w') as f: json.dump({'pid': 1234, 'creation': creation}, f)
    keys.append(watchmod.waiter_state(inbox, time.time())[2])
check('reused PID has separate recovery keys', keys[0] != keys[1], repr(keys))
check('closed previous recovery key does not close new episode',
      not watchmod.key_closed('ok ' + keys[0] + ' 2026-01-01T00:00:00Z', keys[1]), repr(keys))

# Unknown creation time: each newly registered process has a stable generation nonce.
keys = []
for generation in ('a' * 32, 'b' * 32):
    with open(os.path.join(inbox, '.waiter.identity'), 'w') as f:
        json.dump({'pid': 1234, 'creation': None, 'generation': generation}, f)
    keys.append(watchmod.waiter_state(inbox, time.time())[2])
check('unknown creation registrations have distinct keys', keys[0] != keys[1], repr(keys))
check('closed unknown creation episode does not suppress next',
      not watchmod.key_closed('ok ' + keys[0] + ' 2026-01-01T00:00:00Z', keys[1]), repr(keys))
check('unknown registration key stable within episode', watchmod.waiter_state(inbox, time.time())[2] == keys[1])

shutil.rmtree(TMP, ignore_errors=True)
print('RESULT', 'FAIL' if fails else 'PASS', len(fails), 'failures')
sys.exit(1 if fails else 0)
