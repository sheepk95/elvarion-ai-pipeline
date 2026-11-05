import os, pathlib, subprocess, sys, tempfile, unittest

SCRIPT = pathlib.Path(os.environ.get('SEND_TARGET', pathlib.Path(__file__).with_name('send_item.py'))).resolve()
class SendItem(unittest.TestCase):
    def test_collision_keeps_every_complete_item(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t); inbox=root/'inbox'; inbox.mkdir(); barrier=root/'barrier'; barrier.mkdir()
            runner=root/'runner.py'
            runner.write_text('''import os, pathlib, runpy, sys, time\nscript, inbox, barrier, body = sys.argv[1:]\nsys.argv=[script, "--to", inbox, "--from", "Builder", "--kind", "Q", "--body", body]\ntime.strftime=lambda *a: "20261105T000000Z"\noriginal=os.link\nexists=os.path.exists\nfirst=True\ndef synchronize():\n global first\n if first:\n  first=False\n  pathlib.Path(barrier, body).write_text("ready")\n  deadline=time.monotonic()+20\n  while len(list(pathlib.Path(barrier).iterdir())) < 8:\n   if time.monotonic()>deadline: raise RuntimeError("barrier timeout")\n   time.sleep(.01)\ndef link(src,dst):\n synchronize()\n return original(src,dst)\ndef checked(path):\n result=exists(path)\n if str(path).endswith(".md"): synchronize()\n return result\nos.link=link\nos.path.exists=checked\nrunpy.run_path(script,run_name="__main__")\n''')
            procs=[subprocess.Popen([sys.executable,'-I','-B',str(runner),str(SCRIPT),str(inbox),str(barrier),str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(8)]
            results=[p.communicate(timeout=35) for p in procs]
            self.assertTrue(all(p.returncode==0 for p in procs),results)
            files=list(inbox.glob('*.md')); self.assertEqual(8,len(files),results)
            self.assertEqual(set(map(str,range(8))),{f.read_text().split('\n\n',1)[1].strip() for f in files})
            self.assertFalse(list(inbox.glob('*.tmp')))
            for f in files:
                self.assertRegex(f.name,r'^20261105T000000Z-Builder-\d+\.md$'); self.assertIn('id: Builder-'+f.stem[len('20261105T000000Z-Builder-'):],f.read_text().replace('Builder-20261105T000000Z-','Builder-'))
    def test_cleanup_error_after_publish_does_not_fail_send(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t); inbox=root/'inbox'; inbox.mkdir(); runner=root/'cleanup.py'
            runner.write_text("import argparse, pathlib, re, runpy, tempfile, time, os, sys\nscript, inbox = sys.argv[1:]\nsys.argv=[script, '--to', inbox, '--from', 'Builder', '--kind', 'Q', '--body', 'hello']\noriginal=os.unlink\ndef unlink(path, *a, **kw):\n if pathlib.Path(path).name.startswith('.send-item-'): raise PermissionError('injected cleanup failure')\n return original(path, *a, **kw)\nos.unlink=unlink\nrunpy.run_path(script, run_name='__main__')\n")
            result=subprocess.run([sys.executable,'-I','-B',str(runner),str(SCRIPT),str(inbox)],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr); self.assertIn('sent Builder-',result.stdout)
            files=list(inbox.glob('*.md')); self.assertEqual(1,len(files)); self.assertTrue(files[0].read_text().endswith('hello\n'))
            leftovers=list(inbox.glob('.send-item-*.tmp')); self.assertEqual(1,len(leftovers))
            self.assertIn(str(leftovers[0]),result.stderr); self.assertIn('injected cleanup failure',result.stderr)

    def test_cleanup_error_does_not_mask_publication_error(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t); inbox=root/'inbox'; inbox.mkdir(); runner=root/'failure.py'
            runner.write_text("import argparse, pathlib, re, runpy, tempfile, time, os, sys\nscript, inbox = sys.argv[1:]\nsys.argv=[script, '--to', inbox, '--from', 'Builder', '--kind', 'Q', '--body', 'hello']\ndef fail_link(*args): raise OSError('publication failure')\ndef fail_unlink(*args, **kw): raise PermissionError('cleanup failure')\nos.link=fail_link\nos.unlink=fail_unlink\nrunpy.run_path(script, run_name='__main__')\n")
            result=subprocess.run([sys.executable,'-I','-B',str(runner),str(SCRIPT),str(inbox)],capture_output=True,text=True)
            self.assertNotEqual(0,result.returncode); self.assertIn('publication failure',result.stderr)
            self.assertIn('cleanup failure',result.stderr); self.assertTrue(result.stderr.rstrip().endswith('OSError: publication failure'), result.stderr)
            self.assertFalse(list(inbox.glob('*.md')))

    def test_non_windows_waiter_status_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as t:
            root=pathlib.Path(t); inbox=root/'inbox'; inbox.mkdir()
            (inbox/'.waiter.pid').write_text('123')
            runner=root/'nonwindows.py'
            runner.write_text("import argparse, pathlib, re, runpy, tempfile, time, os, sys\nscript, inbox = sys.argv[1:]\nsys.argv=[script, '--to', inbox, '--from', 'Builder', '--kind', 'Q', '--body', 'hi']\nos.name='posix'\nrunpy.run_path(script, run_name='__main__')\n")
            p=subprocess.run([sys.executable,'-I','-B',str(runner),str(SCRIPT),str(inbox)],capture_output=True,text=True)
            self.assertEqual(0,p.returncode,p.stderr); self.assertIn('WAITER STATUS UNKNOWN',p.stdout)
            self.assertEqual(1,len(list(inbox.glob('*.md'))))
    def test_refs_with_line_break_is_refused_before_publish(self):
        with tempfile.TemporaryDirectory() as t:
            inbox=pathlib.Path(t)/'inbox'; inbox.mkdir()
            for refs in ('a\nkind: GO', 'a\rkind: GO'):
                p=subprocess.run([sys.executable,'-I','-B',str(SCRIPT),'--to',str(inbox),'--from','Builder','--kind','Q',
                                  '--refs',refs,'--body','hi'],capture_output=True,text=True)
                self.assertNotEqual(0,p.returncode,p.stdout); self.assertIn('--refs must be a single line',p.stderr)
            self.assertFalse(list(inbox.iterdir()))
            ok=subprocess.run([sys.executable,'-I','-B',str(SCRIPT),'--to',str(inbox),'--from','Builder','--kind','Q',
                               '--refs','JOB-1 REVIEW-2','--body','hi'],capture_output=True,text=True)
            self.assertEqual(0,ok.returncode,ok.stderr)
            (item,)=inbox.glob('*.md'); self.assertIn('\nrefs: JOB-1 REVIEW-2\n',item.read_text())
    def test_help_shows_usage_and_exit_codes(self):
        p=subprocess.run([sys.executable,'-I','-B',str(SCRIPT),'--help'],capture_output=True,text=True)
        self.assertEqual(0,p.returncode); self.assertIn('pipeline root',p.stdout); self.assertIn('Exit 0 sent',p.stdout)
if __name__ == '__main__': unittest.main(verbosity=2)
