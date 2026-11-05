"""GPU lease ledger: every agent on a shared PC books the GPU here before a GPU job and closes the booking when the
job ends, so chats never overload the machine (standard library only; Windows is the tested platform).

Several AI agents (Claude, Codex, local scripts) run in different chats on one machine. Each one that is about to load
the GPU (a game editor, a renderer, a local model, a video encode) books it here first, says how many GB it needs, and
releases the booking when the job ends.

Environment variables (all optional):
  GPU_LEASE_DIR            ledger folder (default: ~/.gpu-lease)
  GPU_LEASE_CONS_PORT      folder of the legacy "give me the GPU" flag files (default: <temp folder>/cons-port)
  GPU_LEASE_BUDGET_GB      GB the leases may share (default 21.6, 90% of a 24 GB card)
  GPU_LEASE_AGENT          default value of --agent (default "claude")
  GPU_LEASE_SEEN_JSON      replaces the list of known GPU programs (selftest)
  GPU_LEASE_TEST_HOLD_S    selftest only: widen the read-decide-write window

State lives in the ledger folder (GPU_LEASE_DIR):
  active/<id>.json    one file per open lease (who, what, gb, exclusive, yields, pid, expires)
  closed/<id>.json    the same file, moved here when the lease closes (never deleted)
  queue/<id>.json     a waiting claim's place in line (removed when it opens or gives up)
  seen/<key>.json     a known GPU program running with no lease (auto-opened, auto-closed when it exits)
  ledger.jsonl        append-only log: open, renew, close, reap, refused, queued, yield-asked, seen-open, seen-close
  .lock               persistent kernel-locked mutex file; never delete or rename it while clients are running

Admission:
  - BUDGET_GB (21.6 of 24 GB; 2.4 kept for the desktop and any always-on local model server) is shared by leases and by seen
    (unbooked) GPU programs. nvidia-smi must also show the asked GB + 0.5 free.
  - An exclusive lease needs nothing else open; nothing opens beside an exclusive lease.
  - Old flags count as foreign exclusive bookings: GPU_HEAVY, or an unexpired cons-port/UNITY_PRIORITY not written here.
  - Waiting claims (--wait) queue first come, first served. A --yields lease (background work such as the 3D asset
    job) always queues behind ordinary claims.
  - Yielding: when the head of the queue is blocked only by --yields leases, it writes cons-port/UNITY_PRIORITY (the old
    "Unity wants the GPU" flag); background work that reads it finishes its current step and stops, its lease closes
    and the waiting claim opens, which keeps the flag until its own lease closes. An exclusive lease also holds the
    flag while open, so the old readers (other tools that watch the flag) pause as they always have.
  - A lease closes when its owner releases it, its pid dies, or it expires without a renew (reaped by the next call).
    A --pid does not stop expiry: --minutes still applies, so book the job's full length (max 480) or renew.
  - A flag left behind (expired, a dead pid, or written here for a lease that no longer exists) is moved aside, never
    honoured forever. Windows refuses a rename while a reader has the file open, so every move is retried for 3 s.

Usage (exit 0 = ok, 3 = GPU busy or refused, or no such lease for renew / adopt, 2 = bad arguments, 1 = tool error;
release of an unknown or closed id is 0; run returns its command's own exit code, 127 when the command cannot start,
and passes the booking id to it as GPU_LEASE_ID):
  python gpu_lease.py status [--json]
  python gpu_lease.py claim --who "<chat title>" --what "<job>" --gb 8 [--exclusive] [--yields] [--minutes 60]
                            [--pid 1234] [--wait 1800]
  python gpu_lease.py renew <id> [--minutes 60]
  python gpu_lease.py adopt <id> <pid>     count another process tree (Unity via Start-Process) as this lease's
  python gpu_lease.py release <id> [--note "done"]
  python gpu_lease.py run --who "<chat title>" --what "<job>" --gb 8 [--exclusive] [--yields] [--wait 1800]
                          -- <command ...>
"""
import argparse
import ctypes
import errno
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get('GPU_LEASE_DIR') or (Path.home() / '.gpu-lease'))
CONS = Path(os.environ.get('GPU_LEASE_CONS_PORT') or (Path(tempfile.gettempdir()) / 'cons-port'))
TOTAL_GB = 24.0
BUDGET_GB = float(os.environ.get('GPU_LEASE_BUDGET_GB') or 21.6)  # 90% of a 24 GB card
FREE_MARGIN_GB = 0.5  # nvidia-smi must show the lease's GB plus this much free
MAX_MINUTES = 480  # every lease, with or without --pid, expires unless renewed within this
HEARTBEAT_S = 60  # `run` renews every minute ...
HEARTBEAT_LEASE_MIN = 5  # ... to five minutes ahead, so a killed wrapper's lease lapses within 5 min
# A claim holds the ledger lock for one telemetry sample: PowerShell (timeout 30 s) plus nvidia-smi (timeout 15 s).
# Two claimants back to back can hold it for 90 s, so a waiting client must be able to outlast that.
LOCK_WAIT_S = 120.0
QUEUE_STALE_S = 120  # a queue ticket not refreshed for this long is dropped (its waiter died)
LABEL = 'gpu_lease'  # line 2 of a UNITY_PRIORITY written here starts with this

