"""CPU/file-only GPU admission and mutex regression tests; no live telemetry or ledger.

Run: python -B test_gpu_safety.py
Optional GPU_SAFETY_MODULE points at an older gpu_lease.py for a born-red comparison.
Optional GPU_SAFETY_TMP chooses the parent of the unique temporary test directory.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TARGET = Path(os.environ.get('GPU_SAFETY_MODULE') or Path(__file__).with_name('gpu_lease.py')).resolve()


def module(root):
    spec = importlib.util.spec_from_file_location('gpu_safety_target', TARGET)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.ROOT, m.CONS = Path(root) / 'ledger', Path(root) / 'cons'
    return m


def worker(mode, root):
    m = module(root)
    if mode == 'holder':
        with m.Lock():
            print('LOCKED', flush=True)
            time.sleep(60)
    elif mode == 'contender':
        # An old lock implementation sees the live holder as >20 seconds old.
        m.now = lambda: time.time() + 100
        m.LOCK_WAIT_S = 0.7
        try:
            with m.Lock():
                print('ACQUIRED', flush=True)
        except RuntimeError:
            print('BLOCKED', flush=True)
    elif mode == 'increment':
        counter = Path(root) / 'counter'
        for _ in range(5):
            with m.Lock():
                n = int(counter.read_text())
                time.sleep(0.02)
                counter.write_text(str(n + 1))
    elif mode == 'cli-missing':
        os.environ['GPU_LEASE_DIR'] = str(Path(root) / 'ledger')
        os.environ['GPU_LEASE_CONS_PORT'] = str(Path(root) / 'cons')
        sys.argv = [str(TARGET), 'run', '--who', 'test', '--what', 'test', '--gb', '1', '--', 'unused']
        with mock.patch('subprocess.run', side_effect=FileNotFoundError('stubbed missing telemetry')), \
             mock.patch('subprocess.call', side_effect=AssertionError('job was launched')):
            runpy.run_path(str(TARGET), run_name='__main__')


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gpu-safety-', dir=os.environ.get('GPU_SAFETY_TMP'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.m = module(self.root)
        self.m.processes = lambda: {}
        self.m.gpu_free_gb = lambda: (20.0, 4.0)

    def args(self, **overrides):
        vals = dict(wait=0, gb=1.0, exclusive=False, yields=False, who='test', what='test',
                    minutes=5, agent='test', session='')
        vals.update(overrides)
        return argparse.Namespace(**vals)

    def queue(self, yields):
        self.m.write_json('queue', 'ticket', dict(id='ticket', ts=time.time()-1, beat=time.time(),
                          pid=os.getpid(), who='queued', what='queued', gb=2, exclusive=False, yields=yields))

    def child(self, kind):
        return subprocess.Popen([sys.executable, '-B', __file__, '--worker', kind, str(self.root)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_reused_pid_does_not_keep_a_booking(self):
        if not hasattr(self.m, 'pid_started'):
            self.fail('no pid_started(): a reused pid keeps a dead job\'s booking alive')
        me = os.getpid()
        real = self.m.pid_started(me)
        self.assertIsNotNone(real, 'this process start time should be readable')
        self.assertEqual(real, self.m.pid_started(me), 'the stamp must be stable for one process')
        lease = dict(id='L1', expires=time.time() + 600, pid=me)
        self.assertIsNone(self.m.why_stale(dict(lease, pid_started=real)))
        self.assertIsNone(self.m.why_stale(lease), 'a record without a stamp keeps the plain pid check')
        self.assertIn('dead', self.m.why_stale(dict(lease, pid_started=real + 1)) or '',
                      'same pid, different start time: a reused pid must count as dead')
        ticket = dict(id='T1', ts=time.time(), beat=time.time(), pid=me, pid_started=real + 1, who='w', what='w',
                      gb=1, exclusive=False, yields=False)
        self.m.write_json('queue', 'T1', ticket)
        with self.m.Lock():
            _, queue = self.m.reap()
        self.assertEqual([], [t['id'] for t in queue], 'a queue ticket on a reused pid must be dropped')

    def test_new_bookings_record_the_start_time(self):
        lease, why = self.m.claim(self.args(), os.getpid())
        self.assertIsNone(why)
        self.assertEqual(self.m.pid_started(os.getpid()), lease.get('pid_started'))

    def test_run_passes_lease_id_and_reports_unstartable_command(self):
        a = self.args()
        seen = {}

        def fake_call(cmd, env=None):
            seen['id'] = (env or {}).get('GPU_LEASE_ID')
            return 5
        with mock.patch.object(self.m.subprocess, 'call', side_effect=fake_call):
            self.assertEqual(5, self.m.run(a, ['job']))
        self.assertRegex(seen.get('id') or '', r'^L\d{10}-[0-9a-f]{4}$')
        with mock.patch.object(self.m.subprocess, 'call', side_effect=FileNotFoundError('no such program')):
            self.assertEqual(127, self.m.run(a, ['missing-program']))
        self.assertEqual([], self.m.read_dir('active'), 'every run booking must be closed afterwards')

    def test_live_lock_not_stolen_and_crash_releases_it(self):
        holder = self.child('holder')
        def stop_holder():
            if holder.poll() is None:
                holder.kill()
            holder.communicate(timeout=5)
        self.addCleanup(stop_holder)
        self.assertEqual(holder.stdout.readline().strip(), 'LOCKED')
        contender = self.child('contender')
        out, err = contender.communicate(timeout=5)
        self.assertEqual(contender.returncode, 0, err)
        self.assertEqual(out.strip(), 'BLOCKED')
        holder.kill()
        holder.communicate(timeout=5)
        contender = self.child('contender')
        out, err = contender.communicate(timeout=5)
        self.assertEqual(contender.returncode, 0, err)
        self.assertEqual(out.strip(), 'ACQUIRED')

    def test_parallel_updates_are_serialized(self):
        (self.root / 'counter').write_text('0')
        children = [self.child('increment') for _ in range(4)]
        for child in children:
            out, err = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, out + err)
        self.assertEqual((self.root / 'counter').read_text(), '20')

    def test_foreground_passes_yielding_ticket(self):
        self.queue(True)
        lease, why = self.m.claim(self.args(), 0)
        self.assertIsNotNone(lease, why)

    def test_foreground_respects_earlier_foreground_ticket(self):
        self.queue(False)
        lease, why = self.m.claim(self.args(), 0)
        self.assertIsNone(lease)
        self.assertIn('queued behind', why)

    def test_yielding_claim_respects_earlier_yielding_ticket(self):
        self.queue(True)
        lease, why = self.m.claim(self.args(yields=True), 0)
        self.assertIsNone(lease)
        self.assertIn('queued behind', why)

    def test_missing_process_telemetry_refuses(self):
        self.m.processes = lambda: None
        with self.assertRaisesRegex(RuntimeError, 'process enumeration'):
            self.m.claim(self.args(), 0)
        self.assertFalse((self.m.ROOT / 'active').exists())

    def test_admission_samples_after_lock_wait(self):
        state = {'acquired': False}
        real_lock = self.m.Lock
        class DelayedAcquisition:
            def __enter__(inner):
                inner.lock = real_lock()
                inner.lock.__enter__()
                state['acquired'] = True  # simulate workload arriving during lock acquisition
                return inner
            def __exit__(inner, *exc):
                return inner.lock.__exit__(*exc)
        self.m.Lock = DelayedAcquisition
        self.m.processes = lambda: None if state['acquired'] else {}
        self.m.gpu_free_gb = lambda: (None, None) if state['acquired'] else (20, 4)
        with self.assertRaisesRegex(RuntimeError, 'process enumeration.*nvidia-smi'):
            self.m.claim(self.args(exclusive=True), 0)
        self.assertEqual(list((self.m.ROOT / 'active').glob('*.json')), [])

    def test_cli_rejects_nonfinite_wait_and_minutes_before_telemetry(self):
        for flag, value in (('--wait', 'nan'), ('--wait', 'inf'), ('--wait', '-1'),
                            ('--minutes', 'nan'), ('--minutes', 'inf'), ('--minutes', '0')):
            with self.subTest(flag=flag, value=value), mock.patch.object(
                    self.m, 'processes', side_effect=AssertionError('telemetry started')), \
                    mock.patch('sys.stderr', new_callable=__import__('io').StringIO):
                with self.assertRaises(SystemExit) as exit_value:
                    self.m.main(['claim', '--who', 'test', '--what', 'test', '--gb', '1', flag, value])
                self.assertEqual(exit_value.exception.code, 2)

    def test_missing_gpu_telemetry_refuses(self):
        self.m.gpu_free_gb = lambda: (None, None)
        with self.assertRaisesRegex(RuntimeError, 'nvidia-smi'):
            self.m.claim(self.args(), 0)
        self.assertFalse((self.m.ROOT / 'active').exists())

    def test_cli_refusal_is_an_error_and_does_not_launch(self):
        child = self.child('cli-missing')
        out, err = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 1, out + err)
        self.assertIn('GPU LEDGER ERROR', err)
        self.assertIn('nvidia-smi', err)
        self.assertNotIn('job was launched', err)

    def fake_clock(self):
        """Replace the module's clock with one that moves only when claim sleeps; returns the sleep patch."""
        clock = [time.time()]
        self.m.now = lambda: clock[0]
        def sleep(s):
            clock[0] += s
        return mock.patch.object(self.m.time, 'sleep', sleep)

    def test_telemetry_failure_cleans_up_existing_wait_ticket(self):
        # First poll: busy, so a queue ticket is written. Every later poll: no process telemetry until the
        # deadline, which must raise and still remove the ticket. The clock moves only in sleep, so a slow
        # first poll cannot reach the deadline early.
        calls = []
        def procs():
            calls.append(1)
            return {} if len(calls) == 1 else None
        self.m.processes = procs
        self.m.blockers = lambda *args: 'busy'
        with self.fake_clock():
            with self.assertRaisesRegex(RuntimeError, 'process enumeration'):
                self.m.claim(self.args(wait=30), 0)
        self.assertGreater(len(calls), 1, 'claim must have polled again after the busy answer')
        self.assertEqual(list((self.m.ROOT / 'queue').glob('*.json')), [])

    def test_wait_survives_one_telemetry_blip(self):
        checks = iter((None, {}))
        self.m.processes = lambda: next(checks)
        with mock.patch.object(self.m.time, 'sleep', lambda s: None):
            lease, why = self.m.claim(self.args(wait=30), os.getpid())
        self.assertIsNotNone(lease, 'one failed process scan while waiting must not abort the wait: %s' % why)
        self.assertEqual(list((self.m.ROOT / 'queue').glob('*.json')), [], 'the ticket closes when the lease opens')

    def test_wait_blip_keeps_the_queue_ticket(self):
        state = {'n': 0, 'queued': None}
        def procs():
            state['n'] += 1
            if state['n'] == 2:  # second poll: the first poll's blip must have left this claim's ticket in line
                state['queued'] = [p.name for p in (self.m.ROOT / 'queue').glob('*.json')]
            return None if state['n'] == 1 else {}
        self.m.processes = procs
        with mock.patch.object(self.m.time, 'sleep', lambda s: None):
            lease, why = self.m.claim(self.args(wait=30), os.getpid())
        self.assertIsNotNone(lease, why)
        self.assertEqual(['%s.json' % lease['id']], state['queued'])

    def test_off_windows_refuses_at_once_naming_the_platform(self):
        self.m.PROCESS_SCAN = False
        self.m.processes = lambda: None
        slept = []
        with mock.patch.object(self.m.time, 'sleep', lambda s: slept.append(s)):
            with self.assertRaisesRegex(RuntimeError, 'Windows-only'):
                self.m.claim(self.args(wait=30), 0)
        self.assertEqual([], slept, 'process enumeration never works off Windows: do not wait for it')
        self.assertEqual(list((self.m.ROOT / 'queue').glob('*.json')), [])

    def test_wait_ticket_records_the_start_time(self):
        self.m.blockers = lambda *args: 'busy'
        seen, real = [], self.m.write_json
        def spy(kind, lid, data):
            if kind == 'queue':
                seen.append(dict(data))
            return real(kind, lid, data)
        self.m.write_json = spy
        with self.fake_clock():
            lease, _ = self.m.claim(self.args(wait=0.05), os.getpid())
        self.assertIsNone(lease)
        self.assertTrue(seen, 'a --wait claim must write a queue ticket')
        self.assertIsNotNone(seen[0].get('pid_started'), 'the ticket must carry a start time')
        self.assertEqual(self.m.pid_started(os.getpid()), seen[0].get('pid_started'))

    def test_run_keeps_exit_code_when_release_cannot_lock(self):
        self.m.claim = lambda a, pid: (dict(id='L1', what='w'), None)
        self.m.renew = lambda *a: {}
        def no_lock(*a):
            raise RuntimeError('could not get lock')
        self.m.release = no_lock
        with mock.patch('sys.stdout', new_callable=__import__('io').StringIO) as output:
            code = self.m.run(self.args(), [sys.executable, '-c', 'raise SystemExit(5)'])
        self.assertEqual(5, code)
        self.assertIn('NOT closed', output.getvalue())

    @unittest.skipUnless(os.name == 'nt', 'Windows process enumeration')
    def test_lock_wait_outlasts_two_telemetry_samples(self):
        # A claim holds the ledger lock while it samples both telemetry commands; two claimants in a row must
        # not be able to time out a third client that is waiting for the lock.
        timeouts = []
        def fake_run(cmd, **kw):
            timeouts.append(kw.get('timeout'))
            return subprocess.CompletedProcess(cmd, 1, b'')
        fresh = module(self.root)
        with mock.patch.object(fresh.subprocess, 'run', side_effect=fake_run):
            fresh.processes()
            fresh.gpu_free_gb()
        self.assertEqual(2, len(timeouts), timeouts)
        self.assertTrue(all(isinstance(t, (int, float)) and t > 0 for t in timeouts), timeouts)
        self.assertGreater(fresh.LOCK_WAIT_S, 2 * sum(timeouts))

    def test_bad_gpu_output_is_unavailable(self):
        cases = [(1, b'0, 24576'), (0, b'nan, 24576'), (0, b'not a number'),
                 (0, b'25000, 24576'), (0, b'0, 0')]
        for rc, data in cases:
            with self.subTest(rc=rc, data=data):
                fresh = module(self.root)
                with mock.patch.object(fresh.subprocess, 'run', return_value=subprocess.CompletedProcess([], rc, data)):
                    self.assertEqual(fresh.gpu_free_gb(), (None, None))

    def test_valid_gpu_output_parses(self):
        fresh = module(self.root)
        with mock.patch.object(fresh.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'1024, 24576')):
            self.assertEqual(fresh.gpu_free_gb(), (23.0, 1.0))

    @unittest.skipUnless(os.name == 'nt', 'Windows process enumeration')
    def test_process_scan_rejects_partial_output(self):
        fresh = module(self.root)
        good = ('%d|1|python.exe|python\nEND\n' % os.getpid()).encode()
        for data, valid in ((good, True), (b'END\n', False), (good.replace(b'END', b'malformed\nEND'), False)):
            with self.subTest(data=data), mock.patch.object(
                    fresh.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, data)):
                result = fresh.processes()
                self.assertEqual(result is not None, valid)

    def test_status_retains_degraded_reporting(self):
        self.m.processes = lambda: None
        self.m.gpu_free_gb = lambda: (None, None)
        with mock.patch('sys.stdout', new_callable=__import__('io').StringIO) as output:
            self.assertEqual(self.m.status(False), 0)
        self.assertIn('process check failed', output.getvalue())
        self.assertIn('free ? GB', output.getvalue())


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--worker':
        worker(sys.argv[2], sys.argv[3])
    else:
        unittest.main(verbosity=2)
