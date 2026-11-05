"""Catalogue descriptions must survive a standard-library-only installation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(os.environ.get('CATALOGUE_TARGET') or Path(__file__).with_name('build_full_catalogue.py'))
spec = importlib.util.spec_from_file_location('catalogue_under_test', SCRIPT)
catalogue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalogue)


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='catalogue-descriptions-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.skill = self.root / 'SKILL.md'
        self.index = self.root / 'INDEX.md'
        self.index.write_text('| probe | vetted | Index fallback | %s | owner | reviewed |\n' % self.skill,
                              encoding='utf-8')

    def entries(self, body):
        self.skill.write_text(body, encoding='utf-8')
        # Force the documented clean installation even on machines with PyYAML installed.
        with patch.dict(sys.modules, {'yaml': None}):
            entries, _ = catalogue.entries_from_index(self.index)
        return entries[0]['text']

    def test_block_descriptions_and_triggers_without_pyyaml(self):
        for marker in ('>', '|', '>-', '|-', '>+', '|+', '>- # folded description', '|2-', '>+2'):
            with self.subTest(marker=marker):
                text = self.entries('---\nname: probe\ndescription: %s\n  Review concurrency\n  and recovery.\n'
                                    'when_to_use: >\n  Use for mailbox changes.\n---\n' % marker)
                self.assertEqual('Review concurrency and recovery. Use for mailbox changes.',
                                 text.splitlines()[-1].strip())
                self.assertNotIn('Index fallback', text)

    def test_scalar_description_and_missing_frontmatter_controls(self):
        text = self.entries('---\nname: probe\ndescription: "Review safely"\n---\n')
        self.assertIn('Review safely', text)
        self.assertNotIn('Index fallback', text)
        text = self.entries('No frontmatter here\n')
        self.assertIn('Index fallback', text)

    def test_cli_without_site_packages_writes_full_description(self):
        self.skill.write_text('---\nname: probe\ndescription: >\n  Review concurrency\n  and recovery.\n---\n',
                              encoding='utf-8')
        out = self.root / 'catalogue'
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(SCRIPT), '--index', str(self.index),
                                 '--catalogue-dir', str(out)], capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
        text = ''.join((out / name).read_text(encoding='utf-8') for name in manifest['parts'])
        self.assertIn('Review concurrency and recovery.', text)


if __name__ == '__main__':
    unittest.main()
