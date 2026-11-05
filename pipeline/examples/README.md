# Worked example (fake content)

A small, made-up job carried through the loop, so you can see what each file looks like. The project is a tiny
command-line tool, `tally`, that counts values in CSV columns. The job: add a `--json` flag.

Treat this folder as a pipeline root. Read the files in this order:

1. [BOARD.md](BOARD.md): the coordinator's board, two lanes.
2. [SCORE-CARD.md](SCORE-CARD.md): the `example` lane's acceptance criteria and bar.
3. [jobs/example-1/JOB.md](jobs/example-1/JOB.md): the job card.
4. [lanes/example/inbox/builder/20260115T091500Z-coordinator-1.md](lanes/example/inbox/builder/20260115T091500Z-coordinator-1.md):
   the JOB item that started it.
5. [jobs/example-1/REVIEW-1.md](jobs/example-1/REVIEW-1.md): the first review, findings as fix recipes.
6. [jobs/example-1/FIXES-1.md](jobs/example-1/FIXES-1.md): the builder's answers, one line per finding.
7. [jobs/example-1/GATE-1.md](jobs/example-1/GATE-1.md): the fresh gate's verdict.
8. [coordinator/inbox/20260115T143000Z-example-reviewer-1.md](coordinator/inbox/20260115T143000Z-example-reviewer-1.md):
   the DONE item to the coordinator.

The recheck round (REVIEW-2.md) and the tester's report (TEST-1.md) are mentioned but left out to keep it short.
Times, names, commits and test results are invented. The card and scorecard pins are real: run the shipped tool
from this folder and it prints the same `card` and `scorecard` values the items carry (if your git checkout turned
the line endings into CRLF, the hashes differ):

`python -I -B ../tools/job_pins.py example-1 --card-only --root .`
