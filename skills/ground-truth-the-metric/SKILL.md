---
name: ground-truth-the-metric
description: Before believing a derived measurement, aim it at a subject whose answer you already know. Use when a number you computed (an angle, a ratio, a distance, a coverage score, a search result) is about to condemn or absolve something; when a metric disagrees with a picture; when a gate or bar is about to reject work; when three green instruments all came from the thing under judgement. Covers known-good and known-bad subjects, aggregates mistaken for local measurements, tools refereeing their own damage, consistent signed disagreement, controls whose reference comes from the same image, and searches that cannot find anything.
---

# Ground-truth the metric

A number you computed yourself is not evidence until it has been aimed at something whose answer is already known. Every
measurement is really two claims, *the subject is X* and *my instrument measures X*, and only the second one can be tested
cheaply.

Condensed for this repo from a longer in-house skill. It started on a game character's axe: three different derived
angles condemned an axe that was correct, in a single afternoon, and each cost a render cycle. Two lessons came out of it:
where a thing is measured to be can mislead, and photographs from several angles settle it. A number can condemn a correct thing, and a number can absolve a broken one.

## The rule

> **Rule.** Any metric you derived (an angle, a ratio, a distance in a convention you reasoned out) gets run against a
> KNOWN-GOOD subject before it is allowed to condemn anything. If it fails the known-good subject too, the instrument is
> broken, not the subject. Fix the instrument or throw it away; do not "adjust" the subject to satisfy it.

The known-good subject is usually free and already in the project: the asset pack's own demo rig, the reference model, the
last version that shipped, the neighbouring system that works.

| metric | verdict on the subject | verdict on ground truth | real cause |
|---|---|---|---|
| angle between haft and the other hand | 81.5 deg "wrong" | **147.3 deg** on the pack's own rig | the pack chops ONE-handed; the premise was invented |
| blade plane vs facing, ground-projected | 69.7 deg "hits with the cheek" | **69.8 deg** on the pack's own rig | projecting a tilted axe onto the floor shortens one axis, not the other |
| blade normal vs facing, unprojected 3D | 146.9 deg | **146.5 deg** on the pack's own rig | the assumed mesh-axis convention was never verified |
| hip rise (crouch detector) | 0.968 "healthy" | pack human 0.975 | **the number was right and blind**: it cannot see a lunge, and a lunge was the actual defect |

Three condemned a correct thing; the fourth absolved a broken one. The instrument had never been characterised.

## The tells

- **The subject and the ground truth agree to within noise.** 69.7 vs 69.8 is not a near-miss, it is the instrument
  reporting its own bias twice.
- **A polished third-party asset "fails" your check.** A shipped commercial pack does not contain a woodcutter who hits the
  tree with the flat of the blade. When your metric says it does, your metric is the defect.
- **The metric can only move in one direction.** A hip-rise number detects squats and nothing else. Ask what the number
  CANNOT see before quoting it as reassurance.
- **You reasoned out the axis convention from extents.** Bounding-box sizes tell you which axis is longest, not which one is
  "forward" for the purpose you care about.
- **The number came from subtracting two aggregates.** See next.

## What to do instead of trusting the number

1. **Photograph it.** Ten bearings round the subject, plus a top-down if a facing direction is part of the question.
2. **Put the other object in the scene.** The axe argument ended when a trunk was stood where the axe head was. A thing that
   interacts with another thing should be photographed interacting with it, not measured in isolation.
3. **Render the ground truth into the same frame.** Side by side beats two numbers in a log.
4. Keep the metric afterwards, but **re-label it with what it cannot see**.
5. **Composite first, read it, THEN decide which number is worth measuring**, and put the composite's path in the message
   beside the number.

---

## An aggregate minus an aggregate is not a local measurement

A handover recorded a "medial mirrored outsole rail defect, left -X and right +X reach ~11.8093 mm; lateral edges ~5.731
mm": two numbers, four decimals, a named side and part. It read as a measurement of a place. Both came from one function
subtracting bounding-box extremes. Measured properly (plan-view footprints compared by signed nearest-boundary distance,
binned along the foot axis) the two sides agree to 0.48 mm across 99 bins. There was no rail; the real defect was fore-aft
and no single-axis extent could express it. A repair built to that brief would have ground a symmetric welt off both boots
and fixed nothing.

- **Do not explain the artefact by saying one number was global and the other local.** Both came from the same formula,
  so neither was local by construction. What differed was luck: the two extremes lay 71 mm apart along the foot on one side
  and 0.55 mm on the other. **The tell is the formula, not the outcome.**
