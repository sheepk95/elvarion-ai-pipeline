"""SAM 3D Body run -> clean body-skeleton motion for a Blender source armature.

Example code: it feeds build_source_blender.py (needs Blender and your own rig, see README.md). What it does, per man:
1. Re-runs Meta's MHR body model (assets/mhr_model.pt, CPU) on every saved frame with ONE body shape and ONE set of
   proportions (the per-frame medians), so bone lengths stay constant; checks first that the saved frame reproduces.
2. Keeps the ~25 body joints the remap needs (BODY below), parented to their nearest kept ancestor.
3. Fills dropped frames (--drop, slerp across), smooths local rotations with a 1-2-1 filter except inside --keep
   windows (hits), and keeps or flattens the depth of the root path (--flatten-depth).
4. Writes <out>.npz for build_source_blender.py: names, parents, rest heads + rest rotations, per-frame global
   rotations and root positions, all in BLENDER axes (X right in the picture, Y away from the camera, Z up), metres.

Environment: SAM3DB_CKPT_DIR = the checkpoint folder holding assets/mhr_model.pt (default ./checkpoints/sam-3d-body-vith
beside the parent kit scripts). Run it with the SAM venv's python (torch, roma, numpy).
Frames: SAM frame files fNNNN are video frames; Blender frame = video frame + 1 at 24 fps.
MHR facts (read from Meta's source): pred_joint_coords are camera axes = MHR axes with y, z negated; the joint
rotations are in MHR axes (y up, z toward the camera) and NOT negated; MHR returns centimetres.
Usage: python -I -B sam_to_source.py <run dir> <out.npz> [--drop 24 26] [--keep 62-66 76-80] [--flatten-depth]
       [--hands] [--spike 25 --arm-smooth 3 --arm-joints clavicle,uparm,lowarm,wrist,fingers --hand-world 3]
The hand options default off. The values shown steadied one test take's held prop from 7.5 to 1.5 deg per key.
--keep-arms also keeps the arms sharp inside the --keep windows (no flick removal, wrist smoothing or hand-world
passes there), for takes whose hit is an arm move such as a swing or strike; off by default, and with it off the output is
byte-identical to the version before it.
--keep-arms-sides r limits --keep-arms to one side (default l,r = as before).
"""
import argparse, glob, json, os, sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
CKPT = Path(os.environ.get("SAM3DB_CKPT_DIR", str(HERE.parent / "checkpoints" / "sam-3d-body-vith")))
MHR_PT = CKPT / "assets" / "mhr_model.pt"
BODY = ["root", "c_spine0", "c_spine1", "c_spine2", "c_spine3", "c_neck", "c_head",
        "l_clavicle", "l_uparm", "l_lowarm", "l_wrist", "r_clavicle", "r_uparm", "r_lowarm", "r_wrist",
        "l_upleg", "l_lowleg", "l_foot", "l_ball", "r_upleg", "r_lowleg", "r_foot", "r_ball"]
M = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)  # MHR axes (x, y up, z to camera) -> Blender (X, Y away, Z up)
FLIP = np.diag([1.0, -1.0, -1.0])                         # camera axes <-> MHR axes


def quat(R):  # rotation matrix -> unit quaternion (w, x, y, z)
    import roma
    q = roma.rotmat_to_unitquat(torch.as_tensor(R, dtype=torch.float64)).numpy()  # (x, y, z, w)
    return np.concatenate([q[..., 3:], q[..., :3]], -1)


def rotm(q):
    import roma
    return roma.unitquat_to_rotmat(torch.as_tensor(np.concatenate([q[..., 1:], q[..., :1]], -1))).numpy()


