"""SAM 3D Body on a reference video or picture, one frame at a time.

Runs Meta's SAM 3D Body (ViT-H checkpoint; you fetch Meta's code and weights yourself, see README.md) one frame at a
time and saves, per frame, the MHR skeleton (127 joint positions + global rotations), the 70 body keypoints in 2D and
3D, the camera translation and the raw MHR parameters. Also writes an overlay of the 2D keypoints on each processed
frame so a person can check the fit.

Our AI-video takes are plain grey backgrounds, so the person box comes from background subtraction (no person
detector). One person per box: --boxes auto (one box around all foreground) or --boxes "x0,y0,x1,y1;x0,y0,x1,y1"
(one per man).

Environment (all optional):
  SAM3DB_SRC         folder holding your clone of facebookresearch/sam-3d-body (default: ./src beside this script)
  SAM3DB_CKPT_DIR    checkpoint folder (default: ./checkpoints/sam-3d-body-vith beside this script); --ckpt-dir wins
  SAM3DB_SRC_COMMIT  the commit of your clone; only recorded in run.json (the kit was tried on b5c765a0d89d)

Usage (the venv's python; book the GPU first if you share it, see gpu-lease/ in this repo):
  python -B run_sam3db.py --input <video.mp4 | picture.png> --out <folder> [--every 1] [--max-frames N]
      [--focal-mult 1.0] [--boxes auto|"x0,y0,x1,y1;..."] [--boxes-json boxes.json] [--inference full|body]
      [--ckpt-dir <folder>]
Writes <out>/frames/f<NNNN>.npz, <out>/overlay/f<NNNN>.jpg, <out>/run.json (timings, VRAM peaks, settings).
--boxes-json: per-frame boxes from boxes_from_mask.py or boxes_by_colour.py ({"boxes": {"<video f>": [[x0, y0, x1,
y1]]}}); frames not in it are skipped. Exits 1 when that file holds no boxes (before the model loads, so no GPU time)
and when no frame was processed (after run.json is written, for the diagnosis).
--focal-mult scales the model's default focal length (image diagonal); our frames are orthographic renders, so a
value above 1 (narrower lens) is closer to the truth, but the model was trained on ordinary lenses: compare both.
"""
import argparse, json, os, sys, time
from pathlib import Path

import cv2
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, os.environ.get("SAM3DB_SRC", str(HERE / "src")))
from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body  # noqa: E402
from sam_3d_body.metadata.mhr70 import pose_info  # noqa: E402

NAME2ID = {v["name"]: k for k, v in pose_info["keypoint_info"].items()}
LINKS = [(NAME2ID[a], NAME2ID[b], tuple(int(c) for c in d["color"][::-1]))  # RGB -> BGR for cv2
         for d in pose_info["skeleton_info"].values() for a, b in [d["link"]] if a in NAME2ID and b in NAME2ID]


def frames(path, every, max_frames):
    p = str(path)
    if p.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            sys.exit(f"cannot read {p}")
        yield 0, img
        return
    cap = cv2.VideoCapture(p)
    if not cap.isOpened():
        sys.exit(f"cannot open {p}")
    i = n = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if i % every == 0:
            yield i, img
            n += 1
            if max_frames and n >= max_frames:
                break
        i += 1
    cap.release()


