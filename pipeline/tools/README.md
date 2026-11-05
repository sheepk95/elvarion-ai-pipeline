# Pipeline tools

Small standard-library Python tools for a pipeline of AI chats that talk to each other through **inbox folders**:
a chat sends another chat an item (a small Markdown file) and the receiver, idle in the background, wakes when it lands.
Python 3, Windows tested (`send_item.py` and `switch_census.py` use `ctypes` to check whether a process is alive).

The pipeline root is the folder above `tools/` (override with `--root` where a tool has it). It holds, among others:
`coordinator/inbox/`, `lanes/<lane>/inbox/<role>/`, `lanes/<lane>/LANE.md` (first line `# LANE: <title> (<role list>)`),
and `jobs/<job>/JOB.md` for job cards. No environment variables are needed.

| Tool | What it does |
|---|---|
| `send_item.py` | Writes one item into an inbox: `python -I -B send_item.py --to <inbox folder> --from <sender> --kind <KIND> [--refs "<ids>"] (--body "<text>" \| --body-file <path>)`. Writes `<name>.tmp`, then renames it to `<UTC>-<from>-<n>.md`, so a reader never sees half an item. Refuses an inbox that holds role subfolders, and a `--from` with anything but letters, digits, space, dot, dash and underscore (or with `..`), because it becomes part of the file name. Afterwards it tells you if the receiver's waiter is dead (`WAITER DEAD`) or absent (`NO WAITER FILE`). Kinds: `JOB REVIEW-ASK FINDINGS TEST-ASK WORKS NOT-WORKS GO READY Q UP DONE BUG FAULT RETEST PLAY MERGED RESUME PAUSE`. |
| `wait_inbox.py` | The receiver's waiter: `python -I -B wait_inbox.py <inbox folder> [--timeout 7200]`. Run it as the last step of a turn, in the background; it exits 0 and prints `NEW ITEMS` and their paths when an item lands (exit 2 on timeout). It writes `.waiter.pid`, and never writes `.seen`: the chat appends an item's file name to `.seen` once it has handled it, so an unhandled item keeps waking a restarted waiter. Only files named `<UTC>-<from>-<n>.md` count, so notes such as `ACKS.md` never wake the chat. |
| `switch_census.py` | After an account switch or app restart killed every chat's waiter: lists each inbox as `ARMED`, `DEAD` or `NONE` with its unread items, and prints `WAKE <session id> <title>` lines for the chats to message. `python -I -B switch_census.py [--root <pipeline root>] [--all] [--account-pairs <json>] [--cwd-marker <text>]`. `--account-pairs` is optional: a JSON file that maps an account e-mail (from the `CLAUDE_CODE_USER_EMAIL` environment variable) to the folder name of that account's session list; without it the most recently written list is used. `--cwd-marker` picks which desktop chats count as pipeline chats (default: the name of the pipeline root folder). It reads the Claude desktop app's session folder under `%LOCALAPPDATA%`. Exit 0 nothing to wake, 4 WAKE lines printed. |
| `job_pins.py` | Prints or checks the **pins line** of a job: `pins: card <sha12> \| scorecard <sha12> \| work <commit or file sha12>`. Every item and record that makes a claim about a job carries it, and the receiver runs the tool again before acting: if a pin differs, the card, the score card or the work changed since the sender looked. Modes: print, `--card-only`, `--check [--ready <READY item>]` (exit 1 on a mismatch, 2 on a missing record), `--self-test`. A card may list other documents the job reads in a `Reads:` section; the tool pins those too. |
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
```

`job_pins.py` mentions `RULES.md` and `JOB-TEMPLATE.md`: the rule and template files of a pipeline that uses it (written separately from these tools). A sibling tool can load `job_pins.py` by path to reuse `read_card`.
