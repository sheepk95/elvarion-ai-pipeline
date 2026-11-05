# JOB example-1: add a `--json` flag to `tally` (code job)
Written by the Coordinator 2026-01-15T09:12Z. Lane: example. Work items: W1.
Systems: cli-output, tool:tally
Work: commit | worktree <PROJECT_ROOT>/worktrees/example-1 | branch job/example-1
Attempt log: jobs/example-1/ATTEMPTS.md
Scorecard: `SCORE-CARD.md`
Reads: none

## Step 0: GRILL (every new card)
Before building, read this card, the lane's scorecard and the owner's past answers for this lane, then write
`jobs/example-1/GRILL-1.md` with only the design questions those do not settle (numbered, 2-3 options each, a
recommended answer with one line of why, `blocking: yes|no`). Send ONE Q item to `coordinator/inbox` naming the file.
Already answered (do not re-ask): output goes to stdout only (owner's answer A3). Likely topics (hints, not answers):
the JSON shape for empty input; key order.

## Skills (do this first)
Ask the skill librarian once for this job and read the picks. Picks the Coordinator already got: none.

## Task
Add `--json` to `tally`. With the flag, print one JSON object `{"columns": {"<name>": {"<value>": <count>, ...}, ...}}`
to stdout and nothing else. Without it, behaviour is unchanged. Files: `src/cli.py`, `src/report.py`,
`tests/test_cli.py`, `README.md`.

## Order of work
1. Add the flag and a `to_json(report)` function in `src/report.py`.
2. Route output through it in `src/cli.py`.
3. Tests: one per case in the criteria below, each seen red first.
4. `--help` text and a README section.

## Waits on
nothing

## Rollback
Revert the job's commits on `job/example-1`. Last good: base commit `5d6e7f8a9b0c` on that branch (git revert, never
reset --hard or force).

## Acceptance criteria
Kind: **feature**. Bar: average 7.0, every part 6.0, no open defect. Hard bars (measured, never scored): 1M-row run
under 2.0 s, with and without `--json`.
### Criteria, applies / why not (EVERY criterion on the scorecard)
- C1 `behaviour`: does what the card says, including empty, bad and large input. APPLIES.
- C2 `tests`: tests cover the new behaviour and can fail. APPLIES.
- C3 `compatibility`: output and exit codes without the new flag are unchanged. APPLIES.
- C4 `docs`: `--help` and README describe the change. APPLIES.
- C5 `packaging`: install still works; new dependencies justified. WHY NOT: the standard library `json` module only;
  no packaging file changes.
### Owner's answers that bind this job
- A3: "machine-readable output goes to stdout, messages to stderr."
### Own checkable lines
- L1 `tally --json samples/small.csv | python -m json.tool` exits 0.
- L2 `tally --json samples/empty.csv` prints valid JSON.
- L3 `tally samples/small.csv` output is byte-identical to `samples/small.expected.txt`.

## Offline tests
Builder, before REVIEW-ASK: `python -m pytest tests/ -q` and the three lines L1-L3. Each test must be able to fail.

## Keep-or-revert measures
- big-run-seconds | `python tools/time_run.py samples/big.csv --json` | bar <2.0 | tolerance 0.2 | lower is better

## Tried and failed (pasted by the Coordinator, 2026-01-15T09:10Z)
none matching

## Tester and owner's gate
Clean review -> TEST-ASK to `lanes/example/inbox/tester`. The tester runs the full test suite on a clean install in a
fresh virtual environment, plus the hard-bar timing three times, and writes `jobs/example-1/TEST-1.md`.
WORKS -> the fresh gate (GATE-BRIEF.md). Gate PASS -> DONE to `coordinator/inbox`. Only the owner's yes, relayed as GO,
sends READY.

## Not in this job
- `--columns` filter (W2). The user-guide page (docs-1, docs lane).

## Done
On GO, the reviewer sends READY to `lanes/integrator/inbox/builder` (JOB-TEMPLATE.md 'Done').
