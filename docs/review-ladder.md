# The review ladder

Every piece of work is checked by an agent that thinks harder than the one that made it, and the final pass/fail
call is made by an agent that never saw how it was made.

## One step up

Effort levels run low, medium, high, extra-high. A reviewer runs one step above the work it checks:

| Work done at | Reviewed at |
|---|---|
| low | medium |
| medium | high |
| high | extra-high |
| extra-high | extra-high, by a fresh reviewer (there is no higher step; see "Fresh gate") |

Nothing runs at max. Extra-high is the ceiling for every agent, reviewer and gate.

## Findings are fix recipes

A finding that says "this is wrong" makes the builder rediscover the problem. A recipe lets a lighter agent fix it.
Every finding has five parts:

1. **Place**: file and line (or section).
2. **What is wrong**: one or two sentences.
3. **The fix**: replacement text, or numbered steps.
4. **How to check**: a command, a grep count, or an observation that shows it is fixed. It must be able to fail.
5. **Tag**: `mechanical` (anyone can apply it from the recipe) or `judgement` (needs a design call).

Example:

```
F3 | src/cli.py:88 | --json prints the summary line before the JSON, so the output is not valid JSON |
fix: move the print("done") behind `if not args.json:` | check: `tally --json in.csv | python -m json.tool`
exits 0 | mechanical
```

A finding that names one case of a class lists the class, and the fix covers every member.

## Who fixes what

1. The reviewer writes the whole review first, then acts on it.
2. **Mechanical** recipes go back to the builder. It applies each one and reports it as `done`, `done differently,
   because ...` or `could not apply, because ...`, with the output of the recipe's check.
3. **Judgement** fixes, and any recipe the builder could not apply, are fixed by the reviewer in place.
   (In the lane pipeline the builder fixes everything and the reviewer only reviews; see
   [`pipeline/RULES.md`](../pipeline/RULES.md). Pick one style per setup and write it down.)
4. The reviewer re-checks only the fixed spots (re-running each "how to check") before the next rung looks.
5. If a rung leaves something it could not settle, the next rung up reviews and fixes the same way.

After two or three rounds with required findings still open, stop looping: escalate to the coordinator, which can
raise the effort, add one specialist with a short hand-off, or change the approach.

## Fresh gate

A finished job gets one last reviewer: started fresh, extra-high, given the job card, the work, the review record
and the test report, and nothing of the builder's reasoning. It does not fix anything; it decides.

1. **Criteria first.** Before it looks at the work, it writes down which acceptance criteria apply, what each needs to
   pass, and why each skipped one does not apply.
2. **Check the whole job**, including whether fixes broke something else and whether the tests can fail.
   It re-runs the tests once itself and compares with the tester's report.
3. **Score** each criterion out of 10 with one line of evidence.
4. **Verdict.** PASS only if every acceptance criterion is met and no defect is open. If it is unsure a criterion is
   met, that is a FAIL with the question written out.
5. On FAIL, its findings are fix recipes too, plus a few different approaches the builder has not tried.

### Pass bars

I use two bars. Pick your own and write them on the scorecard:

- Tools, setup and hand-over documents: average 7.0 or more, every sub-score 6.0 or more.
- Game work: average 6.5 or more, every sub-score 6.0 or more.

A bar measured with a number (a frame time, a file size, a test count) is measured, never scored.

### A score never overrides a failed criterion

A 9/10 average with one failed acceptance criterion is a FAIL. The score explains the review; the criteria decide it.

### Twins

For a gate that decides a merge, an install or a release, I also run a second gate of a different model on the same
brief, which never sees the first gate's file. The twin informs; the main gate decides. Any real fault it finds is
fixed before merge. Ordinary review rounds get no twin.

## Gates only where you asked for them

Not every piece of work needs a gate. In the lane pipeline every finished job has one. Outside it, I only run a gate
when I ask for one, so ad-hoc tasks do not quietly double their cost.

See [`pipeline/coordinator/GATE-BRIEF.md`](../pipeline/coordinator/GATE-BRIEF.md) for the gate's exact steps, and
[`pipeline/examples/`](../pipeline/examples/) for a review, its fixes and a gate on a small fake job.
