# Animation from an AI video: take, SAM 3D Body, remap, review, export

How the game gets character animation without a motion-capture studio. The tools are in
[`animation/sam3dbody-remap/`](../animation/sam3dbody-remap/); this page is the process around them. It is the process
as it ran for a Unity RTS, with one character rig, on one Windows PC. Nothing here is a finished product.

```
AI video take (MiniMax, paid)  ->  boxes  ->  SAM 3D Body per frame (GPU)  ->  checks
        ->  clean motion  ->  source armature in Blender  ->  Auto-Rig Pro Remap onto your rig (paid add-on)
        ->  fix-up layers  ->  review renders + checklist + gate  ->  FBX  ->  round-trip check  ->  Unity
```

## What you need, and who owns what

- **The take.** A short video of the move, made with an AI video model. Here it was MiniMax, a paid service: you pay
  for it, you follow its terms, and the output is a *reference*, not an accepted animation. A plain grey background, one
  fixed camera and one or two people in frame make every later step easier.
- **SAM 3D Body (Meta).** One picture of a person in, a 3D body out: the 127 joints and 70 keypoints of Meta's Momentum
  Human Rig with rotations, shape and scale. It is run **frame by frame**, so a video needs smoothing afterwards. It is
  Meta's code and Meta's weights under the **SAM License**: commercial use is allowed, some end uses are barred (military
  or warfare, nuclear, espionage, guns or illegal weapons, and anything trade controls prohibit), and you must keep the
  licence with anything you redistribute. This repo contains none of it: you fetch the code
  (<https://github.com/facebookresearch/sam-3d-body>) and the weights (`facebook/sam-3d-body-vith` on Hugging Face,
  gated) yourself, read the licence, and **load only weights whose hashes match** Meta's published ones, because the
  files are pickle / TorchScript and loading one can run code; `run_sam3db.py` checks them itself and refuses to load
  a checkpoint that does not match. Details and the hash check:
  [`animation/sam3dbody-remap/README.md`](../animation/sam3dbody-remap/README.md).
- **Blender and Auto-Rig Pro.** Your rig lives in Blender. The remap step here used Auto-Rig Pro's Remap, a **paid
  add-on**; the three scripts plus a preflight helper in `examples-auto-rig-pro/` drive it and only make sense with it and your own rig. Any
  retargeting tool can take their place if you can build the source armature it needs.
- **A GPU.** SAM needs about 3.4 GB of VRAM and about half a second a frame on an RTX 3090. If several agents or jobs
  share the card, book it first: see [`gpu-lease/`](../gpu-lease/).

## The steps

**1. Look at the take.** Make a labelled key-frame sheet (`keyframe_sheet.py`) and read it before anything runs. Decide
what the move is, which frames are key, where a person is hidden or blurred, and where two people overlap.

**2. Boxes.** SAM looks at one person per box. For a single person on a plain background, `run_sam3db.py --boxes auto`
finds the box by background subtraction. For two people, make one box track per person: from a subject mask video
(`boxes_from_mask.py`) or, with no mask, from each person's colours (`boxes_by_colour.py`). Draw the boxes on the key-frame
sheet and check every one; where people overlap, one box can grab the other person.

**3. SAM per frame.** `run_sam3db.py` writes, per frame, the skeleton, the keypoints, the camera and an overlay of the 2D
keypoints on the picture. Run one SAM pass per person (a two-box run feeds only person 0 to the next step). Check the
`RUN_DONE` line: a run with no frame exits 1 now, because an empty run that exits 0 once passed silently.

**4. Check SAM's fit before you remap it.** `overlay_sheet.py` (does the skeleton lie on the body), `facing_scan.py`
(did SAM turn the body 180 degrees, swapping left and right), `views3d.py` (top and front views: the depth a side view
hides). Frames SAM got wrong are dropped and filled across; frames of a real fast move are *kept* out of the smoothing.

