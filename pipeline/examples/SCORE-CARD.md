# SCORE-CARD: example lane (the `tally` CLI)
Use: the coordinator copies the applying criteria onto each job card; the reviewer and the gate score against them.

## A. Kinds of job
- **feature**: new behaviour in the CLI. **fix**: a defect. **docs-only**: help text or README only.

## B. Criteria (score each 0-10; "below 6" means the part fails)
- C1 `behaviour`: does what the card says, including empty input, bad input and large input. Below 6: any stated case
  wrong. The gate checks: runs each case on the card.
- C2 `tests`: tests cover the new behaviour and can fail (seen red on a planted fault). Below 6: a test that cannot
  fail, or a stated case with no test.
- C3 `compatibility`: output and exit codes without the new flag are unchanged. Below 6: any byte of old output differs.
  The gate checks: diffs the old and new output on the sample files.
- C4 `docs`: `--help` and README describe the change. Below 6: either missing.
- C5 `packaging`: install still works; new dependencies are justified. Below 6: install fails.

## D. Bars
- Pass: average 7.0 or more, every part 6.0 or more, no open defect.
- Hard bar (measured, never scored): `tally` on `samples/big.csv` (1M rows) under 2.0 s on the reference machine.