- **Locate the extremes before naming them.** The first correction said the smallest x was "at the forefoot". It was at the
  ankle. Being right that a number is an artefact does not make you right about where its inputs live.
- **A coordinate plane is not a frame.** Splitting medial from lateral on the sign of x assumes the part is aligned to the
  world. These feet toe out 5.46 degrees, which moves x by about 1 mm across a 10 mm band. Derive the frame from the
  geometry (PCA of the footprint) and orient it from something external that knows which end is which.

> **Rule.** A difference between two aggregates (bounding boxes, extremes, min/max, totals) is a property of the whole, and
> may correspond to no point in the thing. Before you let a number name a PLACE, re-derive it as a local measurement AT
> that place (a cross-section, a per-vertex value, a slice). If the local version does not reproduce it, the defect is in
> the arithmetic, not the model.

**Suspicious precision is not evidence of care.** "11.8093 mm" carries four decimals of a quantity that was never local.
And the mirror-image error comes while fixing the first: a window "just the foot part" (z 0.02 to 0.15 m) amputated the
boot exactly where it rises at the heel, so the missing shaft read as a 60 mm overhang that did not exist. A filter that
seems obviously safe deletes evidence at precisely the transition you are measuring. Prefer the projection the question is
about: an overhang is what a plan view shows, so let every height count.

## A tool's own counters cannot referee the damage that tool does

A mesh conformer reports how much work it did: vertices moved, vertices still inside the body. Those read like health. They
measure the tool's effort against its own objective, and they get BETTER as the input gets worse in ways the objective does
not mention. A torn-apart boot shaft reported fewer vertices moved (8,719) and fewer starting inside (65) than the clean
baseline, because the tearing had already opened the shell so the conformer had nothing left to push; a textured render
looked smoother. Two independent signals both endorsed the wrecked mesh. What caught it was a metric about the SURFACE,
not about the fitting: `dev[v] = |co[v] - mean(co[neighbours of v])| / median_edge_length`, reporting the count over
2x/3x/5x and the edge-length p99/median. Clean: 141 vertices over 2x, edge ratio 1.87. Wrecked: 5394 and 8.75.

> **Corollary.** When you add a step to a tool, the gate that proves the step safe must not be a number that step's own
> logic produces. Ask what the step could break that its objective function has no opinion about, and measure that.
> Calibrate it on a known-good build and on a known-BAD one first.

---

## When the instrument and the reference disagree

**Consistent SIGNED disagreement indicts the reference, not the instrument.** A working instrument was graded against two
badly built references and both times the failure looked like the instrument's. The first reference was the *planted* area
of a patch that lay mostly behind steel, so it could never report its whole area (3086 px planted, 65 read, "97.9 % off").
The second was corrected to *exposed* area and still failed in the same direction, because its mask came from a
shell-alone render while the instrument derived its equivalent from a body-plus-shell render.

> **Rule.** Random disagreement is evidence about the instrument; **consistent signed disagreement at every size is
> evidence about the reference.** Build the reference in the same scene context the instrument uses, and check the sign of
> the residual before blaming the subject. (The ratio test passed at 7.3 % while the absolute check failed at 98 %: an
> instrument that tracks size faithfully but reports a different absolute quantity is measuring something well, just not
> the thing you named.)

**"Residual > 0" is not a verdict until you run the same instrument on the target.** A reworked shell showed thousands of
mm^2 of visible skin in the underarm band, which reads as unfinished work. The same instrument on the original and on the
welded reference shell gave larger numbers at every bearing: it was armpit and upper-arm skin no torso piece has ever
covered.

**Before blaming the input, build the version of your method that cannot be blamed.** Per-digit fitting plateaued far below
its bar and read as "the shell is the wrong shape". But the transforms were applied by linear blend skinning, so no group
ever received its own transform. The separation was cheap: give every group its own transform HARD on its own vertices, no
blending, tearing allowed. Useless as a deliverable, but a strict upper bound on what any rigid per-bone segmentation can
do; it came out *worse*, which cleared the shell. A throwaway that violates the deliverable's constraints is often the
cleanest instrument available.

**A metric that improves as quality falls has refuted itself.** Crease crispness, counted as high-dihedral edges, scored a
*rejected* mitten at 264 % of reference, because near-180 degree dihedrals are not sharp edges, they are folded ones, and
self-intersection manufactures them wholesale. A groove count meant to measure "do the digits read" went UP as triangles
came down. Check a metric's behaviour at the ENDS before trusting its middle, pair it with one that fails the other way (a
self-intersection count), and always put a **known-bad** candidate in the table.

