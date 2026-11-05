"""Top-down and front views of SAM 3D Body skeletons, several men in one scene.

Shows the depth a side view hides. Each man's 3D keypoints are placed in the shared camera space with his own
pred_cam_t (all men share the model's default lens, so their placement is consistent with each other, but absolute
depth rests on SAM's body-size guess). Camera space: x right, y down, z away from the camera.
  TOP view: looking down; x to the right, z (away from camera) up the panel.
  FRONT view: looking from the right of the picture toward the left; z to the left, height up.
A grid line every 0.5 m. The right-side limbs are drawn thick, the left ones thin.
Needs Meta's sam_3d_body package on the path: set SAM3DB_SRC to your clone (default ./src beside this script).
Usage: python -I -B views3d.py <out.png> --man name=<run dir> [--man ...] --frames 0 28 64 92 [--px 120]
"""
import argparse, os, sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, os.environ.get("SAM3DB_SRC", str(HERE / "src")))
from sam_3d_body.metadata.mhr70 import pose_info  # noqa: E402

ID = {v["name"]: k for k, v in pose_info["keypoint_info"].items()}
BODY = [("left_shoulder", "right_shoulder"), ("left_hip", "right_hip"), ("left_shoulder", "left_hip"),
        ("right_shoulder", "right_hip")]
for s in ("left", "right"):
    BODY += [(f"{s}_shoulder", f"{s}_elbow"), (f"{s}_elbow", f"{s}_wrist"), (f"{s}_hip", f"{s}_knee"),
             (f"{s}_knee", f"{s}_ankle"), (f"{s}_ankle", f"{s}_big_toe")]
COL = [(230, 160, 40), (60, 200, 60), (40, 160, 255), (220, 80, 220)]  # BGR per man


def load(run, f):
    p = Path(run) / "frames" / f"f{f:04d}.npz"
    if not p.exists():
        return None
    d = np.load(p)
    return d["p0_pred_keypoints_3d"] + d["p0_pred_cam_t"][None, :]


def panel(kps_list, names, proj, title, px, size=(520, 420)):
    w, h = size
    img = np.full((h, w, 3), 245, np.uint8)
    pts_all = np.concatenate([proj(k) for k in kps_list if k is not None])
    c = (pts_all.min(0) + pts_all.max(0)) / 2
    to = lambda p: (int(w / 2 + (p[0] - c[0]) * px), int(h / 2 - (p[1] - c[1]) * px))
    for g in np.arange(-5, 5.01, 0.5):  # grid
        a, b = to((c[0] + g, c[1] - 5)), to((c[0] + g, c[1] + 5))
        cv2.line(img, (int(w / 2 + (np.round((c[0] + g) * 2) / 2 - c[0]) * px), 0),
                 (int(w / 2 + (np.round((c[0] + g) * 2) / 2 - c[0]) * px), h), (225, 225, 225), 1)
        cv2.line(img, (0, int(h / 2 - (np.round((c[1] + g) * 2) / 2 - c[1]) * px)),
                 (w, int(h / 2 - (np.round((c[1] + g) * 2) / 2 - c[1]) * px)), (225, 225, 225), 1)
    for m, (k, name) in enumerate(zip(kps_list, names)):
        if k is None:
            continue
        q = proj(k)
        for a, b in BODY:
            cv2.line(img, to(q[ID[a]]), to(q[ID[b]]), COL[m % len(COL)], 3 if a.startswith("right") else 1, cv2.LINE_AA)
        cv2.circle(img, to(q[ID["nose"]]), 4, COL[m % len(COL)], -1, cv2.LINE_AA)
        hip = (q[ID["left_hip"]] + q[ID["right_hip"]]) / 2
        cv2.putText(img, name, (to(hip)[0] + 6, to(hip)[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.45, COL[m % len(COL)], 1, cv2.LINE_AA)
    cv2.putText(img, title, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 40, 40), 1, cv2.LINE_AA)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--man", action="append", required=True)
    ap.add_argument("--frames", type=int, nargs="+", required=True)
    ap.add_argument("--px", type=float, default=120.0, help="pixels per metre")
    a = ap.parse_args()
    men = [(s.split("=", 1)[0], s.split("=", 1)[1]) for s in a.man]
    names = [n for n, _ in men]
    top = lambda k: np.stack([k[:, 0], k[:, 2]], 1)      # x right, z up the panel
    front = lambda k: np.stack([-k[:, 2], -k[:, 1]], 1)  # seen from picture-right: z to the left, height up
    rows = []
    for f in a.frames:
        ks = [load(r, f) for _, r in men]
        rows.append(np.hstack([panel(ks, names, top, f"f{f}  TOP (camera at bottom, grid 0.5 m)", a.px),
                               panel(ks, names, front, f"f{f}  FRONT (camera at right, grid 0.5 m)", a.px)]))
    cv2.imwrite(a.out, np.vstack(rows))
    print("VIEWS", a.out)


if __name__ == "__main__":
    main()
