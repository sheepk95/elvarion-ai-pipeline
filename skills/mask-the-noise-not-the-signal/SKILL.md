---
name: mask-the-noise-not-the-signal
description: Calibrate a mask, filter or threshold that suppresses known noise in a comparison, without turning it into a blind spot. Use when a diff is drowned by a timestamp, watermark, build id, random seed or any per-run artifact; when setting the pixel box or regex a comparison ignores; or when identical inputs report as changed. Covers why a diff bbox is the wrong ruler, detecting noise by its own signature, dilating instead of loosening, and proving a mask change with planted controls.
---

# Mask the noise, not the signal

Written from a game's proof-render pipeline. Every render bakes a
`PROOF <timestamp>` watermark for freshness, so every diff sees it. A mask was added to
ignore it. The mask was set from **the region where two frames disagreed** — and got the
watermark's position wrong twice, each time in a way
that quietly corrupted a number someone then quoted as evidence.

> **A diff bbox measures where two samples DIFFER, not where the artifact IS.**

Two frames captured the same day share the date digits, so the diff only lights up the
*time* digits and the bbox looks narrow. Set your mask to that bbox and it fits — until a
run crosses midnight, the date digits change too, the bbox jumps 38 px left, and four
byte-for-byte-equivalent frames report as changed.

The first version of the same bug ran the other way: the mask covered one stamp variant
and a **six-pixel sliver** of the other, so a real ~6,000 px difference reported as
"~190 px in a 6x45 box" — and that 190 went into a commit message as proof nothing had
moved. The conclusion happened to be right. The number was the residue of an instrument
blanking the thing it was measuring.

---

## 1. Calibrate against the artifact, never against a difference

Find the noise by its own signature and measure *that*. Signature first, position second —
position is a consequence and it moves.

For a watermark: it is drawn in a known colour. `TextMesh(1, 1, 0.4)` at alpha 0.9
composites to a strongly red+green, weakly blue pixel, which nothing else in a green-and-
grey scene is.

```csharp
static bool StampPixel(int r, int g, int b)
    { return r >= 150 && g >= 150 && (r - b) >= 40; }
```

Then scan real samples for it and print the union of the extents. Ten seconds of scanning
replaces a guess that has already been wrong twice, and it is a script worth keeping:

```
economy-1-woodland.png     10967 px  x[113-897] y[756-803]  (1600x900)
economy-3-ghost-too-poor   10967 px  x[113-897] y[756-803]  (1600x900)
UNION over 5 frame(s):  x[113-897] y[756-803]
```

Identical pixel counts across unrelated scenes is the tell that you have isolated the
artifact and nothing else. The box that had been in use was `x[594-1010]` — missing about
**480 px of stamp** on the left while covering 113 px of innocent scene on the right.

> **Rule.** If the same measurement is wrong twice, the ruler is wrong, not the reading.
> Change what you measure, not by how much.

---

## 2. Mask the artifact's shape, not its bounding box

Once you can detect the noise per-sample, stop using a rectangle. Ignore a pixel *because
it is the artifact*, not because it is near it.

```csharp
// Masked if EITHER sample carries the artifact here: the glyphs move between
// runs, so a pixel that was stamp in the before and scene in the after is
// still the artifact's doing and still uninformative.
core[i] = StampPixel(before) || StampPixel(after);
```

Two properties a box cannot have:

- **Scene pixels between the letters are still compared.** A box blinds its whole area;
  a shape blinds ~15% of it.
- **It survives a resolution change.** Keep any residual geometric guard as a *fraction*
  of the frame (`y/H` in 0.78–0.95), because a camera-pinned artifact moves with the
  render size. An absolute pixel box is only ever correct at one resolution — and nothing
  warns you when someone renders at another.

---

## 3. Keep the detector strict; dilate the result

Anti-aliasing leaves a halo the strict test misses. The tempting fix is to loosen the
threshold — which is how a mask starts eating sunlit stone.

Grow the mask instead. Dilating a strict core by 2 px catches every halo pixel and, by
construction, can never fire where there is no artifact nearby.

```
core alone:        943 px of halo still reported on identical frames
core + 2px dilate:   0 px   -> "identical"
```

> **Rule.** Loosening a detector widens the blind spot everywhere. Dilating widens it only
> next to a real detection. Prefer the one that stays local.

---

## 4. Prove a mask change with planted controls

A mask is a blind spot you are choosing on purpose, so a change to one is never verified
by "the noisy frames went quiet." That is the easy half, and a mask that ignores
everything passes it.

Plant known changes — especially **inside the region the old mask covered** — and confirm
each is still caught:

| plant | where | result |
|---|---|---|
| 20x20 magenta | outside the band | 400 px — caught |
| 18x12 near-black | inside the old box, under the text | 216 px — caught |
| 5x5 magenta | inside the old box, between two glyphs | 15 px — caught |

All three were `identical` under the old box mask. Run the noisy pair too and confirm it
now reports `identical`, and run `-NoMask` and confirm everything reports changed — that
last one proves the mask is the reason, not a broken comparison.

---

## 5. Make every masked run confess

A masked comparison must print its own blind spot in its own output, every time, in the
terms a reader can act on:

```
masked: stamp-coloured pixels in the lower-left band are NOT compared -- a
regression that is itself pale yellow and sits under the timestamp would hide
there. Re-run with -NoMask before concluding a frame is unchanged.
```

Name what can hide, not just what is hidden. "417x101 px is not compared" is a fact;
"a pale-yellow regression under the timestamp would hide" is a fact someone can check.

---

## 6. Pillow RGBA diffs can report an empty box while RGB changed

`ImageChops.difference(before_rgba, after_rgba).getbbox()` uses Pillow's alpha-only
bounding-box behaviour by default for RGBA images. If the renders have identical alpha but
different shading, the difference image's alpha band is zero everywhere and `getbbox()`
returns `None` even while thousands of RGB channels differ. A tower comparison
first reported zero changed pixels this way while its histogram already counted 4,734
changed colour channels.

Use `difference.getbbox(alpha_only=False)`, or convert both inputs to RGB before measuring
the box. Count changed pixels independently of whether the box is empty, and plant a pair
whose RGB changes while alpha stays fixed. The histogram disagreeing with the bbox is the
tell that the ruler is broken.

Related: `guards-that-can-fail` for instruments that cannot fail, and
`prove-a-cache-invisible` for the same shape in a different disguise: a cache that
blinds every probe that measured the uncached path.
