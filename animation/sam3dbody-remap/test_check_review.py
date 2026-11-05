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

    def shipped_fixture(self):
        self.master.write_text(SCRIPT.with_name('REVIEW-CHECKLIST.example.md').read_text(encoding='utf-8'), encoding='utf-8')
        text = re.sub(r'^(\s*-\s*)\[ \](.*)$', r'\1[-]\2\n  reason: not applicable to this clip',
                      self.master.read_text(encoding='utf-8'), flags=re.MULTILINE)
        records = []
        for n, item in enumerate(('2.2', '3.0', '3.1', '3.2')):
            picture = self.dir / f'frame{n}.png'
            picture.write_bytes(b'parser fixture, not an image')
            records.append({'message': {'content': [{'type': 'tool_use', 'name': 'Read', 'input': {'file_path': str(picture)}}]}})
            pattern = rf'(?m)^- \[-\] \*\*{re.escape(item)}\*\*([^\n]*)\n  reason: not applicable to this clip'
            text, count = re.subn(pattern, lambda m: f'- [x] **{item}**{m.group(1)}\n  see: frame{n}.png f1: distinct body pose visible number {chr(97+n)*2}', text)
            self.assertEqual(count, 1)
        transcript = self.dir / 'session.jsonl'
        transcript.write_text(''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8')
        return text, transcript

    def test_shipped_prompts_are_required(self):
        text, transcript = self.shipped_fixture()
        stripped = re.sub(r'(?m)^(- \[[x-]\] \*\*\d+\.\d+[a-z]?\*\*).+$', r'\1', text)
        self.copy.write_text(stripped, encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertIn('PROMPT', result.stdout)

    def test_shipped_copy_allows_marks_evidence_and_blank_signoff(self):
        text, transcript = self.shipped_fixture()
        text = re.sub(r'(?m)^- \[-\] (\*\*11\.[12]\*\*[^\n]*)\n  reason: not applicable to this clip',
                      r'  - [ ] \1  ', text)
        self.copy.write_text(text, encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        result = self.run_gate('--transcript', str(transcript), '--final', 'yes')
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn('BLANK 11.1', result.stdout)

    def test_shipped_questions_are_required(self):
        text, transcript = self.shipped_fixture()
        questions = re.findall(r'(?m)^- \[-\] (.+\?)$', text)
        self.assertEqual(3, len(questions))
        self.copy.write_text(text.replace(questions[1], questions[0]).replace(questions[2], questions[0]), encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertIn('QUESTION', result.stdout)

    def test_shipped_item_section_is_required(self):
        text, transcript = self.shipped_fixture()
        line = next(line for line in text.splitlines() if line.startswith('- [-] **1.1**'))
        moved = text.replace(line + '\n  reason: not applicable to this clip\n', '')
        moved += '\n' + line.replace('[-]', '[ ]') + '\n'
        self.copy.write_text(moved, encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertIn('SECTION', result.stdout)

    def test_duplicate_ids_are_rejected(self):
        text, transcript = self.shipped_fixture()
        line = next(line for line in text.splitlines() if line.startswith('- [-] **1.1**'))
        self.copy.write_text(text + '\n' + line + '\n  reason: not applicable to this clip\n', encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertIn('DUPLICATE', result.stdout)

    def test_hidden_item_and_question_do_not_count(self):
        text, transcript = self.shipped_fixture()
        item = next(line for line in text.splitlines() if line.startswith('- [-] **1.1**'))
        question = '- [-] What would a person watching this clip say looks wrong first?'
        reason = '\n  reason: not applicable to this clip'
        for target in (item, question):
            block = target + reason
            for start, end in (('<!--\n', '\n-->'), ('```markdown\n', '\n```'), ('~~~\n', '\n~~~')):
                with self.subTest(target=target, fence=start):
                    self.copy.write_text(text.replace(block, start + block + end), encoding='utf-8')
                    result = self.run_gate('--transcript', str(transcript))
                    self.assertEqual(1, result.returncode, result.stdout)
                    self.assertIn('MISSING' if target == item else 'QUESTION', result.stdout)
            with self.subTest(target=target, fence='indented code'):
                self.copy.write_text(text.replace(block, '\n'.join('    ' + line for line in block.splitlines())), encoding='utf-8')
                result = self.run_gate('--transcript', str(transcript))
                self.assertEqual(1, result.returncode, result.stdout)
                self.assertIn('MISSING' if target == item else 'QUESTION', result.stdout)

    def test_hidden_section_heading_does_not_move_live_items(self):
        text, transcript = self.shipped_fixture()
        text = text.replace('## 1. Setup (numbers)', '## 1. Setup (numbers)\n```\n## 11. Fake sign-off\n```')
        self.copy.write_text(text, encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_comment_hidden_reason_does_not_count(self):
        text, transcript = self.shipped_fixture()
        line = next(line for line in text.splitlines() if line.startswith('- [-] **1.1**'))
        text = text.replace(line + '\n  reason: not applicable to this clip',
                            line + '\n<!--\n  reason: not applicable to this clip\n-->')
        self.copy.write_text(text, encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertIn('REASON 1.1', result.stdout)

    def test_raw_html_containers_are_refused(self):
        text, transcript = self.shipped_fixture()
        line = next(line for line in text.splitlines() if line.startswith('- [-] **1.1**'))
        block = line + '\n  reason: not applicable to this clip'
        for opening, closing in (('<div hidden>', '</div>'), ('<pre>', '</pre>'),
                                 ('<span style="display:none">', '</span>'), ('<style>', '</style>'),
                                 ('<div\n hidden>', '</div>')):
            with self.subTest(opening=opening):
                self.copy.write_text(text.replace(block, opening + '\n' + block + '\n' + closing), encoding='utf-8')
                result = self.run_gate('--transcript', str(transcript))
                self.assertEqual(1, result.returncode, result.stdout)
                self.assertIn('HTML', result.stdout)

    def test_raw_html_master_and_ambiguous_comment_are_refused(self):
        text, transcript = self.shipped_fixture()
        self.copy.write_text(text, encoding='utf-8')
        self.master.write_text(self.master.read_text(encoding='utf-8') + '\n<div hidden>\n', encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn('unsupported raw HTML', result.stdout)
        self.master.write_text(SCRIPT.with_name('REVIEW-CHECKLIST.example.md').read_text(encoding='utf-8'), encoding='utf-8')
        self.copy.write_text(text + '\n`<!--`\n<div hidden>\n', encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertIn('HTML', result.stdout)

    def test_nested_code_evidence_does_not_count(self):
        text, transcript = self.shipped_fixture()
        reason = '  reason: not applicable to this clip'
        picture = '  see: frame0.png f1: distinct body pose visible number aa'
        for original, code in ((reason, 'REASON 1.1'), (picture, 'NO_LOOK 2.2')):
            for replacement in ('    ```\n    ' + original.strip() + '\n    ```',
                                '      ' + original.strip()):
                with self.subTest(evidence=code, replacement=replacement):
                    self.copy.write_text(text.replace(original, replacement, 1), encoding='utf-8')
                    result = self.run_gate('--transcript', str(transcript))
                    self.assertEqual(1, result.returncode, result.stdout)
                    self.assertIn(code, result.stdout)

    def test_indented_box_and_relative_evidence(self):
        text, transcript = self.shipped_fixture()
        line = next(line for line in text.splitlines() if line.startswith('- [-] **1.1**'))
        original = line + '\n  reason: not applicable to this clip'
        indented = '   ' + line + '\n     reason: not applicable to this clip'
        self.copy.write_text(text.replace(original, indented), encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(0, result.returncode, result.stdout)
        fenced = '   ' + line + '\n     ```\n     reason: not applicable to this clip\n     ```'
        self.copy.write_text(text.replace(original, fenced), encoding='utf-8')
        result = self.run_gate('--transcript', str(transcript))
        self.assertEqual(1, result.returncode, result.stdout)
        self.assertIn('REASON 1.1', result.stdout)

    def test_html_declarations_are_refused(self):
        text, transcript = self.shipped_fixture()
        line = next(line for line in text.splitlines() if line.startswith('- [-] **1.1**'))
        block = line + '\n  reason: not applicable to this clip'
        for opening, closing in (('<![CDATA[', ']]>'), ('<!DOCTYPE html [', ']>'), ('<?hidden', '?>')):
            with self.subTest(opening=opening):
                self.copy.write_text(text.replace(block, opening + '\n' + block + '\n' + closing), encoding='utf-8')
                result = self.run_gate('--transcript', str(transcript))
                self.assertEqual(1, result.returncode, result.stdout)
                self.assertIn('HTML', result.stdout)

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
