"""Labelled key-frame sheet of a take (step 1 of the remap: look at the take before running SAM).

Usage: python -I -B keyframe_sheet.py <video> <out.png> "<frame>:<label>" ["<frame>:<label>" ...] [--cols 4] [--tile 352]
"""
import argparse

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("frames", nargs="+")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--tile", type=int, default=352)
    ap.add_argument("--boxes", action="append", default=[], help="name=boxes.json from boxes_from_mask.py (repeatable)")
    a = ap.parse_args()
    import json
    colours = [(0, 200, 255), (255, 200, 0), (120, 255, 120), (255, 120, 255)]  # BGR: orange, cyan, green, pink
    box_sets = [(s.split("=", 1)[0], json.load(open(s.split("=", 1)[1], encoding="utf-8"))["boxes"]) for s in a.boxes]
    want = [(int(s.split(":", 1)[0]), s.split(":", 1)[1] if ":" in s else "") for s in a.frames]
    cap = cv2.VideoCapture(a.video)
    tiles = []
    for idx, label in want:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, img = cap.read()
        if not ok:
            img = np.zeros((a.tile, a.tile, 3), np.uint8)
        sx, sy = a.tile / img.shape[1], a.tile / img.shape[0]
        img = cv2.resize(img, (a.tile, a.tile), interpolation=cv2.INTER_AREA)
        for k, (name, bs) in enumerate(box_sets):
            col = colours[k % len(colours)]
            for b in bs.get(str(idx), []):
                p0, p1 = (int(b[0] * sx), int(b[1] * sy)), (int(b[2] * sx), int(b[3] * sy))
                cv2.rectangle(img, p0, p1, col, 2)
                cv2.putText(img, name, (p0[0] + 2, p1[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1, cv2.LINE_AA)
        cv2.rectangle(img, (0, 0), (a.tile, 26), (30, 30, 30), -1)
        cv2.putText(img, f"f{idx}  {label}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(img)
    cap.release()
    while len(tiles) % a.cols:
        tiles.append(np.full_like(tiles[0], 40))
    rows = [np.hstack(tiles[i:i + a.cols]) for i in range(0, len(tiles), a.cols)]
    cv2.imwrite(a.out, np.vstack(rows))
    print("SHEET", a.out, len(want), "frames")


if __name__ == "__main__":
    main()
