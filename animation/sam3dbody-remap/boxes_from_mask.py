"""Per-frame person boxes from a subject mask video.

A fit hand-off can keep the subject's mask as a video (here `subject-only-mask.mp4`): a square crop of the full take
(`crop.json` "crop" = [x0, y0, x1, y1] in full-frame pixels, may run past the frame edge), resized to "size" px.
This maps each mask frame back to full-frame pixels and writes {"<frame index>": [[x0, y0, x1, y1]]} for
run_sam3db.py --boxes-json, so SAM 3D Body looks at that one man even when two men overlap.

Usage: python -I -B boxes_from_mask.py <subject-only-mask.mp4> <crop.json> <out boxes.json> [--pad 0.04] [--thr 127]
"""
import argparse, json

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mask")
    ap.add_argument("crop_json")
    ap.add_argument("out")
    ap.add_argument("--pad", type=float, default=0.04)
    ap.add_argument("--thr", type=int, default=127)
    a = ap.parse_args()
    cj = json.load(open(a.crop_json, encoding="utf-8"))
    cx0, cy0, cx1, cy1 = cj["crop"]
    cap = cv2.VideoCapture(a.mask)
    boxes, i, empty = {}, 0, []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        g = img[..., 0] if img.ndim == 3 else img
        sy, sx = (cy1 - cy0) / g.shape[0], (cx1 - cx0) / g.shape[1]
        ys, xs = np.nonzero(g > a.thr)
        if len(xs) < 30:
            empty.append(i)
        else:
            x0, x1 = cx0 + xs.min() * sx, cx0 + (xs.max() + 1) * sx
            y0, y1 = cy0 + ys.min() * sy, cy0 + (ys.max() + 1) * sy
            px, py = a.pad * (x1 - x0), a.pad * (y1 - y0)
            boxes[str(i)] = [[round(x0 - px, 1), round(y0 - py, 1), round(x1 + px, 1), round(y1 + py, 1)]]
        i += 1
    cap.release()
    json.dump({"source_mask": a.mask, "crop": cj["crop"], "pad": a.pad, "frames": i, "empty": empty,
               "boxes": boxes}, open(a.out, "w", encoding="utf-8"), indent=0)
    print(f"BOXES {len(boxes)}/{i} frames, empty={empty[:10]}{'...' if len(empty) > 10 else ''}  -> {a.out}")


if __name__ == "__main__":
    main()
