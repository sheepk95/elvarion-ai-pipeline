# EXAMPLE CODE. Needs Blender, the PAID Auto-Rig Pro add-on (not included, bought separately) and your own rig.
# Rig and armature names below (ARP_target, SAM_source, ...) are placeholders: pass your own with --name / --target.
# Build SAM 3D Body's skeleton as a Blender source armature in the target rig's own rest pose, and key its motion
# (step 5 of the remap, after sam_to_source.py has cleaned the motion).
#
# Why: SAM's body model rests in an A-pose (arms 48 deg down, forearms forward); the target rig here rests in a T-pose. ARP
# Remap transfers rotation relative to each rig's rest, so the rests must match. Each source bone therefore gets the
# REST ORIENTATION of the ARP bone it maps to (MAP below) and SAM's bone LENGTH. Per frame, bone j's world frame is
#   W_j(t) = G_j(t) G_j(rest)^T Q_j S_j
# G = SAM joint rotation, S_j = the ARP rest frame, Q_j = the turn from S_j's direction to SAM's own rest direction of
# that limb. So W_j points the bone along SAM's limb at t and carries SAM's twist. The root alone is keyed with location.
# Units: SAM metres, scaled by target-rig leg / SAM leg (root travel and all), floor set from the standing frames.
#
#
# Hands:
# - PALM: the shortest turn lines up a bone's direction only, which left each hand twisted 23 deg from SAM's. Forearm,
#   hand and finger bones now also line up the palm: the target rig's palm-back normal (index1 - wrist) x (pinky1 - wrist)
#   turns onto SAM's at rest. Needs the hand landmarks that sam_to_source.py saves (rest_hand).
# - ROLL: MHR keeps forearm pronation in the WRIST joint; the target rig's shield rides the FOREARM bone. Each frame the
#   forearm now turns about its own axis by the hand's twist relative to it (from SAM's rest), so the shield follows
#   the hand. Wrist and finger positions do not move (the turn is about the bone's own axis).
# - FINGERS: a source made with sam_to_source.py --hands also gets SAM's 15 finger joints per hand, mapped to
#   c_<finger>1-3.<side>; the last segment borrows the one before it for its direction.
# blender -b <working copy with your ARP rig> --disable-autoexec --python build_source_blender.py --
#     <source.npz> <out.blend> [--name SAM_source] [--origin auto|x,y] [--stand 0-20] [--palm on|off] [--roll on|off]
#     [--target ARP_target]   (the name of your Auto-Rig Pro target armature in the working copy)
import bpy, json, math, sys
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, out_blend = argv[0], argv[1]
opt = dict(zip(argv[2::2], argv[3::2]))
NAME = opt.get("--name", "SAM_source")
stand = [int(v) for v in opt.get("--stand", "0-20").split("-")]
PALM, ROLL = opt.get("--palm", "on") == "on", opt.get("--roll", "on") == "on"
FINGERS = [(f, i) for f in ("thumb", "index", "middle", "ring", "pinky") for i in (1, 2, 3)]

MAP = {"root": "c_root_master.x", "c_spine1": "c_spine_01.x", "c_spine2": "c_spine_02.x", "c_spine3": "c_spine_03.x",
       "c_neck": "c_neck.x", "c_head": "c_head.x"}
for s in ("l", "r"):
    MAP.update({f"{s}_clavicle": f"c_shoulder.{s}", f"{s}_uparm": f"c_arm_fk.{s}", f"{s}_lowarm": f"c_forearm_fk.{s}",
                f"{s}_wrist": f"c_hand_fk.{s}", f"{s}_upleg": f"c_thigh_fk.{s}", f"{s}_lowleg": f"c_leg_fk.{s}",
                f"{s}_foot": f"c_foot_fk.{s}", f"{s}_ball": f"c_toes_fk.{s}"})
# the limb each bone points along at SAM's rest (bone -> child joint); leaves borrow the given joint pair
DIR = {"c_spine0": ("c_spine0", "c_spine1"), "c_spine1": ("c_spine1", "c_spine2"), "c_spine2": ("c_spine2", "c_spine3"),
       "c_spine3": ("c_spine3", "c_neck"), "c_neck": ("c_neck", "c_head")}
