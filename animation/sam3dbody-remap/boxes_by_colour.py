"""Per-man boxes for a two-man take with NO subject-mask hand-off.

Where the men overlap, one box can grab the other man: cap its edge by hand and check every box on the key-frame sheet
(keyframe_sheet.py --boxes) before running SAM.

The two men differ in colour (here a silver killer and a dark-green victim) on a plain grey background, so:
1. foreground = pixels whose Lab colour is far from the frame's background grey (median of the border);
2. a colour model per man is learned from the early frames where the men stand apart (left / right blob);
3. every frame's foreground pixels are labelled by the colour model (Lab histogram ratio), cleaned by an opening
   (which also drops the thin spear and sword), and each man's box is the bbox of his largest blobs.
Writes the boxes_from_mask.py format ({"frames", "empty", "boxes": {"<i>": [[x0, y0, x1, y1]]}}) per man, plus a
mask mp4 per man for checking.

Usage: python -I -B boxes_by_colour.py <take.mp4> <out dir> [--train 0-12] [--split-x 360] [--pad 0.04]
       names: left man = killer, right man = victim (change with --names)
"""
import argparse, json, os

import cv2
import numpy as np

BINS = 24


def lab_bins(lab):
    q = (lab.astype(np.int32) * BINS) // 256
    return (q[..., 0] * BINS + q[..., 1]) * BINS + q[..., 2]


def fg_mask(im, lab, thr):
    h, w = lab.shape[:2]
    border = np.concatenate([lab[:30].reshape(-1, 3), lab[:, :15].reshape(-1, 3), lab[:, -15:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    d = np.linalg.norm(lab.astype(np.float32) - bg, axis=2)
    m = (d > thr).astype(np.uint8)
    m[:20] = 0  # top strip: never a man
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--train", default="0-12")
    ap.add_argument("--split-x", type=int, default=360)
    ap.add_argument("--pad", type=float, default=0.04)
    ap.add_argument("--thr", type=float, default=14.0)
    ap.add_argument("--open", default="5,7", help="opening size per man (left,right); drops spear/sword")
    ap.add_argument("--grow", type=float, default=0.15, help="tracking: blobs must touch the previous box grown by this")
    ap.add_argument("--vmax", type=float, default=25.0, help="max px a box edge moves per frame (0 = off)")
    ap.add_argument("--minfrac", type=float, default=0.05, help="keep blobs at least this share of the biggest")
    ap.add_argument("--names", default="killer,victim")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    names = a.names.split(",")
    cap = cv2.VideoCapture(a.video)
    frames = []
    while True:
        ok, im = cap.read()
        if not ok:
            break
        frames.append(im)
    cap.release()
    t0, t1 = map(int, a.train.split("-"))
    hist = [np.ones(BINS ** 3), np.ones(BINS ** 3)]
    for i in range(t0, t1 + 1):
        lab = cv2.cvtColor(frames[i], cv2.COLOR_BGR2LAB)
        m = fg_mask(frames[i], lab, a.thr).astype(bool)
        b = lab_bins(lab)
        xs = np.arange(m.shape[1])[None, :].repeat(m.shape[0], 0)
        for k, sel in enumerate([m & (xs < a.split_x), m & (xs >= a.split_x)]):
            hist[k] += np.bincount(b[sel], minlength=BINS ** 3)
    p = [h / h.sum() for h in hist]
    ratio = np.log(p[0]) - np.log(p[1])  # >0: man 0 (left)
    h, w = frames[0].shape[:2]
    out = {n: {} for n in names}
    empty = {n: [] for n in names}
    writers = {n: cv2.VideoWriter(os.path.join(a.out, f"mask-{n}.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 24, (w, h),
                                  False) for n in names}
    opens = [int(v) for v in str(a.open).split(",")]
    opens = opens * 2 if len(opens) == 1 else opens
    prev = [None, None]
    raw = {n: {} for n in names}
    for i, im in enumerate(frames):
        lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB)
        m = fg_mask(im, lab, a.thr).astype(bool)
        r = ratio[lab_bins(lab)]
        r = cv2.GaussianBlur(r.astype(np.float32), (9, 9), 0)  # neighbourhood vote
        for k, n in enumerate(names):
            mk = (m & ((r > 0) if k == 0 else (r <= 0))).astype(np.uint8)
            mk = cv2.morphologyEx(mk, cv2.MORPH_OPEN, np.ones((opens[k], opens[k]), np.uint8))
            cnt, lbl, st, cen = cv2.connectedComponentsWithStats(mk)
            keep = np.zeros_like(mk)
            if cnt > 1:
                # tracking: only blobs that touch the man's previous box, grown by --grow
                ok_ids = list(range(1, cnt))
                if prev[k] is not None:
                    x0, y0, x1, y1 = prev[k]
                    gx, gy = a.grow * (x1 - x0), a.grow * (y1 - y0)
                    bx0, by0, bx1, by1 = x0 - gx, y0 - gy, x1 + gx, y1 + gy
                    ok_ids = [j for j in ok_ids if st[j, 0] < bx1 and st[j, 0] + st[j, 2] > bx0
                              and st[j, 1] < by1 and st[j, 1] + st[j, 3] > by0
                              and bx0 <= cen[j][0] <= bx1]
                else:  # first frame: each man's blobs on his own side of --split-x
                    ok_ids = [j for j in ok_ids if (cen[j][0] < a.split_x) == (k == 0)]
                if ok_ids:
                    big = max(st[j, cv2.CC_STAT_AREA] for j in ok_ids)
                    for j in ok_ids:
                        if st[j, cv2.CC_STAT_AREA] >= a.minfrac * big:
                            keep[lbl == j] = 1
            writers[n].write(keep * 255)
            ys, xs = np.nonzero(keep)
            if len(xs) < 50:
                empty[n].append(i)
                continue
            bb = [float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]
            if prev[k] is not None and a.vmax > 0:  # an edge moves at most --vmax px per frame
                bb = [min(max(v, p - a.vmax), p + a.vmax) for v, p in zip(bb, prev[k])]
            prev[k] = bb
            raw[n][i] = bb
    for n in names:
        # 5-frame median on every box edge drops one-frame spikes
        ids = sorted(raw[n])
        arr = np.array([raw[n][i] for i in ids])
        for t, i in enumerate(ids):
            lo, hi = max(0, t - 2), min(len(ids), t + 3)
            x0, y0, x1, y1 = np.median(arr[lo:hi], axis=0)
            px, py = a.pad * (x1 - x0), a.pad * (y1 - y0)
            out[n][str(i)] = [[round(float(x0 - px), 1), round(float(y0 - py), 1),
                               round(float(x1 + px), 1), round(float(y1 + py), 1)]]
    for n in names:
        writers[n].release()
        path = os.path.join(a.out, f"boxes-{n}.json")
        json.dump({"source": a.video, "method": "boxes_by_colour.py", "train": a.train, "pad": a.pad,
                   "frames": len(frames), "empty": empty[n], "boxes": out[n]}, open(path, "w", encoding="utf-8"),
                  indent=0)
        print(f"BOXES {n} {len(out[n])}/{len(frames)} empty={empty[n][:10]} -> {path}")


if __name__ == "__main__":
    main()
