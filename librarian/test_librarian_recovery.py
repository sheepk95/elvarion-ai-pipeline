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


if __name__ == '__main__':
    unittest.main()
