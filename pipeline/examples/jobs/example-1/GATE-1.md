# GATE-1: example-1 (`--json` flag), fresh gate, 2026-01-15T14:25Z
pins: card 281a0c365f42 | scorecard 647b70ad691f | work 3e4f5a6b7c8d
`job_pins.py example-1` now: same line. Pins OK.
Inputs: JOB.md, SCORE-CARD.md, REVIEW-1.md, REVIEW-2.md, FIXES-1.md, TEST-1.md, branch `job/example-1` at 3e4f5a6b7c8d.

## 1. Criteria (written before looking at the work)
- C1 `behaviour` APPLIES. Needs: L1 and L2 pass; small, empty and 1M-row inputs give correct counts; bad input (a
  missing file) exits non-zero with a message on stderr and nothing on stdout.
- C2 `tests` APPLIES. Needs: a test per stated case, each seen red on a planted fault.
- C3 `compatibility` APPLIES. Needs: L3 byte-identical; exit codes unchanged on the sample files.
- C4 `docs` APPLIES. Needs: `--help` and a README section.
- C5 `packaging` WHY NOT, confirmed: `git diff --stat 5d6e7f8a9b0c..3e4f5a6b7c8d` touches no packaging file.
- Hard bar: 1M-row run under 2.0 s, with and without `--json` (measured).
- Card audit: the "applies / why not" list matches the scorecard. No finding.

## 2. Check
- Tests re-run once on 3e4f5a6b7c8d, read-only: `python -m pytest tests/ -q` -> 16 passed. TEST-1.md says 16 passed. Same.
- L1 exit 0. L2 prints `{"columns": {}}`. L3 diff empty.
- Large input: `tally --json samples/big.csv` compared with `samples/big.expected.json` (written before the job, at
  base 5d6e7f8a9b0c, by converting the old text output): identical after `json.tool --sort-keys` on both.
- Bad input: `tally --json missing.csv` -> exit 2, `error: missing.csv not found` on stderr, stdout empty.
- Planted fault (my own, in a scratch copy): swapped two counts in `to_json`; `test_json_output` failed. Removed.
- Callers of the changed names: `to_json` is called only from `src/cli.py:91` (grep: 1 hit outside tests);
  `format_report` (unchanged signature) is still covered by L3.
- Attempt log: one attempt (`stable-key-order`), kept, timing 1.41 -> 1.43 s within tolerance. No finding.
- Hard bar: 1.43 s with `--json`, 1.38 s without (TEST-1.md, three runs each; my one re-run 1.45 s). Met.

## 3. Scores
- C1 behaviour 8: every stated case right, including large and bad input.
- C2 tests 7: each case has a test that went red on a planted fault; the 1M-row counts are checked by hand above,
  not by a test in the suite.
- C3 compatibility 9: L3 byte-identical, exit codes unchanged on all four sample files.
- C4 docs 7: help and README present; the README sample does not show the empty-input shape.
Average 7.75. Every part 6.0 or more. No open defect.

## 4. Verdict
Every acceptance criterion met; no defect open.

## 5. Findings
G1 | `docs/` (new) | not a defect: scripts that read the output would benefit from a published JSON schema | fix: add
`docs/tally-output.schema.json` and point the README at it | check: `python -m json.tool docs/tally-output.schema.json`
exits 0 | judgement | later

GATE PASS avg 7.8
