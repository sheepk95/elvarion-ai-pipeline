"""CPU-only behavioural checks; run with python -I -B test_check_review.py."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(os.environ.get('REVIEW_GATE_SCRIPT', str(Path(__file__).with_name('check_review.py'))))


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
        self.copy.write_text('## 2. Body\n- [-] 2.2 body\n  reason: not applicable to clip\n- [-] 3.1 pose\n  reason: not applicable to clip\n', encoding='utf-8')
        result = self.run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('FEW_PICTURES', result.stdout)

    def test_shipped_checklist_all_not_applicable_fails(self):
        shipped = SCRIPT.with_name('REVIEW-CHECKLIST.example.md')
        self.master.write_text(shipped.read_text(encoding='utf-8'), encoding='utf-8')
        text = re.sub(r'^(\s*-\s*)\[ \](.*)$', r'\1[-]\2\n  reason: not applicable to this clip',
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
                             '- [-] 3.1 pose\n  reason: not applicable to clip\n', encoding='utf-8')
        result = self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        transcript.write_text('', encoding='utf-8')
        result = self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('NOT_OPENED', result.stdout)

    def test_reason_is_separate_from_checklist_text(self):
        self.copy.write_text('## 2. Body\n- [-] 2.2 body has many descriptive words\n'
                             '- [-] 3.1 pose has many descriptive words\n', encoding='utf-8')
        result = self.run_gate()
        self.assertEqual(result.stdout.count('CHECK_REVIEW REASON'), 2, result.stdout)

    def test_non_picture_read_does_not_count_as_visual_evidence(self):
        document = self.dir / 'notes.txt'
        document.write_text('not a picture', encoding='utf-8')
        transcript = self.dir / 'session.jsonl'
        transcript.write_text(json.dumps({'message': {'content': [{'type': 'tool_use', 'name': 'Read',
                               'input': {'file_path': str(document)}}]}}) + '\n', encoding='utf-8')
        self.copy.write_text('## 2. Body\n- [x] 2.2 body\n  see: `notes.txt` f1: body pose is clearly visible here\n'
                             '- [-] 3.1 pose\n  reason: not applicable to clip\n', encoding='utf-8')
        result = self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('NO_PICTURE', result.stdout)
        self.assertIn('FEW_PICTURES', result.stdout)

    def test_empty_reason_does_not_borrow_the_next_line(self):
        self.copy.write_text('## 2. Body\n- [-] 2.2 body\n  reason:\n  other comments are written here\n'
                             '- [-] 3.1 pose\n  reason: not applicable to clip\n', encoding='utf-8')
        result = self.run_gate()
        self.assertIn('CHECK_REVIEW REASON 2.2:', result.stdout)

    def test_section_ten_questions_validate_marks_and_reasons(self):
        self.master.write_text(self.master.read_text() + '## 10. Questions\n- [ ] Question?\n', encoding='utf-8')
        picture = self.dir / 'frame.png'
        picture.write_bytes(b'fixture')
        transcript = self.dir / 'session.jsonl'
        transcript.write_text(json.dumps({'message': {'content': [{'type': 'tool_use', 'name': 'Read',
                               'input': {'file_path': str(picture)}}]}}) + '\n', encoding='utf-8')
        prefix = ('## 2. Body\n- [x] 2.2 body\n  see: frame.png f1: body pose is clearly visible here\n'
                  '- [-] 3.1 pose\n  reason: not applicable to clip\n## 10. Questions\n')
        for question, expected in (('- [-] Question?\n', 'REASON'), ('- [?] Question?\n', 'MARK'),
                                   ('- [ ] Question?\n', 'BLANK'), ('- [!] Question?\n', 'FRAMES')):
            with self.subTest(question=question):
                self.copy.write_text(prefix + question, encoding='utf-8')
                result = self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn('CHECK_REVIEW ' + expected, result.stdout)
        self.copy.write_text(prefix + '- [-] Question?\n  reason: not applicable to clip\n', encoding='utf-8')
        result = self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_codex_call_credit_and_quoted_paths(self):
        picture = self.dir / 'frame one.png'
        other = self.dir / 'frame two.png'
        for p in (picture, other):
            p.write_bytes(b'fixture')
        transcript = self.dir / 'session.jsonl'
        self.copy.write_text('## 2. Body\n- [x] 2.2 body\n  see: `frame one.png` f1: body pose is clearly visible here\n'
                             '- [-] 3.1 pose\n  reason: not applicable to clip\n', encoding='utf-8')
        def run(code):
            transcript.write_text(json.dumps({'payload': {'type': 'custom_tool_call', 'name': 'exec', 'input': code}}) + '\n', encoding='utf-8')
            return self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
        call = 'const r = await tools.view_image({path: ' + json.dumps(str(picture)) + '}); image(r.image_url);'
        good = run(call)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        for code in (call + ' text(' + json.dumps(str(other)) + ');',
                     'text(' + json.dumps(str(picture)) + '); ' + call.replace(json.dumps(str(picture)), json.dumps(str(other))),
                     'if (false) { ' + call + ' }',
                     'text(' + json.dumps(call) + ');'):
            result = run(code)
            self.assertIn('NOT_OPENED', result.stdout, result.stdout)
        direct = {'payload': {'type': 'function_call', 'name': 'view_image', 'arguments': json.dumps({'path': str(picture)})}}
        transcript.write_text(json.dumps(direct) + '\n', encoding='utf-8')
        result = self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_printed_path_is_not_credited_by_neighbor_view(self):
        picture, other = self.dir / 'frame.png', self.dir / 'other.png'
        for p in (picture, other):
            p.write_bytes(b'fixture')
        transcript = self.dir / 'session.jsonl'
        code = 'text(' + json.dumps(str(picture)) + '); const r = await tools.view_image({path: ' + json.dumps(str(other)) + '}); image(r.image_url);'
        transcript.write_text(json.dumps({'payload': {'type': 'custom_tool_call', 'name': 'exec', 'input': code}}) + '\n', encoding='utf-8')
        self.copy.write_text('## 2. Body\n- [x] 2.2 body\n  see: frame.png f1: body pose is clearly visible here\n'
                             '- [-] 3.1 pose\n  reason: not applicable to clip\n', encoding='utf-8')
        result = self.run_gate('--min-pictures', '1', '--transcript', str(transcript))
        self.assertIn('NOT_OPENED', result.stdout, result.stdout)

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
