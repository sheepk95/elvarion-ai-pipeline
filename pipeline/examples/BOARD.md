# BOARD (writer: the Coordinator alone). Updated 2026-01-15T14:35Z.
Usage: weekly 31%, 5-hour 22%. Hold point 80%, pause point 90%. Two lanes, both may run.

| Lane | Next job | Waits on | State | Builder | Reviewer | Tester |
|---|---|---|---|---|---|---|
| example (the `tally` CLI) | example-1: add `--json` output | nothing | owner's gate (GATE-1 PASS avg 7.8) | <session id> | <session id> | <session id> |
| docs (user guide) | docs-1: document the `--json` output | example-1 MERGED | idle | <session id> | <session id> | not started (document lane: the reviewer runs the scripted checks) |

## Work items per lane
### example
- example-1 (W1 `--json` flag): in a job, at the owner's gate.
- W2 `--columns` filter: waiting.
- example-1-idea-1: publish a JSON schema for the output (GATE-1.md, `later`): waiting; take into W2's card or write why not.
### docs
- docs-1 (D1 document `--json`): waiting on example-1 MERGED.

## Log
- 09:15Z JOB example-1 sent (card pins 281a0c365f42 / 647b70ad691f).
- 09:40Z GRILL-1: one question, blocking: no (empty-input shape); builder assumed `{"columns": {}}`.
- 11:05Z REVIEW-1: 3 required, improvement I2 recommended. 12:10Z FIXES-1, REVIEW-2 clean.
- 13:20Z TEST-1 WORKS. 14:30Z GATE-1 PASS avg 7.8; DONE received; sent to the desk for the owner's gate.