def slerp(a, b, t):
    if np.dot(a, b) < 0:
        b = -b
    d = np.clip(np.dot(a, b), -1, 1)
    if d > 0.9995:
        r = a + t * (b - a)
        return r / np.linalg.norm(r)
    th = np.arccos(d)
    return (np.sin((1 - t) * th) * a + np.sin(t * th) * b) / np.sin(th)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("out")
    ap.add_argument("--drop", type=int, nargs="*", default=[], help="video frames to replace by slerp")
    ap.add_argument("--keep", nargs="*", default=[], help="video-frame windows a-b left unsmoothed (hits)")
    ap.add_argument("--flatten-depth", action="store_true", help="hold the root's distance from camera constant")
    ap.add_argument("--hands", action="store_true", help="also keep the 15 finger joints per hand (thumb/index/"
                    "middle/ring/pinky 1-3), so the remap can map SAM's own fingers")
    ap.add_argument("--spike", type=float, default=0.0, help="arm joints (forearm, wrist, fingers): replace a one-key "
                    "flick bigger than this many degrees, whose neighbours agree, by their halfway turn (0 = off)")
    ap.add_argument("--arm-smooth", type=int, default=0, help="extra 1-2-1 passes on the --arm-joints; wrist "
                    "and fingers are smoothed through the hit windows too (orientation only), the others are not")
    ap.add_argument("--arm-joints", default="lowarm,wrist,fingers", help="which arm joints --spike and --arm-smooth "
                    "touch: any of clavicle,uparm,lowarm,wrist,fingers")
    ap.add_argument("--hand-world", type=int, default=0, help="1-2-1 passes on each hand's WORLD turn after everything "
                    "else (moves no joint; a held prop follows it); fingers ride the smoothed hand")
    ap.add_argument("--keep-arms", action="store_true", help="inside the "
                    "--keep windows also skip --spike, the wrist/finger --arm-smooth passes and --hand-world, so an "
                    "arm hit (a swing or strike) stays sharp. Off by default: the output is then byte-identical to before")
    ap.add_argument("--keep-arms-sides", default="l,r", help="sides --keep-arms "
                    "applies to, e.g. r = keep the striking arm sharp but smooth the other arm SAM misreads in a blurred hit frame")
    a = ap.parse_args()
    global BODY
    if a.hands:
        BODY = BODY + [f"{s}_{f}{i}" for s in ("l", "r") for f in ("thumb", "index", "middle", "ring", "pinky")
                       for i in (1, 2, 3)]

    mhr = torch.jit.load(str(MHR_PT), map_location="cpu")
    names = list(mhr.character_torch.skeleton.joint_names)
    parents = dict(mhr.named_buffers())["character_torch.skeleton.joint_parents"].tolist()
    n_expr = dict(mhr.named_buffers())["face_expressions_model.shape_vectors"].shape[0]
    files = glob.glob(os.path.join(a.run, "frames", "f*.npz"))
    files = sorted((f for f in files if Path(f).stem[1:].isascii() and Path(f).stem[1:].isdigit()),
                   key=lambda f: int(Path(f).stem[1:]))
    vf = [int(Path(f).stem[1:]) for f in files]
    D = [np.load(f) for f in files]
    shape = np.median([d["p0_shape_params"] for d in D], 0)
    params = np.stack([d["p0_mhr_model_params"] for d in D])  # (T, 204): 136 pose + 68 scales
    n_pose = params.shape[1] - 68
    params_fixed = params.copy()
    params_fixed[:, n_pose:] = np.median(params[:, n_pose:], 0)

    def run(sh, mp):
        with torch.no_grad():
            _, st = mhr(torch.as_tensor(sh, dtype=torch.float32), torch.as_tensor(mp, dtype=torch.float32),
                        torch.zeros(len(mp), n_expr))
        st = st.numpy().astype(np.float64)
        return st[..., :3] / 100.0, rotm(st[..., [6, 3, 4, 5]])  # coords (m), quats stored x,y,z,w -> w,x,y,z

    # 1. reproduce frame 0 exactly as SAM saved it
    c0, r0 = run(D[0]["p0_shape_params"][None], params[:1])
    pos_err = np.abs(FLIP @ c0[0].T - D[0]["p0_pred_joint_coords"].T).max()
    rot_err = np.abs(r0[0] - D[0]["p0_pred_global_rots"]).max()
    print(f"CHECK reproduce f{vf[0]}: joint pos max err {pos_err * 1000:.2f} mm, rot max err {rot_err:.2e}")
    if pos_err > 0.002 or rot_err > 1e-3:
        sys.exit("STOP: cannot reproduce SAM's saved skeleton; axes or units are wrong")

    # 2. all frames with one shape + one set of proportions, then rest pose (pose params zero)
    C, R = run(np.repeat(shape[None], len(D), 0), params_fixed)
    rest_mp = params_fixed[:1].copy()
    rest_mp[:, :n_pose] = 0
    Cr, Rr = run(shape[None], rest_mp)
    idx = [names.index(n) for n in BODY]

    def kept_parent(j):
        p = parents[j]
        while p >= 0 and names[p] not in BODY:
            p = parents[p]
        return BODY.index(names[p]) if p >= 0 else -1
    par = [kept_parent(j) for j in idx]

    # MHR -> Blender axes; root path gets the camera placement (cam_t is camera axes -> MHR axes)
    G = np.einsum("ab,tjbc,dc->tjad", M, R[:, idx], M)              # global rotations, Blender axes
    camt = np.stack([FLIP @ d["p0_pred_cam_t"] for d in D])          # MHR axes
    P = np.einsum("ab,tjb->tja", M, C[:, idx] + camt[:, None, :])    # joint positions, Blender axes
    rest_G = np.einsum("ab,jbc,dc->jad", M, Rr[0, idx], M)
    rest_P = np.einsum("ab,jb->ja", M, Cr[0, idx])

    # 3a. local rotations (root keeps its global), fill drops, smooth outside the hit windows
    L = np.empty_like(G)
    for j, p in enumerate(par):
        L[:, j] = G[:, j] if p < 0 else np.einsum("tba,tbc->tac", G[:, p], G[:, j])
    Q = quat(L)
    for t in range(1, len(Q)):  # sign continuity
        flip = (Q[t] * Q[t - 1]).sum(-1) < 0
        Q[t, flip] *= -1
    root_path = P[:, 0].copy()
    dropped = [vf.index(f) for f in a.drop if f in vf]
    for t in dropped:
        lo = max(i for i in range(t) if i not in dropped)
        hi = min(i for i in range(t + 1, len(Q)) if i not in dropped)
        w = (vf[t] - vf[lo]) / (vf[hi] - vf[lo])
        Q[t] = np.stack([slerp(Q[lo, j], Q[hi, j], w) for j in range(Q.shape[1])])
        root_path[t] = (1 - w) * root_path[lo] + w * root_path[hi]
    keep = [tuple(int(v) for v in k.split("-")) for k in a.keep]
    hold = lambda f: any(lo <= f <= hi for lo, hi in keep)
    KAS = set(a.keep_arms_sides.split(","))  # sides --keep-arms applies to
    # Hands: SAM reads each frame alone and the hands are
    # ~20 px, blurred and half hidden by the weapon, so forearm and wrist turns shake 15-16 deg per key raw against
    # 3-5 deg for the hips and chest. Flicks out and back go first, then extra smoothing on the arm ends only.
    FING = ("thumb", "index", "middle", "ring", "pinky")
    AJ = a.arm_joints.split(",")
    ARM = [j for j, n in enumerate(BODY) if any(n.endswith("_" + x) for x in AJ if x != "fingers")
           or ("fingers" in AJ and any(f in n for f in FING))]
    POS_HOLD = ("_clavicle", "_uparm", "_lowarm")  # these move the hand: keep their hits sharp
    qang = lambda p, q: float(np.degrees(2 * np.arccos(min(1.0, abs(float(np.dot(p, q)))))))
    spikes, Q_raw = [], Q.copy()
    if a.spike > 0:
        for j in ARM:
            for t in range(1, len(Q) - 1):
                if a.keep_arms and hold(vf[t]) and BODY[j][0] in KAS:
                    continue  # --keep-arms: an arm hit is not a flick
                mid = slerp(Q[t - 1, j], Q[t + 1, j], 0.5)
                dev = qang(Q[t, j], mid)
                if dev > a.spike and dev > qang(Q[t - 1, j], Q[t + 1, j]):
                    Q[t, j] = mid
                    spikes.append([int(vf[t]), BODY[j], round(dev, 1)])
        for t in range(1, len(Q)):  # sign continuity again after the replacements
            flip = (Q[t] * Q[t - 1]).sum(-1) < 0
            Q[t, flip] *= -1
    Qs, Ps = Q.copy(), root_path.copy()
    for t in range(1, len(Q) - 1):
        if hold(vf[t]):
            continue
        for j in range(Q.shape[1]):
            q = 0.25 * Q[t - 1, j] + 0.5 * Q[t, j] + 0.25 * Q[t + 1, j]
            Qs[t, j] = q / np.linalg.norm(q)
        Ps[t] = 0.25 * root_path[t - 1] + 0.5 * root_path[t] + 0.25 * root_path[t + 1]
    for _ in range(a.arm_smooth):
        prev = Qs.copy()
        for t in range(1, len(Q) - 1):
            for j in ARM:
                if (BODY[j].endswith(POS_HOLD) or (a.keep_arms and BODY[j][0] in KAS)) and hold(vf[t]):
                    continue  # these set where the hand is: keep the hits sharp
                q = 0.25 * prev[t - 1, j] + 0.5 * prev[t, j] + 0.25 * prev[t + 1, j]
                Qs[t, j] = q / np.linalg.norm(q)
    jitter_before = float(np.degrees(2 * np.arccos(np.clip(np.abs((Q_raw[1:] * Q_raw[:-1]).sum(-1)), 0, 1))).mean())
    jitter_after = float(np.degrees(2 * np.arccos(np.clip(np.abs((Qs[1:] * Qs[:-1]).sum(-1)), 0, 1))).mean())
    raw_depth = Ps[:, 1].copy()
    if a.flatten_depth:
        Ps[:, 1] = np.median(Ps[: max(3, len(Ps) // 6), 1])

    # back to globals from the smoothed locals
    Ls = rotm(Qs)
    Gs = np.empty_like(Ls)
    for j, p in enumerate(par):
        Gs[:, j] = Ls[:, j] if p < 0 else np.einsum("tab,tbc->tac", Gs[:, p], Ls[:, j])
    if a.hand_world > 0:  # smooth each hand's world turn (positions untouched), then let the fingers ride it
        for s in ("l", "r"):
            j = BODY.index(f"{s}_wrist")
            q = quat(Gs[:, j])
            for t in range(1, len(q)):
                if np.dot(q[t], q[t - 1]) < 0:
                    q[t] *= -1
            for _ in range(a.hand_world):
                p_ = q.copy()
                q[1:-1] = 0.25 * p_[:-2] + 0.5 * p_[1:-1] + 0.25 * p_[2:]
                q /= np.linalg.norm(q, axis=-1, keepdims=True)
                if a.keep_arms and s in KAS:  # the hit keys keep their own hand turn
                    hk = [t for t in range(len(q)) if hold(vf[t])]
                    q[hk] = p_[hk]
            Gs[:, j] = rotm(q)
        for j, p in enumerate(par):
            if any(f in BODY[j] for f in FING):
                Gs[:, j] = np.einsum("tab,tbc->tac", Gs[:, p], Ls[:, j])

    # where the wrists end up (forward kinematics with the rest offsets, as the Blender build does), against SAM's
    # raw joints: the price of smoothing, root-relative, mm; and how much they shake (cm)
    rest_G_ = np.einsum("ab,jbc,dc->jad", M, Rr[0, idx], M)
    rest_P_ = np.einsum("ab,jb->ja", M, Cr[0, idx])
    def fk(Gx):
        X = np.zeros((len(Gx), len(BODY), 3))
        for j, p in enumerate(par):
            if p >= 0:
                off = rest_G_[p].T @ (rest_P_[j] - rest_P_[p])
                X[:, j] = X[:, p] + np.einsum("tab,b->ta", Gx[:, p], off)
        return X
    Xs = fk(Gs)
    Praw = P - P[:, :1]
    pos_rep = {}
    for n in ("l_wrist", "r_wrist", "l_lowarm", "r_lowarm"):
        j = BODY.index(n)
        e = np.linalg.norm(Xs[:, j] - Praw[:, j], axis=-1) * 1000
        sh = np.linalg.norm(Xs[1:-1, j] - (Xs[:-2, j] + Xs[2:, j]) / 2, axis=-1) * 100
        pos_rep[n] = {"vs_raw_mm_mean": round(float(e.mean()), 1), "shake_cm_mean": round(float(sh.mean()), 2),
                      "shake_cm_max": round(float(sh.max()), 1)}

    def shake(R):  # per key: degrees between a joint's world turn and the halfway turn of its two neighbour keys
        q = quat(R)
        out = []
        for t in range(1, len(q) - 1):
            b = q[t + 1] * (1.0 if np.dot(q[t - 1], q[t + 1]) >= 0 else -1.0)
            mid = (q[t - 1] + b) / np.linalg.norm(q[t - 1] + b)
            out.append(qang(mid, q[t]))
        return round(float(np.mean(out)), 2), round(float(np.max(out)), 1)
    shake_rep = {BODY[j]: {"raw": shake(G[:, j]), "out": shake(Gs[:, j])}
                 for j in range(len(BODY)) if BODY[j] in ("root", "c_spine3", "c_head", "l_lowarm", "l_wrist",
                                                          "r_lowarm", "r_wrist")}

    # hand landmarks at rest (knuckles), so the build can line up each palm, not just each bone's direction
    # (the shortest A->T turn left a constant forearm/hand twist)
    HAND = [f"{s}_{j}" for s in ("l", "r") for j in ("wrist", "index1", "middle1", "ring1", "pinky1", "thumb1")]
    hidx = [names.index(n) for n in HAND]
    rest_hand = np.einsum("ab,jb->ja", M, Cr[0, hidx])
    np.savez_compressed(a.out, names=np.array(BODY), parents=np.array(par), video_frames=np.array(vf),
                        rest_heads=rest_P, rest_rots=rest_G, rots=Gs, root_pos=Ps, root_depth_raw=raw_depth,
                        joints_raw=P, hand_names=np.array(HAND), rest_hand=rest_hand)
    rep = {"run": a.run, "frames": len(vf), "dropped_video_frames": [vf[t] for t in dropped], "keep_windows": a.keep,
           "flatten_depth": a.flatten_depth, "reproduce_mm": round(pos_err * 1000, 3),
           "mean_step_deg_before": round(jitter_before, 2), "mean_step_deg_after": round(jitter_after, 2),
           "root_depth_range_raw_m": round(float(raw_depth.max() - raw_depth.min()), 3),
           "rest_leg_len_m": round(float(np.linalg.norm(rest_P[BODY.index("l_upleg")] - rest_P[BODY.index("l_lowleg")])
                                         + np.linalg.norm(rest_P[BODY.index("l_lowleg")] - rest_P[BODY.index("l_foot")])), 4),
           "rest_height_m": round(float(rest_P[:, 2].max() - rest_P[:, 2].min()), 3),
           "spike_deg": a.spike, "arm_smooth_passes": a.arm_smooth, "arm_joints": a.arm_joints,
           "hand_world_passes": a.hand_world, "flicks_removed": spikes, "arm_positions": pos_rep,
           "world_shake_deg_mean_max": shake_rep}
    Path(a.out).with_suffix(".json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("SOURCE", json.dumps(rep))


if __name__ == "__main__":
    main()
