"""Frame-by-frame sheets and clips from render_views.py output: the take, our character laid over the take, the other
angles and hand close-ups, one row per frame.

render_views.py (not in this kit: it is Blender code written around one rig) is expected to have written, into the
render folder, PNGs named <view>_<video frame:04d>.png for the views video, top, left, right, back (the "video" PNG is
RGBA: our render from the take's own camera), plus a views-info.json. See README.md for the shape of that file.

Columns (--cols, any order; or a set name):
  video = the take; over = our video-camera render laid over the take (55%); ours = that render alone on grey;
  top / left / right / back = those renders;
  zl1 / zr1 / zl2 / zr2 ... = a close-up on man N's left / right hand (with its shield or weapon): two tiles, the take
  and ours over the take, the same pixels. The box is the same size all clip long and follows the hand.
  Sets: body = video,over,top,left,right,back (the default); close = zl and zr for every man in views-info.json.
Each video/over tile is cropped once to the box of the take's foreground and our render over the whole clip.
Labels sit INSIDE each tile; the over tile also shows IoU = how much of the take's outline our outline covers, as
overlap / union (a sudden drop marks a frame where the fit broke). Marked renders get a legend bar on each sheet.
Writes: <out>/sheet_v<first>-v<last>.png (--rows frames each: go through EVERY sheet), <out>/rows/row_v<NNN>.png,
<out>/iou.json, and <out>/<tag>-muted.mp4 at the take's speed and <tag>-half-muted.mp4 at half speed (no audio).
Needs ffmpeg on the PATH for the clips.

python -I -B view_sheets.py <take.mp4> <render dir> <out dir> [--cols body|close|video,over,...] [--rows 4]
        [--tile 300] [--every 1] [--tag views] [--fps <take fps>] [--bg-skip-top 40] [--zoom 1.0]
Use the venv python (cv2). Video frame numbers: 0 = the take's first frame.
"""
import json, os, subprocess, sys
import cv2
import numpy as np

a = sys.argv[1:]
if len(a) < 3:
    raise SystemExit(__doc__)
take, ren, out = a[0], a[1], a[2]
opt = {"--cols": "body", "--rows": "4", "--tile": "300", "--every": "1", "--tag": "views", "--fps": "", "--bg-skip-top": "40",
       "--zoom": "1.0"}
for k in range(3, len(a), 2):
    if a[k] not in opt or k + 1 >= len(a):
        raise SystemExit(f"view_sheets.py: unknown option or missing value: {a[k]}")
    opt[a[k]] = a[k + 1]
info_p = os.path.join(ren, "views-info.json")
info = json.load(open(info_p)) if os.path.exists(info_p) else {}
nmen = len(info.get("rigs", [])) or 1
cols = {"body": "video,over,top,left,right,back",
        "close": ",".join(f"z{s}{i + 1}" for i in range(nmen) for s in "lr")}.get(opt["--cols"], opt["--cols"]).split(",")
per, TH, every, skip_top = int(opt["--rows"]), int(opt["--tile"]), int(opt["--every"]), int(opt["--bg-skip-top"])
os.makedirs(os.path.join(out, "rows"), exist_ok=True)
cap = cv2.VideoCapture(take); vid = {}; i = 0
take_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
while True:
    ok, fr = cap.read()
    if not ok:
        break
    if i % every == 0:
        vid[i] = fr
    i += 1
keys = [f for f in sorted(vid) if any(os.path.exists(os.path.join(ren, f"{c}_{f:04d}.png")) for c in ("video", "top", "left", "right", "back"))]
if not keys:
    raise SystemExit("view_sheets.py: no render matches a take frame (names <view>_<video frame:04d>.png)")
H, W = vid[keys[0]].shape[:2]


def lab(t, s):
    t = t.copy(); cv2.rectangle(t, (0, 0), (t.shape[1], 24), (25, 25, 25), -1)
    cv2.putText(t, s, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA); return t


