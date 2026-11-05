"""Check the SAM 3D Body ViT-H checkpoint files against Meta's own published ids.

model.ckpt and mhr_model.pt are pickle / TorchScript files that can run code when loaded, so nothing should load them
unless every file below matches what Meta's gated repo facebook/sam-3d-body-vith publishes (read from the Hugging Face
API, repo commit f7f4ba4f67739e297f291639afb7c59041745367): sha256 for the two big files, git blob id for the small
ones. Check again against the live API if Meta has published a new revision: these ids are a snapshot.

Usage: python -I -B verify_checkpoint.py [checkpoint folder]   -> prints one line per file, exit 0 only if all match.
The folder defaults to $SAM3DB_CKPT_DIR, else ./checkpoints/sam-3d-body-vith beside this script.
"""
import hashlib, os, sys
from pathlib import Path

META = {  # path: (bytes, kind, id)
    "model.ckpt": (1691205237, "sha256", "3b1cb897f4bbd977bf81cbb0b30780a9582681ac642ee112865790ceb4d66056"),
    "assets/mhr_model.pt": (696110248, "sha256", "352e271a6c42729c68554ceaea0c955e866970160c31e35506d782dc0f7377bc"),
    "model_config.yaml": (1486, "gitblob", "47c518dfaca26dd28ab3bf94f9f76a9bc7763d50"),
    "LICENSE": (8204, "gitblob", "e58d758cc3d92e6d1a57b52f7e4d203d02a67e98"),
}
# Text only, never loaded: reported, but a difference does not fail the check (a mirror's README can be its own).
INFO = {"README.md": (5760, "gitblob", "910e03a400fa67497361cefc47f70e9e958cc176")}


def file_id(p, kind):
    if kind == "gitblob":
        data = p.read_bytes()
        return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    here = Path(__file__).resolve().parent
    root = Path(sys.argv[1] if len(sys.argv) > 1 else
                os.environ.get("SAM3DB_CKPT_DIR", str(here / "checkpoints" / "sam-3d-body-vith")))
    bad = 0
    for rel, (size, kind, want) in META.items():
        p = root / rel
        if not p.is_file():
            print(f"MISSING  {rel}")
            bad += 1
            continue
        n = p.stat().st_size
        got = file_id(p, kind)
        ok = n == size and got == want
        bad += not ok
        print(f"{'OK      ' if ok else 'MISMATCH'} {rel}  {n} bytes  {kind} {got}" + ("" if ok else f"  (Meta: {size} bytes, {want})"))
    for rel, (size, kind, want) in INFO.items():
        p = root / rel
        if p.is_file():
            got = file_id(p, kind)
            print(f"{'INFO-OK ' if got == want else 'INFO-DIFF'} {rel}  {p.stat().st_size} bytes  (text only, not loaded)")
    print("ALL_MATCH" if bad == 0 else f"FAILED {bad} file(s): do not load this checkpoint")
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
