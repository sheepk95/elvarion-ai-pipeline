# Review checklist (example master)

An example of the master checklist that `check_review.py` reads. Copy it to `REVIEW-v<N>.md` next to your review
renders, tick every box, and run `check_review.py` on the copy before a clip goes to the person who decides. Edit the
items to fit your project; if you change the numbering, change the `LOOK` set at the top of `check_review.py` to match.

How to fill a box (the gate enforces it):
- `[x]` done and fine, `[!]` done and wrong (name the video frames of the fault, e.g. `f12, f30-48`), `[-]` does not
  apply (say why, 3+ words). `[ ]` is not allowed (section 11 may stay blank until the person passes the clip).
- Items marked (LOOK) are judged by eye. They need a proof line under the box:
  `see: <picture path> f<frames>: <what the picture shows at those frames>`
  and the picture must have been opened by you (the gate reads your transcript). A number is not a look.

Use a separate `reason: why this does not apply` line for each `[-]` item, indented by two or three spaces; indent
`see:` evidence the same way. Quote paths containing spaces with backticks, single or double quotes.
Keep each box's wording and Markdown formatting exactly as in the master and in its original numbered section;
change the mark and add indented evidence or reasons below it. Section 10 questions must also remain unchanged.
Use the simple layout shown: complete prompts on checkbox lines with at most three leading spaces, outside HTML
comments and fenced code. Multiline prompts and nested lists are unsupported; see the README for the parser limits.
Raw HTML tags and declarations are unsupported; angle-bracket placeholders in single-line inline code are allowed.

## 1. Setup (numbers)
- [ ] **1.1** The take, the SAM run folder and the blend reviewed are named at the top of this copy, with their dates.
- [ ] **1.2** `run.json` says frames_done equals the number of frames you meant to run; no frame was skipped for "no box".
- [ ] **1.3** The checkpoint passed `verify_checkpoint.py` (ALL_MATCH) before the run.

## 2. The take and SAM's fit
- [ ] **2.1** The key-frame sheet of the take was made and the boxes sit on the right person on every key frame.
- [ ] **2.2** (LOOK) SAM's overlay sheet for each person: the skeleton lies on the body at the key frames, no limb swapped.

## 3. Body, frame by frame
- [ ] **3.0** (LOOK) Facing: the body faces the way the take shows at every key frame (`facing_scan.py` found no flip).
- [ ] **3.1** (LOOK) Head: tilt and turn match the take.
- [ ] **3.2** (LOOK) Spine and hips: lean, twist and height match the take.
- [ ] **3.3** (LOOK) Left arm: shoulder, elbow and wrist match the take.
- [ ] **3.4** (LOOK) Right arm: shoulder, elbow and wrist match the take.
- [ ] **3.5** (LOOK) Legs and knees: bend and direction match the take; no knee flips.
- [ ] **3.6** (LOOK) Hands and fingers: open or closed as in the take.
- [ ] **3.7** (LOOK) Whole body laid over the take (the `over` column): the outlines agree on every row of every sheet.

## 4. Things held
- [ ] **4.1** (LOOK) The weapon or tool is in the right hand and stays there while held.
- [ ] **4.2** (LOOK) Its angle matches the take at every key frame.
- [ ] **4.3** (LOOK) Its length and depth: it reaches what it should reach, and does not pass through the body.
- [ ] **4.4** (LOOK) The shield or second object sits on the right arm, the right way up, the right face to the camera.
- [ ] **4.5** (LOOK) Release and pick-up frames: nothing snaps or floats.
- [ ] **4.6** (LOOK) Objects do not pass through each other, or through the person holding them.

## 5. Floor
- [ ] **5.1** (LOOK) Feet are on the floor when the take's feet are.
- [ ] **5.1b** (LOOK) Look at the lowest point of the body in the side view: no sink, no hover.
- [ ] **5.2** (LOOK) A planted foot does not slide while it should be planted.
- [ ] **5.3** (LOOK) A lying or falling body ends where the take ends, flat on the floor.

## 6. Motion over time
- [ ] **6.1** (LOOK) Played at the take's speed: the motion has the same rhythm as the take.
- [ ] **6.2** (LOOK) Played at half speed: no pops, flips or one-frame jumps.
- [ ] **6.3** (LOOK) Smoothing did not remove a real move (a hit, a catch, a flick).
- [ ] **6.4** (LOOK) The first and last frames match what the game will blend from and to.
- [ ] **6.5** (LOOK) Root travel: the person ends up where the take ends up.

## 7. Other angles
- [ ] **7.1** (LOOK) Front view, every key frame.
- [ ] **7.2** (LOOK) Side view (left), every key frame.
- [ ] **7.3** (LOOK) Side view (right), every key frame.
- [ ] **7.4** (LOOK) Back view, every key frame.
- [ ] **7.5** (LOOK) Top view: depth is plausible (SAM guesses depth from one picture).

## 8. Two people or a person and an object
- [ ] **8.1** (LOOK) They are the right distance apart at the moment of contact.
- [ ] **8.2** (LOOK) The blow or touch lands where the take shows it landing.
- [ ] **8.3** (LOOK) Neither person passes through the other.
- [ ] **8.4** (LOOK) Eye lines: they look at what the take shows them looking at.
- [ ] **8.5** (LOOK) After the contact, the reaction starts on the right frame.
- [ ] **8.6** (LOOK) Both people are in one world at the same scale and floor height.

## 9. Export
- [ ] **9.1** The export has the frames, frame rate and bone names the game importer expects.
- [ ] **9.2** The exported file was re-imported and compared against the blend (positions in mm, rotations in degrees).
- [ ] **9.3** The comparison was run on EVERY frame, not only the key frames.
- [ ] **9.4** No key-thinning (simplify) was applied to the export, or it was shown to stay inside the bars.
- [ ] **9.5** Object (prop) animation reached the export, or the game plays it another way (say how).
- [ ] **9.6** (LOOK) The re-imported file, rendered, looks like the blend you reviewed.
- [ ] **9.7** File names follow the project's naming rule.
- [ ] **9.8** The review renders, sheets and clips are saved next to the export (keep every recording).
- [ ] **9.9** (LOOK) The clip as it will be shown to the person who decides: the final frame-by-frame sheet.

## 10. Questions (answer each in a sentence; no id)
- [ ] What would a person watching this clip say looks wrong first?
- [ ] Which frame are you least sure about, and why?
- [ ] What did you not check, and why?

## 11. Sign-off (stays blank until the person passes the clip, then `--final yes`)
- [ ] **11.1** The person who decides has seen the clip and passed it.
- [ ] **11.2** Anything they asked to change is listed and done.