for s in ("l", "r"):
    DIR.update({f"{s}_clavicle": (f"{s}_clavicle", f"{s}_uparm"), f"{s}_uparm": (f"{s}_uparm", f"{s}_lowarm"),
                f"{s}_lowarm": (f"{s}_lowarm", f"{s}_wrist"), f"{s}_wrist": (f"{s}_lowarm", f"{s}_wrist"),
                f"{s}_upleg": (f"{s}_upleg", f"{s}_lowleg"), f"{s}_lowleg": (f"{s}_lowleg", f"{s}_foot"),
                f"{s}_foot": (f"{s}_foot", f"{s}_ball")})

d = np.load(src)
names, par = [str(n) for n in d["names"]], [int(p) for p in d["parents"]]
vf, Pr, Gr, G, root = d["video_frames"], d["rest_heads"], d["rest_rots"], d["rots"], d["root_pos"]
LM = {str(n): Vector(v) for n, v in zip(d["hand_names"], d["rest_hand"])} if "rest_hand" in d.files else {}
if (PALM or ROLL) and not LM:
    raise SystemExit("STOP: --palm/--roll need the hand landmarks; re-export the source with the current sam_to_source.py")
HANDS = all(f"{s}_{f}{i}" in names for s in ("l", "r") for f, i in FINGERS)
for s in ("l", "r"):
    if LM and PALM:  # the hand points wrist -> middle knuckle, as the target rig's hand bone does (it used to borrow the forearm)
        DIR[f"{s}_wrist"] = (f"{s}_wrist", f"{s}_middle1")
    if HANDS:
        for f, i in FINGERS:
            MAP[f"{s}_{f}{i}"] = f"c_{f}{i}.{s}"
            DIR[f"{s}_{f}{i}"] = (f"{s}_{f}{i}", f"{s}_{f}{i + 1}") if i < 3 else (f"{s}_{f}2", f"{s}_{f}3")
tgt = bpy.data.objects[opt.get("--target", "ARP_target")]
tb = tgt.data.bones
missing = [b for b in MAP.values() if b not in tb]
if missing:
    raise SystemExit(f"STOP: target bones missing {missing}")
TW = tgt.matrix_world.to_3x3()

def tgt_rest(bname):
    return (TW @ tb[bname].matrix_local.to_3x3()).normalized()

# scale: target-rig leg (thigh head -> foot head) over SAM leg
tgt_leg = (tb["c_thigh_fk.l"].head_local - tb["c_leg_fk.l"].head_local).length + \
          (tb["c_leg_fk.l"].head_local - tb["c_foot_fk.l"].head_local).length
J = {n: i for i, n in enumerate(names)}
sam_leg = np.linalg.norm(Pr[J["l_upleg"]] - Pr[J["l_lowleg"]]) + np.linalg.norm(Pr[J["l_lowleg"]] - Pr[J["l_foot"]])
k = tgt_leg / sam_leg

def unit(v):
    v = Vector(v)
    return v / v.length

def rot_between(a, b):
    return a.rotation_difference(b).to_matrix()

def rest_pt(n):  # SAM rest position of a kept joint, or of a hand landmark (knuckles) when the joint is not kept
    return Vector(Pr[J[n]]) if n in J else LM[n]

def perp(v, axis):  # the part of v at right angles to the unit vector axis
    return v - axis * v.dot(axis)

def palm_normal(w, i, p):  # palm-back normal from wrist, index knuckle, pinky knuckle (same formula both rigs, per side)
    return (i - w).cross(p - w).normalized()

NE = {s: palm_normal(*(tgt.matrix_world @ tb[b].head_local for b in (f"c_hand_fk.{s}", f"c_index1.{s}", f"c_pinky1.{s}")))
      for s in ("l", "r")} if LM else {}
NA = {s: palm_normal(LM[f"{s}_wrist"], LM[f"{s}_index1"], LM[f"{s}_pinky1"]) for s in ("l", "r")} if LM else {}
PALM_BONES = {f"{s}_{b}": s for s in ("l", "r") for b in ["lowarm", "wrist"] + [f"{f}{i}" for f, i in FINGERS]}

