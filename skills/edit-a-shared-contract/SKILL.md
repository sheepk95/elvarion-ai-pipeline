---
name: edit-a-shared-contract
description: Change a file other agents and tools depend on - a layout table, a module-of-record, an append-only ledger, a manifest, any artefact whose bytes or digest something else pins. Use before editing any shared record, before running a script named pin/verify/check/guard, when a "surgical" edit breaks tools that never read the field you changed, when a contract number has been transcribed into other files, and when deciding whether to fix forward or roll back. Covers grepping the digest before the edit, append-only versus byte-extension, asymmetric guards on stale copies, and restoring by two independent routes.
---

# Editing a shared contract

Condensed for this repo from a longer in-house skill. Every rule came from an incident where **every invariant checked
was internal to the file, and the thing that broke was external to it.**

A shared contract is any artefact whose consumers are not in the same directory: a layout table, a module-of-record
file, a manifest, a pinned fixture. It has two kinds of correctness, what it *says* and what its *bytes* are, and the
second one is usually the one that breaks.

---

## 1. Before touching it, grep the tree for its own DIGEST

A table edit was as careful as one can be made. The pre-image round-tripped byte-exactly before anything was written;
totals were asserted unchanged; rectangles were checked pairwise disjoint and in bounds; untouched entries were compared
equal to the pre-image; the write-back was re-read and re-hashed. Thirty-two fields changed, none removed.

The next command in the workspace failed, and so would every other agent's:

    EffectiveRefusal: [TABLE_SHA_MISMATCH]

The constructor under **every coverage gate in the project** loaded its exclusions through a module that pins the
table's **whole-file sha256**. Changing one field in one entry invalidated it exactly as thoroughly as corrupting the
file. A grep for the old hash found it in six live pin/guard scripts plus three pinned record payloads, most belonging to
another agent's close-out chain.

```bash
git -C "$REPO" grep -n "$OLD_SHA256"        # one command; this IS the blast radius
grep -rn "$OLD_SHA256" --include='*.py' --include='*.json' .
```

> **Rule.** Before editing a shared artefact, grep the tree for its current digest. That one command enumerates every
> consumer that pinned it, which is precisely the set a "surgical" edit will break, and precisely the set no amount of
> internal validation can reveal.

**Roll back first, discuss second.** Restoring the verified pre-image, re-hashing, and re-running a real consumer took
under a minute, while every other agent kept working. Fixing forward would have meant re-pinning another agent's
attestations while its gate was still blocked.

**Do not silently re-pin what you just changed.** A pin tool's literals were transcribed from a work order written before
the script existed, "so this is a pin, not a self-measurement". Bumping the hash from your own edit is a two-character
change that **converts an independent attestation into a self-measurement**. Propose a structural fix instead (pin a
content digest over the one entry the oracle is about, which your edit leaves byte-identical) and let the guard's owner
decide.

**Another structural fix: a versioned sibling file.** When a value in a whole-file-pinned contract must change and the
consumer census can only be bounded, never proved complete, leave the old file byte-identical for good and publish the
change as `name-v2.json` beside it. A consumer reads v2 only by naming its path and hash in its own release. Every old
guard, attestation and frozen copy keeps its meaning, and an incomplete census stops mattering, because nothing changes
under a consumer that has not opted in.

---

## 2. "Append-only" and "the new bytes extend the old bytes" are different guarantees

An append-only record was extended with a new top-level key and, for a reader's convenience, a sibling key inside an
existing block. The writer refused: *"the new bytes do not extend the old ones - the serialiser reordered or reformatted
pre-existing content."* It was right. Nothing was removed or changed, so the leaf-value check passed, but **a key inserted
mid-document pushes every subsequent line**, so the file was no longer the old file plus a suffix. On an 800 KB record
that many agents pin, "semantically a superset" and "byte-identical up to the tail" are not the same promise.

> **Rule.** Layer the checks so the cheap one cannot substitute for the strict one. The leaf diff catches a deletion or a
> reword; the **byte-prefix** check catches a reformat that preserves meaning. Placement convenience is not worth
> weakening a structural guarantee: put the correction at the top level and add a pointer.

### Prove append-only against the file as it is NOW, not as you read it

The record was read early at 113 keys. By the time the append ran it held 114: another agent had landed a key in between.
Writing back a structure built from the early read would have made that key **vanish**, and the write would have looked
completely clean. The harness that saved it never used the early read as a base:

1. re-read immediately before the write;
2. deep-copy *that* as the pre-image;
3. after writing, re-load and require key count exactly +1, every pre-existing key byte-identical, and the key ORDER
   unchanged;
4. restore the raw pre-image and exit non-zero on any difference.

> **Rule.** Append-only is a property of the WRITE, not of your intent. Verify it against the bytes you are actually
> overwriting, and say in the report when the file moved under you.

### An append-only CORRECTION must not stop the rule refusing

