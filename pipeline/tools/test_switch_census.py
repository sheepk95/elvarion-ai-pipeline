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

    def run_census(self, localappdata):
        env = dict(os.environ)
        env.pop('LOCALAPPDATA', None)
        if localappdata is not None:
            env['LOCALAPPDATA'] = str(localappdata)
        return subprocess.run([sys.executable, '-I', '-B', str(self.root / 'tools' / 'switch_census.py')],
                              capture_output=True, text=True, env=env, timeout=60)

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