**An aggregation whose answer falls outside the range of its own inputs.** A tolerance floor derived per hand came out
8.57 mm on one hand and 0.39 mm on the other, and `min()` over the hands would have produced a floor below every measurement
that produced it. When an aggregation puts the answer outside the range of its own inputs, the quantity is the problem, not
the aggregation.

**Record HOW MANY and WHICH, never just whether.** Re-running with the vertex count and ids split one incoherent dataset
into two different defects: a loss whose size grows with the stimulus is caused by the stimulus; a loss that is the **same
single vertex at every magnitude** is a marginal case flipping, and no threshold can ever be derived from it. Design the
remedy so its failure is informative: a fix that cut the suspected cause 32x without changing the symptom falsified the
cause, which is worth more than a pass.

**A duplicate-output tell is only as good as the precision it is printed at.** Three renders all reported 61.19 %
coverage: real, a renderer-culling defect. After the fix three renders reported 52.23 %, which looked like the defect
returning; it was `%.2f` colliding (52.2110 / 52.2038 / 52.2015, three distinct sha256s). Print enough digits that a
coincidence is implausible, compare content digests rather than a rounded statistic, and confirm a suspected collision by
independent measurement.

## Ground-truth a SEARCH before believing what it did not find

Five recorded digests matched nothing, and "matches nothing" was about to become "these bytes are gone". The corpus was a
folder of backup manifests, searched by grep. Then the positive control: grep the same manifests for a digest that
**certainly exists**. Also no hits: the recent manifests recorded `"Sha256": null` for full-additive copies, so the
instrument could not have found anything. Rebuilt by hashing the trees directly, two of the "missing" digests were found
on the backup drive.

> **Rule.** A negative result from an unvalidated search is not evidence. Aim it at something you know is there first. It
> took forty seconds, and the alternative was reporting authored work as lost.

It recurs as a grep over a compressed or binary container (a `.blend` is zstd and returns 0 either way) and as a query
against a corpus whose relevant field is null or empty for the subset you care about.

**A grep over evidence folders also finds the fixtures that test the reader.** A design cited "median 1.2 ms, n = 468,
MEASURED" from a grep that matched 519 files; 512 came from an acceptance-reader's controls, packets written by a fake
engine with 29 unique contents and a hard-coded `1.2 + 0.1 * (Captures % 3)`. Before pooling grep hits as a sample, count
unique file hashes, group by origin folder and drop folders named controls, fixtures, mutants or packets. A value
identical across hundreds of "runs", printed at one decimal, is a generator's tell.

---

## Aim EVERY derived metric at the subject's own body part

A question had to decide whether a glove was mis-rotated or mis-placed. Four derived metrics were built; **three failed on
the character's own hand**, each plausibly. "The finger axis is the long axis of the distal 45 % of the patch" read
65 degrees on a spread glove, because it was the across-the-knuckles axis.

> **Rule.** A metric aimed at a PART needs its ground truth on the **same part of the known-good subject**. "The
> instrument works on this model" is not the claim; "the instrument reads the finger axis as the finger axis" is.

- **Wrong by construction is a category, and tuning does not fix it.** A PCA long axis on a patch wider than it is long, a
  plane through a ring, a centroid track through a region with a lump on one side: each is a different quantity wearing the
  right name. Replace it; do not tune it.
- **The same ruler on both sides.** When a reference is too coarse for your instrument, resample the reference until the
  instrument fits; never swap in a different instrument for the reference side.
- **Ask whether the PIXEL will exist before you measure it.** Rank metrics by what the engine will draw, not by what the
  scene contains. A measurement of geometry the renderer masks is a right measurement of a non-question.
- **A follower that scores far WORSE or far BETTER than its driver indicts the instrument.** A score above the driver is
  impossible; a score far below at ONE joint while every other joint is fine deserves identical suspicion, and does not get
  it, because a low score reads like a defect report.
- **A frame built from the SUBJECT measures the subject's own motion as 0.00.** A frame, axis or origin derived from the
  subject co-moves with it, so any motion measured in it is zero by construction. Capture the frame once at the reference
  pose and hold it.
- **Two implementations of "the same" metric differed by exactly their own epsilon.** A second script that re-implements a
  published metric must reproduce the published number on the published subject before its readings are quoted anywhere
  near it. The epsilon, the reach, the clip and the ray origin are part of the definition.

## Three green instruments whose answer came from the thing under judgement

> **Rule.** For any instrument, ask: *could this number have been produced without the subject being present or correct?*
> An expectation built from the observed output, a preference read from its own history, a liveness check that any moving
> pixel satisfies: each is measuring its own reflection. Derive the expectation from something that exists **before** the
> run (the fixture, the design document, the geometry).