A ruling made a live artefact authoritative for seven stale stamps and rewrote none of them: the identity rule keeps
refusing all seven. That is the design, and it is also the thing most likely to be quietly wrong in the other direction (a
write that actually repaired a field looks like success everywhere except in a check nobody ran). So the check is aimed at
the LIVE record after the write, with positive arms (inputs that must be accepted) beside the refusals; without them,
"everything refused" is also what a rule that refuses unconditionally reports.

> **Rule.** A synthetic guard proves the code is right on fixtures; only a check aimed at the LIVE record proves the
> record is still refused. Only the second can be broken by writing an edge.

### Derive the formatting convention from the bytes; never hardcode it

A shared writer re-encoded the parsed document and refused unless it reproduced the file byte for byte. **The encoder
hardcoded CRLF.** A concurrent agent's append wrote the file with LF endings, and from then on the shared writer refused
for EVERY agent, including the one that caused it. Try each newline and trailing-newline combination, keep only the one
that round-trips exactly, never "close enough".

> **Rule.** A formatting invariant asserted by a shared tool must be derived, not assumed. And **do not repair a shared
> tool other agents are mid-write in**: route around it, record the fault where the next agent will read it, and let the
> fix land when the window is quiet.

---

## 3. A script named `_pin_*` or `_verify_*` may be a WRITER

A ruling restructured six pin/guard scripts, and the obvious next move was to run each to confirm it still passed. Three
of them **regenerate a record payload as their normal output**; running them rewrote the exact three files the ruling said
not to edit. One was a superseded writer that replaced a current-generation record with an older generation of the same
document. A sha comparison would only have said "differs"; **diffing the parsed content** revealed a whole different
`configuration_id`, the difference between "restore a field" and "you resurrected a dead generation".

```bash
grep -n "open(.*'w'\|json\.dump\|save_as" <script>      # one command, before you "just smoke it"
```

> **Rule.** "Pin", "verify", "check" and "guard" in a filename predict nothing about side effects. Ask what a script
> WRITES before running it as a check.

**Restore from an independent copy, then reproduce it a second way.** A backup mirror supplied the pre-run bytes; one
record was additionally re-derived by re-running its pin with the input temporarily swapped back to the pre-image, and the
output matched byte for byte. Two independent routes agreeing is what makes a restore trustworthy rather than hopeful.

**Then make the mistake unrepeatable, not just repaired.** The replacement smoke test evaluates each script's gate
condition directly against the live data and never executes any of them. A smoke test that mutates the thing it is
checking is not a smoke test.

---

## 4. A stale COPY of a contract number fails loudly or silently by DIRECTION

One amendment moved four numbers at once (a window, a safe box, a budget and a bone list). Four other files carried
transcribed copies. Grepping the old literals found all four in a minute; they were **not equally dangerous**:

| copy | kind | consequence |
|---|---|---|
| a probe's `SAFE = (...)` rectangle | stale **window** | silent: scores a real bake as "outside the cell" |
| a run script's `BUDGET = ...` | stale **ceiling** | silent: every tier passes with budget unspent |
| a script's list of 6 arm bones | stale **subset** | silent: weight is RENORMALISED onto the survivors |
| a quarantined script's constants | stale, cannot execute | harmless |

The third is the worst. That list is a whitelist of vertex groups the derived meshes are rebuilt onto: the code wipes every
group, recreates only the listed ones, then **renormalises to sum 1**. A bone the contract lists and the list omits does
not go missing, its weight is *redistributed onto the bones that made the list*: a vertex at 90 % finger / 10 % forearm
comes out 100 % forearm, and a "vertices took no weight" check cannot fire because the vertex did take weight. **A guard
that only catches the empty case is blind to the diluted one.**

> **Rule 1.** Do not transcribe a contract number; **read** it. The fix to the probe was not `240 -> 304`, it was deleting
> the literal and loading the value from the contract.

> **Rule 2.** Where a literal must stay, guard it **asymmetrically, by which direction is silent.** For the bone
> whitelist: MISSING (the contract has a bone the list lacks) refuses, because that is the renormalising direction; EXTRA
> only prints a note, because a superset renormalises nothing away. A symmetric equality check would have blocked an agent
> that had nothing wrong.

**When a stale constant is a symptom of a stale DESIGN, repairing the constant is worse.** The budget was not updated from
340 to 458: that tool also re-skinned to the old bone count and assumed an old source, so quietly correcting the number
would have made the one visible symptom go away behind a constant that now looked right. It refuses instead; repairing the
constant removes the evidence.

### A mirror's safe direction on a SNAPSHOT is its silent direction on an EDGE

A watcher wakes a worker when its "eligible ready" projection gains an order. The projection mirrors the queue's claim
predicate. The queue then tightened two rules; the mirror kept the old ones, so it was a strict SUPERSET of what could be
claimed. Judged on one snapshot, that is the benign direction (at worst a spurious wake). Judged on the TRANSITION it is
the silent one: an order the mirror already lists cannot be "added" when its blocker is released, so the release wakes
nobody. 7 of 14 dynamic cases missed the wake under the new queue and 0 of 14 under the old; the 30 static scenarios
passed against both.

