"""Close-up sheet of run_sam3db.py overlays around one man (check SAM's fit before remapping).

Crops each chosen overlay frame to a square around that man's box (from boxes_from_mask.py), so the skeleton is big
enough to judge. Usage:
  python -I -B overlay_sheet.py <run dir> <boxes.json> <out.png> "<frame>:<label>" ... [--cols 4] [--tile 352] [--grow 1.3]
"""
import argparse, json
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("boxes")
    ap.add_argument("out")
    ap.add_argument("frames", nargs="+")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--tile", type=int, default=352)
    ap.add_argument("--grow", type=float, default=1.3)
    a = ap.parse_args()
    boxes = json.load(open(a.boxes, encoding="utf-8"))["boxes"]
    tiles = []
    for s in a.frames:
        idx, label = (int(s.split(":", 1)[0]), s.split(":", 1)[1] if ":" in s else "")
        img = cv2.imread(str(Path(a.run) / "overlay" / f"f{idx:04d}.jpg"))
        if img is None:
            tiles.append(np.full((a.tile, a.tile, 3), 40, np.uint8))
            continue
        x0, y0, x1, y1 = boxes[str(idx)][0]
        cx, cy, half = (x0 + x1) / 2, (y0 + y1) / 2, a.grow * max(x1 - x0, y1 - y0) / 2
        pad = int(half) + 2
        big = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(90, 90, 90))
        c = big[int(cy - half) + pad:int(cy + half) + pad, int(cx - half) + pad:int(cx + half) + pad]
        t = cv2.resize(c, (a.tile, a.tile), interpolation=cv2.INTER_AREA)
        cv2.rectangle(t, (0, 0), (a.tile, 24), (30, 30, 30), -1)
        cv2.putText(t, f"f{idx}  {label}", (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(t)
    while len(tiles) % a.cols:
        tiles.append(np.full_like(tiles[0], 40))
    cv2.imwrite(a.out, np.vstack([np.hstack(tiles[i:i + a.cols]) for i in range(0, len(tiles), a.cols)]))
    print("SHEET", a.out)


if __name__ == "__main__":
    main()