def read(v, f):
    p = os.path.join(ren, f"{v}_{f:04d}.png")
    im = cv2.imread(p, cv2.IMREAD_UNCHANGED) if os.path.exists(p) else None
    if im is not None and v == "video" and im.shape[:2] != (H, W):
        im = cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA)
    return im


def fg_mask(v):  # the take's foreground: away from the flat grey background (median of the frame's lower corners)
    bg = np.median(np.concatenate([v[-20:, :20].reshape(-1, 3), v[-20:, -20:].reshape(-1, 3)]), 0)
    m = np.abs(v.astype(int) - bg).max(axis=2) > 18
    m[:skip_top] = False
    return m


def box_of(m, minpix=3):
    rows, cs = np.nonzero(m.sum(1) >= minpix)[0], np.nonzero(m.sum(0) >= minpix)[0]
    return (cs.min(), rows.min(), cs.max(), rows.max()) if len(rows) and len(cs) else None


# one crop for the video-camera columns over the whole clip: the take's foreground plus our render
x0, y0, x1, y1 = W, H, 0, 0
iou = {}
for f in keys:
    v = vid[f]; dv = fg_mask(v); m = read("video", f)
    mm = (m[:, :, 3] > 25) if m is not None and m.shape[2] == 4 else np.zeros(dv.shape, bool)
    mm[:skip_top] = False
    if m is not None:
        u = (dv | mm).sum(); iou[f] = round(float((dv & mm).sum()) / u, 3) if u else 0.0
    b = box_of(dv | mm)
    if b:
        x0, y0, x1, y1 = min(x0, b[0]), min(y0, b[1]), max(x1, b[2]), max(y1, b[3])
if x1 <= x0:
    x0, y0, x1, y1 = 0, 0, W - 1, H - 1
x0, y0 = max(0, x0 - 20), max(0, y0 - 20); x1, y1 = min(W, x1 + 20), min(H, y1 + 20)

# close-up boxes: per man and hand, a fixed size (2.4 x the longest projected forearm, at least 180 px, x --zoom
# smaller), centred on the hand moved a third of the way to that hand's prop, smoothed over 5 frames
pts = info.get("points", {})
zbox = {}
for c in cols:
    if not c.startswith("z"):
        continue
    s, man = c[1], int(c[2:]) - 1
    hand, elbow = f"hand.{s}", f"forearm_stretch.{s}"
    pname = next((k for k, p in info.get("props", {}).items() if p.get("rig") == man and p.get("side") == s), None)
    cen, flen = {}, [0.0]
    for f in keys:
        q = pts.get(str(f), [{}] * nmen)[man] if man < len(pts.get(str(f), [])) else {}
        h, e = q.get(hand), q.get(elbow)
        if not h:
            continue
        h = np.array(h); p = q.get("prop:" + pname) if pname else None
        cen[f] = h + (np.array(p) - h) * (1 / 3) if p else h
        if e:
            flen.append(float(np.linalg.norm(h - np.array(e))))
    side = int(max(180, 2.4 * max(flen)) / float(opt["--zoom"]))
    sm = {}
    fs = sorted(cen)
    for j, f in enumerate(fs):
        win = [cen[g] for g in fs[max(0, j - 2):j + 3]]
        sm[f] = np.mean(win, 0)
    zbox[c] = (side, sm, pname)


def zcrop(im, c, f):
    side, sm, _ = zbox[c]
    if f not in sm:
        return None
    cx, cy = sm[f]; h = side // 2
    xa, ya = int(min(max(cx - h, 0), W - side)), int(min(max(cy - h, 0), H - side))
    return im[max(ya, 0):max(ya, 0) + side, max(xa, 0):max(xa, 0) + side]


def fit(im):
    return cv2.resize(im, (max(1, int(im.shape[1] * TH / im.shape[0])), TH), interpolation=cv2.INTER_AREA)