**5. Clean motion.** `sam_to_source.py` re-runs the body model with **one body shape and one set of proportions** for the
whole clip (so bone lengths stay constant), keeps the 25 or so joints the remap needs, fills dropped frames, smooths the
local rotations with a short filter, and writes the result in Blender axes and metres. Options protect the frames where
a hit happens and calm the hands, which SAM reads worst because they are small, blurred and half hidden by what they hold.

**6. Source armature.** SAM's rest pose is an A-pose; many rigs rest in a T-pose. Remap tools copy rotation relative to
each rig's rest, so `build_source_blender.py` builds SAM's skeleton as an armature **in your rig's rest orientation**
with SAM's bone lengths, keyed with SAM's motion. It checks itself: its rest frames equal the rig's, and Blender's
playback equals the computed pose to within a millimetre and a tenth of a degree, or it stops.

**7. Remap.** `remap_to_arp.py` maps the source bones onto the rig explicitly (never the add-on's auto-map), runs a
preflight, bakes with Auto-Rig Pro, and reads back what happened: world rotation of every mapped bone against its source
(should be about zero, since the rests match), root path, joint positions against SAM's, the rig's rest unchanged, and the
mesh's lowest point per frame against the floor. These checks prove the add-on copied the source; they do **not** judge
the motion.

**8. Fix-up layers (not in this kit).** A pose estimate from one picture is never final. The project added small
layers on top of the remap, each with its own check, for the things the estimate gets wrong: a weapon or shield held in
the hand and aimed the way the video shows, the head levelled, feet planted on the floor, arms that must reach an object
the rig's shorter arms cannot reach, a dead character's props falling under physics. They were written around one rig and
its props, so they are not published; the lesson is that each layer needs a check that can fail
(see [`skills/guards-that-can-fail`](../skills/guards-that-can-fail/SKILL.md)).

**9. Review, by eye, on every frame.** Render the result from the video camera and several others (front, both sides,
back, top), lay it over the take, and look at every frame of every sheet (`view_sheets.py` builds the sheets and
muted clips, plus an outline-overlap number per frame that flags a frame where the fit broke). A number can condemn a
correct thing or absolve a broken one; pictures from several angles settle it
(see [`skills/ground-truth-the-metric`](../skills/ground-truth-the-metric/SKILL.md)).

**10. The review gate.** A numbered checklist ([`REVIEW-CHECKLIST.example.md`](../animation/sam3dbody-remap/REVIEW-CHECKLIST.example.md))
is copied for every clip and filled in. `check_review.py` refuses a copy that skips items, ticks a look item without a
`see: <picture> f<frames>: <what it shows>` line, names a picture that does not exist or is older than the blend, pastes
one description on many items, or names pictures that the reviewing agent never opened (it reads the agent's own session
transcript for the file reads). The reason it exists: reviewers wrote short copies of the checklist and ticked the
angle items from numbers. A clip does not go to the person who decides until the gate prints `PASS`.

**11. Export.** One character per FBX, with no key thinning (a simplify option can hide errors between the frames you
check). Re-import the file and compare it with the blend **on every frame**: positions within 10 mm and rotations within
1 degree were the bars. Check that prop (object) motion survived the export, or that the game plays it another way.

**12. Unity.** Import the FBX, play it through the game's real input path, and look at it in play, not only in the
importer. A direct call that forces the animation is a component test, not a player test.

## Traps that cost time

- Left and right swapped for a few frames; the foot-plant says the standing foot moves forward with the body.
- Depth: the picture agrees and the top view does not. A shield "too close to the body" can be a depth error.
- Hands twisted by the same angle on every frame: the A-to-T turn lined up bone directions but not the palm.
- A weapon pointing up in a level thrust, because SAM put the wrong hand on a hidden hilt.
- Smoothing removed a real flick (a fast swing). Keep windows around the hits.
- A check that passes because its expectation came from the output it checks. Derive expectations from something that
  exists before the run.

## Keep your footage

Every render, sheet and clip from a review is evidence of what the pipeline did, successes and failures alike. Save
them next to the work with a one-line note of what each shows, but keep one clip per *new* thing (the first good take,
each distinct failure, a visible change after a fix) so the folder does not fill with the same picture a hundred times.
