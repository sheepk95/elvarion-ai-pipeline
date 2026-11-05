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

    @staticmethod
    def manifest_of(folder):
        """The owner's manifest, computed here independently of build_index.package_manifest."""
        return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.rglob('*') if p.is_file()}

    def trust(self, entries):
        records = self.library / '_records'
        records.mkdir(parents=True, exist_ok=True)
        (records / 'TRUST.json').write_text(json.dumps(entries), encoding='utf-8')

    def test_simulate_install_hashes_the_candidate_folder(self):
        candidate = self.root / 'candidate-src'
        (candidate / 'scripts').mkdir(parents=True)
        (candidate / 'SKILL.md').write_text('---\nname: candidate\ndescription: sample\n---\n', encoding='utf-8')
        helper = candidate / 'scripts' / 'helper.py'
        helper.write_text('print(1)', encoding='utf-8')
        self.trust({'candidate': {'files': self.manifest_of(candidate), 'kind': 'reviewed', 'provenance': 'owner review'}})
        destination = self.library / 'candidate'
        result = self.run_index('--simulate-install', 'candidate=' + str(candidate))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual('vetted', out['check']['status'], 'matching owner trust for the candidate bytes: vetted')
        self.assertEqual(str(destination / 'SKILL.md').replace('\\', '/'), out['check']['path'].replace('\\', '/'))
        self.assertFalse(destination.exists(), 'a dry run creates nothing')
        helper.write_text('print(2)', encoding='utf-8')
        result = self.run_index('--simulate-install', 'candidate=' + str(candidate))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual('installed-unverified', json.loads(result.stdout)['check']['status'])
        self.assertFalse(destination.exists())

    def test_after_install_passes_a_fresh_unreviewed_install(self):
        folder = self.library / 'fresh'
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text('---\nname: fresh\ndescription: new\n---\n', encoding='utf-8')
        result = self.run_index('--after-install', 'fresh')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        out = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(out['ok'], out)
        self.assertEqual('installed-unverified', out['status'])
        self.assertEqual(1, out['rows'])
        # the dry run of the same package gives the same answer
        other = self.root / 'other-src'
        other.mkdir()
        (other / 'SKILL.md').write_text('---\nname: other\ndescription: new\n---\n', encoding='utf-8')
        sim = self.run_index('--simulate-install', 'other=' + str(other))
        self.assertEqual(sim.returncode, 0, sim.stdout + sim.stderr)
        self.assertEqual('installed-unverified', json.loads(sim.stdout)['check']['status'])

    def test_simulate_install_over_an_existing_live_skill_is_refused(self):
        self.skill('taken')
        candidate = self.root / 'taken-src'
        candidate.mkdir()
        (candidate / 'SKILL.md').write_text('---\nname: taken\ndescription: new\n---\n', encoding='utf-8')
        result = self.run_index('--simulate-install', 'taken=' + str(candidate))
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)['check']['ok'])

    def test_verify_name_needs_one_row_at_the_expected_path(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('build_index_under_test', SCRIPT)
        bi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bi)
        real = self.root / 'real' / 'SKILL.md'
        real.parent.mkdir()
        real.write_text('x', encoding='utf-8')
        wrong = self.root / 'wrong' / 'SKILL.md'
        wrong.parent.mkdir()
        wrong.write_text('x', encoding='utf-8')
        def line(status, path):
            return '| s | %s | d | %s | src | v |' % (status, str(path).replace('\\', '/'))
        one = line('installed-unverified', real)
        self.assertTrue(bi.verify_name(one, 's', str(real))['ok'])
        self.assertEqual('installed-unverified', bi.verify_name(one, 's', str(real))['status'])
        self.assertTrue(bi.verify_name(line('vetted', real), 's', str(real))['ok'])
        self.assertFalse(bi.verify_name(line('vetted', wrong), 's', str(real))['ok'], 'wrong path')
        self.assertFalse(bi.verify_name('', 's', str(real))['ok'], 'no row')
        two = one + '\n' + line('vetted', real)
        result = bi.verify_name(two, 's', str(real))
        self.assertFalse(result['ok'], 'duplicate rows')
        self.assertEqual(2, result['rows'])
        gone = self.root / 'gone' / 'SKILL.md'
        self.assertFalse(bi.verify_name(line('vetted', gone), 's', str(gone))['ok'], 'missing file')

    def test_blank_trust_provenance_is_not_approval(self):
        self.skill('blank')
        self.trust({'blank': {'files': self.manifest_of(self.skills / 'blank'), 'kind': 'reviewed', 'provenance': '  \t '}})
        result = self.run_index()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('| blank | installed-unverified |', (self.library / 'INDEX.md').read_text(encoding='utf-8'))
        # control: the same entry with a real provenance is approved, so the test hinges on provenance alone
        self.trust({'blank': {'files': self.manifest_of(self.skills / 'blank'), 'kind': 'reviewed', 'provenance': 'owner'}})
        result = self.run_index()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('| blank | vetted |', (self.library / 'INDEX.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
