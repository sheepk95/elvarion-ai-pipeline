# Pipeline tools

Small standard-library Python tools for a pipeline of AI chats that talk to each other through **inbox folders**:
a chat sends another chat an item (a small Markdown file) and the receiver, idle in the background, wakes when it lands.
Python 3, Windows tested (`send_item.py` and `switch_census.py` use `ctypes` to check whether a process is alive).

The pipeline root is the folder above `tools/` (override with `--root` where a tool has it). It holds, among others:
`coordinator/inbox/`, `lanes/<lane>/inbox/<role>/`, `lanes/<lane>/LANE.md` (first line `# LANE: <title> (<role list>)`),
and `jobs/<job>/JOB.md` for job cards. No environment variables are needed.

| Tool | What it does |
|---|---|
| `send_item.py` | Writes one item into an inbox: `python -I -B send_item.py --to <inbox folder> --from <sender> --kind <KIND> [--refs "<ids>"] (--body "<text>" \| --body-file <path>)`. Closes a unique temporary file, then publishes it with a no-overwrite hard link as `<UTC>-<from>-<n>.md`; a collision retries with the next number. Requires a local filesystem supporting hard links (for example NTFS); unsupported filesystems fail without publishing, with one `ERROR: cannot publish into <inbox> (...)` line and no temporary file left. Refuses an inbox that holds role subfolders, unsafe sender names, and a `--refs` value containing NUL or any line break `str.splitlines()` knows (`\r`, `\n`, `\v`, `\f`, `\x1c`-`\x1e`, `\x85`, U+2028, U+2029; it would forge header lines). A temporary-file cleanup warning after publication does not mean delivery failed; the printed item id/path is the receipt. Afterwards it reports receiver liveness on Windows, or an unknown status on other platforms. Kinds: `JOB REVIEW-ASK FINDINGS TEST-ASK WORKS NOT-WORKS GO READY Q UP DONE BUG FAULT RETEST PLAY MERGED RESUME PAUSE`. |
| `wait_inbox.py` | The receiver's waiter: `python -I -B wait_inbox.py <inbox folder> [--timeout 7200]`. Run it as the last step of a turn, in the background; it exits 0 and prints `NEW ITEMS` and their paths when an item lands (exit 2 on timeout). It writes `.waiter.pid`, and never writes `.seen`: the chat appends an item's file name to `.seen` once it has handled it, so an unhandled item keeps waking a restarted waiter. Only files named `<UTC>-<from>-<n>.md` count, so notes such as `ACKS.md` never wake the chat. |
| `switch_census.py` | After an account switch or app restart: lists `ARMED`, `DEAD`, `UNKNOWN` or `NONE` and prints `WAKE` lines. PID plus Windows process creation time identifies a waiter; legacy PID-only registrations and inaccessible processes are UNKNOWN and require re-arming. `python -I -B switch_census.py [--root <pipeline root>] [--all] --account-pairs <json> [--cwd-marker <text>]`. The required account map selects an exact relative pair path (e.g. `{"you@example.com": "account/org"}`), keyed by `CLAUDE_CODE_USER_EMAIL`; missing, invalid or unmapped account data fails closed even when only one pair exists. Existing users must supply this mapping after upgrading. Unreadable session or archive metadata suppresses all routing and returns exit 5. CWD must be the canonical pipeline root or a descendant; `--cwd-marker` is only an additional filter. Duplicate open titles and any session matched to multiple inboxes (including empty inboxes) are unresolved and do not produce WAKE lines. Exit 0 nothing to wake, 4 WAKE lines, 5 unresolved account/title or unread items with no matching chat (including when WAKE lines also appear). |
| `job_pins.py` | Prints or checks the **pins line** of a job: `pins: card <sha12> \| scorecard <sha12> \| work <commit or file sha12>`. Every item and record that makes a claim about a job carries it, and the receiver runs the tool again before acting: if a pin differs, the card, the score card or the work changed since the sender looked. Modes: print, `--card-only`, `--check [--ready <READY item>]` (exit 1 on a mismatch, 2 on a missing record, a record holding two different pins lines, a git error or a dirty worktree), `--self-test`. A card may list other documents the job reads in a `Reads:` section; the tool pins those too. |
| `test_job_pins_reads.py` | Tests for the `Reads:` pins of `job_pins.py`: 21 tests through the real command line against a scratch pipeline root, then 26 "plants" (one exact mutation of a copy of `job_pins.py` each) that must each turn a named test red. Exit 0 only when every test is green and every plant red. |

## Item format

```
id: <from>-<UTC>-<n>
kind: <KIND>
from: <sender>
refs: <ids>

<body>
```

## Tests

```
python -I -B job_pins.py --self-test        # 14 checks, uses git and a temp folder
python -I -B test_job_pins_reads.py          # 21 tests + 26 plants, temp folder only
python -I -B test_job_pins_integrity.py      # record/card/score identity and dirty-worktree checks
python -I -B test_send_item.py               # concurrent publication, cleanup-failure and --refs checks
python -I -B test_switch_census.py           # missing, empty or damaged desktop session folders
```

Current commit pins require a clean worktree, including non-ignored untracked files: a dirty worktree is exit 2, and
the error names the first changed paths (commit or move them out; do not `git clean` proof media). The checker's git
calls use `--no-optional-locks`, so they never take `index.lock` from a builder committing in the same worktree. Historical `--work <commit>`
is still available for recording a known old revision; it is not proof that a dirty working copy ran those bytes.
`--check` requires REVIEW, TEST and GATE records and compares their card, scorecard and work pins. A scoped re-gate
may reuse a TEST only if its complete tuple matches the explicitly named earlier gate, the gate file holds a
`tester not re-run: <why>` line in its first 2000 characters, and the TEST's card/scorecard still match the current
gate; otherwise `--check` prints a `NOTE scoped re-gate` line naming the condition that failed. That exception permits an older work revision, not untested acceptance criteria.

The check establishes identity at the time of inspection, not a PASS verdict, authorization to merge, or protection
against later edits. Keep source fixed during tests/review, read the actual gate result and owner approval separately,
and merge the exact accepted commit. Use an immutable checkout when other writers cannot be excluded.

`job_pins.py` mentions `RULES.md` and `JOB-TEMPLATE.md`: the rule and template files of a pipeline that uses it (written separately from these tools). A sibling tool can load `job_pins.py` by path to reuse `read_card`.

Waiter registrations and cleanup use the persistent `.waiter.lock` OS lock. Re-arm old waiters after upgrading: older versions do not participate in the lock. Do not delete the lock file while any waiter may be running.

Only one live waiter may register per inbox. A second waiter exits with an error; if an existing PID has unknown identity it is preserved unless the OS proves that process is dead. Investigate a stale unknown registration before removing it. New identity records carry a random registration generation even when process creation time is unavailable.
