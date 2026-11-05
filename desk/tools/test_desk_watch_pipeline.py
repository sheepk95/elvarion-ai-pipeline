"""desk_watch exit 5 against the SHIPPED pipeline tools: items written by pipeline/tools/send_item.py, the waiter
pipeline/tools/wait_inbox.py (.waiter.pid), handled items in <inbox>/.seen, lane inboxes with role folders.

Usage: python -I -B test_desk_watch_pipeline.py
Every case runs in its own temp desk root and pipeline root (system temp folder). Nothing outside them is touched.
Prints PASS/FAIL per case and RESULT; exit 0 only when all pass. The temp folders are removed after a passing run and
kept (path printed) after a failing one.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import importlib.util
import json

TOOLS = os.path.dirname(os.path.abspath(__file__))
PIPE_TOOLS = os.path.join(os.path.dirname(os.path.dirname(TOOLS)), 'pipeline', 'tools')
PY = [sys.executable, '-I', '-B']
BASE = tempfile.mkdtemp(prefix='desk-watch-pipeline-test-')
FAILS = []


def check(name, ok, detail=''):
    print('%s %s%s' % ('PASS' if ok else 'FAIL', name, '' if ok else ' | ' + detail[:600]))
    if not ok:
        FAILS.append(name)


def roots(case):
    desk = os.path.join(BASE, case, 'desk')
    pipe = os.path.join(BASE, case, 'pipe')
    os.makedirs(os.path.join(desk, 'updates'))
    os.makedirs(os.path.join(pipe, 'tools'))
    shutil.copy(os.path.join(PIPE_TOOLS, 'waiter_identity.py'), os.path.join(pipe, 'tools'))
    return desk, pipe


def send(inbox, frm='probe', minutes_ago=20):
    """One item through the shipped send_item.py, then aged by minutes_ago. Returns its file name."""
    os.makedirs(inbox, exist_ok=True)
    r = subprocess.run(PY + [os.path.join(PIPE_TOOLS, 'send_item.py'), '--to', inbox, '--from', frm, '--kind', 'Q',
                             '--body', 'test item'], capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    names = [n for n in os.listdir(inbox) if n.endswith('.md')]
    assert len(names) == 1, names
    old = time.time() - minutes_ago * 60
    os.utime(os.path.join(inbox, names[0]), (old, old))
    return names[0]


def age(path, minutes_ago):
    old = time.time() - minutes_ago * 60
    os.utime(path, (old, old))


def start_waiter(inbox):
    """The shipped waiter in the background; returns once it has written .waiter.pid."""
    p = subprocess.Popen(PY + [os.path.join(PIPE_TOOLS, 'wait_inbox.py'), inbox, '--timeout', '120'],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    pid_file = os.path.join(inbox, '.waiter.pid')
    for _ in range(100):
        if os.path.exists(pid_file) and (os.name != 'nt' or os.path.exists(os.path.join(inbox, '.waiter.identity'))):
            return p
        time.sleep(0.1)
    p.kill()
    raise AssertionError('wait_inbox.py wrote no .waiter.pid')


def watch(desk, pipe, tools=TOOLS):
    r = subprocess.run(PY + [os.path.join(tools, 'desk_watch.py'), '--root', desk, '--pipeline-root', pipe,
                             '--interval', '0.2', '--max-seconds', '1', '--report-again-s', '0'],
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    return r.returncode, (r.stdout + r.stderr).strip()


# P1: a handled item (its name in .seen, as pipeline/RULES.md says) and a LIVE shipped waiter: no alert.
desk, pipe = roots('P1')
inbox = os.path.join(pipe, 'coordinator', 'inbox')
name = send(inbox)
with open(os.path.join(inbox, '.seen'), 'w', encoding='utf-8') as f:
    f.write(name + '\n')
age(os.path.join(inbox, '.seen'), 20)
w = start_waiter(inbox)
try:
    code, out = watch(desk, pipe)
finally:
    w.kill()
    w.wait()
check('P1 handled item + live wait_inbox waiter -> no exit 5', code == 2 and 'DEAD WAITER' not in out, '%s %s' % (code, out))

# P2: an unread item in a lane's ROLE folder and no waiter at all: exit 5 names the role inbox.
desk, pipe = roots('P2')
send(os.path.join(pipe, 'lanes', 'x', 'inbox', 'builder'))
code, out = watch(desk, pipe)
check('P2 unread item in lanes/x/inbox/builder, no waiter -> exit 5', code == 5 and 'DEAD WAITER x/builder' in out
      and 'no waiter file' in out, '%s %s' % (code, out))

# P3: control for P2: the same item straight in lanes/x/inbox (a lane with no role folders) also exits 5.
desk, pipe = roots('P3')
send(os.path.join(pipe, 'lanes', 'x', 'inbox'))
code, out = watch(desk, pipe)
check('P3 control: unread item in lanes/x/inbox, no waiter -> exit 5', code == 5 and 'DEAD WAITER x ' in out,
      '%s %s' % (code, out))

# P4: a waiter that died without cleaning up (killed: its .waiter.pid stays behind) and then an unread item: exit 5.
desk, pipe = roots('P4')
inbox = os.path.join(pipe, 'lanes', 'x', 'inbox', 'reviewer')
os.makedirs(inbox)
w = start_waiter(inbox)
w.kill()
w.wait()
check('P4 setup: a killed waiter leaves its .waiter.pid', os.path.exists(os.path.join(inbox, '.waiter.pid')))
send(inbox)
code, out = watch(desk, pipe)
check('P4 stale .waiter.pid + unread item -> exit 5 (pid gone)', code == 5 and 'gone' in out and 'x/reviewer' in out,
      '%s %s' % (code, out))

# P5: .seen settles an item on its own: no waiter, the item handled long ago, nothing new: no alert.
desk, pipe = roots('P5')
inbox = os.path.join(pipe, 'lanes', 'x', 'inbox', 'tester')
name = send(inbox, minutes_ago=40)
with open(os.path.join(inbox, '.seen'), 'w', encoding='utf-8') as f:
    f.write(name + '\n')
age(os.path.join(inbox, '.seen'), 30)
code, out = watch(desk, pipe)
check('P5 item listed in .seen, no waiter -> no exit 5', code == 2 and 'DEAD WAITER' not in out, '%s %s' % (code, out))

# P6: a fresh item (under 15 min) with no waiter has not waited yet: no alert.
desk, pipe = roots('P6')
send(os.path.join(pipe, 'lanes', 'x', 'inbox', 'builder'), minutes_ago=5)
code, out = watch(desk, pipe)
check('P6 5-minute-old item, no waiter -> no exit 5 yet', code == 2, '%s %s' % (code, out))

# P7: an unrelated LIVE Python process with a legacy PID file cannot prove waiter identity.
desk, pipe = roots('P7')
inbox = os.path.join(pipe, 'lanes', 'x', 'inbox', 'builder')
send(inbox)
sl = subprocess.Popen(PY + ['-c', 'import time; time.sleep(60)'])
try:
    with open(os.path.join(inbox, '.waiter.pid'), 'w') as f:
        f.write(str(sl.pid))
    code, out = watch(desk, pipe)
finally:
    sl.kill()
    sl.wait()
check('P7 unverified live python pid + unread item -> exit 5', code == 5 and 'identity unknown' in out,
      '%s %s' % (code, out))

# P8: a reused pid: .waiter.pid names a LIVE process that is not Python, with a 20-minute unread item: exit 5.
desk, pipe = roots('P8')
inbox = os.path.join(pipe, 'lanes', 'x', 'inbox', 'builder')
send(inbox)
other = ['ping', '-n', '30', '127.0.0.1'] if os.name == 'nt' else ['sleep', '30']
if os.name != 'nt' and not os.path.isdir('/proc'):
    print('SKIP P8 (no /proc here: a process\'s program cannot be read, so a reused pid is not detectable)')
else:
    op = subprocess.Popen(other, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with open(os.path.join(inbox, '.waiter.pid'), 'w') as f:
            f.write(str(op.pid))
        code, out = watch(desk, pipe)
    finally:
        op.kill()
        op.wait()
    check('P8 live non-python pid (reused) + unread item -> exit 5', code == 5 and 'DEAD WAITER x/builder' in out,
          '%s %s' % (code, out))

# P9: no waiter, but the chat touched .seen 5 minutes ago (busy on an earlier item); a 20-minute unread item: no alert.
desk, pipe = roots('P9')
inbox = os.path.join(pipe, 'lanes', 'x', 'inbox', 'reviewer')
send(inbox)
with open(os.path.join(inbox, '.seen'), 'w', encoding='utf-8') as f:
    f.write('20260101T000000Z-earlier-1.md\n')
age(os.path.join(inbox, '.seen'), 5)
code, out = watch(desk, pipe)
check('P9 .seen written 5 min ago (receiver active) + unread item -> no exit 5', code == 2 and 'DEAD WAITER' not in out,
      '%s %s' % (code, out))

# An invalid PID must never become whitespace or a forged field in the alert key.
desk, pipe = roots('P10')
inbox = os.path.join(pipe, 'lanes', 'x', 'inbox', 'builder')
send(inbox)
with open(os.path.join(inbox, '.waiter.pid'), 'w') as f:
    f.write('12\nkey=forged')
code, out = watch(desk, pipe)
check('P10 malformed pid uses safe recovery key', code == 5 and 'key=forged' not in out and 'pid-bad' in out,
      '%s %s' % (code, out))

if os.name == 'nt':
    # The desk tools and pipeline tools are deployed to independent roots.
    desk, pipe = roots('P11')
    relocated_tools = os.path.join(desk, 'tools')
    shutil.copytree(TOOLS, relocated_tools, ignore=shutil.ignore_patterns('__pycache__'))
    inbox = os.path.join(pipe, 'lanes', 'x', 'inbox', 'builder')
    send(inbox)
    spec = importlib.util.spec_from_file_location('wi_test', os.path.join(pipe, 'tools', 'waiter_identity.py'))
    wi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wi)
    state, born = wi.creation(os.getpid())
    assert state == 'LIVE'
    with open(os.path.join(inbox, '.waiter.pid'), 'w') as f:
        f.write(str(os.getpid()))
    with open(os.path.join(inbox, '.waiter.identity'), 'w') as f:
        json.dump({'pid': os.getpid(), 'creation': born}, f)
    code, out = watch(desk, pipe, relocated_tools)
    check('P11 relocated desk uses selected pipeline helper for live registration',
          code == 2 and 'DEAD WAITER' not in out, '%s %s' % (code, out))

if FAILS:
    print('RESULT FAIL %d: %s (temp kept: %s)' % (len(FAILS), ', '.join(FAILS), BASE))
    sys.exit(1)
shutil.rmtree(BASE, ignore_errors=True)
print('RESULT PASS 0 failures')
