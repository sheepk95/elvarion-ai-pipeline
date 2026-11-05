"""Self-test for gpu_lease.py against a throwaway folder (never a real ledger or cons-port folder).

Usage: python selftest.py        exit 0 when every check passes. Uses nvidia-smi's real free memory, so run it while
the card has at least 19 GB free.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = str(HERE / 'gpu_lease.py')
TMP = Path(tempfile.mkdtemp(prefix='gpu-lease-selftest-'))
FAKE = 'gpu-lease-selftest-fakejob'  # the only "known GPU program" during the test: never a real Unity or Blender
ENV = dict(os.environ, GPU_LEASE_DIR=str(TMP / 'lease'), GPU_LEASE_CONS_PORT=str(TMP / 'cons'),
           GPU_LEASE_BUDGET_GB='20',  # the checks below count against 20 GB; the default budget is 21.6
           GPU_LEASE_SEEN_JSON=json.dumps([{'kind': 'fake', 'cmd': FAKE, 'gb': 4, 'exclusive': False}]))
FAILS = []


def call(*args, timeout=120, env=None):
    p = subprocess.run([sys.executable, '-B', TOOL] + list(args), env=dict(ENV, **(env or {})), capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + detail))
    if not cond:
        FAILS.append(name)


def live():
    return json.loads(call('status', '--json')[1])['leases']


def lid(out):
    return out.splitlines()[0]


C = ['--who', 'selftest', '--what']
rc, out, _ = call('claim', *C, 'a', '--gb', '8')
a = lid(out)
check('shared 8 GB opens', rc == 0)
rc, out, _ = call('claim', *C, 'b', '--gb', '10')
b = lid(out)
check('shared 10 GB opens beside it', rc == 0)
rc, out, _ = call('claim', *C, 'c', '--gb', '4')
check('4 GB more is over the 20 GB budget', rc == 3 and 'budget' in out, out)
rc, out, _ = call('claim', *C, 'x', '--gb', '20', '--exclusive')
check('exclusive refused while shared leases are open', rc == 3 and 'exclusive needs an empty card' in out, out)
call('release', a, '--note', 'done')
call('release', b)
check('release closes both', live() == [])
closed = sorted(p.name for p in (TMP / 'lease' / 'closed').glob('*.json'))
check('closed leases are kept, not deleted', len(closed) == 2, str(closed))

# a lease whose pid died is reaped by the next call
dead = subprocess.Popen([sys.executable, '-c', 'pass'])
dead.wait()
rc, out, _ = call('claim', *C, 'dead-pid', '--gb', '2', '--pid', str(dead.pid))
check('lease with a pid opens', rc == 0)
check('lease of a dead pid is reaped', live() == [])

# a lease that expires is reaped
rc, out, _ = call('claim', *C, 'short', '--gb', '2', '--minutes', '0.02')
time.sleep(2)
check('expired lease is reaped', live() == [])

# exclusive writes the old UNITY_PRIORITY flag and releases it by rename
rc, out, _ = call('claim', *C, 'unity', '--gb', '10', '--exclusive')
u = lid(out)
flag = TMP / 'cons' / 'UNITY_PRIORITY'
check('exclusive mirrors cons-port/UNITY_PRIORITY', rc == 0 and flag.exists() and u in flag.read_text(), out)
check('mirror names no dead pid (old readers would take it over)', ', pid ' not in flag.read_text())
rc, out, _ = call('claim', *C, 'y', '--gb', '1')
check('shared refused while exclusive is open', rc == 3 and ('exclusive %s open' % u) in out, out)
call('release', u)
check('release renames the mirror', not flag.exists() and (TMP / 'cons' / 'UNITY_PRIORITY.released').exists())

# a reader holding the flag open (Windows refuses the rename then) only delays renew and release
rc, out, _ = call('claim', *C, 'held-open', '--gb', '4', '--exclusive')
ho = lid(out)


def hold_open(path, seconds):
    with open(path, 'rb'):
        time.sleep(seconds)


with ThreadPoolExecutor(1) as ex:
    fh = ex.submit(hold_open, flag, 1.5)
    time.sleep(0.3)
    rr = call('renew', ho, '--minutes', '30')
    fh.result()
check('renew survives a reader holding the flag open', rr[0] == 0 and 'Traceback' not in rr[2], rr[2][-300:])
with ThreadPoolExecutor(1) as ex:
    fh = ex.submit(hold_open, flag, 1.5)
    time.sleep(0.3)
    rr = call('release', ho)
    fh.result()
check('release survives a reader holding the flag open', rr[0] == 0 and not flag.exists(), rr[2][-300:])

# a release that cannot move the lease file says so and leaves the lease open (never a false "closed")
rc, out, _ = call('claim', *C, 'pinned', '--gb', '2')
pn = lid(out)
with ThreadPoolExecutor(1) as ex:
    fh = ex.submit(hold_open, TMP / 'lease' / 'active' / ('%s.json' % pn), 5)
    time.sleep(0.3)
    rr = call('release', pn)
    fh.result()
check('a blocked release fails loudly and the lease stays open', rr[0] == 1 and 'COULD NOT CLOSE' in rr[1]
      and [x['id'] for x in live()] == [pn], str(rr))
rr = call('release', pn)
check('release succeeds once the reader lets go', rr[0] == 0 and live() == [], str(rr))

# leftovers never block forever: our own orphan, an expired foreign flag, a foreign flag of a dead pid
for name, text in [('orphan written here', '%d\ngpu_lease L0000000000-dead selftest\n' % (time.time() + 600)),
                   ('expired foreign flag', '%d\nold run, pid 4\n' % (time.time() - 5)),
                   ('foreign flag of a dead pid', '%d\nold run, pid %d\n' % (time.time() + 600, dead.pid))]:
    flag.write_text(text)
    rc, out, _ = call('claim', *C, 'after ' + name, '--gb', '4', '--exclusive')
    check('a leftover %s does not block' % name, rc == 0 and lid(out) in flag.read_text(), out)
    call('release', lid(out))
(TMP / 'cons' / 'GPU_HEAVY').write_text('%d\n%d\n' % (time.time() - 5, os.getpid()))
rc, out, _ = call('claim', *C, 'after expired GPU_HEAVY', '--gb', '2')
check('an expired GPU_HEAVY does not block', rc == 0, out)
call('release', lid(out))
os.replace(TMP / 'cons' / 'GPU_HEAVY', TMP / 'cons' / 'GPU_HEAVY.released-expired')
rc, out, _ = call('claim', *C, 'bad', '--gb', '22')
check('more than the budget is a bad argument', rc == 2, out)
rc, out, _ = call('claim', *C, 'bad', '--gb', '2', '--minutes', '0')
check('zero minutes is a bad argument', rc == 2, out)

# a foreign old-style flag blocks every lease
flag.write_text('%d\nGame merge perf run, pid 4\n' % (time.time() + 600))
rc, out, _ = call('claim', *C, 'z', '--gb', '1')
check('foreign UNITY_PRIORITY blocks', rc == 3 and 'old-style booking' in out, out)
os.replace(flag, TMP / 'cons' / 'UNITY_PRIORITY.released-test')
(TMP / 'cons' / 'GPU_HEAVY').write_text('x')
rc, out, _ = call('claim', *C, 'z', '--gb', '1')
check('GPU_HEAVY blocks', rc == 3 and 'GPU_HEAVY' in out, out)
os.replace(TMP / 'cons' / 'GPU_HEAVY', TMP / 'cons' / 'GPU_HEAVY.released-test')

# twelve agents race for 3 GB each: exactly six fit in 20 GB. The test hold keeps each one 0.5 s between reading the
# ledger and writing its lease, so without the mutex they overlap every time (red control: 12 of 12 admitted).
with ThreadPoolExecutor(12) as ex:
    res = list(ex.map(lambda i: call('claim', *C, 'race%d' % i, '--gb', '3',
                                     env={'GPU_LEASE_TEST_HOLD_S': '0.5'}), range(12)))
ok = [r for r in res if r[0] == 0]
check('race: exactly 6 of 12 admitted', len(ok) == 6, '%d admitted' % len(ok))
check('race: ledger shows 6 open', len(live()) == 6)
for r in ok:
    call('release', lid(r[1]))

# run: lease held while the command runs, closed after; a second exclusive run waits for the first
with ThreadPoolExecutor(2) as ex:
    f1 = ex.submit(call, 'run', *C, 'run1', '--gb', '6', '--exclusive', '--',
                   sys.executable, '-c', 'import time; time.sleep(6)')
    time.sleep(2.5)
    mid = live()
    f2 = ex.submit(call, 'run', *C, 'run2', '--gb', '6', '--exclusive', '--wait', '60', '--',
                   sys.executable, '-c', 'pass')
    r1, r2 = f1.result(), f2.result()
check('run holds its lease while the command runs', len(mid) == 1 and mid[0]['what'] == 'run1', str(mid))
check('second exclusive run waited, then ran', r1[0] == 0 and r2[0] == 0 and 'waiting' in r2[2], r2[2][-300:])
check('both run leases closed', live() == [])
def sleeper(*extra):
    return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'] + list(extra))


def wait_for(cond, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.5)
    return False


# queue: first come, first served
rc, out, _ = call('claim', *C, 'holder', '--gb', '4', '--exclusive')
h = lid(out)
with ThreadPoolExecutor(2) as ex:
    fb = ex.submit(call, 'claim', *C, 'first', '--gb', '4', '--wait', '90')
    wait_for(lambda: len(json.loads(call('status', '--json')[1])['queue']) == 1)
    fc = ex.submit(call, 'claim', *C, 'second', '--gb', '4', '--exclusive', '--wait', '90')
    wait_for(lambda: len(json.loads(call('status', '--json')[1])['queue']) == 2)
    call('release', h)
    rb = fb.result()
    st = json.loads(call('status', '--json')[1])
    check('queue: the first waiter opens first', rb[0] == 0 and [x['what'] for x in st['leases']] == ['first'],
          str(st['leases']))
    check('queue: the second waits behind it', [t['what'] for t in st['queue']] == ['second'], str(st['queue']))
    call('release', lid(rb[1]))
    rc_ = fc.result()
    check('queue: the second opens once the first closes', rc_[0] == 0, rc_[1] + rc_[2][-200:])
    call('release', lid(rc_[1]))

# yield: a --yields lease steps aside when someone waits
bg = sleeper()
rc, out, _ = call('claim', *C, 'background 3D job', '--gb', '12', '--exclusive', '--yields', '--pid', str(bg.pid))
check('yields lease opens', rc == 0, out)
check('a yields lease does not raise UNITY_PRIORITY itself', not flag.exists())
with ThreadPoolExecutor(1) as ex:
    fx = ex.submit(call, 'claim', *C, 'unity test', '--gb', '6', '--wait', '90')
    asked = wait_for(lambda: flag.exists() and 'gpu_lease' in flag.read_text() and lid(out) not in flag.read_text())
    check('waiter writes UNITY_PRIORITY to ask the background job to yield', asked)
    bg.kill()  # the supervisor's part: finish the current item and exit
    bg.wait()
    rx = fx.result()
check('waiter opens once the background job exits', rx[0] == 0, rx[1] + rx[2][-200:])
check('a waiter keeps its yield flag while its lease is open (the background job stays paused)',
      flag.exists() and lid(rx[1]) in flag.read_text())
rr = call('renew', lid(rx[1]), '--minutes', '30')
check('renew refreshes the yield flag it holds', str(int(json.loads(call('status', '--json')[1])['leases'][0]['expires']))
      == flag.read_text().splitlines()[0])
call('release', lid(rx[1]))
check('the yield flag goes when that lease closes', not flag.exists())
rc, out, _ = call('claim', *C, 'bg2', '--gb', '12', '--exclusive', '--yields', '--wait', '5')
y2 = lid(out) if rc == 0 else None
rc2, out2, _ = call('claim', *C, 'no-wait', '--gb', '2')
check('a claim without --wait does not make anyone yield', rc2 == 3 and not flag.exists(), out2)
if y2:
    call('release', y2)

# seen: a known GPU program with no lease is logged, counted and closed
fake = sleeper(FAKE)
st = json.loads(call('status', '--json')[1])
check('unbooked GPU program is seen', [x['pid'] for x in st['seen']] == [fake.pid], str(st['seen']))
rc, out, _ = call('claim', *C, 'big', '--gb', '18')
check('seen program counts against the budget', rc == 3 and 'budget' in out, out)
rc, out, _ = call('run', *C, 'wrapped', '--gb', '4', '--', sys.executable, '-c', 'import time; time.sleep(1)', FAKE)
st2 = json.loads(call('status', '--json')[1])
check('a program inside a lease is not seen twice', rc == 0 and len(st2['seen']) == 1, str(st2['seen']))
rc, out, _ = call('claim', *C, 'adopter', '--gb', '4')
ad = lid(out)
rc, out, _ = call('adopt', ad, str(fake.pid))
st2 = json.loads(call('status', '--json')[1])
check('adopt: a process started outside the tree counts as the lease, not seen', rc == 0 and st2['seen'] == [],
      str(st2['seen']))
call('release', ad)
fake.kill()
fake.wait()
st = json.loads(call('status', '--json')[1])
check('seen program closes when it exits', st['seen'] == [], str(st['seen']))
check('no temp files left behind', not list(TMP.rglob('*.tmp-*')), str(list(TMP.rglob('*.tmp-*'))))

events = [json.loads(x)['event'] for x in (TMP / 'lease' / 'ledger.jsonl').read_text().splitlines()]
check('ledger logs every event kind', {'open', 'close', 'reap', 'refused', 'queued', 'yield-asked', 'seen-open',
                                       'seen-close'} <= set(events), str(sorted(set(events))))

if FAILS:
    print('\nFAILED (%d failed) folder kept: %s' % (len(FAILS), TMP))
else:
    shutil.rmtree(TMP, ignore_errors=True)
    print('\nALL PASS (0 failed) folder removed: %s' % TMP)
sys.exit(1 if FAILS else 0)