# rest frames S_j and the A->T turn Q_j (shortest turn of the bone's direction; palm bones also turn about it so the
# target rig's palm normal lands on SAM's)
S, Q, dirA, palm_twist = {}, {}, {}, {}
for n in names:
    if n in MAP:
        S[n] = tgt_rest(MAP[n])
    else:  # unmapped (c_spine0): use its parent's frame
        S[n] = S[names[par[J[n]]]] if par[J[n]] >= 0 else Matrix.Identity(3)
    if n in DIR:
        a, b = DIR[n]
        dirA[n] = unit(rest_pt(b) - rest_pt(a))
        Q[n] = rot_between(S[n].col[1], dirA[n])
        if PALM and n in PALM_BONES:
            s = PALM_BONES[n]
            u, w = perp(Q[n] @ NE[s], dirA[n]), perp(NA[s], dirA[n])
            if u.length > 0.3 and w.length > 0.3:
                u.normalize()
                w.normalize()
                tw = math.atan2(dirA[n].dot(u.cross(w)), u.dot(w))
                Q[n] = Matrix.Rotation(tw, 3, dirA[n]) @ Q[n]
                palm_twist[n] = round(math.degrees(tw), 2)
            else:
                palm_twist[n] = "kept the shortest turn: the palm normal lies nearly along this bone"
    else:
        Q[n] = Matrix.Identity(3)
palm_rest_deg = {s: round(math.degrees((Q[f"{s}_wrist"] @ NE[s]).angle(NA[s])), 2) for s in ("l", "r")} if LM else {}

# rest heads in the T-pose: limb chains follow the ARP direction with SAM's lengths; other offsets stay SAM's
H = {}
for n in names:  # names are parent-first
    p = par[J[n]]
    if p < 0:
        H[n] = Vector(Pr[J[n]]) * k
        continue
    pn = names[p]
    # every child offset turns A -> T with its parent's turn, so in the pose it comes back as G_p G0_p^T (SAM's own
    # offset). Turning only the along-the-limb children twisted the clavicles by spine3's turn (wrists 118 mm off,
    # an earlier run; numpy chain test 72 mm).
    off = Q[pn].inverted() @ (Vector(Pr[J[n]] - Pr[J[pn]]) * k)
    H[n] = H[pn] + off

# floor: standing frames' lowest ankle at the target rig's rest ankle height; origin: this man's first root XY or given
lo = [i for i, f in enumerate(vf) if stand[0] <= f <= stand[1]]
joints_raw = d["joints_raw"] * k
ankle_z = np.median([min(joints_raw[i, J["l_foot"], 2], joints_raw[i, J["r_foot"], 2]) for i in lo])
tgt_ankle = (tgt.matrix_world @ tb["c_foot_fk.l"].head_local).z
og = opt.get("--origin", "auto")
ox, oy = (root[0, 0] * k, root[0, 1] * k) if og == "auto" else (float(og.split(",")[0]), float(og.split(",")[1]))
shift = Vector((-ox, -oy, tgt_ankle - ankle_z))

# Rest placement. ARP Remap moves the target root to (source root head + target rest head - source rest head), a
# fixed WORLD offset that does not turn with the hips (auto_rig_remap.py _retarget, *_ROOT_OFFSET). So the source root
# rests exactly on the target's root bone (offset 0) and the other bones rest with their hip midpoint on the target rig's.
# (An earlier run added the floor shift to the rest and sat about 2 m above the rig: the remap would have put the
# rig about 2 m under the floor.)
TWM = tgt.matrix_world
ROOT_T = MAP["root"]
rm_E = TWM @ tb[ROOT_T].head_local
hip_E = (TWM @ tb["c_thigh_fk.l"].head_local + TWM @ tb["c_thigh_fk.r"].head_local) / 2
ob = hip_E - (H["l_upleg"] + H["r_upleg"]) / 2
RESTPOS = {n: (rm_E.copy() if n == "root" else H[n] + ob) for n in names}
ROOT_ARM = rm_E - H["root"] - ob   # SAM root joint -> source root head, in the root's rest frame (world axes)

# armature
sc = bpy.context.scene
sc.render.fps, sc.render.fps_base = 24, 1.0
adata = bpy.data.armatures.new(NAME)
arm = bpy.data.objects.new(NAME, adata)
sc.collection.objects.link(arm)
for o in bpy.context.view_layer.objects:
    o.select_set(False)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
for n in names:
    eb = adata.edit_bones.new(n)
    eb.head, eb.tail = (0, 0, 0), (0, 1, 0)  # a new bone has zero length; give it one BEFORE setting its matrix
    L = 0.1
    if n in DIR and DIR[n][0] == n:
        L = float((rest_pt(DIR[n][1]) - rest_pt(n)).length * k)
    m = S[n].to_4x4()
    m.translation = RESTPOS[n]
    eb.matrix = m
    eb.length = max(L, 0.02)
    if par[J[n]] >= 0:
        eb.parent = adata.edit_bones[names[par[J[n]]]]
