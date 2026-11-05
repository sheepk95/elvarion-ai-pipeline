---
name: guards-that-can-fail
description: Write an automated guard (a test, a gate, a validator) that can actually fail, and prove it did. Use when adding a test for a cost, a gate, a refusal or an approved number, when a suite is green and the claim is "it is covered", when a test starts failing and you are about to call it a regression, when retiring or deleting a test, or when reviewing whether a test tests anything. Covers neutering the fix, expectations read from the code under test or from the run's own output, assertions that hold by construction, born-red tests, and names that promise more than they measure.
---

# Guards that can fail

Condensed for this repo from a longer in-house skill (the long version also carried about 280 incident notes tied to one
game's code, which are not published). The examples are Unity / C# / NUnit, but the rules are about tests in any language.

The headline case, from a completion review of a game's building economy:

> **Change `CostPerUnit` to 2 and the entire suite stays green.**

Three tests guarded the build cost. Two of them could not fail.

---

## 1. Neuter the fix and watch the test go red

Before claiming a guard exists, break the thing it guards and re-run. If the suite stays green, you have a test, not a
guard.

```bash
# change the constant, run only that fixture, expect RED
# restore, re-run, expect GREEN, and QUOTE BOTH RESULTS in the commit message
```

The lesson of that review: the tests *"asserted the implementation instead of the outcome, and did so for two days."*

> **Rule.** A guard is not verified by passing. It is verified by failing when it should. Report both numbers, the red run
> and the green one.

**Neuter each case, not just the fix.** Removing the fix only reddens the cases that need it; a "fresh name still installs
normally" case stays green under that neuter and so is not yet proven. Run more than one neuter, one per kind of case: the
fix removed (the refuse and rename cases go red), the fix over-applied (the check ignores its key and blocks everything, so
the "normal path" cases go red), and the wiring removed (the live registration emptied, so the registration case goes
red). Report which neuter reddened which case; every new case must go red under at least one.

**One mutant per guarantee, run alone.** When many planted faults give a healthy FAIL count, plant each fault alone and
require its own line (and plant the floors too). A mutant that is a no-op, or one that an earlier check already makes
fail, adds nothing. A wrong-but-valid mutant (it compiles, it runs, and it changes behaviour the guard cannot see) needs a
second guard. Give every mutant run a subprocess timeout: a "no Clear" mutant grew its list without bound and hung.

## 2. Never read the expected value from the code under test

```csharp
Assert.AreEqual(Tool.CostPerModule * 6, spent);   // asserts NOTHING about the approved number
Assert.AreEqual(24, spent, "design doc: 24 units = 6 modules = 24 wood");  // asserts the approval
```

The constant appeared on the *expected* side of every cost assertion, so the approved numbers (4 and 20) were asserted
nowhere. A constant on both sides of `AreEqual` is a tautology dressed as coverage.

> **Rule.** One literal assertion per approved number, with the document that approved it quoted in the message. If a
> designer agreed to a number, a literal must defend it.

### 2b. An expectation computed from the RUN is the same tautology, one level up

This is the version that survives review, because the expected side is *computed* and looks like work. A ring-of-doors
guard had to prove each man climbs the door nearest to him **among the doors that serve**. It defined the serving set as
the doors the men actually used. If all fifty men use one door, that IS the serving set, every man is trivially at his
nearest serving door, and the guard passes on the exact behaviour it exists to forbid. It logged one serving door, fifty
men, GREEN.

The honest expectation is read off the FIXTURE and fixed before the click:

```csharp
var serving = new List<int>();
for (int i = 0; i < RingItemCount; i++)
    if (i != InwardItemIndex) serving.Add(ring.ItemIds[i]);
Assert.AreEqual(RingItemCount - 1, serving.Count,
    "the ring fixture did not produce the expected outward doors");
```

> **Rule.** Ask where each side of the assertion came from. If the expected side was derived from the run (a set built
> from the observed output, a baseline recomputed after the operation, a tolerance scaled by the result), the guard cannot
> fail in the direction you care about. Derive expectations from the FIXTURE, the design document, or the geometry, all of
> which exist before the click.

A validator rule has the same hole: if it reads the ruled number (an edge, a gap, a place) from the document it checks, a
self-consistent wrong document passes. The rule must read the number from the ruling.

## 3. Check the path you drive actually has the check

A test called `WithNoEconomyEverythingIsStillFree` asserted that placing a line returned a positive number.

> `PlaceLine` has no affordability check in **any** configuration; cost lives in the tool. This line passes
> identically with the economy present and empty, so it cannot detect the failure it names.

Cost lives in the **tool**; the test drove the **network**. Drive the tool's own draft and commit steps and the test
becomes what its docstring claims.

> **Rule.** Before writing the assert, grep the method you are calling for the guard you think you are testing. If it is
> not in there, you are testing a different layer.

**The same trap in reverse: the WORK may not be in that layer either.** A control meant to exercise junction crest cuts
called the network's place-line method and measured no crest at all, because that method spawns the edge and stops;
opening the battlements is the CALLER's step (the tool and the perimeter-wrap helper each call the refresh after
committing). The test looked reasonable and asserted on a scene where the feature had never run.

