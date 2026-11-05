round 1 | sent back by: first | required open 3 | closed since round 0 0 | new 3
pins: card 281a0c365f42 | scorecard 647b70ad691f | work 9c8b7a6d5e4f
# REVIEW-1: example-1 (`--json` flag), reviewer `Example reviewer`, 2026-01-15T11:05Z

## Card audit (first review)
"Applies / why not" checked against SCORE-CARD.md: C1-C4 apply, C5 rightly skipped (no packaging change; confirmed
with `git diff --stat 5d6e7f8a9b0c..9c8b7a6d5e4f`: no `pyproject.toml`). Nothing wrongly skipped.

## Offline tests re-run
- `python -m pytest tests/ -q`: 14 passed (builder said 14).
- L1: exit 1 (builder said 0). See F1.
- L2: prints nothing, exit 0. See F2.
- L3: identical (diff empty).
- Planted fault: changed `to_json` to drop the last column; `test_json_output` still passed. See F1.

## Required fixes
F1 | `src/cli.py:88` | `--json` prints `done` before the JSON, so the output is not valid JSON (L1 fails); and
`tests/test_cli.py:41` `test_json_output` only checks the exit code, so it cannot catch this or a dropped column |
fix: (1) move `print("done")` behind `if not args.json:` and send it to stderr (answer A3); (2) in the test, parse
stdout with `json.loads` and assert the full expected dict for `samples/small.csv` | check: L1 exits 0; re-plant the
dropped-column fault and see `test_json_output` fail, then remove it | mechanical

F2 | `src/report.py:23` | empty input returns `None` and nothing is printed; the card asks for valid JSON. The shape is a
design call: `{"columns": {}}` (matches the GRILL-1 assumption) or `[]` | fix: return `{"columns": {}}` for empty
input, add `test_json_empty` | check: L2 prints `{"columns": {}}` and `python -m json.tool` accepts it | judgement

F3 | `src/cli.py:30`, `README.md` | `--help` does not list `--json`, and the README has no section for it (C4) | fix:
add `help="print counts as one JSON object on stdout"` to the argument; add a README section "JSON output" with the
L1 command and a three-line sample | check: `tally --help | grep -c -- --json` prints 1; `grep -c "## JSON output"
README.md` prints 1 | mechanical

## Improvements (up to 3; first review only)
- I1 `--pretty` (indented JSON). Benefit: easier to read by eye. Effort: small. Most callers of this CLI are
  scripts, so low value.
- I2 Stable key order (`sort_keys=True`). Benefit: output diffs cleanly between runs, so tests and users can compare
  files byte for byte (verification improvement). Effort: one argument plus one test. **Recommended.**
- I3 A `"version": 1` field. Benefit: room to change the shape later. Effort: small, but it fixes the shape before
  anyone has asked; better left for W2.

## Outcome
3 required (2 mechanical, 1 judgement), I2 recommended. FINDINGS sent to the builder naming this file.
