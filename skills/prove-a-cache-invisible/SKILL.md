---
name: prove-a-cache-invisible
description: How to guard a cache, memo, pool or incremental rebuild so it provably produces exactly what the uncached path produces. Use when adding or changing any "skip the work if nothing changed" optimisation, or when reviewing one. Covers the suppression-seam equivalence test, id-independent comparison, what a census misses, positive controls that can actually fail, one mutant per key term, and the cache-key omissions that silently break other tests.
---

# Prove a cache invisible

A cache is only correct if it is **invisible**. The test that proves that is the whole price of admission: without it,
the failure mode is not "slow", it is "permanently wrong output that no one notices for weeks".

Condensed for this repo from a longer in-house skill. The examples come from a Unity game (a scoped rebuild of built
structures, and later a round of simulation performance work), but the rules are about caches in general.

## The shape

1. A static seam that forces the old path: `public static bool SuppressRebuild;`
2. One long **mixed** edit script driven through the **real public API**.
3. Run it twice, once scoped and once suppressed, and compare what is on screen.
4. Clear the seam in `TearDown`.

```csharp
var scoped = CensusAfter(EditScript, suppress: false);
var full   = CensusAfter(EditScript, suppress: true);
CollectionAssert.AreEquivalent(full, scoped);
```

## Compare the right thing

**Counts alone pass on stale geometry**, which is precisely the defect. Compare, per piece: owner kind, world pose, mesh
bounds, vertex count, triangle count.

**Make it id-independent.** Ids are never reused, so pass 2 builds `Item_5` where pass 1 built `Item_1`. The first
version of this guard failed on all 91 entries of a scene that was geometrically identical. Group by container, strip the
trailing `_N`, keep the kind; world positions already pin down which object is which.

But **note the coupling**: if any solver breaks ties by id ("higher edge id loses"), the two passes only agree because the
identical script produces the same relative id ordering. Say so in a comment, or a future change to id allocation makes
the test fail for a reason that is not a bug.

## What a census MISSES: check each one deliberately

A mesh census is blind to everything that is not a mesh:

- **`Renderer.enabled`.** An edge left permanently invisible produces a byte-identical census. If the cache interacts
  with a preview/hide path, assert visibility explicitly and drive hide/show in the script.
- **Colliders.** A rebuild that respawned meshes but skipped colliders gives geometry you cannot click or demolish, with an
  identical census.
- **Materials.** Preview-material leaks have shipped before; a census cannot see one.
- **End state only.** Thirteen edits and one comparison hides any transient staleness that a later edit happens to heal.
  Census after **each** edit and compare per step.

## The positive control must be able to fail the way the subject fails

1. **It must change an EXISTING object, not add a new one.** A control that adds a container proves the census notices new
   objects, not that it notices a changed one, which is the only failure equality is looking for.
2. **It must run the way the real caller runs.** The low-level API may not perform the step you are trying to observe (see
   `guards-that-can-fail`, "Check the path you drive actually has the check").
3. **It must exercise the specific mechanism the cache gates.** A tower-shaft cut proves the census can see one eraser
   call. It does **not** prove the census can see a junction notch or a merlon drop, the two cut sites inside the crest
   pass, which are 73.6% of the cost and the only thing the crest cache gates. A cache guarded by a control that cannot
   fail the way it fails is not guarded.

## Know how your census GROUPS things before you count them

The census grouped pieces by `mf.transform.parent`. Anything with its own MeshFilter parented straight to the container
therefore collapsed into the CONTAINER's single entry. Counting entries whose name starts with a prefix returned **0 in a
scene that had two**, and failed a control for a reason that was not the subject. The equality assertion was fine
throughout.

> Count by substring across all entries, or key the census explicitly. And when a count comes back 0, check the counting
> before you believe the scene.

## Assert that the script exercised what it claims

A script placed a node that was **refused every run**, so the guard had been comparing two scenes without it and passing.
Only a coverage assertion noticed:

```csharp
Assert.Greater(network.NodeCount, 0,
    "no node placed, so the special path went unexercised and this compared two scenes "
    + "without it. Widen the offsets - do NOT drop the assertion, which is the only thing "
    + "that noticed.");
```

Add one per mutation kind the script claims to cover. Placement can be refused by terrain grade, so a fixed coordinate is
a coin toss on real ground: try several and fail loudly if none took.

## Fold EVERY input into the key, including static seams

The cache key must cover everything that determines the output:

- **Static suppression seams that change what gets built.** None of several seams was in the key, so flipping one and
  rebuilding became **silently inert**. Worse: flip it while data is dirty and the rebuild spawns wrong geometry *and
  stamps it as correct*, which no later rebuild can repair. Fix: one `static int SeamGeneration`, bumped by each setter,
  mixed into every stamp. (This left a landmine: two control arms survive only because they reload the scene between arms,
  which hands them a fresh component with empty caches. Delete the reload as an "optimisation" and the control silently
  stops controlling.)
- **Sampled inputs are not proved inputs.** Probing terrain at 3 points per edge catches the sculpting the project does; a
  bump raised between samples does not move the key. Document the invalidation call, and note that a documented rule with
  **zero enforcing call sites** is a comment, not a guarantee.
- **Deliberate omissions need a stated reason.** A swing angle is excluded because leaves animate without a rebuild and
  folding it in would respawn the edge every frame of every opening. Write the reason next to the omission or the next
  reader "fixes" it.

## Hash the key over exact bits

FNV-1a over `float.GetHashCode()` (the exact bit pattern, -0 and NaN normalised), not `Vector3.GetHashCode()`, which shifts
components into each other and throws bits away. A collision here does not cost performance, it leaves output permanently
wrong, because the rebuild decides it is already correct.

```csharp
const int HashSeed = unchecked((int)2166136261);
static int Mix(int h, int v) { unchecked { return (h ^ v) * 16777619; } }
static int MixF(int h, float f) => Mix(h, f.GetHashCode());
```

Dirtying too eagerly is FREE (a respawn that was not needed); dirtying too lazily is permanent damage. When unsure, fail
towards rebuilding, and make unknown cases fail that way too (`NeedsEviction` evicts any child whose name it does not know).

## A second instrument, with different blind spots

The equivalence test compares a MESH CENSUS. Rendered proof frames compare the SCREEN. Neither subsumes the other, and the
second is nearly free if the suite already renders: diff the regenerated frames against the versions committed BEFORE the
change. For the scoped rebuild: 34 of 35 frames identical outside the timestamp stamp, the 35th differing by ONE
anti-aliased pixel, across junction types the census guard never builds.

- **Run it with the mask off before concluding.** A masked run hides a region; quote the unmasked numbers and let the mask
  only sort the timestamp from everything else (see `mask-the-noise-not-the-signal`).
- **It cannot catch what the suite does not build.** These frames come from a run that was already green: a second angle
  on the same scenes, not new coverage.

Landing the cache also blinds anything that measured the uncached path: update the performance instruments.

---

## Lessons from a round of cache and pooling work on a simulation hot path

Each of these caught a guard that would have stayed green with the bug in.

- **A cache with no seam: split the cached thing from the verdict, then plant one mutant per key term.** A preview kept its
  prepared geometry per drawn input, while the refusal and builder-access checks were still asked every frame, so the cache
  can never make a refused wall look buildable. List the key terms from the code (the inputs, the selected kit, towers at
  the ends, the dependency check) and plant one mutant per term; each must be red on exactly its own test. Check the
  mutable statics instead of assuming: say in the record that none is read by the cached part, so none belongs in the key.
- **A frame number is not a complete key.** A new object may appear later in the same frame. Keep per-search lifetimes for
  immutable snapshots and rebuild snapshots that must see edits on every gather; test two captures with an intervening
  edit and no frame advance. A scope around a spatial index is only safe if its body cannot mutate the indexed data:
  inspect the transitive calls, including callbacks.
