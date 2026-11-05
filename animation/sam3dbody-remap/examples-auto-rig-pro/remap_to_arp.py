# EXAMPLE CODE. Needs Blender, the PAID Auto-Rig Pro add-on (not included, bought separately) and your own rig.
# Rig and armature names below (ARP_target, SAM_source, ...) are placeholders: pass your own with --source / --target.
# ARP Remap the SAM 3D Body source armature onto the target rig, with a preflight and read-backs (step 6 of the remap).
# blender -b <source.blend from build_source_blender.py> --disable-autoexec --python remap_to_arp.py --
#     <out.blend> <report.json> [--source SAM_source] [--target ARP_target]
# Mapping: explicit (never ARP's auto-map); root -> c_root_master.x is the one root row, read back before and after.
# Checks after the bake, at every source key: each mapped target bone's WORLD rotation against its source bone (the
# rests are identical, so this should be ~0), target root head against source root head, joint positions against
# SAM's, the target rest fingerprint unchanged, and the target rig mesh's lowest point per frame (feet against the floor).
import bpy, addon_utils, importlib, json, math, os, sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
out_blend, out_json = argv[0], argv[1]
opt = dict(zip(argv[2::2], argv[3::2]))
SRC, TGT = opt.get("--source", "SAM_source"), opt.get("--target", "ARP_target")
# arp_retarget_preflight.py sits beside this script (override the folder with REMAP_PREFLIGHT_DIR)
sys.path.insert(0, os.environ.get("REMAP_PREFLIGHT_DIR", os.path.dirname(os.path.abspath(__file__))))
from arp_retarget_preflight import capture, validate  # noqa: E402

MOD = os.environ.get("ARP_ADDON_MODULE", "bl_ext.superhivemarket_com.auto_rig_pro")  # where your Blender installed the add-on
if not addon_utils.check(MOD)[1] and addon_utils.enable(MOD, default_set=False, persistent=False) is None:
    raise SystemExit("STOP: Auto-Rig Pro is not available")
remap = importlib.import_module(MOD + ".src.auto_rig_remap")

MAP = {"root": "c_root_master.x", "c_spine1": "c_spine_01.x", "c_spine2": "c_spine_02.x", "c_spine3": "c_spine_03.x",
       "c_neck": "c_neck.x", "c_head": "c_head.x"}
for s in ("l", "r"):
    MAP.update({f"{s}_clavicle": f"c_shoulder.{s}", f"{s}_uparm": f"c_arm_fk.{s}", f"{s}_lowarm": f"c_forearm_fk.{s}",
                f"{s}_wrist": f"c_hand_fk.{s}", f"{s}_upleg": f"c_thigh_fk.{s}", f"{s}_lowleg": f"c_leg_fk.{s}",
                f"{s}_foot": f"c_foot_fk.{s}", f"{s}_ball": f"c_toes_fk.{s}"})

scn = bpy.context.scene
src, dst = bpy.data.objects[SRC], bpy.data.objects[TGT]
# SAM's own fingers, when the source was built from sam_to_source.py --hands (variant B)
for s in ("l", "r"):
    for f in ("thumb", "index", "middle", "ring", "pinky"):
        for i in (1, 2, 3):
            if f"{s}_{f}{i}" in src.pose.bones:
                MAP[f"{s}_{f}{i}"] = f"c_{f}{i}.{s}"
act = src.animation_data.action
from bpy_extras.anim_utils import action_get_channelbag_for_slot  # noqa: E402
keys = sorted({int(round(kp.co.x)) for fc in action_get_channelbag_for_slot(act, src.animation_data.action_slot).fcurves
               for kp in fc.keyframe_points})
f0, f1 = keys[0], keys[-1]
scn.frame_start, scn.frame_end = f0, f1

if bpy.context.object and bpy.context.object.mode != "OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")
scn.source_rig, scn.target_rig = SRC, TGT
remap.save_source_action(src)
scn.batch_retarget = False
scn.bones_map_v2.clear()
scn.arp_remap_allow_root_update = False
try:
    for i, (s, t) in enumerate(MAP.items()):
        item = scn.bones_map_v2.add()
        item.source_bone, item.name = s, t
        scn.bones_map_index = i
        item.set_as_root = (s == "root")
finally:
    scn.arp_remap_allow_root_update = True
roots = [r.name for r in scn.bones_map_v2 if r.set_as_root]
if roots != [MAP["root"]]:
    raise SystemExit(f"STOP: root designation did not stick: {roots}")

plan = {"source_rig": SRC, "target_rig": TGT, "source_action": act.name,
        "source_slot": src.animation_data.action_slot.identifier, "bake_range": [f0, f1],
        "root_source": "root", "root_target": MAP["root"], "required_sources": list(MAP),
        "mapping": [{"source": s, "target": t} for s, t in MAP.items()]}
snap = capture(plan)
pre = validate(snap, plan)
if pre["status"] != "PASS":
    raise SystemExit(f"STOP: preflight {pre['status']}: {pre['findings']}")

