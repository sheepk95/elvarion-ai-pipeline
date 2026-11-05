"""Isolated behavioural checks: python -I -B test_build_index.py."""
import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('build_index.py')


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='skill-index-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.skills = self.root / 'skills'
        self.library = self.root / 'library'
        self.env = dict(os.environ, SKILLS_DIR=str(self.skills), SKILL_LIBRARY=str(self.library),
                        SKILL_RECORDS=str(self.library / '_records'), SKILL_CORE_FILE=str(self.library / 'CORE.txt'))

    def run_index(self, *args):
        return subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True)

    def skill(self, name, origin=''):
        folder = self.skills / name
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text('---\nname: %s\ndescription: test\n%s---\n' %
                                         (name, ('origin: ' + origin + '\n') if origin else ''), encoding='utf-8')

    def test_missing_directories_are_read_only_and_actionable(self):
        result = self.run_index('--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('missing directory', result.stderr)
        self.assertFalse(self.skills.exists())
        self.assertFalse(self.library.exists())
        result = self.run_index()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('create SKILL_LIBRARY', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_unverified_in_house_and_recorded_approval(self):
        self.skill('unknown')
        self.skill('local', 'in-house')
        self.skill('reviewed')
        records = self.library / '_records'
        records.mkdir(parents=True)
        (records / 'INSTALLS.jsonl').write_text(json.dumps({'name': 'reviewed', 'source_id': 'repo', 'commit': 'abc'}) + '\n', encoding='utf-8')
        (records / 'REVIEWS.jsonl').write_text(json.dumps({'source_id': 'repo', 'commit': 'abc', 'approved': True}) + '\n', encoding='utf-8')
        package = self.skills / 'reviewed'
        scripts = package / 'scripts'
        scripts.mkdir()
        script = scripts / 'helper.py'
        script.write_text('print(1)', encoding='utf-8')
        manifest = {p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in package.rglob('*') if p.is_file()}
        (records / 'TRUST.json').write_text(json.dumps({'reviewed': {'files': manifest, 'kind': 'reviewed', 'provenance': 'owner review'}}), encoding='utf-8')
        result = self.run_index()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        index = (self.library / 'INDEX.md').read_text(encoding='utf-8')
        self.assertIn('| unknown | installed-unverified |', index)
        self.assertIn('| local | installed-unverified |', index)
        self.assertIn('| reviewed | vetted |', index)
        env = dict(self.env, LIBRARIAN_ROOT=str(self.root / 'librarian'))
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT.with_name('build_full_catalogue.py'))],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        catalogue = ''.join(p.read_text(encoding='utf-8') for p in (self.root / 'librarian' / 'catalogue').glob('CATALOGUE-PART-*.md'))
        self.assertIn('reviewed', catalogue)
        self.assertNotIn('unknown', catalogue)
        simulation = self.root / 'new-skill'
        simulation.mkdir()
        (simulation / 'SKILL.md').write_text('---\nname: candidate\ndescription: sample\n---\n', encoding='utf-8')
        result = self.run_index('--simulate-install', 'candidate=' + str(simulation))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['check']['status'], 'installed-unverified')
        def assert_unverified():
            result = self.run_index()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('| reviewed | installed-unverified |', (self.library / 'INDEX.md').read_text(encoding='utf-8'))

        script.write_text('print(2)', encoding='utf-8')
        assert_unverified()
        script.write_text('print(1)', encoding='utf-8')
        added = scripts / 'added.py'
        added.write_text('new', encoding='utf-8')
        assert_unverified()
        added.unlink()
        script.unlink()
        assert_unverified()
        script.write_text('print(1)', encoding='utf-8')
        result = self.run_index()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('| reviewed | vetted |', (self.library / 'INDEX.md').read_text(encoding='utf-8'))
        link = package / 'unsafe-link'
        target = self.root / 'outside'
        target.mkdir()
        if os.name == 'nt':
            created = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        else:
            link.symlink_to(target, target_is_directory=True)
        assert_unverified()
        if os.name == 'nt':
            os.rmdir(link)
        else:
            link.unlink()
        (records / 'TRUST.json').write_text('{malformed', encoding='utf-8')
        result = self.run_index()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('invalid TRUST.json', result.stderr)
        self.assertIn('| reviewed | installed-unverified |', (self.library / 'INDEX.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