rows = []
for f in keys:
    v = vid[f]; m = read("video", f); tiles = []
    al = (m[:, :, 3:4].astype(float) / 255.0) if m is not None and m.shape[2] == 4 else None
    over = ((v * (1 - 0.55 * al) + m[:, :, :3] * 0.55 * al).astype(np.uint8)) if al is not None else None
    for c in cols:
        if c == "video":
            tiles.append(lab(fit(v[y0:y1, x0:x1]), f"video f{f}"))
        elif c == "over" and over is not None:
            tiles.append(lab(fit(over[y0:y1, x0:x1]), f"ours over the video  IoU {iou.get(f, 0):.2f}"))
        elif c == "ours" and al is not None:
            im = (np.full_like(v, 155) * (1 - al) + m[:, :, :3] * al).astype(np.uint8)
            tiles.append(lab(fit(im[y0:y1, x0:x1]), "ours (video camera)"))
        elif c.startswith("z") and c in zbox:
            cv_, co_ = zcrop(v, c, f), zcrop(over, c, f) if over is not None else None
            nm = f"m{c[2:]} {'left' if c[1] == 'l' else 'right'} hand"
            if cv_ is not None and cv_.size:
                tiles.append(lab(fit(cv_), f"{nm} video f{f}"))
            if co_ is not None and co_.size:
                tiles.append(lab(fit(co_), f"{nm} ours over"))
        elif c in ("top", "left", "right", "back"):
            im = read(c, f)
            if im is not None:
                tiles.append(lab(fit(im[:, :, :3]), f"{c} f{f}"))
    if not tiles:
        continue
    row = np.hstack([np.pad(t, ((0, 0), (0, 4), (0, 0)), constant_values=20) for t in tiles])
    cv2.imwrite(os.path.join(out, "rows", f"row_v{f:03d}.png"), row); rows.append((f, row))
if not rows:
    raise SystemExit("view_sheets.py: no tiles (check --cols and that render_views.py made the views asked for)")
legend = info.get("legend") if info.get("look") == "marked" else None
for s in range(0, len(rows), per):
    part = rows[s:s + per]; w = max(r.shape[1] for _, r in part)
    sheet = np.vstack([np.pad(r, ((0, 4), (0, w - r.shape[1]), (0, 0)), constant_values=20) for _, r in part])
    if legend:
        bar = np.full((26, w, 3), 25, np.uint8)
        cv2.putText(bar, legend, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
        sheet = np.vstack([sheet, bar])
    cv2.imwrite(os.path.join(out, f"sheet_v{part[0][0]:03d}-v{part[-1][0]:03d}.png"), sheet)
if iou:
    vals = sorted(iou.items(), key=lambda kv: kv[1])
    json.dump({"iou": {str(k): v for k, v in sorted(iou.items())}, "mean": round(float(np.mean(list(iou.values()))), 3),
               "lowest": [[k, v] for k, v in vals[:8]]}, open(os.path.join(out, "iou.json"), "w"), indent=1)
w = max(r.shape[1] for _, r in rows); w += w % 2; h = TH + (TH % 2)
fps = float(opt["--fps"] or take_fps) / every
for name, rate in ((f"{opt['--tag']}-muted.mp4", fps), (f"{opt['--tag']}-half-muted.mp4", fps / 2)):
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(rate),
                          "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
                          os.path.join(out, name)], stdin=subprocess.PIPE)
    for _, r in rows:
        fr = np.full((h, w, 3), 20, np.uint8); fr[:r.shape[0], :r.shape[1]] = r[:h, :w]; p.stdin.write(fr.tobytes())
    p.stdin.close(); p.wait()
print("VIEW_SHEETS_DONE", out, "rows", len(rows), "sheets", (len(rows) + per - 1) // per,
      ("IoU mean %.2f, lowest %s" % (np.mean(list(iou.values())), sorted(iou.items(), key=lambda kv: kv[1])[:5])) if iou else "")