- **Callback exemptions must cover every invocation and diagnostics.** A multicast delegate's `Method`/`Target` describe
  its last target only, so a mutating target followed by an approved pure one fooled the witness. `Exception.Message` is
  virtual, so restoring a cached index before the catch formats the exception lets the getter issue a reentrant query. A
  getter can reach logging, which runs arbitrary code. A property cannot be classified pure from its syntax.
- **A moved footprint can stay in the same broad-phase cell**, so a stale-bounds mutant may still pass its narrow phase.
  Establish the cell geometry before treating a passing mutant as evidence, and keep the failed controls.
- **Pool with exact length, not grow-only.** `Rent(ref slot, n)` reuses the slot only when its Length equals n, and only
  after `Array.Clear`; otherwise it returns `new T[n]`, so the array is indistinguishable from a fresh one to every reader.
  Give a nested (re-entrant) call fresh arrays. One pool per buffer: the compiler catches a pool of the wrong element
  type, not two buffers of the same type sharing one pool, so assert each slot is rented once (reading the IL of the method
  can do it: each pooled field must be the operand of exactly one `ldflda`).
- **A guard whose length never repeats cannot see a missing clear.** The first version used lengths that never repeated on
  consecutive steps; with `Array.Clear` deleted it still passed 3/3. Rent each length three steps running, then run one
  mutant per guarantee (no clear, grow-only, pooling a nested call, no reuse) and require each to turn exactly its own test
  red. For any thread-static take/return scratch, give the guard a validator that runs a small nested solve, and show a
  slot-sharing mutant turning it red.
- **An exact broad phase for a solver whose loop order matters.** If the solver changes values mid-loop, the visit order is
  part of the result: build the candidate list once, keep it in the original order, and use it in every pass. A mutant
  with unsorted candidates changed 3,320 of 20,000 results. Derive the bound from the narrow phase including any comfort
  band and the move budget re-checked after the validator. Real-arithmetic bounds need a float envelope: 2 of 1.67 M pairs
  between the exact bound and the envelope still conflicted. Test the lemma at the envelope, not at the bound.
- **NaN trap.** `if (d2 > r*r) continue;` ACCEPTS a NaN distance. Keep non-finite and huge coordinates as always-candidates
  and make a non-finite, negative or huge query visit everything. Below about 40 entries a grid was slower than the pair
  loop; add an exhaustive threshold.
- **Mutants that stay SAME are unexercised paths, not proof.** A bound-shrink mutant stayed SAME on random worlds because
  the cells were wider than the shrink band; it differed only with pairs placed at the radius (and one ulp either side).
  A stale group set stayed SAME until a whole group left between frames. "Cache ignores owner" stayed SAME until two
  encounters reached an equal sequence number. Report equivalent mutants and say why; a SAME mutant is only equivalence
  evidence beside a DIFFing one. Generate placements from the candidate's own cell-size formula.
- **A flag's OFF path is a control only if it is faithful.** A performance flag's off path was documented as "the
  control", but one site walked a list without the redundant ownership test, so with the index off it saw every blow:
  250 blows off against 249 on. Run the old build with each flag off against the same build with it on before using the
  flag as your control. And if both arms share a changed helper (a cached sort comparer used by both), a mutant of it
  passes every on/off guard: give the OFF arm the pre-change code verbatim, and prove the copy is reached.
- **A guard that compares only sequence numbers cannot see an owner-key bug.** Compare payload fields, and make twin
  encounters equal on every key term except the one under test.
- **A sequence-keyed cache is not exact on the writer's exception path.** `Dequeue`, several calls, `Enqueue(++seq)`: a
  throw between drops an event while the sequence stays put. Add the container count to the key (every Enqueue raises seq,
  every Dequeue lowers the count). An extra key term can only force recopies, and a recopy IS the original computation, so
  it is safe by construction.
