"""CPU-only behavioural checks; run with python -I -B test_check_review.py."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('check_review.py')


class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='review-gate-test-')
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.master = self.dir / 'master.md'
        self.copy = self.dir / 'review.md'
        self.master.write_text('## 2. Body\n- [ ] 2.2 body\n- [ ] 3.1 pose\n', encoding='utf-8')

    def run_gate(self, *args):
        return subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), str(self.copy),
                               '--checklist', str(self.master), *args], capture_output=True, text=True)

    def test_all_not_applicable_is_not_a_visual_review(self):
        self.copy.write_text('## 2. Body\n- [-] 2.2 not applicable to clip\n- [-] 3.1 not applicable to clip\n', encoding='utf-8')
        result = self.run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('FEW_PICTURES', result.stdout)

    def test_shipped_checklist_all_not_applicable_fails(self):
        shipped = SCRIPT.with_name('REVIEW-CHECKLIST.example.md')
        self.master.write_text(shipped.read_text(encoding='utf-8'), encoding='utf-8')
        text = re.sub(r'^(\s*-\s*)\[ \](.*)$', r'\1[-]\2 not applicable to this clip',
                      self.master.read_text(encoding='utf-8'), flags=re.MULTILINE)
        self.copy.write_text(text, encoding='utf-8')
        result = self.run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('FEW_PICTURES', result.stdout)

    def test_valid_picture_with_individual_not_applicable_passes(self):
        picture = self.dir / 'frame.png'
        picture.write_bytes(b'test picture')
        transcript = self.dir / 'session.jsonl'
        transcript.write_text(json.dumps({'message': {'content': [{'type': 'tool_use', 'name': 'Read',
                               'input': {'file_path': str(picture)}}]}}) + '\n', encoding='utf-8')
        self.copy.write_text('## 2. Body\n- [x] 2.2 body\n  see: frame.png f1: body pose is clearly visible here\n'
                             '- [-] 3.1 not applicable to clip\n', encoding='utf-8')
        result = self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        transcript.write_text('', encoding='utf-8')
        result = self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('NOT_OPENED', result.stdout)

    def test_bad_options_and_missing_master_are_usage_errors(self):
        self.copy.write_text('x', encoding='utf-8')
        for args in (('--min-pictures', '0'), ('--min-pictures', 'no'), ('--min-words', '-1'),
                     ('--blend', str(self.dir / 'missing.blend'))):
            result = self.run_gate(*args)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stderr)
        self.master.unlink()
        result = self.run_gate()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
