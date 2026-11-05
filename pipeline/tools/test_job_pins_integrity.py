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

if __name__ == '__main__': unittest.main(verbosity=2)
