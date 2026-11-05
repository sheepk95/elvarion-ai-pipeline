import os, pathlib, subprocess, sys, tempfile, unittest

SCRIPT = pathlib.Path(os.environ.get('PINS_TARGET', pathlib.Path(__file__).with_name('job_pins.py'))).resolve()

class PinIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = pathlib.Path(self.tmp.name)
        self.jd = self.root/'jobs'/'d-1'; self.jd.mkdir(parents=True)
        self.score = self.root/'score.md'; self.score.write_text('score')
        self.work = self.root/'work.md'; self.work.write_text('work')
        self.card = self.jd/'JOB.md'; self.card.write_text(f'Systems: x\nWork: file | {self.work}\nScorecard: `{self.score}`\n')
        self.line = self.runpins().stdout.splitlines()[0]
        for kind in ('REVIEW','TEST','GATE'): self.record(kind, 1, self.line)
    def tearDown(self): self.tmp.cleanup()
    def runpins(self,*args):
        return subprocess.run([sys.executable, '-I','-B',str(SCRIPT),'d-1','--root',str(self.root),*args],text=True,capture_output=True)
    def record(self, kind, n, line, heading=None, note=''):
        (self.jd/f'{kind}-{n}.md').write_text(f'{heading or "# " + kind}\n{line}\n{note}\n')
    def test_each_record_component_and_missing_review(self):
        self.assertEqual(0,self.runpins('--check').returncode)
        for kind in ('REVIEW','TEST'):
            for old,new in (('card ','card '),('scorecard ','scorecard '),('work ','work ')):
                pos=self.line.index(old)+len(old); bad=self.line[:pos]+'0'*12+self.line[pos+12:]
                self.record(kind,1,bad)
                result=self.runpins('--check'); self.assertEqual(1,result.returncode,(kind,old,result.stdout)); self.assertIn('MISMATCH '+old.strip(),result.stdout)
                self.record(kind,1,self.line)
        (self.jd/'REVIEW-1.md').unlink(); self.assertEqual(2,self.runpins('--check').returncode)
    def test_scoped_re_gate_requires_named_prior_complete_tuple(self):
        old=self.line; self.work.write_text('new'); now=self.runpins().stdout.splitlines()[0]
        self.record('REVIEW',2,now); self.record('GATE',2,now,'# SCOPED RE-GATE of GATE-1','tester not re-run: untouched')
        self.assertEqual(0,self.runpins('--check').returncode)
        pos=old.index('card ')+5; bad=old[:pos]+'0'*12+old[pos+12:]; self.record('TEST',1,bad)
        self.assertEqual(1,self.runpins('--check').returncode)
        self.record('TEST',1,old); self.record('GATE',3,now,'# SCOPED RE-GATE of GATE-2','tester not re-run: untouched')
        self.assertEqual(1,self.runpins('--check').returncode)
    def test_scoped_re_gate_rejects_changed_card_or_score(self):
        card_original = self.card.read_text(); score_original = self.score.read_text()
        for changed in ('card', 'score'):
            with self.subTest(changed=changed):
                self.card.write_text(card_original); self.score.write_text(score_original); self.work.write_text('work')
                old = self.runpins().stdout.splitlines()[0]
                self.record('TEST', 1, old); self.record('GATE', 1, old)
                if changed == 'card': self.card.write_text(card_original + 'Extra: amended\n')
                else: self.score.write_text(score_original + ' amended')
                self.work.write_text('new work'); now = self.runpins().stdout.splitlines()[0]
                self.record('REVIEW', 2, now)
                self.record('GATE', 2, now, '# SCOPED RE-GATE of GATE-1', 'tester not re-run: untouched')
                result = self.runpins('--check')
                self.assertEqual(1, result.returncode, result.stdout)
                self.assertIn('MISMATCH ' + ('card' if changed == 'card' else 'scorecard'), result.stdout)
                (self.jd/'GATE-2.md').unlink(); (self.jd/'REVIEW-2.md').unlink()
    def test_current_git_dirty_but_historical_override_allowed(self):
        wt=self.root/'repo'; wt.mkdir()
        def git(*args): return subprocess.run(['git','-C',str(wt),*args],check=True,capture_output=True,text=True).stdout.strip()
        git('init','-b','work'); git('config','user.email','test@example.invalid'); git('config','user.name','Test')
        (wt/'tracked').write_text('one'); git('add','tracked'); git('commit','-m','one'); sha=git('rev-parse','HEAD')
        self.card.write_text(f'Systems: x\nWork: commit | worktree {wt} | branch work\nScorecard: `{self.score}`\n')
        clean=self.runpins(); self.assertEqual(0,clean.returncode,clean.stdout)
        for kind in ('REVIEW','TEST','GATE'): self.record(kind,1,clean.stdout.splitlines()[0])
        self.assertEqual(0,self.runpins('--check').returncode)
        for path in (wt/'tracked',wt/'untracked'):
            path.write_text('changed'); self.assertEqual(2,self.runpins().returncode); self.assertEqual(2,self.runpins('--check').returncode)
            self.assertEqual(0,self.runpins('--work',sha).returncode)
            if path.name=='tracked': path.write_text('one')
            else: path.unlink()
        (wt/'.gitignore').write_text('ignored\n'); git('add','.gitignore'); git('commit','-m','ignore'); (wt/'ignored').write_text('ignored')
        self.assertEqual(0,self.runpins().returncode)
        # the dirty error names the changed paths (first 5 only) and warns against git clean
        names=['proof clip %d.mp4' % i for i in range(7)]
        for n in names: (wt/n).write_text('media')
        r=self.runpins(); out=r.stdout+r.stderr
        self.assertEqual(2,r.returncode,out)
        for n in sorted(names)[:5]: self.assertIn(n,out)
        self.assertNotIn(sorted(names)[5],out); self.assertIn('and 2 more',out)
        self.assertIn('do not git clean proof media',out)

    # A record carries exactly one pins line: the authoritative one is in its top 5 lines, and a different one anywhere
    # in the file is refused (exit 2). Expected tuples are built here from the fixture's own line, not by job_pins.
    def other_line(self):
        pos = self.line.index('work ') + 5
        return self.line[:pos] + '0' * 12 + self.line[pos + 12:]
    def test_record_with_two_different_pins_lines_is_refused(self):
        (self.jd/'REVIEW-1.md').write_text('# REVIEW\n%s\n%s\n' % (self.line, self.other_line()))
        r = self.runpins('--check')
        self.assertEqual(2, r.returncode, r.stdout + r.stderr)
        self.assertIn('different pins lines', r.stdout + r.stderr)
    def test_conflicting_pin_after_line_5_is_refused(self):
        filler = ''.join('note %d\n' % i for i in range(3))          # header pin on line 2, the other on line 6
        for kind in ('REVIEW', 'TEST', 'GATE'):
            with self.subTest(kind=kind):
                p = self.jd/f'{kind}-1.md'
                p.write_text('# %s\n%s\n%s%s\n' % (kind, self.line, filler, self.other_line()))
                self.assertEqual(self.other_line(), p.read_text().splitlines()[5])
                r = self.runpins('--check')
                self.assertEqual(2, r.returncode, r.stdout + r.stderr)
                self.assertIn('different pins lines', r.stdout + r.stderr)
                p.write_text('# %s\n%s\n%s%s\n' % (kind, self.line, filler, self.line))   # the same line again: fine
                self.assertEqual(0, self.runpins('--check').returncode)
                p.write_text('# %s\n%s%s\n%s\n' % (kind, filler, 'more\n', self.line))     # only pin on line 6
                r = self.runpins('--check')
                self.assertEqual(2, r.returncode, r.stdout)
                self.assertIn('no pins line in its top 5 lines', r.stdout)
                self.record(kind, 1, self.line)
    def test_scoped_header_with_trailing_text_is_not_scoped(self):
        self.work.write_text('new'); now = self.runpins().stdout.splitlines()[0]
        self.record('REVIEW', 2, now)
        self.record('GATE', 2, now, '# SCOPED RE-GATE of GATE-1 (draft)', 'tester not re-run: untouched')
        self.assertEqual(1, self.runpins('--check').returncode)

    # When a scoped header matched but the older TEST is refused, a NOTE names the condition that failed.
    def test_scoped_refusal_names_the_failed_condition(self):
        old = self.line; self.work.write_text('new'); now = self.runpins().stdout.splitlines()[0]
        self.record('REVIEW', 2, now)
        cpos = old.index('card ') + 5; card_bad = old[:cpos] + '0' * 12 + old[cpos + 12:]
        wpos = old.index('work ') + 5; work_bad = old[:wpos] + '0' * 12 + old[wpos + 12:]
        cases = [
            ('no skip line', old, '# SCOPED RE-GATE of GATE-1', '', "no 'tester not re-run: <why>' line"),
            ('card differs', card_bad, '# SCOPED RE-GATE of GATE-1', 'tester not re-run: untouched',
             "card or scorecard pin differs from the current gate"),
            ('TEST not the named gate', work_bad, '# SCOPED RE-GATE of GATE-1', 'tester not re-run: untouched',
             "pins differ from the named GATE-1"),
            ('named gate not earlier', old, '# SCOPED RE-GATE of GATE-2', 'tester not re-run: untouched',
             "GATE-2 is missing, has no pins line in its top 5 lines, or is not earlier than this gate"),
            ('named gate missing', old, '# SCOPED RE-GATE of GATE-0', 'tester not re-run: untouched',
             "GATE-0 is missing"),
        ]
        for label, test_line, heading, note, reason in cases:
            with self.subTest(label):
                self.record('TEST', 1, test_line); self.record('GATE', 2, now, heading, note)
                r = self.runpins('--check'); out = r.stdout
                self.assertEqual(1, r.returncode, out)
                self.assertIn('NOTE scoped re-gate of GATE-', out)
                self.assertIn(reason, out)
                self.assertTrue(out.rstrip().splitlines()[-1].startswith('next: '), out)
        self.record('TEST', 1, old); self.record('GATE', 2, now, '# SCOPED RE-GATE of GATE-1', 'tester not re-run: untouched')
        r = self.runpins('--check'); self.assertEqual(0, r.returncode, r.stdout); self.assertNotIn('NOTE', r.stdout)

    def test_ready_mismatch_is_printed_once(self):
        ready = self.root/'ready.md'
        ready.write_text('id: B-1\nkind: READY\nfrom: B\nrefs: d-1\n\nREADY d-1\n%s\n' % self.other_line())
        r = self.runpins('--check', '--ready', str(ready))
        self.assertEqual(1, r.returncode, r.stdout)
        lines = [l for l in r.stdout.splitlines() if l.startswith('MISMATCH') and 'READY' in l]
        self.assertEqual(['MISMATCH work READY vs GATE: %s vs %s' % ('0' * 12, self.line[-12:])], lines, r.stdout)

if __name__ == '__main__': unittest.main(verbosity=2)
