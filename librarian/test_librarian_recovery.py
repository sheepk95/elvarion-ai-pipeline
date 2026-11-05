"""CPU-only lock and failed-sweep regressions; fixtures never use a live mailbox."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

TARGET = Path(os.environ.get('LIBRARIAN_RECOVERY_TARGET') or Path(__file__).with_name('librarian_inbox.py'))
spec = importlib.util.spec_from_file_location('li_recovery', TARGET)
li = importlib.util.module_from_spec(spec)
spec.loader.exec_module(li)
ask_spec = importlib.util.spec_from_file_location('ask_recovery', Path(__file__).with_name('ask_librarian.py'))
ask = importlib.util.module_from_spec(ask_spec)
ask_spec.loader.exec_module(ask)
ask.LI = li
RID = '20261105T010000000000Z-1234-0123abcd'


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='librarian-recovery-')
        self.addCleanup(self.temp.cleanup)
        self.mb = Path(self.temp.name)
        li.ensure(str(self.mb))

    def stale_request(self):
        (self.mb / 'requests' / (RID + '.json')).write_text(json.dumps({'brief': 'find a skill'}))
        path = self.mb / 'claimed' / (RID + '.claim')
        path.write_text('librarian old pid 1234\n')
        self.age(path)

    def age(self, path):
        old = time.time() - 120
        os.utime(path, (old, old))

    def late_fixture(self):
        (self.mb / 'late').mkdir(exist_ok=True)
        for suffix in ('.shown', '.json'):
            (self.mb / 'late' / 'seen' / (RID + suffix)).unlink(missing_ok=True)
        (self.mb / 'late' / (RID + '.json')).write_text(json.dumps(
            {'id': RID, 'from': 'test', 'reply_to': 'local_01234567-0123-0123-0123-0123456789ab', 'utc': 'test'}))
        (self.mb / 'done' / (RID + '.md')).write_text(
            'PICKS: unique-answer\n' + 'x' * 200000 + '\n' + li.END_MARKER, encoding='utf-8')

    def late_command(self, next_ask=False):
        cmd = [sys.executable, '-I', '-B', str(Path(__file__).with_name('ask_librarian.py')),
               '--mailbox', str(self.mb), '--no-finder']
        return cmd + (['a task'] if next_ask else ['--late', RID, '--late-wait', '0'])

    def test_failed_output_retains_late_answer_for_both_paths(self):
        for next_ask in (False, True):
            with self.subTest(next_ask=next_ask):
                self.late_fixture()
                env = dict(os.environ, CLAUDE_CODE_HOST_SESSION_ID='local_01234567-0123-0123-0123-0123456789ab')
                proc = subprocess.Popen(self.late_command(next_ask), stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=env)
                proc.stdout.close()
                self.assertNotEqual(0, proc.wait(timeout=15))
                self.assertFalse((self.mb / 'late' / 'seen' / (RID + '.shown')).exists())
                retry = subprocess.run(self.late_command(), capture_output=True, text=True, timeout=15, env=env)
                self.assertEqual(0, retry.returncode)
                self.assertIn('PICKS: unique-answer', retry.stdout)
                (self.mb / 'late' / 'seen' / (RID + '.shown')).unlink()
                (self.mb / 'late' / 'seen' / (RID + '.json')).unlink()

    def test_competing_late_processes_deliver_once(self):
        self.late_fixture()
        env = dict(os.environ, CLAUDE_CODE_HOST_SESSION_ID='local_01234567-0123-0123-0123-0123456789ab')
        files = [tempfile.TemporaryFile() for _ in range(2)]
        self.addCleanup(lambda: [f.close() for f in files])
        procs = [subprocess.Popen(self.late_command(next_ask), stdout=files[i],
                                  stderr=subprocess.PIPE, env=env) for i, next_ask in enumerate((False, True))]
        errors = [proc.communicate(timeout=15)[1] for proc in procs]
        for f in files:
            f.seek(0)
        outputs = [f.read() for f in files]
        self.assertEqual([0, 3], [p.returncode for p in procs], errors)
        self.assertEqual(1, sum(b'PICKS: unique-answer' in out for out in outputs))

    def test_read_apis_do_not_acknowledge_preview(self):
        self.late_fixture()
        self.assertIn('unique-answer', ask.wait_late(str(self.mb), RID, 0)[1])
        self.assertIn('unique-answer', ask.unread_late(str(self.mb), 'local_01234567-0123-0123-0123-0123456789ab')[0])
        with patch.object(ask, 'host_session', return_value='local_01234567-0123-0123-0123-0123456789ab'):
            self.assertIn('unique-answer', ask.ask(str(self.mb), 'a task')[1])
        self.assertFalse((self.mb / 'late' / 'seen' / (RID + '.shown')).exists())

    def test_next_ask_delivers_and_acknowledges(self):
        self.late_fixture()
        env = dict(os.environ, CLAUDE_CODE_HOST_SESSION_ID='local_01234567-0123-0123-0123-0123456789ab')
        first = subprocess.run(self.late_command(True), capture_output=True, env=env, timeout=15)
        second = subprocess.run(self.late_command(True), capture_output=True, env=env, timeout=15)
        self.assertEqual((3, 3), (first.returncode, second.returncode))
        self.assertIn(b'PICKS: unique-answer', first.stdout)
        self.assertNotIn(b'PICKS: unique-answer', second.stdout)
        self.assertTrue((self.mb / 'late' / 'seen' / (RID + '.shown')).exists())

    def test_waiting_for_other_answer_does_not_block_ready_answer(self):
        self.late_fixture()
        other = '20261105T010000000001Z-1234-0123abcd'
        (self.mb / 'late' / (other + '.json')).write_text(json.dumps({'id': other}))
        waiter = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).with_name('ask_librarian.py')),
                                   '--mailbox', str(self.mb), '--late', other, '--late-wait', '4'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: waiter.kill() if waiter.poll() is None else None)
        time.sleep(0.5)
        self.assertIsNone(waiter.poll())
        ready = subprocess.run(self.late_command(), capture_output=True, timeout=2)
        self.assertEqual(0, ready.returncode)
        self.assertIn(b'PICKS: unique-answer', ready.stdout)
        self.assertIsNone(waiter.poll())
        waiter.terminate()
        waiter.communicate(timeout=5)

    def test_blocked_reader_does_not_block_other_ready_answer(self):
        self.late_fixture()
        other = '20261105T010000000001Z-1234-0123abcd'
        (self.mb / 'late' / (other + '.json')).write_text(json.dumps({'id': other}))
        (self.mb / 'done' / (other + '.md')).write_text('OTHER ANSWER\n' + li.END_MARKER)
        blocked = subprocess.Popen(self.late_command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: blocked.kill() if blocked.poll() is None else None)
        time.sleep(0.5)
        self.assertIsNone(blocked.poll())
        cmd = [sys.executable, '-I', '-B', str(Path(__file__).with_name('ask_librarian.py')),
               '--mailbox', str(self.mb), '--late', other, '--late-wait', '0']
        ready = subprocess.run(cmd, capture_output=True, timeout=3)
        self.assertEqual(0, ready.returncode, ready.stderr)
        self.assertIn(b'OTHER ANSWER', ready.stdout)
        env = dict(os.environ, CLAUDE_CODE_HOST_SESSION_ID='local_01234567-0123-0123-0123-0123456789ab')
        ordinary = subprocess.run(self.late_command(True), capture_output=True, timeout=3, env=env)
        self.assertEqual(3, ordinary.returncode, ordinary.stderr)
        self.assertIn(b'LIBRARIAN_UNAVAILABLE', ordinary.stdout)
        blocked.kill()
        blocked.communicate(timeout=5)

    def test_ack_error_is_not_reported_as_success(self):
        self.late_fixture()
        original_open = ask.os.open
        def fail_marker(path, *args, **kwargs):
            if str(path).endswith('.shown'):
                raise PermissionError('marker denied')
            return original_open(path, *args, **kwargs)
        with patch.object(ask.os, 'open', side_effect=fail_marker), patch.object(ask.sys, 'stdout'):
            with self.assertRaises(PermissionError):
                ask.wait_late(str(self.mb), RID, 0, deliver=True)
        self.assertTrue((self.mb / 'late' / (RID + '.json')).exists())

    def test_marker_write_failure_removes_partial_marker(self):
        self.late_fixture()
        with patch.object(ask.os, 'write', side_effect=OSError('disk full')), patch.object(ask.sys, 'stdout'):
            with self.assertRaises(OSError):
                ask.wait_late(str(self.mb), RID, 0, deliver=True)
        self.assertFalse((self.mb / 'late' / 'seen' / (RID + '.shown')).exists())
        retry = subprocess.run(self.late_command(), capture_output=True, timeout=10)
        self.assertEqual(0, retry.returncode)
        self.assertIn(b'PICKS: unique-answer', retry.stdout)

    def test_marker_close_failure_removes_partial_marker(self):
        self.late_fixture()
        real_close = ask.os.close
        def fail_close(fd):
            real_close(fd)
            raise OSError('close failed')
        with patch.object(ask.os, 'close', side_effect=fail_close), patch.object(ask.sys, 'stdout'):
            with self.assertRaisesRegex(OSError, 'close failed'):
                ask.wait_late(str(self.mb), RID, 0, deliver=True)
        self.assertFalse((self.mb / 'late' / 'seen' / (RID + '.shown')).exists())

    def test_marker_cleanup_failure_is_explicit(self):
        self.late_fixture()
        with patch.object(ask.os, 'write', side_effect=OSError('disk full')), \
             patch.object(ask.os, 'unlink', side_effect=PermissionError('cleanup denied')), \
             patch.object(ask.sys, 'stdout'):
            with self.assertRaisesRegex(RuntimeError, 'could not remove incomplete marker'):
                ask.wait_late(str(self.mb), RID, 0, deliver=True)

    def test_on_time_stage_is_locked_before_publish(self):
        self.late_fixture()
        (self.mb / 'late' / (RID + '.json')).unlink()
        real_mark = ask.mark_late
        attempted = []
        def interleaved(*args, **kwargs):
            real_mark(*args, **kwargs)
            attempted.append(ask.wait_late(str(self.mb), RID, 0, deliver=True))
        import io
        output = io.StringIO()
        with patch.object(ask, '_ask', return_value=(0, 'ON TIME ANSWER', {'id': RID})), \
             patch.object(ask, 'mark_late', side_effect=interleaved), \
             patch.object(ask.sys, 'stdout', output):
            code = ask.main(['--mailbox', str(self.mb), '--no-finder', 'test'])
        self.assertEqual(0, code)
        self.assertEqual(3, attempted[0][0])
        self.assertIn('ON TIME ANSWER', output.getvalue())
        self.assertNotIn('PICKS: unique-answer', output.getvalue())

    def test_on_time_answer_survives_broken_stdout(self):
        li.write_json_atomic(str(self.mb / 'heartbeat.json'), {'loaded': True, 'epoch': time.time()})
        cmd = self.late_command(True) + ['--timeout', '10']
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
        deadline = time.time() + 5
        requests = []
        while time.time() < deadline and not requests and proc.poll() is None:
            requests = list((self.mb / 'requests').glob('*.json'))
            time.sleep(0.02)
        self.assertEqual(1, len(requests))
        rid = requests[0].stem
        proc.stdout.close()
        (self.mb / 'answers' / (rid + '.md')).write_text('ON TIME ANSWER\n' + 'x' * 200000 + '\n' + li.END_MARKER)
        self.assertNotEqual(0, proc.wait(timeout=15))
        retry = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).with_name('ask_librarian.py')),
                                '--mailbox', str(self.mb), '--late', rid, '--late-wait', '0'],
                               capture_output=True, timeout=10)
        self.assertEqual(0, retry.returncode, retry.stdout)
        self.assertIn(b'ON TIME ANSWER', retry.stdout)

    def test_failed_sweep_retries_after_backoff(self):
        self.stale_request()
        with patch.object(li, 'move_retry', return_value=False):
            self.assertEqual([], li.claim_all(str(self.mb)))
        self.assertEqual([], li.pending(str(self.mb)))
        self.assertTrue((self.mb / 'requests' / (RID + '.json')).exists())
        self.age(self.mb / 'claimed' / (RID + '.sweep'))
        self.assertEqual([RID], li.pending(str(self.mb)))
        self.assertEqual([RID], [d['id'] for d in li.claim_all(str(self.mb))])
        self.assertEqual([], li.claim_all(str(self.mb)))
        self.assertEqual([RID], [d['id'] for d in li.unanswered_claimed(str(self.mb))])

    def holder(self, lock_path):
        code = '''import importlib.util, pathlib, sys, time
spec = importlib.util.spec_from_file_location('li', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
lock = m.OsLock(sys.argv[2]); assert lock.acquire()
pathlib.Path(sys.argv[3]).touch()
end = time.monotonic() + 15
try:
    while not pathlib.Path(sys.argv[4]).exists():
        if time.monotonic() > end: raise RuntimeError('fixture not released')
        time.sleep(.01)
finally: lock.release()
'''
        ready, release = self.mb / 'ready', self.mb / 'release'
        child = subprocess.Popen([sys.executable, '-I', '-B', '-c', code, str(TARGET), str(lock_path),
                                  str(ready), str(release)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def finish():
            release.touch()
            out, err = child.communicate(timeout=20)
            self.assertEqual(0, child.returncode, (out, err))
        self.addCleanup(finish)
        end = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < end:
            time.sleep(.01)
        self.assertTrue(ready.exists(), 'holder did not acquire lock')
        return child, release

    def test_heartbeat_refuses_contended_write_then_retry_preserves_counts(self):
        li.write_heartbeat(str(self.mb), loaded=True, add_answered=1)
        before = (self.mb / 'heartbeat.json').read_bytes()
        child, release = self.holder(self.mb / 'heartbeat.lock')
        acquire = li.OsLock.acquire
        # Shorten only the wait; use a real competing process and the actual OS lock.
        with patch.object(li.OsLock, 'acquire', lambda lock, **kw: acquire(lock, timeout=.1)):
            with self.assertRaises(TimeoutError):
                li.write_heartbeat(str(self.mb), loaded=False, add_answered=1)
        self.assertEqual(before, (self.mb / 'heartbeat.json').read_bytes())
        release.touch(); child.wait(timeout=10)
        li.write_heartbeat(str(self.mb), loaded=False, add_answered=1)
        hb = json.loads((self.mb / 'heartbeat.json').read_text())
        self.assertEqual(2, hb['requests_answered'])
        self.assertFalse(hb['loaded'])

    def test_competing_request_claim_obeys_os_lock(self):
        self.stale_request()
        child, release = self.holder(self.mb / 'claimed' / (RID + '.lock'))
        self.assertEqual([], li.claim_all(str(self.mb)))
        self.assertTrue((self.mb / 'requests' / (RID + '.json')).exists())
        release.touch(); child.wait(timeout=10)
        self.assertEqual([RID], [d['id'] for d in li.claim_all(str(self.mb))])
        self.assertEqual([], li.claim_all(str(self.mb)))

    def test_failed_legacy_abandon_keeps_marker_for_timeout_recovery(self):
        request = self.mb / 'requests' / (RID + '.json')
        request.write_text(json.dumps({'brief': 'legacy abandoned request'}))
        move = li.move_retry
        def fail_request_move(src, dst, *args, **kwargs):
            return False if Path(src) == request else move(src, dst, *args, **kwargs)
        with patch.object(li, 'move_retry', side_effect=fail_request_move):
            ask.abandon(str(self.mb), RID)
        claim = self.mb / 'claimed' / (RID + '.claim')
        self.assertTrue(request.exists())
        self.assertTrue(claim.exists(), 'failed move discarded the abandonment marker')
        self.assertTrue(claim.read_text().startswith('abandoned-by-requester'))
        self.assertEqual([], li.claim_all(str(self.mb)))
        self.age(claim)
        self.assertEqual([], li.claim_all(str(self.mb)))
        self.assertFalse(request.exists())
        self.assertTrue((self.mb / 'done' / (RID + '.timeout.json')).exists())
        self.assertTrue((self.mb / 'done' / (RID + '.timeout.claim')).exists())
        self.assertEqual([], li.unanswered_claimed(str(self.mb)))

    def test_legacy_abandon_obeys_request_lock(self):
        request = self.mb / 'requests' / (RID + '.json')
        request.write_text(json.dumps({'brief': 'legacy abandoned request'}))
        child, release = self.holder(self.mb / 'claimed' / (RID + '.lock'))
        ask.abandon(str(self.mb), RID)
        self.assertTrue(request.exists(), 'abandon bypassed the competing request lock')
        self.assertFalse((self.mb / 'claimed' / (RID + '.claim')).exists())
        release.touch(); child.wait(timeout=10)
        ask.abandon(str(self.mb), RID)
        self.assertFalse(request.exists())
        self.assertTrue((self.mb / 'done' / (RID + '.timeout.json')).exists())


if __name__ == '__main__':
    unittest.main()