**Score a KNOWN-BAD artefact before tuning any threshold.** A proof clip aimed at the wrong side of a tower filmed a blank
wall for its whole length and passed `DistinctFrames > 1`. Raising the bar to "nine tenths of frames must differ" would not
have caught it: the blank wall scored 186 distinct of 234 captured frames (79 %), the correct shot of men marching past one
door 117 of 160 (73 %). The ratio ranked the bad clip above the good one, because a clip of nothing is mostly shadow drift
while a marching column is mostly similar neighbouring frames.

> **Rule.** Do not tune a threshold until you have scored a known-bad artefact with it. If the bad one outscores the good
> one, the metric is wrong and no threshold will save it. Write both numbers beside the weak guard, keep it as a liveness
> check, and say in the comment what it cannot prove. What actually caught the blank clip was opening the PNG: log the
> frame directory in the test's own output so the next reader can.

Two corollaries about the window a recording is scored over; both change the denominator, not the metric. A recording of an
event starts and ends at the event (filming the courtyard while the men are still outside, or for forty seconds after they
arrive, adds only identical frames of scenery). And a "work in progress" counter is zero on BOTH sides of the work: a
shutter opened on `count > 0` and closed on `count == 0` stopped at frame 25 having filmed five frames of an empty
courtyard. Latch an `everActive` flag before honouring the stop condition; the same asymmetry makes that counter useless as
a "did anything happen" assertion.

## Run every new GATE against "do nothing" before you trust a rejection

> **Rule.** Before a bar is allowed to reject anything, run it on the **untreated control**. If "do nothing" fails your bar,
> the bar is wrong, not the work. Re-derive the bar from what the treatment could DESTROY, and make it relative: a gate on a
> treatment belongs in units of what the treatment could take away, measured against the untreated subject in the same run,
> not in absolute units borrowed from a row that measured a different thing. Keep the absolute number in the log as a
> reading; do not let it branch.

> **Rule.** Anything that defines what a comparison **looks at** (a highlighted set, a camera target derived from it, a
> region mask, a bin edge) must be computed once on the CONTROL and carried. Otherwise the treatment redraws the frame it is
> being judged in, and every such error flatters it.

## Smaller traps, all measured

- **Absolute cutoffs need scale controls.** A review disagreed on three triangle pairs because its endpoint deduplication
  floor was an absolute 1 nm and the real segments were 0.49 to 0.59 nm. Exact rational predicates on the parsed binary
  coordinates confirmed the intersections; a scaled known-answer control exposed the checker. Do not tune a cutoff until two
  algorithms agree, and test the same known intersection at the smallest relevant scale. `scripts/exact_triangle_segment.py`
  is the extracted pure standard-library predicate with five known-answer controls (non-coplanar case only; it is not a
  complete contact classifier). Run it directly.
- **A nearest surface normal does not establish containment.** The sign of `dot(point - nearestSurfacePoint,
  nearestFaceNormal)` is a local half-space result; concave fingers, folds and mesh boundaries can make it negative for an
  outside point. One checker reported "inside" vertices around 0.26 m from a curled hand and caused a pointless 55 mm
  offset experiment. The replacement used three-direction ray-parity votes plus unsigned clearance, calibrated with known
  internal and external points and a deliberately translated prop. Keep the queried point, nearest point, normal and
  distance in the diagnostic.
- **A red control whose reference comes from the same image is not a control.** A metric compared forest pixels to grass
  medians measured from the same frame; the red control was a pure magenta frame, expected to score 0, and scored 1.000
  because the "grass" references were magenta too. Keep the references real and corrupt ONLY the tested region.
- **A pass exactly at the bar under a truncating instrument is not a pass yet.** The bar was "ramp error <= 10"; the render
  printed exactly 10.0 through an `int()` truncation and 10.03 without it. When a number lands on the bar, recompute it at
  full precision on both sides and report it as marginal with both readings.
- **A multi-agent run record's `totalTokens` is the sum of each agent's LAST request context, not tokens processed.** On
  one 11-agent run it was 2.64 M against 110 M when every request was summed with cache reads (41.8x), and 1.11x without
  cache reads; across 202 runs one helper found about 18x and another 1.24x because they used different definitions, and
  both were right. Name the metric beside the number, and do not quote the record's total as work done or cost.

## Cost of skipping it

An afternoon, four render cycles, and two false defect reports written up as real. The ground-truth check that resolved it
each time took one extra instantiate in the same scene.

Related: `guards-that-can-fail` (the same discipline aimed at tests), `mask-the-noise-not-the-signal`, `prove-a-cache-invisible`.