def auto_box(bgr, pad=0.06, thr=28):
    """Box around everything that differs from the plain background (median of the 4 px border)."""
    h, w = bgr.shape[:2]
    border = np.concatenate([bgr[:4].reshape(-1, 3), bgr[-4:].reshape(-1, 3),
                             bgr[:, :4].reshape(-1, 3), bgr[:, -4:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    fg = (np.abs(bgr.astype(np.int16) - bg.astype(np.int16)).sum(axis=2) > thr).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    ys, xs = np.nonzero(fg)
    if len(xs) < 50:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    px, py = pad * (x1 - x0 + 1), pad * (y1 - y0 + 1)
    return np.array([max(0, x0 - px), max(0, y0 - py), min(w - 1, x1 + px), min(h - 1, y1 + py)], np.float32)


def overlay(bgr, results):
    out = bgr.copy()
    for r in results:
        k = r["pred_keypoints_2d"]
        for a, b, col in LINKS:
            cv2.line(out, tuple(int(v) for v in k[a][:2]), tuple(int(v) for v in k[b][:2]), col, 2, cv2.LINE_AA)
        for j in range(min(len(k), 21)):  # body + feet; the hand points crowd the picture
            cv2.circle(out, (int(k[j][0]), int(k[j][1])), 3, (255, 255, 255), -1, cv2.LINE_AA)
        x0, y0, x1, y1 = (int(v) for v in r["bbox"])
        cv2.rectangle(out, (x0, y0), (x1, y1), (0, 200, 255), 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--focal-mult", type=float, default=1.0)
    ap.add_argument("--boxes", default="auto")
    ap.add_argument("--boxes-json", default="", help="per-frame boxes from boxes_from_mask.py; frames not in it are skipped")
    ap.add_argument("--inference", default="full", choices=["full", "body"])
    ap.add_argument("--ckpt-dir", default=os.environ.get("SAM3DB_CKPT_DIR", str(HERE / "checkpoints" / "sam-3d-body-vith")))
    a = ap.parse_args()
    ck = Path(a.ckpt_dir)
    for f in ("model.ckpt", "model_config.yaml", "assets/mhr_model.pt"):
        if not (ck / f).exists():
            sys.exit(f"MISSING checkpoint file {ck / f} (gated Hugging Face repo facebook/sam-3d-body-vith)")
    # Read the boxes before the model loads: a bad --boxes or an empty --boxes-json stops
    # here, not after a model load under the GPU lease.
    fixed = None if a.boxes == "auto" else np.array(
        [[float(v) for v in b.split(",")] for b in a.boxes.split(";")], np.float32)
    per_frame = json.load(open(a.boxes_json, encoding="utf-8"))["boxes"] if a.boxes_json else None
    if per_frame is not None and not per_frame:
        sys.exit(f"run_sam3db.py: {a.boxes_json} has no boxes: nothing to run (did boxes_from_mask.py or "
                 "boxes_by_colour.py find no man?)")
    out = Path(a.out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    (out / "overlay").mkdir(parents=True, exist_ok=True)

    torch.cuda.init()
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    model, cfg = load_sam_3d_body(str(ck / "model.ckpt"), device="cuda", mhr_path=str(ck / "assets" / "mhr_model.pt"))
    est = SAM3DBodyEstimator(sam_3d_body_model=model, model_cfg=cfg)
    t_load = time.time() - t0

    per, done = [], 0
    for idx, bgr in frames(a.input, a.every, a.max_frames):
        h, w = bgr.shape[:2]
        if per_frame is not None:
            if str(idx) not in per_frame:
                print(f"SKIP f{idx:04d}: no box in {a.boxes_json}")
                continue
            box = np.array(per_frame[str(idx)], np.float32)
            box[:, [0, 2]] = box[:, [0, 2]].clip(0, w - 1)
            box[:, [1, 3]] = box[:, [1, 3]].clip(0, h - 1)
        else:
            box = fixed if fixed is not None else auto_box(bgr)
        if box is None:
            print(f"SKIP f{idx:04d}: no person found")
            continue
        cam = None
        if a.focal_mult != 1.0:
            f = a.focal_mult * (h * h + w * w) ** 0.5
            cam = torch.tensor([[[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1]]], dtype=torch.float32)
        t1 = time.time()
        res = est.process_one_image(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), bboxes=box.reshape(-1, 4), cam_int=cam,
                                    inference_type=a.inference)
        dt = time.time() - t1
        keep = ("bbox", "focal_length", "pred_keypoints_2d", "pred_keypoints_3d", "pred_cam_t", "global_rot",
                "body_pose_params", "hand_pose_params", "scale_params", "shape_params", "pred_joint_coords",
                "pred_global_rots", "mhr_model_params")
        np.savez_compressed(out / "frames" / f"f{idx:04d}.npz", n_people=len(res),
                            **{f"p{i}_{k}": np.asarray(r[k]) for i, r in enumerate(res) for k in keep})
        cv2.imwrite(str(out / "overlay" / f"f{idx:04d}.jpg"), overlay(bgr, res))
        per.append(round(dt, 3))
        done += 1
        print(f"FRAME f{idx:04d} people={len(res)} secs={dt:.2f}", flush=True)

    rep = {"input": a.input, "frames_done": done, "every": a.every, "focal_mult": a.focal_mult,
           "boxes": a.boxes_json or a.boxes,
           "inference": a.inference, "ckpt_dir": str(ck), "load_secs": round(t_load, 1),
           "secs_per_frame": per, "mean_secs": round(float(np.mean(per)), 3) if per else None,
           "peak_alloc_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
           "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / 1e9, 2),
           "torch": torch.__version__, "source_commit": os.environ.get("SAM3DB_SRC_COMMIT", "unknown")}
    (out / "run.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("RUN_DONE", json.dumps({k: rep[k] for k in ("frames_done", "load_secs", "mean_secs", "peak_reserved_gb")}))
    if done == 0:  # a run with no frame is a failure, not a silent zero
        sys.exit("run_sam3db.py: 0 frames processed (no box on any frame read: check --boxes-json against --every "
                 "and --max-frames, or --boxes auto found no person)")


if __name__ == "__main__":
    main()
