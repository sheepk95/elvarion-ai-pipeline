"""Find left/right flips in a run_sam3db.py run (check SAM's fit before remapping).

A single view cannot always tell a body seen from the front from one seen from behind; when SAM guesses wrong it
mirrors left and right and turns the body ~180 degrees. This prints, per processed frame, the body's facing angle
(yaw about the vertical, camera space, from shoulders + hips in pred_keypoints_3d) and the jump from the previous
frame, and marks jumps above --jump degrees as FLIP?. Also writes facing.json in the run folder.
Needs Meta's sam_3d_body package on the path: set SAM3DB_SRC to your clone (default ./src beside this script).
Usage: python -I -B facing_scan.py <run dir> [--jump 90]
"""
import argparse, json, os, sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, os.environ.get("SAM3DB_SRC", str(HERE / "src")))
from sam_3d_body.metadata.mhr70 import pose_info  # noqa: E402

ID = {v["name"]: k for k, v in pose_info["keypoint_info"].items()}


def yaw(k):
    lr = (k[ID["left_shoulder"]] - k[ID["right_shoulder"]]) + (k[ID["left_hip"]] - k[ID["right_hip"]])
    up = (k[ID["left_shoulder"]] + k[ID["right_shoulder"]] - k[ID["left_hip"]] - k[ID["right_hip"]]) / 2
    f = np.cross(lr, up)  # forward, up to a fixed sign; only the change between frames matters
    return float(np.degrees(np.arctan2(f[0], f[2])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--jump", type=float, default=90.0)
    a = ap.parse_args()
    rows, prev = [], None
    for p in sorted((Path(a.run) / "frames").glob("f*.npz")):
        d = np.load(p)
        if int(d["n_people"]) < 1:
            continue
        y = yaw(d["p0_pred_keypoints_3d"])
        dj = None if prev is None else (y - prev + 180) % 360 - 180
        rows.append({"frame": int(p.stem[1:]), "yaw": round(y, 1), "jump": None if dj is None else round(dj, 1),
                     "flip": dj is not None and abs(dj) > a.jump})
        prev = y
    (Path(a.run) / "facing.json").write_text(json.dumps(rows, indent=0), encoding="utf-8")
    print(" ".join(f"f{r['frame']}:{r['yaw']:+.0f}{'!' if r['flip'] else ''}" for r in rows))
    print("FLIPS", [r["frame"] for r in rows if r["flip"]])


if __name__ == "__main__":
    main()