# Known GPU programs. A running one that sits outside every lease's process tree is "seen": logged and counted against
# the budget as if booked. name = image name, cmd = substring of the command line (lower case, forward slashes).
# GPU_LEASE_SEEN_JSON replaces the list (selftest).
PYTHONS = ['python.exe', 'pythonw.exe', 'py.exe']  # command-line rules match only these, never a shell that mentions them
SEEN_RULES = json.loads(os.environ.get('GPU_LEASE_SEEN_JSON') or 'null') or [
    {'kind': 'unity', 'name': 'unity.exe', 'gb': 6, 'exclusive': False},
    {'kind': 'blender', 'name': 'blender.exe', 'gb': 4, 'exclusive': False},
    {'kind': 'comfyui', 'name': PYTHONS, 'cmd': 'worker_entry.py --listen 127.0.0.1', 'gb': 16, 'exclusive': True},
    {'kind': 'ffmpeg-nvenc', 'name': 'ffmpeg.exe', 'cmd': '_nvenc', 'gb': 1, 'exclusive': False},
]
TEST_HOLD_S = float(os.environ.get('GPU_LEASE_TEST_HOLD_S') or 0)
RETRY_S = 3.0  # Windows refuses rename/replace/delete while another process has the file open: retry this long
PROCESS_SCAN = os.name == 'nt'  # process enumeration (PowerShell/CIM) exists only on Windows


def retry(fn, *args):
    """fn(*args), retried on PermissionError for up to RETRY_S (readers hold flag and lock files open briefly)."""
    end = time.monotonic() + RETRY_S
    while True:
        try:
            return fn(*args)
        except PermissionError:
            if time.monotonic() >= end:
                raise
            time.sleep(0.03)


def write_atomic(path, text):
    """Write text to path through a temp file and a retried replace; the temp file never outlives a failure."""
    tmp = Path(str(path) + '.tmp-%d' % os.getpid())
    tmp.write_text(text, encoding='utf-8')
    try:
        retry(os.replace, tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def now():
    return time.time()


def iso(t=None):
    return datetime.fromtimestamp(now() if t is None else t, timezone.utc).isoformat(timespec='seconds')


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def pid_started(pid):
    """An opaque start-time stamp of process pid (Windows creation FILETIME; Linux /proc start ticks), or None.

    Stored beside a pid so a reused pid (a new process given a dead one's number) does not keep a booking alive."""
    if not pid:
        return None
    if os.name != 'nt':
        try:
            with open('/proc/%d/stat' % int(pid), 'rb') as f:
                return int(f.read().rsplit(b')', 1)[1].split()[19])  # field 22, starttime
        except (OSError, ValueError, IndexError):
            return None  # no /proc (macOS) or gone: fall back to the pid check alone
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    k32.GetProcessTimes.argtypes = (ctypes.c_void_p,) + (ctypes.POINTER(ctypes.c_ulonglong),) * 4
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        t = [ctypes.c_ulonglong() for _ in range(4)]
        if not k32.GetProcessTimes(handle, *[ctypes.byref(x) for x in t]):
            return None
        return int(t[0].value)
    finally:
        k32.CloseHandle(handle)


def pid_alive(pid, started=None):
    """OpenProcess plus GetExitCodeProcess; never os.kill, which terminates the process on Windows.

    With started (a pid_started() stamp recorded when the booking was made), a live process whose stamp differs is a
    reused pid and counts as dead. A stamp that cannot be read now leaves the plain pid answer."""
    if not pid:
        return False
    if started is not None and pid_alive(pid):
        now_started = pid_started(pid)
        return now_started is None or now_started == started
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    k32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: it exists
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


# ---------- the mutex ----------
class Lock:
    """Kernel-owned lock on a persistent file; process death releases it. Never rename or unlink the file."""

    def __init__(self):
        self.path = ROOT / '.lock'

    def __enter__(self):
        ROOT.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        end = time.monotonic() + LOCK_WAIT_S
        try:
            while True:
                try:
                    if os.name == 'nt':
                        import msvcrt
                        os.lseek(self.fd, 0, os.SEEK_SET)
                        msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError as err:
                    if err.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) and getattr(err, 'winerror', None) not in (33, 36):
                        raise
                    if time.monotonic() >= end:
                        raise RuntimeError('could not get %s within %g s' % (self.path, LOCK_WAIT_S)) from err
                    time.sleep(0.02)
        except BaseException:
            os.close(self.fd)
            raise

    def __exit__(self, *exc):
        try:
            if os.name == 'nt':
                import msvcrt
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)