bpy.ops.object.mode_set(mode="POSE")
for pb in arm.pose.bones:
    pb.rotation_mode = "QUATERNION"

rest = {n: arm.data.bones[n].matrix_local.copy() for n in names}

def ang(qa, qb):  # smallest turn between two orientations, degrees (q and -q are the same turn: 360 means 0)
    a = math.degrees(qa.rotation_difference(qb).angle)
    return round(min(a, 360.0 - a), 3)

bad = {n: ang(rest[n].to_3x3().to_quaternion(), S[n].to_quaternion()) for n in names}
if max(bad.values()) > 0.05:
    raise SystemExit(f"STOP: source rest frames differ from the ARP frames they copy (deg): {bad}")
bad_t = {n: round((rest[n].translation - RESTPOS[n]).length * 1000, 3) for n in names}
if max(bad_t.values()) > 0.5:
    raise SystemExit(f"STOP: source rest heads are not where they were set (mm): {bad_t}")
G0 = {n: Matrix(Gr[J[n]].tolist()) for n in names}
err, perr, want, roll, palm_raw = [], {}, {}, {}, {}
for t, f in enumerate(vf):
    W = {}
    for n in names:
        R = Matrix(G[t, J[n]].tolist()) @ G0[n].transposed() @ Q[n] @ S[n]
        W[n] = R.to_4x4()
    for s in ("l", "r"):
        lo, wr = f"{s}_lowarm", f"{s}_wrist"
        D_lo = Matrix(G[t, J[lo]].tolist()) @ G0[lo].transposed()
        D_wr = Matrix(G[t, J[wr]].tolist()) @ G0[wr].transposed()
        if ROLL:  # forearm takes the hand's twist about the forearm axis (relative to SAM's rest)
            y = (D_lo @ dirA[lo]).normalized()
            u, w = perp(D_lo @ NA[s], y).normalized(), perp(D_wr @ NA[s], y).normalized()
            phi = math.atan2(y.dot(u.cross(w)), u.dot(w))
            W[lo] = (Matrix.Rotation(phi, 3, y) @ W[lo].to_3x3()).to_4x4()
            roll.setdefault(s, []).append(math.degrees(phi))
        if HANDS:  # the target-rig palm the hand bone carries, against SAM's raw knuckles this frame (smoothing included)
            jr = d["joints_raw"][t]
            n_raw = palm_normal(*(Vector(jr[J[f"{s}_{b}"]]) for b in ("wrist", "index1", "pinky1")))
            n_tgt = W[wr].to_3x3() @ S[wr].inverted() @ NE[s]
            palm_raw.setdefault(s, []).append(math.degrees(n_tgt.angle(n_raw)))
    P_t = Vector(root[t] * k) + shift   # SAM's root joint, scaled and placed
    W["root"].translation = P_t + (W["root"].to_3x3() @ S["root"].inverted()) @ ROOT_ARM
    pose = {}
    for n in names:
        p = par[J[n]]
        if p < 0:
            pose[n] = W[n]
        else:  # position follows the hierarchy; orientation is ours
            pn = names[p]
            local_rest = rest[pn].inverted() @ rest[n]
            pos = (pose[pn] @ local_rest).translation
            pose[n] = W[n].copy()
            pose[n].translation = pos
        pb = arm.pose.bones[n]
        basis = (rest[n].inverted() @ pose[n]) if p < 0 else \
            ((rest[names[p]].inverted() @ rest[n]).inverted() @ pose[names[p]].inverted() @ pose[n])
        loc, rq, _ = basis.decompose()
        pb.rotation_quaternion = rq
        pb.keyframe_insert("rotation_quaternion", frame=int(f) + 1)
        if p < 0:
            pb.location = loc
            pb.keyframe_insert("location", frame=int(f) + 1)
    want[t] = {n: pose[n].copy() for n in names}
    # check: root-relative joint positions against SAM's own (scaled), before smoothing
    rr = Vector(joints_raw[t, J["root"]])
    for n in names:
        a = (pose[n].translation if n != "root" else
             pose[n].translation - (pose[n].to_3x3() @ S["root"].inverted()) @ ROOT_ARM) - P_t
        b = Vector(joints_raw[t, J[n]]) - rr
        perr.setdefault(n, []).append((a - b).length)
        if n in ("l_wrist", "r_wrist", "l_foot", "r_foot", "c_head"):
            err.append((a - b).length)