> **Rule.** When you drive an API instead of the tool, list what the tool does AFTER that call and do it too. Grep the
> production call sites of the method you are driving; what they do on the next line is part of the operation.

Symptom to recognise: the assertion fails at zero (zero patches, zero cuts, zero cost) rather than at a wrong value. Zero
usually means *never ran*, not *ran and got it wrong*.

Two more shapes of the same trap:
- **An EditMode harness reaches only the no-provider branch.** A method that branches on "is a provider/service
  registered?" returned from its early `return true` in a test scene that had none, so inverting the production loop
  left the test green. Say which branch the test reaches, and put a fake provider behind the interface to reach the other.
- **A guard that enumerates one population cannot see the other.** A proof walked 3,145 bound trees; the scope also held
  4,815 decorative ones, none in view, and nothing asserted they were cut or restored. When a feature's scope is a union,
  count each part in the guard and check one member of each part. A scope guard that only checks "nothing outside the scope
  was swapped" passes on an empty scope.

## 4. The name is a claim; make it true

`BuildingChargesPerModule` measured "some multiple of four". `WithNoEconomyEverythingIsStillFree` measured a method
that is always free. A test name is read far more often than its body, and a wrong one misleads the next reviewer into
thinking an area is covered. The same holds for a failure MESSAGE's unit: a stair-gap census counted (deck node, ground
square) PAIRS but printed them as "low deck node(s)", and the red run printed "432 low deck node(s) (of 192 ...)", a count
larger than its own denominator. Cheap check on the first red: compare every "K of N" message with K <= N.

## 5. The seam rules that make any of this reliable

- Never assume a creation API returns the durable id you need. `PlaceLine(...)` returns the **number of modules
  built**; two correct route tests went red comparing module counts with stable graph ids. Read the declaration, assert the
  expected record-count delta, then take the id from the record the system stored.
  > **Rule.** A positive integer is not evidence that an API returned an id.
- **NUnit `Assert.AreEqual(object, object)` boxes, so `int 50 != long 50`.** Moving an assertion onto a `long` counter turns
  a correct run red with *"Expected: 50, But was: 50"*, which reads as a framework bug. Cast on the expected side.
- Set the tool's "suppress live input" seam **before** driving its draft and simulate steps, or its `Update` processes the
  real mouse and races the seams, making counts coin-flips.
- Restore globals in `[TearDown]`, not at the end of the happy path (a global that tests hijack and nobody restores).
- Beware order-dependence: a dictionary's iteration order is unspecified and a shipped probe steered on it.
- A fixture that silently degrades makes every test in it meaningless (six of eight lodge tests ran against a FAIL-OPEN
  condition). Assert the fixture is in the state you think it is.
- **A `if (false && <the fix's condition>)` seam compiles silently and keeps the condition type-checked.** `false && f(x)`
  is not a constant expression in C#, so there is no unreachable-code warning, it is safe under warnings-as-errors, and it
  cannot rot: a rename of anything inside the condition still breaks the compile. Check the seamed file's sha differs from
  the fix before trusting the red.
- **A suite that finds its subject by a hard-coded path needs an environment override for that path**, so the same suite
  runs against a staged copy and against throwaway mutants, and the live file is never edited to test it. Give every run a
  scratch path for any live state file the subject reads, otherwise exact-text checks go red the day that file appears in
  production.
- **A test-built twin leaves the real wiring unguarded.** A proof that asserts counts on an instance the test built never
  runs the component's own `Register` or start call; guard that call.
- **Which `Assert.IsTrue` fired?** When a red says `Expected: True But was: False` on a line with several assertions, the
  stack's IL offset identifies it (decode it from the compiled assembly). Better, give each assertion its own message.
- **A step that can hang** (a `tarfile` mode `r|` on a git pipe waits forever) needs a watchdog that turns the hang into a
  red.

## 6. Assert the call, not just the data