# ---------- the ledger ----------
def log_event(event, lease, **extra):
    rec = {'ts': iso(), 'event': event}
    rec.update(extra)
    rec['lease'] = lease
    with open(ROOT / 'ledger.jsonl', 'a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def sub(name):
    d = ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_dir(name):
    out = []
    for p in sorted(sub(name).glob('*.json')):
        try:
            out.append(json.loads(p.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    return out


def write_json(name, key, data):
    write_atomic(sub(name) / ('%s.json' % key), json.dumps(data, indent=1, ensure_ascii=False))


def drop(name, key):
    try:
        (ROOT / name / ('%s.json' % key)).unlink()
    except OSError:
        pass


def close_lease(lease, event, note=''):
    """Move active/<id>.json to closed/, log the event and release its UNITY_PRIORITY. Caller holds the Lock."""
    lease = dict(lease, closed=iso(), close_event=event, note=note)
    dst = sub('closed') / ('%s.json' % lease['id'])
    src = sub('active') / ('%s.json' % lease['id'])
    try:
        retry(os.replace, src, dst)  # move first: never open twice
    except FileNotFoundError:
        pass
    except OSError:
        if src.exists():
            raise  # still open: never report a close that did not happen
    try:
        write_atomic(dst, json.dumps(lease, indent=1, ensure_ascii=False))
    except OSError as err:
        sys.stderr.write('%s could not write %s: %s\n' % (iso(), dst, err))
    release_flag(lease['id'])
    log_event(event, lease)
    return lease


def why_stale(lease):
    if lease.get('expires', 0) <= now():
        return 'expired at %s' % iso(lease.get('expires', 0))
    if lease.get('pid') and not pid_alive(lease['pid'], lease.get('pid_started')):
        return 'pid %s is dead' % lease['pid']
    return None


def reap():
    """Close leases that expired or whose pid died, and drop dead queue tickets. Caller holds the Lock."""
    live = []
    for lease in read_dir('active'):
        why = why_stale(lease)
        if why:
            try:
                close_lease(lease, 'reap', why)
                continue
            except OSError as err:
                sys.stderr.write('%s could not reap %s (%s); still counted\n' % (iso(), lease['id'], err))
        live.append(lease)
    queue = []
    for t in read_dir('queue'):
        if now() - t.get('beat', 0) > QUEUE_STALE_S or not pid_alive(t.get('pid'), t.get('pid_started')):
            drop('queue', t['id'])
            release_flag(t['id'])
        else:
            queue.append(t)
    owner = flag_owner(flag_lines())
    if owner and owner not in {x['id'] for x in live + queue}:
        release_flag(owner)  # written here, but its lease or ticket is gone (crash between steps): never block forever
    return live, sorted(queue, key=lambda t: (bool(t.get('yields')), t['ts']))


# ---------- known GPU programs nobody booked ----------
PROCS_PS = r'''$ErrorActionPreference = 'Stop'
Get-CimInstance -ClassName Win32_Process -Property ProcessId, ParentProcessId, Name, CommandLine | ForEach-Object {
  [Console]::Out.WriteLine(('{0}|{1}|{2}|{3}' -f $_.ProcessId, $_.ParentProcessId, $_.Name, ([string]$_.CommandLine -replace '[\r\n|]', ' ')))
}
[Console]::Out.WriteLine('END')
'''


def processes():
    """{pid: (ppid, name lower, command line lower with / slashes)} or None when the list cannot be read."""
    if not PROCESS_SCAN:
        return None
    try:
        p = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', PROCS_PS],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=30, creationflags=0x08000000)
        lines = p.stdout.decode('utf-8', 'replace').splitlines()
        if p.returncode != 0 or not lines or lines[-1].strip() != 'END':
            return None
        out = {}
        for ln in lines[:-1]:
            parts = ln.split('|', 3)
            if len(parts) != 4 or not parts[0].isdigit() or not (parts[1] or '0').isdigit() or not parts[2]:
                return None  # a partial or malformed process list is not a successful scan
            out[int(parts[0])] = (int(parts[1] or 0), parts[2].lower(), parts[3].replace('\\', '/').lower())
        if os.getpid() not in out:
            return None  # a successful snapshot must include this process
        return out
    except Exception:
        return None


def under(pid, roots, procs):
    """True when pid or one of its ancestors is in roots (stops on loops)."""
    seen = set()
    while pid and pid not in seen:
        if pid in roots:
            return True
        seen.add(pid)
        pid = procs.get(pid, (0,))[0]
    return False


def scan_seen(procs, live):
    """[{key, kind, pid, gb, exclusive, yields}] for known GPU programs outside every lease's process tree and outside
    this command's own ancestry."""
    if procs is None:
        return None
    roots = {p for x in live for p in [x.get('pid')] + list(x.get('pids') or []) if p}
    me = set()
    p = os.getpid()
    while p and p not in me:
        me.add(p)
        p = procs.get(p, (0,))[0]
    def matches(r, v):
        names = r.get('name')
        names = [names] if isinstance(names, str) else names
        return (not names or v[1] in names) and ('cmd' not in r or r['cmd'] in v[2])

    out = []
    for r in SEEN_RULES:
        hits = {pid for pid, v in procs.items() if pid not in me and matches(r, v) and not under(pid, roots, procs)}
        for pid in sorted(hits):
            if under(procs[pid][0], hits, procs):
                continue  # a child of a program already counted under this rule (Unity workers, Blender children)
            out.append({'key': '%s-%d' % (r['kind'], pid), 'kind': r['kind'], 'pid': pid, 'gb': float(r['gb']),
                        'exclusive': bool(r.get('exclusive')), 'yields': bool(r.get('yields')),
                        'who': 'unbooked ' + r['kind'], 'what': procs[pid][1]})
    return out


def sync_seen(found):
    """Open seen/ entries for new programs; close those that exited or are now inside a lease. found is None when the
    process list could not be read: then only exited programs close. Caller holds the Lock. Returns the open ones."""
    old = {x['key']: x for x in read_dir('seen')}
    if found is None:
        found = [x for x in old.values() if pid_alive(x['pid'])]
    new = {x['key']: x for x in found}
    for key, x in old.items():
        if key not in new:
            drop('seen', key)
            log_event('seen-close', dict(x, closed=iso(), why='booked' if pid_alive(x['pid']) else 'exited'))
    for key, x in new.items():
        if key not in old:
            x = dict(x, started=iso())
            write_json('seen', key, x)
            log_event('seen-open', x)
    return [old.get(k, x) for k, x in new.items()]


# ---------- UNITY_PRIORITY, the old "give me the GPU" flag ----------
def flag_lines():
    try:
        return (CONS / 'UNITY_PRIORITY').read_text(encoding='utf-8-sig', errors='replace').splitlines()
    except OSError:
        return None


def flag_owner(lines):
    """The lease/ticket id that wrote UNITY_PRIORITY, or None when another tool did."""
    if lines and len(lines) > 1 and lines[1].startswith(LABEL + ' '):
        return lines[1].split()[1]
    return None


def foreign_hold(name, lines):
    """Why an old-style flag (line 1 = expiry epoch, line 2 names its pid) still holds the card, or None when it has
    expired or its pid is dead (old readers take such a claim over). No readable expiry counts as held."""
    try:
        expires = float(lines[0])
    except (IndexError, ValueError):
        return 'cons-port/%s has no readable expiry (treated as held)' % name
    if expires <= now():
        return None
    who = lines[1] if len(lines) > 1 else ''
    m = re.search(r'pid[ =:]*(\d+)\s*$', who) or re.fullmatch(r'\s*(\d+)\s*', who)
    if m and not pid_alive(int(m.group(1))):
        return None
    return 'cons-port/%s held until %s by %r' % (name, iso(expires), who)


def legacy_holds():
    """Foreign exclusive bookings made the old way: a live GPU_HEAVY, or a live UNITY_PRIORITY not written here."""
    out = []
    try:
        heavy = (CONS / 'GPU_HEAVY').read_text(encoding='utf-8-sig', errors='replace').splitlines()
    except OSError:
        heavy = None
    if heavy is not None:
        why = foreign_hold('GPU_HEAVY', heavy)
        if why:
            out.append(why)
    lines = flag_lines()
    if lines is not None and not flag_owner(lines):
        why = foreign_hold('UNITY_PRIORITY', lines)
        if why:
            out.append(why)
    return out


def write_flag(key, who, expires, pid=0):
    """Create (or, if ours, refresh) UNITY_PRIORITY. Old readers take over a claim whose "pid N" is dead, so a lease
    with no pid of its own names none (held until it expires). False when another id or tool holds the flag."""
    CONS.mkdir(parents=True, exist_ok=True)
    tail = ', pid %d' % pid if pid else ''
    text = '%d\n%s %s %s%s\n' % (expires, LABEL, key, who, tail)
    lines = flag_lines()
    if lines is not None:
        owner = flag_owner(lines)
        if owner == key:
            write_atomic(CONS / 'UNITY_PRIORITY', text)
            return True
        if owner is None and foreign_hold('UNITY_PRIORITY', lines):
            return False
        if owner is not None and (find_active(owner) or (ROOT / 'queue' / ('%s.json' % owner)).exists()):
            return False
        try:  # expired, dead pid, or our own orphan: move it aside (never deleted) and create ours
            retry(os.replace, CONS / 'UNITY_PRIORITY', CONS / ('UNITY_PRIORITY.stale-%s' % stamp()))
        except OSError:
            return False
    try:
        fd = os.open(CONS / 'UNITY_PRIORITY', os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except (FileExistsError, PermissionError):
        return False
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return True


def release_flag(key):
    """Move our UNITY_PRIORITY aside (retried while a reader holds it open); never raises."""
    if flag_owner(flag_lines()) == key:
        try:
            retry(os.replace, CONS / 'UNITY_PRIORITY', CONS / 'UNITY_PRIORITY.released')
        except OSError as err:
            sys.stderr.write('%s could not release cons-port/UNITY_PRIORITY (%s); reap retries\n' % (iso(), err))


# ---------- the card ----------
def gpu_free_gb():
    """(free GB, used GB) from nvidia-smi, or (None, None) when it cannot be read."""
    try:
        p = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
                           capture_output=True, timeout=15, stdin=subprocess.DEVNULL,
                           creationflags=0x08000000 if os.name == 'nt' else 0)
        if p.returncode:
            return None, None
        used, total = [float(x) for x in p.stdout.decode().strip().splitlines()[0].split(',')]
        if not math.isfinite(used) or not math.isfinite(total) or total <= 0 or used < 0 or used > total:
            return None, None
        return (total - used) / 1024.0, used / 1024.0
    except Exception:
        return None, None


def blockers(holders, gb, exclusive, free=None):
    """None when a lease of `gb` may open beside `holders` (open leases plus seen programs), else the reason."""
    legacy = legacy_holds()
    if legacy:
        return 'old-style booking: ' + '; '.join(legacy)
    ex = [x for x in holders if x.get('exclusive')]
    if ex:
        return 'exclusive %s open (%s: %s)' % (ex[0].get('id') or ex[0]['key'], ex[0]['who'], ex[0]['what'])
    if exclusive and holders:
        return 'exclusive needs an empty card; open: ' + ', '.join(
            '%s %s %.1f GB' % (x.get('id') or x['key'], x['who'], x['gb']) for x in holders)
    booked = sum(float(x.get('gb', 0)) for x in holders)
    if booked + gb > BUDGET_GB:
        return 'budget: %.1f GB booked + %.1f asked > %.1f GB' % (booked, gb, BUDGET_GB)
    if free is not None and free < gb + FREE_MARGIN_GB:
        return 'nvidia-smi shows only %.1f GB free (unbooked GPU use?); %.1f asked' % (free, gb)
    return None


# ---------- commands ----------
def new_id():
    return 'L%s-%s' % (datetime.now(timezone.utc).strftime('%m%d%H%M%S'), uuid.uuid4().hex[:4])


def new_lease(a, pid, lid):
    minutes = min(float(a.minutes), MAX_MINUTES)
    return {'id': lid, 'who': a.who, 'agent': a.agent, 'session': a.session or '', 'what': a.what, 'gb': float(a.gb),
            'exclusive': bool(a.exclusive), 'yields': bool(a.yields), 'pid': pid, 'pid_started': pid_started(pid),
            'host': os.environ.get('COMPUTERNAME', ''), 'started': iso(), 'expires': int(now() + minutes * 60),
            'renewed': iso()}


class TelemetryError(RuntimeError):
    """Admission cannot safely proceed without both telemetry sources."""


def claim(a, pid):
    """(lease, None) or (None, reason). With --wait, queues and waits up to a.wait seconds.

    Missing telemetry refuses admission (TelemetryError). With --wait it counts as a busy reason until the deadline:
    the queue ticket is kept and the claim polls again; only a sample still missing at the deadline raises. Off
    Windows process enumeration can never succeed, so the claim raises at once."""
    lid = new_id()
    end = now() + float(a.wait or 0)
    waiting = float(a.wait or 0) > 0
    last = None
    ticket = None

    def hold_place(why):
        """Write (or refresh) this claim's queue ticket. Caller holds the Lock."""
        nonlocal ticket
        if ticket is None:
            ticket = {'id': lid, 'ts': now(), 'beat': now(), 'pid': os.getpid(),
                      'pid_started': pid_started(os.getpid()), 'who': a.who,
                      'what': a.what, 'gb': float(a.gb), 'exclusive': bool(a.exclusive),
                      'yields': bool(a.yields)}
            log_event('queued', ticket, reason=why)
        ticket['beat'] = now()
        write_json('queue', lid, ticket)

    def admit(procs, free):
        """One admission decision from this poll's sample. Caller holds the Lock. Returns (lease or None, why)."""
        live, queue = reap()
        seen = sync_seen(scan_seen(procs, live))
        holders = live + seen
        why = blockers(holders, float(a.gb), a.exclusive, free)
        if TEST_HOLD_S:
            time.sleep(TEST_HOLD_S)  # selftest only: widen the read-decide-write window so a missing lock shows
        priority = (bool(a.yields), ticket['ts'] if ticket else now())
        ahead = [t for t in queue if t['id'] != lid and
                 (bool(t.get('yields')), t['ts']) < priority]
        if why is None and ahead:
            why = 'queued behind %s (%s: %s)' % (ahead[0]['id'], ahead[0]['who'], ahead[0]['what'])
        if why is None:
            lease = new_lease(a, pid, lid)
            # Only foreground exclusive work raises the old "give me the GPU" flag; background (--yields) work
            # must leave it free so a waiter can use it to ask that work to step aside.
            # A waiter that asked background work to yield keeps its flag until its own lease closes, or
            # the background job would come straight back mid-job.
            raised = flag_owner(flag_lines()) == lid
            if (a.exclusive and not a.yields) or raised:
                if not write_flag(lid, a.who, lease['expires'], pid):
                    why = 'cons-port/UNITY_PRIORITY appeared at the same moment'
        if why is None:
            write_json('active', lid, lease)
            log_event('open', lease)
            if ticket:
                drop('queue', lid)
            return lease, None
        if waiting:
            hold_place(why)
            # Head of the line and blocked only by background (--yields) work: ask it to step aside.
            if not a.yields and not ahead and not legacy_holds():
                rest = [x for x in holders if not x.get('yields')]
                if len(rest) < len(holders) and blockers(rest, float(a.gb), a.exclusive) is None:
                    if write_flag(lid, a.who, int(end), 0) and why != last:
                        log_event('yield-asked', ticket, yielding=[x.get('id') or x['key'] for x in holders
                                                                   if x.get('yields')])
        elif why != last:
            log_event('refused', {'who': a.who, 'what': a.what, 'gb': float(a.gb),
                                  'exclusive': bool(a.exclusive)}, reason=why)
        return None, why

    try:
        while True:
            blind = None  # the TelemetryError text when this poll could not read telemetry
            with Lock():
                # A claimant may have waited for this lock. Sample after acquiring it so an unbooked
                # process that started during that wait is not hidden by an old snapshot.
                procs = processes()
                free, _ = gpu_free_gb()
                missing = []
                if procs is None:
                    missing.append('process enumeration (PowerShell/CIM)')
                if free is None or not math.isfinite(free) or free < 0:
                    missing.append('GPU free memory (nvidia-smi)')
                if missing:
                    if procs is None and not PROCESS_SCAN:
                        raise TelemetryError('GPU admission refused: unavailable %s; process enumeration is '
                                             'Windows-only, so this tool cannot admit GPU work on this platform; '
                                             'use status for diagnostics' % ' and '.join(missing))
                    blind = ('GPU admission refused: unavailable %s; restore telemetry and retry; '
                             'use status for diagnostics' % ' and '.join(missing))
                    if not waiting:
                        raise TelemetryError(blind)
                    why = 'telemetry unavailable: ' + ' and '.join(missing)
                    hold_place(why)  # a blip while waiting: keep the place in line and poll again
                else:
                    lease, why = admit(procs, free)
                    if lease:
                        return lease, None
            if why != last:
                if waiting:
                    sys.stderr.write('%s waiting: %s\n' % (iso(), why))
                last = why
            if now() >= end:
                if blind is not None:
                    raise TelemetryError(blind)  # still no telemetry at the deadline
                return None, why
            time.sleep(min(10.0, max(0.5, end - now())))
    finally:
        if ticket and not find_active(lid):
            with Lock():
                drop('queue', lid)
                release_flag(lid)


def find_active(lid):
    try:
        return json.loads((ROOT / 'active' / ('%s.json' % lid)).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def renew(lid, minutes):
    with Lock():
        lease = find_active(lid)
        if not lease:
            return None
        lease['expires'] = int(now() + min(float(minutes), MAX_MINUTES) * 60)
        lease['renewed'] = iso()
        write_json('active', lid, lease)
        if (lease.get('exclusive') and not lease.get('yields')) or flag_owner(flag_lines()) == lid:
            try:
                write_flag(lid, lease['who'], lease['expires'], lease.get('pid') or 0)
            except OSError as err:
                sys.stderr.write('%s could not refresh cons-port/UNITY_PRIORITY: %s\n' % (iso(), err))
        return lease


def adopt(lid, pid):
    """Count pid's process tree as part of lease lid (Unity started with Start-Process sits outside the launcher's tree,
    so it would otherwise be counted again as unbooked). The lease still closes only on its own pid or expiry."""
    with Lock():
        lease = find_active(lid)
        if not lease:
            return None
        lease['pids'] = sorted(set(lease.get('pids') or []) | {int(pid)})
        write_json('active', lid, lease)
        log_event('adopt', lease, pid=int(pid))
        return lease


def release(lid, note=''):
    with Lock():
        lease = find_active(lid)
        if not lease:
            return None
        return close_lease(lease, 'close', note)


def status(as_json):
    procs = processes()
    free, used = gpu_free_gb()
    with Lock():
        live, queue = reap()
        seen = sync_seen(scan_seen(procs, live))
    booked = sum(float(x.get('gb', 0)) for x in live + seen)
    legacy = legacy_holds()
    if as_json:
        print(json.dumps({'leases': live, 'seen': seen, 'queue': queue, 'booked_gb': booked, 'budget_gb': BUDGET_GB,
                          'gpu_used_gb': used, 'gpu_free_gb': free, 'legacy': legacy,
                          'process_check': procs is not None}, indent=1))
        return 0
    print('GPU leases %s  booked %.1f / %.1f GB  card used %s GB, free %s GB' % (
        iso(), booked, BUDGET_GB, '?' if used is None else '%.1f' % used, '?' if free is None else '%.1f' % free))
    for x in live:
        print('  %s  %-5s %5.1f GB  %s | %s | pid %s | until %s%s' % (
            x['id'], 'EXCL' if x.get('exclusive') else 'share', x['gb'], x['who'], x['what'], x.get('pid') or '-',
            iso(x['expires']), ' | yields' if x.get('yields') else ''))
    for x in seen:
        print('  SEEN  %-5s %5.1f GB  %s | %s | pid %s (running with no lease)' % (
            'EXCL' if x.get('exclusive') else 'share', x['gb'], x['who'], x['what'], x['pid']))
    for t in queue:
        print('  WAITING  %s  %s | %s | %.1f GB%s' % (t['id'], t['who'], t['what'], t['gb'],
                                                     ' | yields' if t.get('yields') else ''))
    for x in legacy:
        print('  OLD-STYLE  ' + x)
    if procs is None:
        print('  (process check failed: unbooked GPU programs are not shown)')
    if not live and not seen and not legacy and not queue:
        print('  (nothing booked)')
    return 0


def run(a, cmd):
    lease, why = claim(a, os.getpid())
    if not lease:
        print('GPU BUSY: %s' % why, flush=True)
        return 3
    print('lease %s open: %s' % (lease['id'], lease['what']), flush=True)
    stop = threading.Event()

    def beat():
        while not stop.wait(HEARTBEAT_S):
            try:
                if renew(lease['id'], HEARTBEAT_LEASE_MIN) is None:
                    sys.stderr.write('%s WARNING: lease %s is no longer open (reaped?); the job runs unbooked\n'
                                     % (iso(), lease['id']))
            except Exception as err:
                sys.stderr.write('%s heartbeat failed: %s\n' % (iso(), err))

    renew(lease['id'], HEARTBEAT_LEASE_MIN)
    t = threading.Thread(target=beat, daemon=True)
    t.start()
    code = 1
    try:
        # GPU_LEASE_ID lets the job (or a launcher it starts) adopt its own process tree or renew this booking.
        try:
            code = subprocess.call(cmd, env=dict(os.environ, GPU_LEASE_ID=lease['id']))
        except OSError as err:  # not found / not runnable: 127 like a shell, never 3, which means "GPU busy"
            print('could not start %s: %s' % (cmd[0] if cmd else '(no command)', err), flush=True)
            code = 127
    finally:
        stop.set()
        try:
            release(lease['id'], 'run exited %s' % code)
            print('lease %s closed (exit %s)' % (lease['id'], code), flush=True)
        except (OSError, RuntimeError) as err:  # RuntimeError: the ledger lock was not free within LOCK_WAIT_S
            print('lease %s NOT closed (%s); it lapses within %d min' % (lease['id'], err, HEARTBEAT_LEASE_MIN),
                  flush=True)
    return code


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = []
    if '--' in argv:
        i = argv.index('--')
        argv, cmd = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sp = ap.add_subparsers(dest='op', required=True)
    s = sp.add_parser('status')
    s.add_argument('--json', action='store_true')
    for name in ('claim', 'run'):
        c = sp.add_parser(name)
        c.add_argument('--who', required=True, help='exact chat title (or the lane/thread name)')
        c.add_argument('--what', required=True, help='the job, e.g. "game editor playmode test"')
        c.add_argument('--gb', type=float, required=True, help='peak VRAM in GB (exclusive: still give your estimate)')
        c.add_argument('--exclusive', action='store_true', help='needs the whole card (timing runs, 3D generation)')
        c.add_argument('--yields', action='store_true',
                       help='background work: queues last and steps aside when someone waits (via UNITY_PRIORITY)')
        c.add_argument('--minutes', type=float, default=60, help='lease length before a renew is needed (max 480)')
        c.add_argument('--wait', type=float, default=0, help='seconds to queue for room (default: do not wait)')
        c.add_argument('--agent', default=os.environ.get('GPU_LEASE_AGENT', 'claude'), help='claude or codex')
        c.add_argument('--session', default='', help='the chat or thread id of the caller (free text)')
        if name == 'claim':
            c.add_argument('--pid', type=int, default=0, help='pid of the GPU process; the lease ends when it dies')
    r = sp.add_parser('renew')
    r.add_argument('id')
    r.add_argument('--minutes', type=float, default=60)
    ad = sp.add_parser('adopt')
    ad.add_argument('id')
    ad.add_argument('pid', type=int)
    rel = sp.add_parser('release')
    rel.add_argument('id')
    rel.add_argument('--note', default='')
    a = ap.parse_args(argv)
    if a.op == 'status':
        return status(a.json)
    if a.op in ('claim', 'run') and (not math.isfinite(a.gb) or a.gb <= 0 or a.gb > BUDGET_GB):
        ap.error('--gb must be more than 0 and at most the %g GB budget' % BUDGET_GB)
    if not math.isfinite(getattr(a, 'minutes', 1)) or getattr(a, 'minutes', 1) <= 0:
        ap.error('--minutes must be finite and more than 0')
    if not math.isfinite(getattr(a, 'wait', 0)) or getattr(a, 'wait', 0) < 0:
        ap.error('--wait must be finite and at least 0')
    if a.op == 'claim':
        lease, why = claim(a, a.pid)
        if not lease:
            print('GPU BUSY: %s' % why)
            return 3
        print(lease['id'])
        print('open until %s; release with: gpu_lease.py release %s' % (iso(lease['expires']), lease['id']))
        return 0
    if a.op == 'run':
        if not cmd:
            ap.error('run needs a command after --')
        return run(a, cmd)
    if a.op == 'renew':
        lease = renew(a.id, a.minutes)
        print('renewed until %s' % iso(lease['expires']) if lease else 'no open lease %s' % a.id)
        return 0 if lease else 3
    if a.op == 'adopt':
        lease = adopt(a.id, a.pid)
        print('lease %s now covers pid %d' % (a.id, a.pid) if lease else 'no open lease %s' % a.id)
        return 0 if lease else 3
    if a.op == 'release':
        try:
            lease = release(a.id, a.note)
        except OSError as err:
            print('COULD NOT CLOSE %s: %s (something holds the lease file open); run release again' % (a.id, err))
            return 1
        print('closed %s' % a.id if lease else 'no open lease %s (already closed or reaped)' % a.id)
        return 0
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except TelemetryError as err:
        print('GPU LEDGER ERROR: %s' % err, file=sys.stderr)
        sys.exit(1)
