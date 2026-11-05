"""CPU-only tests of output refusal and source frame ordering; no model imports or loads."""
import importlib.util
import inspect
import subprocess
import time
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StopAtCheckpoint(Exception):
    pass


class StopAtFrames(Exception):
    pass


class AnimationTests(unittest.TestCase):
    def test_output_refusal_precedes_checkpoint_and_runtime(self):
        runner = load('runner_test', HERE / 'run_sam3db.py')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, content in [('frames/f9999.npz', b'old frame'), ('overlay/f9999.jpg', b'old overlay'),
                                  ('run.json', b'old report')]:
                out = root / name.replace('/', '_')
                target = out / name
                target.parent.mkdir(parents=True)
                target.write_bytes(content)
                with self.subTest(name=name), patch.object(sys, 'argv', ['runner', '--input', 'x', '--out', str(out)]), \
                     patch.object(runner, 'check_checkpoint', side_effect=AssertionError('checkpoint reached')), \
                     patch.object(runner, 'load_runtime', side_effect=AssertionError('runtime reached')):
                    with self.assertRaisesRegex(SystemExit, 'not an empty directory'):
                        runner.main()
                self.assertEqual(target.read_bytes(), content)

    def test_fresh_outputs_reach_checkpoint_without_runtime(self):
        runner = load('runner_fresh_test', HERE / 'run_sam3db.py')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ck = root / 'ck'
            for name in ('model.ckpt', 'model_config.yaml', 'assets/mhr_model.pt'):
                p = ck / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
            empty = root / 'empty'
            empty.mkdir()
            for out in (empty, root / 'absent'):
                with self.subTest(out=out), patch.object(sys, 'argv', ['runner', '--input', 'x', '--out', str(out), '--ckpt-dir', str(ck)]), \
                     patch.object(runner, 'check_checkpoint', side_effect=StopAtCheckpoint), \
                     patch.object(runner, 'load_runtime', side_effect=AssertionError('runtime reached')):
                    with self.assertRaises(StopAtCheckpoint):
                        runner.main()

    def test_competing_process_cannot_claim_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ck = root / 'ck'
            for name in ('model.ckpt', 'model_config.yaml', 'assets/mhr_model.pt'):
                p = ck / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
            out, ready, release = root / 'out', root / 'ready', root / 'release'
            script = r"""
import importlib.util, pathlib, sys, time
path, out, ck, ready, release = sys.argv[1:]
sys.path.insert(0, str(pathlib.Path(path).parent))
spec = importlib.util.spec_from_file_location('runner', path)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
def checkpoint(*args):
    pathlib.Path(ready).touch()
    deadline = time.monotonic() + 15
    while not pathlib.Path(release).exists():
        if time.monotonic() > deadline: raise RuntimeError('release timed out')
        time.sleep(.01)
    raise SystemExit(0)
r.check_checkpoint = checkpoint
r.load_runtime = lambda: (_ for _ in ()).throw(AssertionError('runtime reached'))
sys.argv = ['runner', '--input', 'x', '--out', out, '--ckpt-dir', ck]
r.main()
"""
            cmd = [sys.executable, '-I', '-B', '-c', script, str(HERE / 'run_sam3db.py'),
                   str(out), str(ck), str(ready), str(release)]
            first = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists(), 'first process did not reach checkpoint')
                second = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(second.returncode, 0)
                self.assertIn('already claimed', second.stderr)
                self.assertTrue((out / '.sam3db-claim').is_file())
            finally:
                release.touch()
                first_out, first_err = first.communicate(timeout=10)
            self.assertEqual(first.returncode, 0, first_out + first_err)
            # The marker remains after termination, so even a failed run cannot be reused.
            third = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(third.returncode, 0)
            self.assertIn('already claimed', third.stderr)

    def test_converter_main_uses_full_numeric_frames_in_order(self):
        fake_np = types.ModuleType('numpy')
        fake_np.array = lambda *a, **k: None
        fake_np.diag = lambda *a, **k: None
        seen = []
        fake_np.load = lambda f: seen.append(Path(f).name) or {'p0_shape_params': 0, 'p0_mhr_model_params': 0}
        fake_np.median = lambda *a: None
        def stop_stack(*args):
            frame = inspect.currentframe().f_back
            self.assertEqual(frame.f_locals['vf'], [2, 9999, 10000, 10001])
            raise StopAtFrames()
        fake_np.stack = stop_stack
        fake_torch = types.ModuleType('torch')
        model = types.SimpleNamespace(character_torch=types.SimpleNamespace(skeleton=types.SimpleNamespace(joint_names=[])),
                                      named_buffers=lambda: [('character_torch.skeleton.joint_parents', types.SimpleNamespace(tolist=lambda: [])),
                                                             ('face_expressions_model.shape_vectors', types.SimpleNamespace(shape=(0,)))])
        fake_torch.jit = types.SimpleNamespace(load=lambda *a, **k: model)
        with patch.dict(sys.modules, {'numpy': fake_np, 'torch': fake_torch}):
            converter = load('converter_test', HERE / 'examples-auto-rig-pro' / 'sam_to_source.py')
            with tempfile.TemporaryDirectory() as td:
                frames = Path(td) / 'frames'
                frames.mkdir()
                for name in ('f10001.npz', 'f0002.npz', 'f10000.npz', 'f9999.npz'):
                    (frames / name).touch()
                with patch.object(sys, 'argv', ['converter', td, 'out.npz']):
                    with self.assertRaises(StopAtFrames):
                        converter.main()
        self.assertEqual(seen, ['f0002.npz', 'f9999.npz', 'f10000.npz', 'f10001.npz'])


if __name__ == '__main__':
    unittest.main()