A guard that a component is **configured** correctly is not a guard that the component is **used**. A swing-variant system
was authored, weighted, catalogued and covered by a passing test that checked the profile returned the right clip for the
right inputs. Nothing called it; the graph was built by iterating a motion enum, variants are not motion ids, and every
unit played the fallback clip. A shield arc had six EditMode tests; after a parameter was added, `ResolveHit` moved to a
4-argument overload and the tests kept calling the 3-argument one, which then had no production caller at all. Six green
tests, exercising a configuration the game never runs.

The fix is an assertion about the *observed effect*, reached through the real entry point (not "does the selector return 3
different answers?" but "did the driver actually pose from 3 different graph inputs?").

> **Ask "what would still be green if I deleted the production call site?"** If the answer is "everything", the suite is
> testing a library, not a feature. After adding a parameter, grep the OLD signature's callers: if they are all tests, the
> tests are now the only thing keeping it alive. A public overload with no production caller should be deleted or made
> private.

## 7. Measure the accumulation, not the increment

For anything that repeats and does not reset, a single-cycle guard proves nothing about the tenth cycle. A per-blow leak of
0.02 m looked like nothing; twelve blows moved a pair 0.16 m inside its planned spacing and jammed the formation behind
it. The single-swing guard stayed green throughout. Run the loop many times, count the iterations in the assertion message,
and measure the quantity that accumulates.

---

## 8. A test can be BORN RED: ask whether it has ever been green before calling it a regression

A clause inside a movement test was written against an **uncapped** door lead-off. The very next commit capped the lead-off
at 1.6 m for an unrelated and correct reason. From that moment the clause could never pass again. Nobody noticed for hours,
because the class had only ever been run **filtered**; the first full suite surfaced it, which made it read as new. It was
reported up the chain as a REGRESSION and a bisect across four commits was nearly started.

The check that answered it in seconds, before any bisect:

```bash
cd logs/test-results && for f in *.xml; do
  r=$(grep -o 'name="MyTest"[^>]*result="[A-Za-z]*"' "$f" \
      | grep -o 'result="[A-Za-z]*"' | head -1)
  [ -n "$r" ] && echo "$f $r"
done
```

Two runs on disk contained it. Both `Failed`. It had never been green anywhere.

> **Rule.** Before calling a newly-failing test a regression, ask whether it has EVER been green: grep every results XML on
> disk for its name. A test whose premise the NEXT commit invalidated is not a regression and there is nothing to revert;
> reverting the commit that "broke" it would have re-broken the thing that commit was written to fix.

- **"Newly failing versus baseline" spans every commit since that baseline**, not the ones you happen to be thinking about.
  When the baseline predates N commits, say N out loud.
- **A filtered-only class hides its own red.** If a fixture has never appeared in a full run, its results are unknown, not
  green.
- **The answer is a snapshot**, so re-run the grep instead of quoting its count.
- **Search EVERY lane, and compare the failing line and message, not just Passed/Failed.** Three proofs a batch did not own
  were red in its run. Listing each test's history across all agents' result folders (start time, file, result, duration,
  failing `file.cs:line`, first line of the message) settled it: one had failed weeks before the batch existed (born red);
  one failed at the same line in earlier rounds and identically in this one, so the batch did not cause it. The same line
  and message before the batch existed clears the batch. A pass elsewhere followed by a gap with no runs means the live
  baseline is UNKNOWN: say so, do not call it pre-existing. A 0.03 s red at the test's first line is "never ran", not a
  result.
- **A test that went red once and green on repeats is not yet a flake.** Compare the red run's numbers with the greens'
  before writing "did not repeat".
- **Adding a required condition to a checker can hollow its old "refuses X" tests**: they keep passing, now for the new
  reason. A mutant that drops X from the exit code must still go red.

## 9. Retiring a test: sort its assertions into three piles

Four guards drove a synchronous seam that no longer existed, and all four failed identically. Deleting them was right. Two
of the four were still asserting something TRUE, and deleting a true assertion silently is how coverage evaporates during a
refactor.

| pile | what to do |
|---|---|
| premise removed | delete, **with the reason written in the file** |
| still true, expressible elsewhere | **MOVE** the assertions onto the surviving path where the numbers already exist; do not rewrite them from memory |
| still true, not expressible | record as **owed debt** where the next reader will find it, and flag it as a deviation rather than quietly taking it |

> **Rule.** A deleted test with no note is indistinguishable from a test deleted to get green. The note is what tells the
> next reviewer which of the two happened, and it costs one line.

---

## Related

- `prove-a-cache-invisible` (in this repo): equivalence guards for caches, which are instances of rule 1.
- `ground-truth-the-metric` (in this repo): the same discipline aimed at measurements instead of tests.
- `mask-the-noise-not-the-signal` (in this repo): a mask is a blind spot you chose; prove a change to it with planted controls.