sc.frame_start, sc.frame_end = int(vf[0]) + 1, int(vf[-1]) + 1
bpy.ops.object.mode_set(mode="OBJECT")
arm.animation_data.action.name = NAME + "_action"
try:  # Blender 4.4+ keeps keys in action slots (channelbags); older builds still have action.fcurves
    from bpy_extras.anim_utils import action_get_channelbag_for_slot
    fcs = action_get_channelbag_for_slot(arm.animation_data.action, arm.animation_data.action_slot).fcurves
except Exception:
    fcs = getattr(arm.animation_data.action, "fcurves", [])
n_linear = 0
for fc in fcs:  # keys are 2 video frames apart: linear, so nothing overshoots between them
    for kp in fc.keyframe_points:
        kp.interpolation = "LINEAR"
        n_linear += 1
if n_linear == 0:
    raise SystemExit("STOP: no keyframes found to set linear")
# playback check: what Blender itself plays at each key must be the pose computed above (this is what ARP Remap reads)
play_mm, play_deg = [], []
for t, f in enumerate(vf):
    sc.frame_set(int(f) + 1)
    for n in names:
        m = arm.matrix_world @ arm.pose.bones[n].matrix
        play_mm.append((m.translation - want[t][n].translation).length * 1000)
        play_deg.append(ang(m.to_quaternion(), want[t][n].to_quaternion()))
if max(play_mm) > 1.0 or max(play_deg) > 0.1:
    raise SystemExit(f"STOP: Blender playback differs from the computed pose: max {max(play_mm):.2f} mm, "
                     f"{max(play_deg):.3f} deg")
bpy.ops.wm.save_as_mainfile(filepath=out_blend, copy=False)
rep = {"source": src, "out": out_blend, "armature": NAME, "scale_k": round(k, 4), "elf_leg_m": round(tgt_leg, 4),
       "sam_leg_m": round(float(sam_leg), 4), "floor_shift_z": round(shift.z, 4), "origin_xy": [round(ox, 3), round(oy, 3)],
       "frames": [int(vf[0]) + 1, int(vf[-1]) + 1], "keys": len(vf), "fps": 24,
       "shift": [round(v, 4) for v in shift], "camera_world": [round(v, 4) for v in shift],
       "rest_root_head": [round(v, 4) for v in rm_E], "rest_hip_offset": [round(v, 4) for v in ob],
       "joint_check_mm": {"mean": round(float(np.mean(err)) * 1000, 1), "max": round(float(np.max(err)) * 1000, 1),
                          "note": "smoothed source vs SAM raw, root-relative, wrists/ankles/head"},
       "playback_check": {"max_mm": round(max(play_mm), 3), "max_deg": round(max(play_deg), 4),
                          "note": "Blender's evaluated pose at each key vs the computed pose"},
       "hands": {"palm": PALM, "roll": ROLL, "fingers_mapped": HANDS, "mapped_bones": len(MAP),
                 "palm_twist_added_deg": palm_twist,
                 "palm_rest_angle_deg": palm_rest_deg,
                 "forearm_roll_deg": {s: {"min": round(min(v), 1), "max": round(max(v), 1),
                                          "mean": round(sum(v) / len(v), 1)} for s, v in roll.items()},
                 "palm_vs_raw_knuckles_deg": {s: {"mean": round(sum(v) / len(v), 1), "max": round(max(v), 1)}
                                              for s, v in palm_raw.items()},
                 "note": "palm_rest_angle = target-rig palm normal vs SAM's at rest after the turn (0 = lined up; the "
                         "along-the-bone part is not turned). forearm_roll = the twist added to each forearm per frame."},
       "per_joint_mm": {n: round(float(np.mean(v)) * 1000, 1) for n, v in perr.items()},
       "frame0_mm": {n: round(float(v[0]) * 1000, 1) for n, v in perr.items()}}
json.dump(rep, open(out_blend.replace(".blend", ".json"), "w"), indent=1)
print("BUILD_SOURCE_DONE", json.dumps(rep))