- **A cache latched by a flag that only the pass owner resets is stale for any outside caller.** Scope it with an explicit
  in-pass flag; probe with outside calls while the inputs change between them (7 of 25,200 answers were stale before the
  fix, 0 after).
- **Invalidate on a version raised in EVERY mutator of the container, before its notification.** Digests caught "Add
  without the bump" in every battle but not "RemoveAt without the bump", because a removal is always followed by an Add that
  masks it. A white-box test that applies each mutator alone, then compares the memo with the uncached function and asserts
  the mutation moved a sample, caught 6 of 6.
- **Identity keys spare you the collision proof of the index, NOT the test of each key check.** A direct-mapped memo keyed
  by three string OBJECTS passed a mutant without one check, because a sweep almost never puts two keys in one slot. Force
  the collision: a second key that differs in one string only and has a different answer, keeping the other two strings as
  the first key's own objects, with an assertion by reflection that the slot really holds the first key.
- **A fast path that falls back to the original on a fault must catch EVERY exception type**, otherwise another type
  escapes in the fast path's call order, not the original's.
- **A digest that includes performance counters forbids changing how an existing cache fills.** New caches sit beside the
  instrumented ones, or the digest tool excludes named counters and prints which ones moved.
- **Place one mutant at EVERY site that writes the cached state**, not one per cache. A mutant that dropped an add at the
  entry path the real scenes use was SAME on 8/8 battles because no offline battle drove that path.
- **A cache's slow fallback can be dead in every test.** A fallback that runs only on a non-finite sample was reached in 0
  of 45 fresh battles. Turn the fast path's flag off so the fallback becomes the main path, then re-run the digests and the
  mutant (with the flag off the stale-carry mutant differed in 7 of 10). A path that stays unreached either way rests on a
  READ argument; name it as such.
- **A visit-order mutant on an order-insensitive query is invisible.** Prove a reordering with a mutant that changes an
  order the decisions actually read.
- **Digests of lossy outputs cannot prove the inputs exact.** A plan digest hashes facings, which come out of a bearing; two
  predicted values a bit apart can give the same facing. An instrumented build that ALSO computes the replaced value at
  every shortcut (pure calls only) and counts bit mismatches proves the values themselves (790 M checks, 0 mismatches), and
  its gameplay digests must still equal base. Perturb how the cache is called, not only what battle runs: reverse or
  shuffled push order, an extra misaligned push, each plan built twice.
- **A memo of a pure predicate inside one straight run.** When a hot loop asks the same ownership callback several times
  per body, a `struct Run { bool Asked, Holds; }` passed by `ref` lets the first check ask and the later ones reuse it.
  The run ends at the first foreign call (an observer, another body's iteration, a log, a surface or route-cost
  callback), and one run belongs to one loop ITERATION. The exactness argument has two halves: nothing between the calls is
  foreign, and the callback's inputs are not among what the run writes. State the non-exact case: a stateful callback that
  flips its answer between two calls sees fewer calls. Guard each seam with preconditions that prove the seam fired, and
  build the red controls (hoisting the run out of the loop, passing it past the seam) as real compiled trees so the red is
  an assertion, not a compile error.
- **Squared pre-tests.** Skip a square root in a min loop with a relative margin (`dx*dx + dy*dy > best*best*1.00001f`) and
  only while `best` is in (1e-6, 1e18); use +infinity otherwise. A re-cell may keep rows when the cell RANGE is unchanged
  and the entry was not dropped since. A set that is only cleared and added to is a per-object stamp.
- **Give mutant runs a subprocess timeout.** A "no Clear" mutant grew its list without bound and hung. Kill only your own
  child process; a blanket `taskkill /IM` would kill other agents' jobs.

Related: `guards-that-can-fail` (every rule above is an instance of its "neuter the fix" test) and
`mask-the-noise-not-the-signal`.
