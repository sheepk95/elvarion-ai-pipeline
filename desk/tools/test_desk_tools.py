"""Self-test for desk/tools desk_read.py and desk_watch.py in a throwaway root."""
import atexit, os, shutil, subprocess, sys, tempfile, time

TOOLS = os.path.dirname(os.path.abspath(__file__))  
root = tempfile.mkdtemp(prefix='desktest-')
atexit.register(shutil.rmtree, root, True)   # removed even when a step raises
# never read a real pipeline folder. Both the flag and the env var point at an empty scratch root.
elv = os.path.join(root, 'elv-empty')
os.makedirs(elv)
os.environ['PIPELINE_ROOT'] = elv
os.makedirs(os.path.join(root, 'updates'))
os.makedirs(os.path.join(root, 'tools', 'state'))
lane = os.path.join(root, 'updates', 'local_aaaa.md')
fails = []


def run(script, *args):
    r = subprocess.run([sys.executable, '-B', '-I', os.path.join(TOOLS, script), '--root', root,
                        *(['--pipeline-root', elv] if script == 'desk_watch.py' else []), *args],
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    return r.returncode, r.stdout.strip()


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ' :: ' + detail))
    if not cond:
        fails.append(name)


def append(text):
    with open(lane, 'ab') as f:
        f.write(text.encode('utf-8'))


def watch_bg(*args):
    return subprocess.Popen([sys.executable, '-B', '-I', os.path.join(TOOLS, 'desk_watch.py'), '--root', root,
                             '--pipeline-root', elv, *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')


# 1 read sees a new update, then nothing
append('[DESK UPDATE] G9 loop 1 | 2026-10-26T04:10:00Z | ok – café | /x/report.md\n')
code, out = run('desk_read.py')
check('read sees update', '1 new [DESK UPDATE]' in out and 'café' in out, out)
code, out = run('desk_read.py')
check('read consumed', '0 new [DESK Q], 0 new [DESK UPDATE]' in out, out)

# 2 watch with nothing new times out with exit 2
code, out = run('desk_watch.py', '--interval', '0.5', '--max-seconds', '1.5')
check('watch times out exit 2', code == 2, '%s %s' % (code, out))

# 3 half-written question does not fire; newline does
w = watch_bg('--interval', '0.5', '--max-seconds', '20')
time.sleep(1.5)
append('[DESK Q] G9 | blocking: no | half line')
time.sleep(2)
check('partial line does not fire', w.poll() is None, 'exited %s' % w.poll())
append('\n')
try:
    out, err = w.communicate(timeout=10)
except subprocess.TimeoutExpired:
    w.kill(); out, err = w.communicate()
check('newline fires exit 0', w.returncode == 0 and 'half line' in out, '%s %s %s' % (w.returncode, out, err))

# 4 watcher does not consume; peek shows, read consumes, watch then quiet
code, out = run('desk_read.py', '--peek')
check('peek shows question', '1 new [DESK Q]' in out, out)
code, out = run('desk_watch.py', '--interval', '0.5', '--max-seconds', '1')
check('unread question fires again at once', code == 0, '%s %s' % (code, out))
code, out = run('desk_read.py')
check('read consumes question', '1 new [DESK Q]' in out, out)
code, out = run('desk_watch.py', '--interval', '0.5', '--max-seconds', '1')
check('quiet after read', code == 2, '%s %s' % (code, out))

# 5 a second watcher refuses while one is alive
w = watch_bg('--interval', '1', '--max-seconds', '20')
time.sleep(1.5)
code, out = run('desk_watch.py', '--interval', '1', '--max-seconds', '2')
check('second watcher exit 4', code == 4, '%s %s' % (code, out))

# 6 STOP file stops the live watcher
open(os.path.join(root, 'tools', 'state', 'STOP-WATCH'), 'w').close()
try:
    out, err = w.communicate(timeout=10)
except subprocess.TimeoutExpired:
    w.kill(); out, err = w.communicate()
check('STOP exits 3', w.returncode == 3, '%s %s %s' % (w.returncode, out, err))
check('STOP removes watch.alive', not os.path.exists(os.path.join(root, 'tools', 'state', 'watch.alive')))
os.remove(os.path.join(root, 'tools', 'state', 'STOP-WATCH'))
code, out = run('desk_watch.py', '--interval', '1', '--max-seconds', '1')
check('re-arm right after STOP is not refused', code == 2, '%s %s' % (code, out))

# 7 shrink is reported and re-read
with open(lane, 'wb') as f:
    f.write(b'[DESK Q] G9 | blocking: yes | rewritten\n')
code, out = run('desk_read.py')
check('shrink noted and re-read', 'shrank' in out and 'rewritten' in out, out)

# 8 README and dot files are ignored; a second lane file is read
with open(os.path.join(root, 'updates', 'README.md'), 'w') as f:
    f.write('[DESK Q] example line in readme\n')
with open(os.path.join(root, 'updates', 'local_bbbb.md'), 'w', newline='\r\n') as f:
    f.write('[DESK UPDATE] G8 loop 2 | crlf line\n')
code, out = run('desk_read.py')
check('readme ignored, crlf lane read', '0 new [DESK Q], 1 new [DESK UPDATE]' in out and '\r' not in out, repr(out))

# 9 a copied question marked answered does not wake the watcher, but read still shows it
append('[DESK Q] G9 | blocking: no | old one | local_aaaa (answered: desk chat ruling, A)\n')
code, out = run('desk_watch.py', '--interval', '0.5', '--max-seconds', '1')
check('answered copy does not wake', code == 2, '%s %s' % (code, out))
code, out = run('desk_read.py')
check('answered copy still read', '1 new [DESK Q]' in out and 'old one' in out, out)

# 10 an update that only mentions [DESK Q] is not a question; a BOM before [DESK Q] still is
append('[DESK UPDATE] G9 closing | earlier [DESK Q] on X is resolved\n')
code, out = run('desk_watch.py', '--interval', '0.5', '--max-seconds', '1')
check('mention of [DESK Q] does not wake', code == 2, '%s %s' % (code, out))
code, out = run('desk_read.py')
check('mention counted as update only', '0 new [DESK Q], 1 new [DESK UPDATE]' in out, out)
with open(os.path.join(root, 'updates', 'local_cccc.md'), 'wb') as f:
    f.write('\ufeff[DESK Q] G7 | blocking: no | bom first line\n'.encode('utf-8'))
code, out = run('desk_watch.py', '--interval', '0.5', '--max-seconds', '1')
check('BOM question wakes', code == 0 and 'bom first line' in out, '%s %s' % (code, out))

shutil.rmtree(root, ignore_errors=True)
print('RESULT', 'FAIL' if fails else 'PASS', len(fails), 'failures')
sys.exit(1 if fails else 0)   # a FAIL must not exit 0
