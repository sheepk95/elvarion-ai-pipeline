"""CPU-only checkpoint path checks; imports use stubs, never model code."""
import os
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import patch

SOURCE = Path(os.environ.get('SAM_SOURCE_SCRIPT', Path(__file__).parent / 'examples-auto-rig-pro' / 'sam_to_source.py'))

class CheckpointPathTests(unittest.TestCase):
    def load(self, override=None):
        numpy = types.ModuleType('numpy')
        numpy.array = lambda *a, **k: object()
        numpy.diag = lambda *a, **k: object()
        env = dict(os.environ)
        env.pop('SAM3DB_CKPT_DIR', None)
        if override is not None:
            env['SAM3DB_CKPT_DIR'] = override
        with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {'numpy': numpy, 'torch': types.ModuleType('torch')}):
            return runpy.run_path(str(SOURCE))

    def test_default_is_parent_kit_checkpoint(self):
        self.assertEqual(self.load()['MHR_PT'], SOURCE.resolve().parent.parent / 'checkpoints' / 'sam-3d-body-vith' / 'assets' / 'mhr_model.pt')

    def test_environment_override(self):
        self.assertEqual(self.load('custom checkpoint')['MHR_PT'], Path('custom checkpoint') / 'assets' / 'mhr_model.pt')

if __name__ == '__main__':
    unittest.main()
