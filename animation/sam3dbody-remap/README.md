# SAM 3D Body remap kit

Small tools for one job: take an **AI-video animation take**, get a **3D body per frame** out of it with Meta's SAM 3D
Body, **remap that motion onto your own rig** in Blender, and review the result before it reaches the game. The process
is explained in [`docs/animation.md`](../../docs/animation.md); this page is about the files.

This is a working kit that grew while making a game, not a polished product. The generic tools run on their own. The
three scripts plus a preflight helper in `examples-auto-rig-pro/` are labelled **example code**: they need Blender, the paid Auto-Rig Pro
add-on and your own rig, and the rig, bone and take names inside them are this project's examples.

## What is not here, and where to get it

**SAM 3D Body is Meta's, not mine, and none of it is in this repo.** Fetch it yourself:

- Code: <https://github.com/facebookresearch/sam-3d-body> (paper: <https://arxiv.org/abs/2602.15989>). Clone it into
  `./src` beside the scripts, or point `SAM3DB_SRC` at your clone.
- Weights: the Hugging Face repo `facebook/sam-3d-body-vith` (<https://huggingface.co/facebook/sam-3d-body-vith>). It is
  gated: you request access on that page and Meta approves each request. Waits of days to weeks, and refusals with no
  reason, were reported by other people in the project's issues.
- Licence: the **SAM License** (Meta, last updated 19 November 2025; the `LICENSE` file in Meta's repo and in the weights
  repo). Read it yourself; this is a summary, not legal advice. It grants a non-exclusive, worldwide, royalty-free licence
  to use, copy, modify and distribute the SAM Materials, **commercial use included**. Conditions include: anything you
  redistribute stays under the same licence and carries a copy of it; research you publish must acknowledge the use; you
  must comply with law and trade controls; you must not reverse engineer or decompile the materials; and you must not use
  them for activities under the US ITAR or for end uses that trade controls prohibit, which the licence says include
  military or warfare purposes, nuclear applications, espionage, and the development or use of guns or illegal weapons.
  The materials and their output come "as is", with no warranty. Check whether your own use is allowed.
- **Load only weights whose hashes match.** `model.ckpt` and `assets/mhr_model.pt` are pickle / TorchScript files, and
  loading such a file can run code. `verify_checkpoint.py` checks the files against the ids Meta publishes for that repo
  (sha256 for the two big files). Run it after every download, from any source, and load nothing unless it prints
  `ALL_MATCH`. Meta's ids are a snapshot: compare with the live Hugging Face page if the repo has been updated.
- Pick the **ViT-H checkpoint**, not the DINOv3 one: the DINOv3 backbone fetches and runs unpinned code from GitHub at
  every load (`torch.hub.load(..., source="github")`), the ViT-H one runs only the code in your clone.

Also not here: Blender, the Auto-Rig Pro add-on (paid), the video generator (the takes in the project were made with
MiniMax, a paid service), `render_views.py` (Blender code written around one rig), and any game asset.

## Files

| File | What it does | Needs |
|---|---|---|
| `install_venv.sh` | Builds a Python 3.11 venv with the core inference packages (torch CUDA 12.6 wheels). It writes the freeze it made to `requirements-freeze.txt` inside the venv; the tracked `requirements-installed.txt` is the freeze from one tested run. | Meta's clone in `./src`; Python 3.11 |
| `get_checkpoint.sh` | Downloads the ViT-H files with the `hf` command. | Your own Hugging Face access to the gated repo |
| `verify_checkpoint.py` | Hash check of the downloaded files against Meta's published ids. | stdlib |
| `run_sam3db.py` | Video or picture in, per frame out: `frames/fNNNN.npz` (skeleton, keypoints, camera), `overlay/fNNNN.jpg`, `run.json`. | venv, GPU (about 3.4 GB, about 0.5 s a frame on an RTX 3090) |
| `boxes_from_mask.py` | Per-frame person boxes from a subject-mask video plus its crop file. | cv2, numpy |
| `boxes_by_colour.py` | Per-man boxes for a two-person take with no mask, by learning each man's colours. | cv2, numpy |
| `keyframe_sheet.py` | Labelled key-frame sheet of a take; `--boxes name=boxes.json` draws the boxes on it. | cv2, numpy |
| `overlay_sheet.py` | Close-up sheet of SAM's overlays around one person. | cv2, numpy |
| `facing_scan.py` | Finds left/right flips (SAM turning a body 180 degrees) in a run. | numpy, `SAM3DB_SRC` |
| `views3d.py` | Top and front views of the skeletons, to see the depth a side view hides. | cv2, numpy, `SAM3DB_SRC` |
| `view_sheets.py` | Frame-by-frame review sheets and muted clips: the take, your render over it, other angles, hand close-ups. | cv2, numpy, ffmpeg, renders in the shape below |
| `check_review.py` | The "prove you looked" gate for a review checklist copy. | stdlib |
| `REVIEW-CHECKLIST.example.md` | An example master checklist for `check_review.py`. Edit it to fit your project. | |
| `examples-auto-rig-pro/sam_to_source.py` | SAM run to clean, constant-bone-length motion (numpy file) for a Blender source armature. | SAM venv (torch, roma); the MHR file from the checkpoint |
| `examples-auto-rig-pro/build_source_blender.py` | Builds that motion as a source armature in your rig's rest pose. | Blender, your rig |
| `examples-auto-rig-pro/remap_to_arp.py` (+ `arp_retarget_preflight.py`) | Runs Auto-Rig Pro's Remap onto your rig, with a preflight and read-backs. | Blender, the paid Auto-Rig Pro add-on, your rig |

## Setting it up

All paths are parameters or environment variables; nothing is hard-coded.

| Variable | Used by | Default |
|---|---|---|
| `SAM3DB_SRC` | `run_sam3db.py`, `facing_scan.py`, `views3d.py` | `./src` beside the script (your clone of Meta's repo) |
| `SAM3DB_CKPT_DIR` | `run_sam3db.py`, `verify_checkpoint.py`, `get_checkpoint.sh`, `sam_to_source.py` | `./checkpoints/sam-3d-body-vith` beside the script |
| `SAM3DB_SRC_COMMIT` | `run_sam3db.py` | `unknown` (only written to `run.json`; the kit was tried on commit `b5c765a0d89d789985e186d396315e7590887b94`) |
| `SAM3DB_VENV`, `PYTHON`, `TORCH_INDEX` | `install_venv.sh` | `./venv`, `python3.11`, the cu126 wheel index |
| `SAM3DB_HF_REPO`, `SAM3DB_HF_REVISION`, `HF` | `get_checkpoint.sh` | `facebook/sam-3d-body-vith`, the repo's latest, the venv's `hf` |
| `REVIEW_CHECKLIST`, `CLAUDE_PROJECTS_DIR` | `check_review.py` | the example checklist beside it; `<USER_HOME>/.claude/projects` |
| `REMAP_ROOT` | (convention) the folder that holds one remap job: takes, boxes, SAM runs, blends, sheets | your choice |
| `REMAP_PREFLIGHT_DIR`, `ARP_ADDON_MODULE` | `remap_to_arp.py` | the script's own folder; the module name Blender gave the add-on |

A first run looks like this (run the Python tools with the SAM venv's python, and **book the GPU first if you share
it**: see [`gpu-lease/`](../../gpu-lease/) in this repo):

```
bash install_venv.sh                       # after cloning Meta's repo into ./src
bash get_checkpoint.sh                     # needs your own Hugging Face access
python -I -B verify_checkpoint.py          # must print ALL_MATCH before anything loads the weights
python -I -B keyframe_sheet.py take.mp4 $REMAP_ROOT/keys.png "0:start" "24:swing" "48:end"
python -B run_sam3db.py --input take.mp4 --out $REMAP_ROOT/sam --every 2
python -I -B facing_scan.py $REMAP_ROOT/sam          # left/right flips?
python -I -B overlay_sheet.py $REMAP_ROOT/sam boxes.json $REMAP_ROOT/fit.png "0:start" "24:swing"
```

Two people in one take: run SAM once per person with his own `--boxes-json` (the default `auto` box puts one box around
all foreground, both people in it), and note that `sam_to_source.py` reads person 0 only.

## The render folder `view_sheets.py` expects

`view_sheets.py` does not render anything. It reads PNGs another script (yours) wrote into one folder, named
`<view>_<video frame, 4 digits>.png` for the views `video`, `top`, `left`, `right`, `back`. The `video` PNG is RGBA: your
character rendered from the take's own camera. An optional `views-info.json` in that folder carries `rigs` (one entry
per person), `points` (per video frame, per person, the 2D pixel of `hand.l`, `hand.r`, `forearm_stretch.l`/`.r` and
`prop:<name>` points, used to place the hand close-ups), `props` (`{name: {rig, side}}`), and `look` / `legend`.

## Traps worth knowing before you start

- SAM works on **one picture at a time**: expect frame-to-frame jitter (smooth before remapping), and sometimes a body
  read from behind that is really seen from the front (`facing_scan.py` finds the 180 degree jumps).
- Depth from one view is a guess. Check the top view (`views3d.py`) before trusting where a hand or a weapon is.
- The model's zero pose is an A-pose (arms about 48 degrees down); many rigs rest in a T-pose. Remap tools copy rotation
  relative to each rig's rest, so the two rests must be made to match (that is what `build_source_blender.py` does).
- MHR returns **centimetres**; its joint coordinates are in camera axes (the MHR axes with y and z negated), its joint
  rotations are in MHR axes. `sam_to_source.py` documents the conversion to Blender axes.
- `run_sam3db.py` exits 1 on an empty `--boxes-json` or when no frame was processed; check the `RUN_DONE` line.

## Licence note for the Blender scripts

Scripts that import `bpy` run inside Blender (GPL-3.0-or-later). This repo ships them under Apache-2.0, which is
GPLv3-compatible; a Blender add-on built and redistributed from them is GPL.

## Tests

CPU only, stdlib: `python -m py_compile` on every script. `check_review.py` was exercised in a temporary folder with a
generated copy of the example checklist (a good copy passes; an unopened picture, a look item with no `see:` line and a
missing item each fail). SAM, torch, Blender and the GPU were not run for this repo.
