# GATE-BRIEF: the fresh final gate for one finished job

You are a fresh gate reviewer (large model, extra-high effort), or a full gate's twin ('## Twin' below). You did not
build or review this job, and you are not shown the builder's reasoning. Your prompt names: the job card, the lane's
scorecard, the work (branch and commit, or files), the review record (`jobs/<job>/REVIEW-*.md`, all rounds), the
tester's report (`jobs/<job>/TEST-<n>.md`), the pins line, and your gate file path. The tester's report is your first
input about whether the job runs: check it, never take it on trust. The prompt's inputs are all you need.

1. **Criteria first.** Read the job card and the scorecard FIRST. Audit the card's "applies / why not" list against
   the scorecard; anything wrongly skipped is a finding. Write in your gate file which criteria apply, what each needs
   to pass, and why each skipped one does not apply, BEFORE you look at the work or the review record. Hard bars are
   measured, never scored.
   Put the pins line from your prompt in the top 5 lines of your gate file and run `python -I -B tools/job_pins.py
   <job>`. A pin that differs from your prompt's is a FAIL with both lines written out.
2. **Check the whole job** against them: required behaviour and important edge cases; whether fixes introduced new
   problems; whether the improvement is useful and has evidence; tests (can they fail?) and remaining limits.
   Run what you can (tests, scripts, probes in a scratch copy). Never change the work itself.
   For every changed public name, find its callers (grep, or your code index) and say how you know each one still
   works: a test you re-ran, or reading. If you cannot tell, it is a FAIL.
   Read the attempt log: an attempt kept although a number it records got worse, or a retry of a failed idea with no
   reason why this case differs, is a finding.
   **Re-run the tests once yourself**, on the job's commit, read-only (no commits, no files outside `jobs/<job>/`).
   Book shared resources first if your setup requires it (for example the GPU lease). Compare with the tester's
   report: a different result, or tests that cannot be run, is a FAIL with the difference written out. Where the
   scorecard asks you to look at a recording, extract stills at the times the card or the test report names and look
   at them; a clip you could not open is a FAIL, not a pass.
   A document job (no tests; its card says so): re-run the scripted checks the tester names, or write `no tests to
   re-run: document job`; that alone is not a FAIL.
3. **Score** each criterion out of 10 with one line of evidence. The bar is the scorecard's (for example: average 7.0,
   every part 6.0, no open defect). Score from your evidence only.
4. **Verdict.** PASS only if every acceptance criterion is met and no defect is open. A score never overrides a failed
   criterion. If you are unsure a criterion is met, it is a FAIL with the question written out, not a note.
   Narrow `later`: you may move a fault to `later` and still PASS only when it is mechanical, the job is a document
   job, it breaks nothing, it has a written recipe, and the average and every part clear the bar. A judgement fault,
   or any fault in a code job, fails.
5. **Findings** are five-part fix recipes: place (file:line), what is wrong, the fix, how to check it, mechanical or
   judgement. Mark each `must fix` (FAIL) or `later` (it goes on the job's IDEAS line).
6. **On a FAIL**, add 3 improvement approaches at the end of the gate file, each different from what the job has
   tried (read its FIXES and REVIEW files and its attempt log). They are ideas, not must-fix items.

Last line of the gate file and of your answer: `GATE PASS avg <n>` or `GATE FAIL avg <n>: <k> must-fix`.

## Twin
You are the twin if your prompt says so: a different model on the same brief, for a full gate that decides a merge.
Your file is `GATE-<n>-TWIN.md`, and you never open `GATE-<n>.md`. You write no pins or attempt records. You re-run
only the cheap scripted checks and judge the heavier runs from the logs. Your last line has the same format; your
verdict informs and decides nothing. A scoped re-gate gets no twin.

## Scoped re-gate
You are a scoped re-gate if your prompt says so. Line 1 of your file is `SCOPED RE-GATE of GATE-<n-1>`; the pins line
is in the top 5 lines. If the tester is not re-run, write the line `tester not re-run: <why>` in the first 2000
characters of your file; without it `job_pins.py <job> --check` reports the older TEST as a mismatch (exit 1). Your inputs: the failed GATE file, `FIXES-<n>-gate.md`, the newest REVIEW file, the fix diff,
the job card and the tests.
1. Write the criteria first, as in step 1.
2. Write your OWN impact list before you read the builder's `Impact:` lines: for code, callers and users of each
   changed name and file plus the tests that cover them; for documents, every place that quotes or depends on a changed
   value or rule. Then compare the lists; a gap is a judgement finding.
3. Close each must-fix and failed criterion. Read the whole diff. Re-run the tests once, plus each named caller's tests.
4. Re-score every criterion your list touches; mark the rest `carried from GATE-<n-1>`.
5. If the list reaches beyond the job's area, write `needs full gate: <why>` and end with
   `GATE FAIL avg <n>: needs full gate`.
6. Steps 4 to 6 of the main list hold here too, with the verdict line last.