> **Rule 3.** When a copy of a predicate decides WHEN something happens, check its direction on the edge, not on the state.
> Mirror exactly, by reading or importing the source predicate, and pin a drift test that drives BOTH through the
> transition: before, blocked, released, re-checked.

> **Rule 4.** A change detector over JSON must compare canonical encodings, never Python `==`. `1 == True == 1.0`, so an
> edit from `1` (refused) to `true` (accepted) produced an empty diff and no wake. `json.dumps(v, sort_keys=True)` tells
> them apart.

> **Rule 5.** Read the authority's exception boundary together with its predicate, and mirror the mapping exactly. A
> lenient mirror lists orders the authority refuses (a missed wake later); a strict mirror with no mapping raises and
> stops every idle worker's waiter; the right one maps exactly the exceptions the authority maps to "refused". Being
> louder than the authority is safe; being quieter is the missed wake.

> **Rule 6.** A mirror names the authority bytes it mirrors (record their sha256), and its tests default to those bytes.
> A differential control that defaults to "the nearest live contract" measures whatever was deployed that day, not the
> mirror under test. Checking the live authority is a separate, explicit deploy step.

---

## 5. A stored baseline has a CONFIGURATION attached, and an amendment can expire it

An instrument re-measured a recorded reading on the unmodified subject before reporting any "after" number, and exited:
recorded 3.510, remeasured 9.360. The reflex is to hunt the harness. The cause was an earlier amendment that had added
two parts to a module's hide list after the baseline was measured. The control was not detecting a broken instrument; it
was detecting that **the world had moved underneath a stored baseline**, which is the more valuable thing to catch. (It
also turned out to be a live shipping regression: the module hid the hands while carrying nothing to cover them.)

> **Rule.** Any recorded number a contract can invalidate needs the contract state stamped beside it. Re-anchor the
> comparison instead of forcing the old one: same harness, same LIVE contract state, same frame, only the subject
> changes. The historical number becomes context, not the basis.

---

## 6. Attribution: date the artefact, do not infer from who wrote last

Two records named one agent's appends as the writes that converted a shared record to LF. Both were wrong, and both got
there the same way: *the file is LF, that agent wrote most recently, therefore that agent did it.* Dated per-batch
snapshots made it answerable: counting CR and LF bytes across the series took one command and showed the conversion
happened ninety minutes before the accused agent arrived, and that it had **preserved** what it found.

> **Rule.** "Who touched it last" is a hypothesis; a dated artefact series is a measurement. When a brief hands you a
> causal claim, the claim is a premise to check, not a fact to act on.

## 7. A provenance line whose file cannot be opened is decoration

A battery recorded its subject as a path that stopped existing when copies were moved; the subject had meanwhile been
REBUILT at the new location. Re-running against the files that exist reproduced every number exactly, which is the answer
one wants and not one to assume.

> **Rule.** After any move or rebuild, re-measure rather than reasoning about whether the move could have mattered, and
> have the packet generator hash the subject at pack time, so an unverifiable path shows up as a missing line instead of a
> plausible one.

## 8. Numbering and shared append-only logs

When several agents append to one numbered log, numbers collide. Do **not** renumber mid-file: that is an edit to a shared
document while others are live, and a lost update is worse than a duplicate heading, especially once a record cites
entries by number. Flag the collision in the file, keep your numbers, and resolve at window close with a prefix per agent or
a claimed-range register.

## 9. A tool's own results file is a contract too

Eight clips were measured and written to `results.json`. One clip was re-run under a corrected check and the log came
back holding **only that clip**. Seven measurements were gone, invisibly, because every render was still on disk.

> **Rule.** A tool that always writes `<fixed name>.json` must **merge**, carrying forward every entry this run did not
> produce, and must **refuse to merge across different inputs**, keyed on a digest of what was measured. Silently merging
> measurements of two different subjects into one table is worse than losing a row, because it cannot be detected
> afterwards.

Prove the merge on the next run by printing both lists: `clips in log: [9 clips] | carried [8 clips]`. `clips in log`
alone would be satisfied by a clobber that happened to re-measure everything; `carried` can only be non-empty if the merge
ran.

---

## 10. Small habits from the same incidents

- Generate approval files by code from the same hunk list that builds the staged copies, and re-assert the live file's
  sha256 at generation, so approval text cannot drift from what was tested.
- When adding a type or key to an existing immutable command, keep legacy payloads replayable, refuse a type change on
  replay, and retain the key through copy and change paths.
- A fix recipe applied word for word can carry its own bug (a wrong guard, a claim true only on the first step, an "every"
  that is not). Probe a clause from its own bytes, not from the author's description of it.

## Related

- `verify-on-a-shared-dirty-tree` (in this repo): the same problem for source code and commits.
- `guards-that-can-fail` (in this repo): the plant pair that proves a narrowed guard actually narrowed.
