pins: card 281a0c365f42 | scorecard 647b70ad691f | work 3e4f5a6b7c8d
# FIXES-1: example-1, builder `Example builder`, 2026-01-15T12:10Z (answers REVIEW-1.md)

F1 | done | L1: `tally --json samples/small.csv | python -m json.tool` exit 0; planted dropped-column fault: `test_json_output` FAILED (1 failed, 13 passed), fault removed: 14 passed
F2 | done | L2: prints `{"columns": {}}`, `python -m json.tool` exit 0; new `test_json_empty` passes, and fails with the old `return None`
F3 | done | `tally --help | grep -c -- --json` -> 1; `grep -c "## JSON output" README.md` -> 1
I2 | done | `sort_keys=True` in `to_json`; new `test_json_key_order` runs the same file twice with shuffled rows and compares bytes: passes, and fails with `sort_keys=False`

Attempt log: one attempt, `stable-key-order` (I2), commit 3e4f5a6b7c8d, tests pass, big-run-seconds 1.41 -> 1.43
(tolerance 0.2): kept. F1-F3 are recipe fixes, not attempts.
Tests: `python -m pytest tests/ -q` -> 16 passed (14 before, plus `test_json_empty` and `test_json_key_order`).
