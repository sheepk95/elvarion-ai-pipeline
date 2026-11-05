"""CPU-only Windows job containment tests; no GPU or ledger access."""
import ctypes
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TARGET = Path(os.environ.get('LEASE_TIMEOUT_MODULE') or Path(__file__).with_name('lease_timeout.py'))
spec = importlib.util.spec_from_file_location('lease_timeout_target', TARGET)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Tests(unittest.TestCase):
    def test_timeout_kills_descendant_before_return(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / 'child-started'
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(60)"
            # The child writes a marker, then writes another after the wrapper returns if it survives.
            child = "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); p.write_text('started'); time.sleep(3); p.write_text('survived')"
            r = subprocess.run([sys.executable, '-B', str(TARGET), '2', sys.executable, '-c', parent, child, str(marker)], capture_output=True, timeout=15)
            self.assertEqual(124, r.returncode, r.stderr.decode(errors='replace'))
            self.assertEqual('started', marker.read_text())
            time.sleep(2)
            self.assertEqual('started', marker.read_text(), 'descendant survived timeout')

    def test_normal_exit_and_invalid_time(self):
        r = subprocess.run([sys.executable, '-B', str(TARGET), '5', sys.executable, '-c', 'raise SystemExit(7)'], capture_output=True, timeout=15)
        self.assertEqual(7, r.returncode, r.stderr.decode(errors='replace'))
        r = subprocess.run([sys.executable, '-B', str(TARGET), 'nan', sys.executable], capture_output=True, timeout=15)
        self.assertEqual(125, r.returncode)

    def test_assignment_failure_kills_suspended_command_without_resuming(self):
        job = mock.Mock()
        job.assign.side_effect = OSError('assignment denied')
        process = mock.Mock()
        process.poll.side_effect = [None, 1]
        with mock.patch.object(m, 'Job', return_value=job), mock.patch.object(m.subprocess, 'Popen', return_value=process) as popen:
            self.assertEqual(125, m.main(['lease_timeout', '5', 'job']))
        self.assertEqual(0x4, popen.call_args.kwargs['creationflags'])
        process.kill.assert_called_once()
        job.resume.assert_not_called()
        job.close.assert_called_once()

    def test_drain_retries_after_failed_termination_and_query(self):
        job = object.__new__(m.Job)
        job.handle = 1
        calls = []
        class Kernel:
            def TerminateJobObject(self, handle, code):
                calls.append('terminate')
                return len(calls) > 1
            def QueryInformationJobObject(self, handle, kind, ptr, size, returned):
                if calls.count('terminate') == 1:
                    return 0
                ctypes.cast(ptr, ctypes.POINTER(m.Accounting)).contents.active_processes = 0
                return 1
        job.k = Kernel()
        with mock.patch.object(m.time, 'sleep') as sleep:
            job.drain()
        self.assertEqual(2, calls.count('terminate'))
        sleep.assert_called_once_with(1)

if __name__ == '__main__':
    unittest.main()
