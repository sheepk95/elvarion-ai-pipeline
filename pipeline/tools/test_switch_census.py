"""switch_census.py must report, not crash, when the desktop app's session folder is missing, empty or damaged.

Run: python -I -B pipeline/tools/test_switch_census.py   (Windows; the census itself is Windows-only)
"""
import os, pathlib, shutil, subprocess, sys, tempfile, unittest
import importlib.util, json, time

SCRIPT = pathlib.Path(os.environ.get('CENSUS_TARGET', pathlib.Path(__file__).with_name('switch_census.py'))).resolve()


@unittest.skipUnless(os.name == 'nt', 'switch_census.py is Windows-only')
class Census(unittest.TestCase):
    def setUp(self):
        self.t = pathlib.Path(tempfile.mkdtemp(prefix='census-'))
        self.root = self.t / 'pipe'
        (self.root / 'tools').mkdir(parents=True)
        (self.root / 'coordinator' / 'inbox').mkdir(parents=True)
        shutil.copy(SCRIPT, self.root / 'tools' / 'switch_census.py')
        shutil.copy(pathlib.Path(__file__).with_name('waiter_identity.py'), self.root / 'tools' / 'waiter_identity.py')
        self.pair = self.t / 'la' / 'Claude-Data' / 'claude_x' / 'claude-code-sessions' / 'acct' / 'org'
        self.pair.mkdir(parents=True)
        self.amap = self.t / 'default-pairs.json'
        self.amap.write_text(json.dumps({'test@example.invalid': 'acct/org'}), encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def run_census(self, localappdata, *args, mapped=True):
        env = dict(os.environ)
        env.pop('LOCALAPPDATA', None)
        env['CLAUDE_CODE_USER_EMAIL'] = 'test@example.invalid'
        if mapped and '--account-pairs' not in args:
            args = (*args, '--account-pairs', str(self.amap))
        if localappdata is not None:
            env['LOCALAPPDATA'] = str(localappdata)
        return subprocess.run([sys.executable, '-I', '-B', str(self.root / 'tools' / 'switch_census.py'), *args],
                              capture_output=True, text=True, env=env, timeout=60)

    def good_chat(self):
        (self.pair / 'local_good.json').write_text(
            '{"title": "Coordinator", "cwd": "%s"}' % str(self.root).replace('\\', '\\\\'), encoding='utf-8')

    def assert_good_chat_listed(self, p):
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        self.assertNotIn('Traceback', p.stderr)
        self.assertRegex(p.stdout, r'Coordinator\s+local_good\s')

    def test_structurally_damaged_session_files_are_skipped_and_named(self):
        self.good_chat()
        bad = {'local_null': 'null', 'local_list': '[]', 'local_num': '7',
               'local_title_list': '{"title": ["x"], "cwd": "%s"}' % str(self.root).replace('\\', '\\\\'),
               'local_cwd_num': '{"title": "Other", "cwd": 5}'}
        for name, text in bad.items():
            (self.pair / (name + '.json')).write_text(text, encoding='utf-8')
        p = self.run_census(self.t / 'la')
        self.assertEqual(5, p.returncode, p.stdout + p.stderr)
        self.assertNotIn("WAKE ", p.stdout)
        for name in bad:
            self.assertRegex(p.stdout, r'skipped unreadable session file .*%s\.json' % name)

    def test_damaged_archive_index_warns_and_lists_chats(self):
        self.good_chat()
        for text in ('{', '[]', '{"other": 1}', '{"archived": 5}', '{"archived": [{"a": 1}]}', 'null'):
            with self.subTest(text=text):
                (self.pair / 'archived-sessions.idx').write_text(text, encoding='utf-8')
                p = self.run_census(self.t / 'la')
                self.assertEqual(5, p.returncode, p.stdout + p.stderr)
                self.assertNotIn("WAKE ", p.stdout)
                self.assertIn('archived-sessions.idx unreadable', p.stdout)
        (self.pair / 'archived-sessions.idx').write_text('{"archived": ["local_good"]}', encoding='utf-8')
        p = self.run_census(self.t / 'la')        # control: a good index still hides an archived chat
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertNotIn('local_good', p.stdout)

    def test_explicit_account_map_fails_closed_and_valid_map_selects(self):
        self.good_chat()
        amap = self.t / 'pairs.json'
        for text in ('{', '[]', '{}', '{"other": "acct/org"}'):
            amap.write_text(text, encoding='utf-8')
            p = self.run_census(self.t / 'la', '--account-pairs', str(amap))
            self.assertEqual(5, p.returncode, p.stdout + p.stderr)
            self.assertNotIn('local_good', p.stdout)
        env = dict(os.environ, LOCALAPPDATA=str(self.t / 'la'), CLAUDE_CODE_USER_EMAIL='test@example.invalid')
        amap.write_text(json.dumps({'test@example.invalid': 'acct/org'}), encoding='utf-8')
        p = subprocess.run([sys.executable, '-I', '-B', str(self.root / 'tools' / 'switch_census.py'), '--account-pairs', str(amap)], capture_output=True, text=True, env=env)
        self.assert_good_chat_listed(p)
        amap.write_text(json.dumps({'test@example.invalid': 'missing/org'}), encoding='utf-8')
        p = subprocess.run([sys.executable, '-I', '-B', str(self.root / 'tools' / 'switch_census.py'), '--account-pairs', str(amap)], capture_output=True, text=True, env=env)
        self.assertEqual(5, p.returncode, p.stdout + p.stderr)
        self.assertNotIn('local_good', p.stdout)

    def test_duplicate_titles_and_other_root_are_never_selected(self):
        self.good_chat()
        inbox = self.root / 'coordinator' / 'inbox'
        (inbox / '20260101T000000Z-builder-1.md').write_text('item')
        other = self.pair / 'local_other.json'
        other.write_text(json.dumps({'title': 'Coordinator', 'cwd': str(self.root) + '-other'}))
        p = self.run_census(self.t / 'la')
        self.assertEqual(4, p.returncode, p.stdout + p.stderr)
        self.assertIn('local_good', p.stdout)
        other.write_text(json.dumps({'title': 'Coordinator', 'cwd': str(self.root / 'child')}))
        p = self.run_census(self.t / 'la')
        self.assertEqual(5, p.returncode, p.stdout + p.stderr)
        self.assertIn('AMBIGUOUS CHAT', p.stdout)
        self.assertNotIn('WAKE ', p.stdout)

    def test_platform_check_comes_before_ctypes_import(self):
        # Off Windows the friendly message must show even if ctypes.wintypes cannot load: run the census with
        # os.name faked to posix and every ctypes import failing.
        runner = self.t / 'posix_runner.py'
        runner.write_text(
            "import argparse, builtins, glob, json, os, re, runpy, shutil, sys, time  # load before os.name is faked\n"
            "real = builtins.__import__\n"
            "def imp(name, *a, **kw):\n"
            "    if name == 'ctypes' or name.startswith('ctypes.'):\n"
            "        raise ImportError('no ctypes here')\n"
            "    return real(name, *a, **kw)\n"
            "builtins.__import__ = imp\n"
            "os.name = 'posix'\n"
            "script = sys.argv[1]\n"
            "sys.argv = [script]\n"
            "runpy.run_path(script, run_name='__main__')\n", encoding='utf-8')
        p = subprocess.run([sys.executable, '-I', '-B', str(runner), str(self.root / 'tools' / 'switch_census.py')],
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(0, p.returncode)
        self.assertIn('Windows and the Claude desktop app only', p.stderr)
        self.assertNotIn('Traceback', p.stderr)

    def test_no_localappdata(self):
        p = self.run_census(None)
        self.assertEqual(5, p.returncode, p.stderr)
        self.assertIn('no single session root', p.stdout)

    def test_unmatched_unread_is_nonzero(self):
        inbox = self.root / 'coordinator' / 'inbox'
        (inbox / '20260101T000000Z-builder-1.md').write_text('item')
        p = self.run_census(None)
        self.assertEqual(5, p.returncode, p.stdout + p.stderr)
        self.assertIn('NO CHAT', p.stdout)
        self.good_chat()
        p = self.run_census(self.t / 'la')
        self.assertEqual(4, p.returncode, p.stdout + p.stderr)
        self.assertIn('WAKE', p.stdout)

    def test_waiter_identity_and_reused_pid(self):
        inbox = self.root / 'coordinator' / 'inbox'
        self.good_chat()
        waiter = subprocess.Popen([sys.executable, '-I', '-B', str(pathlib.Path(__file__).with_name('wait_inbox.py')),
                                   str(inbox), '--timeout', '30'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not (inbox / '.waiter.identity').exists() and time.monotonic() < deadline:
                time.sleep(.05)
            identity = json.loads((inbox / '.waiter.identity').read_text())
            p = self.run_census(self.t / 'la')
            self.assertRegex(p.stdout, r'waiter ARMED')
        finally:
            waiter.terminate()
            waiter.communicate(timeout=10)
        # Keep the process alive while census reads the queued item; a real waiter
        # would consume it on its next poll, making this test timing-dependent.
        sleeper = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'])
        try:
            spec = importlib.util.spec_from_file_location('wi_test', pathlib.Path(__file__).with_name('waiter_identity.py'))
            wi = importlib.util.module_from_spec(spec); spec.loader.exec_module(wi)
            state, born = wi.creation(sleeper.pid)
            self.assertEqual('LIVE', state)
            (inbox / '.waiter.pid').write_text(str(sleeper.pid))
            identity = {'pid': sleeper.pid, 'creation': born}
            # Same live Python PID but an earlier process creation: a stale registration.
            identity['creation'] -= 1
            (inbox / '.waiter.identity').write_text(json.dumps(identity))
            (inbox / '20260101T000000Z-builder-1.md').write_text('item')
            p = self.run_census(self.t / 'la')
            self.assertEqual(4, p.returncode, p.stdout + p.stderr)
            self.assertRegex(p.stdout, r'waiter DEAD')
            self.assertIn('WAKE', p.stdout)
            (inbox / '.waiter.identity').unlink()
            p = self.run_census(self.t / 'la')
            self.assertEqual(4, p.returncode, p.stdout + p.stderr)
            self.assertRegex(p.stdout, r'waiter UNKNOWN')
        finally:
            sleeper.terminate()
            sleeper.wait(timeout=10)

    def test_competing_waiter_rejected_and_owner_cleans_up(self):
        inbox = self.root / 'coordinator' / 'inbox'
        cmd = [sys.executable, '-I', '-B', str(pathlib.Path(__file__).with_name('wait_inbox.py')), str(inbox)]
        for first_timeout, second_timeout in ((30, 1), (3, 30)):
            first = subprocess.Popen(cmd + ['--timeout', str(first_timeout)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                while not (inbox / '.waiter.identity').exists() and time.monotonic() < deadline: time.sleep(.02)
                self.assertTrue((inbox / '.waiter.identity').exists())
                second = subprocess.run(cmd + ['--timeout', str(second_timeout)], capture_output=True, timeout=10)
                self.assertNotEqual(0, second.returncode)
                self.assertIn(b'existing waiter', second.stderr)
                self.assertEqual(str(first.pid), (inbox / '.waiter.pid').read_text())
                if first_timeout == 3:
                    first.communicate(timeout=10)
                    self.assertFalse((inbox / '.waiter.pid').exists())
                    successor = subprocess.run(cmd + ['--timeout', '0'], capture_output=True, timeout=10)
                    self.assertEqual(2, successor.returncode)
            finally:
                if first.poll() is None: first.terminate(); first.communicate(timeout=10)
                # Windows terminate skips cleanup; remove only this owned fixture's files.
                for name in ('.waiter.pid', '.waiter.identity'):
                    (inbox / name).unlink(missing_ok=True)

    def test_unknown_live_registration_is_not_replaced(self):
        inbox = self.root / 'coordinator' / 'inbox'
        sleeper = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'])
        try:
            (inbox / '.waiter.pid').write_text(str(sleeper.pid))
            cmd = [sys.executable, '-I', '-B', str(pathlib.Path(__file__).with_name('wait_inbox.py')), str(inbox), '--timeout', '0']
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            self.assertNotEqual(0, result.returncode)
            self.assertIn(b'identity unknown', result.stderr)
            self.assertEqual(str(sleeper.pid), (inbox / '.waiter.pid').read_text())
        finally:
            sleeper.terminate(); sleeper.wait(timeout=10)

    def test_unknown_creation_registers_distinct_generations(self):
        spec = importlib.util.spec_from_file_location('wi_generation', pathlib.Path(__file__).with_name('waiter_identity.py'))
        wi = importlib.util.module_from_spec(spec); spec.loader.exec_module(wi)
        wi.creation = lambda pid: ('UNKNOWN', None)
        inbox = str(self.root / 'coordinator' / 'inbox')
        first, second = wi.register(inbox), wi.register(inbox)
        self.assertIsNone(first['creation'])
        self.assertNotEqual(first['generation'], second['generation'])
        self.assertEqual(second, json.loads((pathlib.Path(inbox) / '.waiter.identity').read_text()))

    def test_multiple_account_pairs_require_mapping_even_without_unread(self):
        self.good_chat()
        other = self.pair.parent.parent / 'other' / 'org'
        other.mkdir(parents=True)
        (other / 'local_other.json').write_text(json.dumps({'title': 'Coordinator', 'cwd': str(self.root)}))
        p = self.run_census(self.t / 'la', mapped=False)
        self.assertEqual(5, p.returncode, p.stdout + p.stderr)
        self.assertNotIn('WAKE ', p.stdout)
        self.assertIn('account mapping unresolved', p.stdout)

    def test_unmapped_sole_old_account_never_wakes(self):
        self.good_chat()
        inbox = self.root / 'coordinator' / 'inbox'
        (inbox / '20260101T000000Z-builder-1.md').write_text('item')
        env = dict(os.environ, LOCALAPPDATA=str(self.t / 'la'), CLAUDE_CODE_USER_EMAIL='new-account@example.invalid')
        p = subprocess.run([sys.executable, '-I', '-B', str(self.root / 'tools' / 'switch_census.py')], capture_output=True, text=True, env=env)
        self.assertEqual(5, p.returncode, p.stdout + p.stderr)
        self.assertNotIn('WAKE ', p.stdout)
        self.assertNotIn('local_good', p.stdout)
        # The correct explicit account mapping continues to route the item.
        p = self.run_census(self.t / 'la')
        self.assertEqual(4, p.returncode, p.stdout + p.stderr)
        self.assertIn('WAKE local_good ', p.stdout)

    def test_shared_fallback_session_is_not_routed_even_if_one_inbox_empty(self):
        lane = self.root / 'lanes' / 'archer'
        (lane / 'inbox' / 'Builder').mkdir(parents=True)
        (lane / 'inbox' / 'Reviewer').mkdir()
        (lane / 'LANE.md').write_text('# LANE: Archer (test)\n')
        item = '20260101T000000Z-builder-1.md'
        (lane / 'inbox' / 'Builder' / item).write_text('item')
        (self.pair / 'local_archer.json').write_text(json.dumps({'title': 'Archer', 'cwd': str(self.root)}))
        p = self.run_census(self.t / 'la')
        self.assertEqual(5, p.returncode, p.stdout + p.stderr)
        self.assertIn('AMBIGUOUS INBOX', p.stdout)
        self.assertNotIn('WAKE local_archer ', p.stdout)
        # An exact title assigns the other inbox to a different session, so both can route.
        (self.pair / 'local_reviewer.json').write_text(json.dumps({'title': 'Archer Reviewer', 'cwd': str(self.root)}))
        (lane / 'inbox' / 'Reviewer' / item).write_text('item')
        p = self.run_census(self.t / 'la')
        self.assertEqual(4, p.returncode, p.stdout + p.stderr)
        self.assertIn('WAKE local_archer ', p.stdout)
        self.assertIn('WAKE local_reviewer ', p.stdout)

    def test_registration_waits_for_os_lock(self):
        spec = importlib.util.spec_from_file_location('wi_reg_lock', pathlib.Path(__file__).with_name('waiter_identity.py'))
        wi = importlib.util.module_from_spec(spec); spec.loader.exec_module(wi)
        inbox = self.root / 'coordinator' / 'inbox'
        cmd = [sys.executable, '-I', '-B', str(pathlib.Path(__file__).with_name('wait_inbox.py')), str(inbox), '--timeout', '0']
        proc = None
        try:
            with wi.registration_lock(str(inbox)):
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(.5)
                self.assertFalse((inbox / '.waiter.pid').exists())
                self.assertIsNone(proc.poll())
            proc.communicate(timeout=10)
            self.assertEqual(2, proc.returncode)
        finally:
            if proc is not None and proc.poll() is None: proc.terminate(); proc.communicate(timeout=10)

    def test_cleanup_waits_for_os_lock(self):
        spec = importlib.util.spec_from_file_location('wi_cleanup_lock', pathlib.Path(__file__).with_name('waiter_identity.py'))
        wi = importlib.util.module_from_spec(spec); spec.loader.exec_module(wi)
        inbox = self.root / 'coordinator' / 'inbox'
        cmd = [sys.executable, '-I', '-B', str(pathlib.Path(__file__).with_name('wait_inbox.py')), str(inbox), '--timeout', '1']
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not (inbox / '.waiter.identity').exists() and time.monotonic() < deadline: time.sleep(.02)
            self.assertTrue((inbox / '.waiter.identity').exists())
            with wi.registration_lock(str(inbox)):
                time.sleep(2.5)
                self.assertIsNone(proc.poll(), 'cleanup bypassed OS lock')
                self.assertEqual(str(proc.pid), (inbox / '.waiter.pid').read_text())
            proc.communicate(timeout=10)
            self.assertEqual(2, proc.returncode)
            self.assertFalse((inbox / '.waiter.pid').exists())
        finally:
            if proc.poll() is None: proc.terminate(); proc.communicate(timeout=10)

    def test_armed_waiter_without_chat_is_unresolved(self):
        inbox = self.root / 'coordinator' / 'inbox'
        sleeper = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'])
        try:
            spec = importlib.util.spec_from_file_location('wi_test', pathlib.Path(__file__).with_name('waiter_identity.py'))
            wi = importlib.util.module_from_spec(spec); spec.loader.exec_module(wi)
            state, born = wi.creation(sleeper.pid)
            self.assertEqual('LIVE', state)
            (inbox / '.waiter.pid').write_text(str(sleeper.pid))
            (inbox / '.waiter.identity').write_text(json.dumps({'pid': sleeper.pid, 'creation': born}))
            (inbox / '20260101T000000Z-builder-1.md').write_text('item')
            p = self.run_census(None)
            self.assertEqual(5, p.returncode, p.stdout + p.stderr)
            self.assertIn('NO CHAT', p.stdout)
            self.assertRegex(p.stdout, r'waiter ARMED\s+unread 1')
        finally:
            sleeper.terminate()
            sleeper.wait(timeout=10)

    def test_session_root_without_chats(self):
        p = self.run_census(self.t / 'la')
        self.assertEqual(5, p.returncode, p.stderr)
        self.assertIn('no session pair holds any chat', p.stdout)

    def test_damaged_session_file_is_skipped_and_named(self):
        (self.pair / 'local_bad.json').write_text('{not json', encoding='utf-8')
        (self.pair / 'local_good.json').write_text(
            '{"title": "Coordinator", "cwd": "%s"}' % str(self.root).replace('\\', '\\\\'), encoding='utf-8')
        p = self.run_census(self.t / 'la')
        self.assertEqual(5, p.returncode, p.stderr)
        self.assertIn('skipped unreadable session file', p.stdout)
        self.assertIn('local_bad.json', p.stdout)
        self.assertNotIn('local_good', p.stdout)  # corrupt metadata suppresses all routing


if __name__ == '__main__':
    unittest.main(verbosity=2)
