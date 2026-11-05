"""CPU-only, stdlib-only checks of the checkpoint guard; run with python -I -B test_verify_checkpoint.py.

The expected ids below are hard-coded constants for literal bytes (sha256 of b"abc" and b"hello\\n", git blob ids of
b"hello\\n" and b""; the same values `sha256sum` and `git hash-object` print), not values computed by the code under
test. run_sam3db.main() is driven with torch, cv2, numpy and sam_3d_body blocked, to show the refusal happens before
any of them is imported.
"""
import contextlib
import importlib.abc
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verify_checkpoint  # noqa: E402

SHA_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"      # sha256(b"abc")
SHA_HELLO = "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"    # sha256(b"hello\n")
BLOB_HELLO = "ce013625030ba8dba906f756967f9e9ca394464a"                           # git blob of b"hello\n"
BLOB_EMPTY = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"                           # git blob of b""

FIXTURE = {"model.ckpt": b"abc", "assets/mhr_model.pt": b"hello\n", "model_config.yaml": b"hello\n", "LICENSE": b""}
EXPECTED = {
    "model.ckpt": (3, "sha256", SHA_ABC),
    "assets/mhr_model.pt": (6, "sha256", SHA_HELLO),
    "model_config.yaml": (6, "gitblob", BLOB_HELLO),
    "LICENSE": (0, "gitblob", BLOB_EMPTY),
}
INFO = {"README.md": (6, "gitblob", BLOB_HELLO)}
HEAVY = {"torch", "cv2", "numpy", "sam_3d_body"}


class Blocker(importlib.abc.MetaPathFinder):
    """Records and refuses any import of the heavy runtime modules."""

    def __init__(self):
        self.seen = []

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in HEAVY:
            self.seen.append(name)
            raise ImportError(f"blocked by test: {name}")
        return None


class VerifyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="verify-ckpt-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "ckpt"
        for rel, data in FIXTURE.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def check(self):
        return verify_checkpoint.verify(self.root, expected=EXPECTED, info=INFO)

    def test_all_good_passes(self):
        ok, lines = self.check()
        self.assertTrue(ok, lines)
        self.assertEqual(lines[-1], "ALL_MATCH")

    def test_same_size_changed_bytes_fails(self):
        (self.root / "model.ckpt").write_bytes(b"abd")  # same 3 bytes long, other content
        ok, lines = self.check()
        self.assertFalse(ok, lines)
        self.assertTrue(any(l.startswith("MISMATCH model.ckpt") for l in lines), lines)
        self.assertTrue(lines[-1].startswith("FAILED 1 "), lines)

    def test_same_size_changed_small_file_fails(self):
        (self.root / "model_config.yaml").write_bytes(b"hellO\n")
        ok, lines = self.check()
        self.assertFalse(ok, lines)
        self.assertTrue(any(l.startswith("MISMATCH model_config.yaml") for l in lines), lines)

    def test_wrong_size_fails_without_hashing(self):
        (self.root / "assets/mhr_model.pt").write_bytes(b"hello\n!")
        hashed = []
        real = verify_checkpoint.file_id
        verify_checkpoint.file_id = lambda p, kind: hashed.append(Path(p).name) or real(p, kind)
        try:
            ok, lines = self.check()
        finally:
            verify_checkpoint.file_id = real
        self.assertFalse(ok, lines)
        self.assertTrue(any(l.startswith("MISMATCH assets/mhr_model.pt") and "not hashed" in l for l in lines), lines)
        self.assertNotIn("mhr_model.pt", hashed)

    def test_missing_file_fails(self):
        (self.root / "LICENSE").unlink()
        ok, lines = self.check()
        self.assertFalse(ok, lines)
        self.assertIn("MISSING  LICENSE", lines)

    def test_info_file_never_fails(self):
        (self.root / "README.md").write_bytes(b"a mirror's own readme")
        ok, lines = self.check()
        self.assertTrue(ok, lines)
        self.assertTrue(any(l.startswith("INFO-DIFF README.md") for l in lines), lines)

    def test_cli_exit_codes(self):
        prog = ("import sys; sys.path.insert(0, sys.argv[1]); import verify_checkpoint as v; "
                f"v.META = {EXPECTED!r}; v.INFO = {{}}; sys.argv = [sys.argv[0], sys.argv[2]]; v.main()")
        run = lambda: subprocess.run([sys.executable, "-I", "-B", "-c", prog, str(HERE), str(self.root)],
                                     capture_output=True, text=True)
        good = run()
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertIn("ALL_MATCH", good.stdout)
        (self.root / "model.ckpt").write_bytes(b"xyz")
        bad = run()
        self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
        self.assertIn("do not load this checkpoint", bad.stdout)


