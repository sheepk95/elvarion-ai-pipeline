"""switch_census.py must report, not crash, when the desktop app's session folder is missing, empty or damaged.

Run: python -I -B pipeline/tools/test_switch_census.py   (Windows; the census itself is Windows-only)
"""
import os, pathlib, shutil, subprocess, sys, tempfile, unittest

SCRIPT = pathlib.Path(os.environ.get('CENSUS_TARGET', pathlib.Path(__file__).with_name('switch_census.py'))).resolve()


@unittest.skipUnless(os.name == 'nt', 'switch_census.py is Windows-only')
class Census(unittest.TestCase):
    def setUp(self):
        self.t = pathlib.Path(tempfile.mkdtemp(prefix='census-'))
        self.root = self.t / 'pipe'
        (self.root / 'tools').mkdir(parents=True)
        (self.root / 'coordinator' / 'inbox').mkdir(parents=True)
        shutil.copy(SCRIPT, self.root / 'tools' / 'switch_census.py')
        self.pair = self.t / 'la' / 'Claude-Data' / 'claude_x' / 'claude-code-sessions' / 'acct' / 'org'
        self.pair.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def run_census(self, localappdata, *args):
        env = dict(os.environ)
        env.pop('LOCALAPPDATA', None)
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
        self.assert_good_chat_listed(p)
        for name in bad:
            self.assertRegex(p.stdout, r'skipped unreadable session file .*%s\.json' % name)

    def test_damaged_archive_index_warns_and_lists_chats(self):
        self.good_chat()
        for text in ('{', '[]', '{"other": 1}', '{"archived": 5}', '{"archived": [{"a": 1}]}', 'null'):
            with self.subTest(text=text):
                (self.pair / 'archived-sessions.idx').write_text(text, encoding='utf-8')
                p = self.run_census(self.t / 'la')
                self.assert_good_chat_listed(p)
                self.assertIn('archived-sessions.idx unreadable', p.stdout)
        (self.pair / 'archived-sessions.idx').write_text('{"archived": ["local_good"]}', encoding='utf-8')
        p = self.run_census(self.t / 'la')        # control: a good index still hides an archived chat
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertNotIn('local_good', p.stdout)

    def test_damaged_account_pairs_file_warns_and_lists_chats(self):
        self.good_chat()
        amap = self.t / 'pairs.json'
        for text in ('{', '[]', '"acct"', '{"a@example.invalid": 5}'):
            with self.subTest(text=text):
                amap.write_text(text, encoding='utf-8')
                p = self.run_census(self.t / 'la', '--account-pairs', str(amap))
                self.assert_good_chat_listed(p)
                self.assertIn('--account-pairs %s unreadable' % amap, p.stdout)

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
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertIn('no single session root', p.stdout)

    def test_session_root_without_chats(self):
        p = self.run_census(self.t / 'la')
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertIn('no session pair holds any chat', p.stdout)

    def test_damaged_session_file_is_skipped_and_named(self):
        (self.pair / 'local_bad.json').write_text('{not json', encoding='utf-8')
        (self.pair / 'local_good.json').write_text(
            '{"title": "Coordinator", "cwd": "%s"}' % str(self.root).replace('\\', '\\\\'), encoding='utf-8')
        p = self.run_census(self.t / 'la')
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertIn('skipped unreadable session file', p.stdout)
        self.assertIn('local_bad.json', p.stdout)
        self.assertRegex(p.stdout, r'Coordinator\s+local_good\s')   # the good chat is still found


if __name__ == '__main__':
    unittest.main(verbosity=2)