for o in bpy.context.view_layer.objects:
    o.select_set(False)
bpy.context.view_layer.objects.active = src
src.select_set(True)
ret = bpy.ops.arp.retarget(frame_start=f0, frame_end=f1, interpolation_type="LINEAR", show_freeze_warn=False)
if ret != {"FINISHED"}:
    raise SystemExit(f"STOP: arp.retarget returned {ret}")
if bpy.context.object and bpy.context.object.mode != "OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")
tact = dst.animation_data.action if dst.animation_data else None
if tact is None:
    raise SystemExit("STOP: no target action after the bake")
tkeys = sorted({int(round(kp.co.x)) for fc in action_get_channelbag_for_slot(tact, dst.animation_data.action_slot).fcurves
                for kp in fc.keyframe_points})
roots_after = [r.name for r in scn.bones_map_v2 if r.set_as_root]
fp_after = capture(plan)["target_rest_fingerprint"]

def ang(qa, qb):
    a = math.degrees(qa.rotation_difference(qb).angle)
    return min(a, 360.0 - a)

JOINTS = {"l_upleg": ("c_thigh_fk.l", "head"), "l_lowleg": ("c_leg_fk.l", "head"), "l_foot": ("c_foot_fk.l", "head"),
          "r_upleg": ("c_thigh_fk.r", "head"), "r_lowleg": ("c_leg_fk.r", "head"), "r_foot": ("c_foot_fk.r", "head"),
          "l_lowarm": ("c_forearm_fk.l", "head"), "l_wrist": ("c_hand_fk.l", "head"),
          "r_lowarm": ("c_forearm_fk.r", "head"), "r_wrist": ("c_hand_fk.r", "head"), "c_head": ("c_head.x", "head")}
meshes = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render and
          any(m.type == "ARMATURE" and m.object == dst for m in o.modifiers)]
rot_err = {t: 0.0 for t in MAP.values()}
joint_err = {j: [] for j in JOINTS}
root_err, low, travel = [], [], []
for f in keys:
    scn.frame_set(f)
    for s, t in MAP.items():
        qs = (src.matrix_world @ src.pose.bones[s].matrix).to_quaternion()
        qt = (dst.matrix_world @ dst.pose.bones[t].matrix).to_quaternion()
        rot_err[t] = max(rot_err[t], ang(qs, qt))
    hs = src.matrix_world @ src.pose.bones["root"].head
    ht = dst.matrix_world @ dst.pose.bones[MAP["root"]].head
    root_err.append((hs - ht).length * 1000)
    travel.append([list(hs), list(ht)])
    for j, (b, end) in JOINTS.items():
        pj = src.matrix_world @ src.pose.bones[j].head
        pt = dst.matrix_world @ getattr(dst.pose.bones[b], end)
        joint_err[j].append((pj - pt).length * 1000)
    dg = bpy.context.evaluated_depsgraph_get()
    zmin = 1e9
    for o in meshes:
        e = o.evaluated_get(dg)
        me = e.to_mesh()
        mw = e.matrix_world
        zmin = min(zmin, min((mw @ v.co).z for v in me.vertices))
        e.to_mesh_clear()
    low.append([f, round(zmin, 4)])
tr_s = (Vector(travel[-1][0]) - Vector(travel[0][0])).length
tr_t = (Vector(travel[-1][1]) - Vector(travel[0][1])).length
bpy.ops.wm.save_as_mainfile(filepath=out_blend, copy=False)
rep = {"source_blend": bpy.data.filepath, "out": out_blend, "arp_return": sorted(ret), "preflight": pre["status"],
       "unmapped_source_bones": pre["unmapped_source_bones"], "bake_range": [f0, f1],
       "target_action": tact.name, "target_keyed_range": [tkeys[0], tkeys[-1]], "target_keyed_frames": len(tkeys),
       "root_rows_before_after": [roots, roots_after],
       "target_rest_unchanged": fp_after == snap["target_rest_fingerprint"],
       "world_rotation_max_deg": {t: round(v, 3) for t, v in rot_err.items()},
       "root_head_mm": {"mean": round(sum(root_err) / len(root_err), 2), "max": round(max(root_err), 2)},
       "root_travel_m": {"source": round(tr_s, 4), "target": round(tr_t, 4)},
       "joint_vs_source_mm": {j: {"mean": round(sum(v) / len(v), 1), "max": round(max(v), 1)} for j, v in joint_err.items()},
       "mesh_lowest_z": {"min": min(z for _, z in low), "max": max(z for _, z in low), "per_key": low},
       "meshes": [o.name for o in meshes],
       "limits": ["Rotation and root checks prove ARP copied the source; they do not judge the motion.",
                  "Joint offsets include real proportion differences (target rig vs SAM scaled by leg length)."]}
json.dump(rep, open(out_json, "w"), indent=1)
print("REMAP_DONE", json.dumps({k: rep[k] for k in ("arp_return", "preflight", "target_keyed_range", "root_rows_before_after",
                                                    "target_rest_unchanged", "root_head_mm", "root_travel_m")}))