class RunnerRefusesBeforeLoad(unittest.TestCase):
    """run_sam3db.main(): the checkpoint check runs before torch / cv2 / numpy / sam_3d_body are imported."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="run-sam3db-guard-test-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "ckpt"
        for rel, data in FIXTURE.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        self.saved = dict(verify_checkpoint.META), dict(verify_checkpoint.INFO)
        verify_checkpoint.META.clear()
        verify_checkpoint.META.update(EXPECTED)
        verify_checkpoint.INFO.clear()
        self.addCleanup(self.restore)
        for name in list(sys.modules):
            if name.split(".")[0] in HEAVY:
                del sys.modules[name]
        self.blocker = Blocker()
        sys.meta_path.insert(0, self.blocker)
        self.addCleanup(sys.meta_path.remove, self.blocker)
        import run_sam3db
        self.run_sam3db = run_sam3db

    def restore(self):
        for table, saved in zip((verify_checkpoint.META, verify_checkpoint.INFO), self.saved):
            table.clear()
            table.update(saved)

    def main(self, *extra):
        argv = ["run_sam3db.py", "--input", str(self.tmp / "take.mp4"), "--out", str(self.tmp / "out"),
                "--ckpt-dir", str(self.root), *extra]
        out, err = io.StringIO(), io.StringIO()
        old = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    self.run_sam3db.main()
                    code = 0
                except SystemExit as e:
                    code = e.code
                except ImportError as e:  # the blocker: main got past the check and reached the runtime imports
                    code = f"import:{e}"
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_bad_checkpoint_refused_before_any_heavy_import(self):
        (self.root / "model.ckpt").write_bytes(b"abd")
        code, out, err = self.main()
        self.assertEqual(code, 2, out + err)
        self.assertIn("REFUSED", err)
        self.assertEqual(self.blocker.seen, [], "a heavy module was imported before the refusal")

    def test_each_missing_file_refused_with_exit_2_before_any_heavy_import(self):
        for rel in FIXTURE:  # every file the runner needs; the runner checks some of them before verify() runs
            with self.subTest(missing=rel):
                path = self.root / rel
                path.unlink()
                self.blocker.seen.clear()
                try:
                    for extra in ((), ("--trust-unverified-checkpoint",)) if rel != "LICENSE" else ((),):
                        code, out, err = self.main(*extra)
                        self.assertEqual(code, 2, (extra, out + err))
                        # the runner's own check names the file on stderr; verify() lists it on stdout and refuses
                        self.assertRegex(out + err, r"MISSING.*" + Path(rel).name, (extra, out, err))
                        if rel != "LICENSE":
                            self.assertIn("MISSING checkpoint file", err, (extra, out, err))
                        self.assertEqual(self.blocker.seen, [], "a heavy module was imported before the refusal")
                finally:
                    path.write_bytes(FIXTURE[rel])

    def test_good_checkpoint_reaches_the_runtime(self):
        code, out, err = self.main()
        self.assertTrue(str(code).startswith("import:"), (code, out, err))
        self.assertIn("CHECKPOINT ALL_MATCH", out)
        self.assertTrue(self.blocker.seen, "main never tried to load the runtime")

    def test_trust_flag_skips_loudly(self):
        (self.root / "model.ckpt").write_bytes(b"abd")
        code, out, err = self.main("--trust-unverified-checkpoint")
        self.assertTrue(str(code).startswith("import:"), (code, out, err))
        self.assertIn("NOT verified", err)
        self.assertNotIn("CHECKPOINT ALL_MATCH", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
