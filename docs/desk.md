# The desk: one chat you talk to

When you run many AI chats in parallel (a coordinator, builders, reviewers, a tester), each one will want to ask you
something. If every chat asks you in its own window, you spend the day switching windows and the chats sit blocked
waiting for you. The desk pattern fixes that: **one chat is the desk, and it is the only chat that talks to you.**
Every other chat sends its questions and news to the desk, and keeps working.

## The parts

| Part | What it is |
|---|---|
| Desk chat | The one long-lived chat you stay in. It gets the questions and the loop updates, and answers you back. |
| `DESK.json` | A small file naming the desk chat (its session id, the folder of desk files, the queue). Every lane reads it before it writes to the desk. See `desk/DESK.example.json`. |
| `updates/<session id>.md` | One append-only file per lane chat. Only that chat writes it. |
| `QUEUE.md` | The desk chat's log of every question and the answer it got. |
| `desk_read.py` | Prints what lanes added since the last read, then moves a per-file read offset. |
| `desk_watch.py` | A background job that exits when a new `[DESK Q]` line lands, so the idle desk chat wakes. It never moves the read offsets. |
| `limit_waker.py` | A background job that sleeps until a UTC time and then exits, to wake a chat after a usage limit resets. |

## The three line types

All three are single lines appended to the lane's own file in `updates/`.

```
[DESK Q] <title> | blocking: yes|no | <question> | Options: A ... / B ... | Recommended: <answer> because <one line> | Assumed and continuing: yes|no | Needs: <files, ids> | <session id>
[DESK UPDATE] <title> loop N | <UTC> | <result in one line> | <absolute path to the full report>
[DESK HANDOVER] <title> | old <session id> -> new <session id> | <UTC> | compactions at handover: N | <path to the handover file>
[DESK HANDOVER] <title> | self-clear, same chat <session id> | <UTC> | <path to the handover file>
[DESK UPDATE] <title> RESUMED | <UTC> | <what was recovered>
```

- `[DESK Q]` is a question for the human. It wakes the desk chat.
- `[DESK UPDATE]` is the end-of-loop result, one to three lines with a path to the full report. It does not wake the
  desk chat; the desk chat reads it the next time it wakes.
- `[DESK HANDOVER]` marks a chat that handed its work to a successor (or cleared itself in place). The successor
  copies the old file's open questions into its own file.

Rules for the files: append only, UTF-8, one line per entry ending in a newline, absolute paths, times read from the
clock. A half-written line (no newline yet) is ignored until its newline arrives.

## Reversible? Carry on.

A lane never blocks waiting for an answer it can reasonably guess. When the choice can be undone:

1. Write the `[DESK Q]` line with your **recommended answer and one line of why**.
2. Carry on with that recommendation, and mark it in your own records as **assumed, the owner can overrule**.
3. Say so in the question (`Assumed and continuing: yes`).

Only stop for what truly cannot be undone or that you were not asked to decide: money, publishing, deleting, account
or settings changes, changes to the rules themselves, and the scope of your own lane. Those wait for the answer.

## The queue of answers

The desk chat writes a row in `QUEUE.md` for each question: an id (`DQ-nnn`), the lane, the question, and once the
human has answered, the answer in the human's words. It also messages the answer back to the lane when it can.

- **Silence is not an answer.** No row yet means the question has not been read yet.
- **An answer in `QUEUE.md` counts**, whether or not a message arrived. A chat that resumes after a pause looks for its
  session id in the queue before it carries on.
- When a lane copies a question that already has an answer, it ends the line with `(answered DQ-nnn)` so the watcher
  does not wake the desk chat for it again.
- Rulings the desk chat makes itself are marked as the desk chat's rulings, never recorded as the human's decisions.

## One rule for the lanes

A lane chat never asks the human in its own chat. It writes the `[DESK Q]` line (and sends one message to the desk
chat if it can). If the human types into a lane chat directly, the lane answers there, and still records any decision
in its desk file.

## A typical loop for the desk chat

1. Start `desk_watch.py` in the background and go idle.
2. A lane writes a `[DESK Q]`; the watcher exits; the desk chat wakes. Two more lines wake it the same way (exit 0):
   a `[DESK HANDOVER]` line that announces a self-clear (the lane's own resume timer dies with the clear, so the desk
   chat sends the resume message), and a `[DESK UPDATE]` holding `SELF-CLEAR BLOCKED` (the clear may still have gone
   through: check the chat and wake it if needed).
3. `desk_read.py` prints the new lines and moves the offsets. Log each question in `QUEUE.md`, file each update.
4. Ask the human the questions that need a human (the desk chat is the only chat that does), record the answers in
   `QUEUE.md`, and message them to the lanes.
5. Re-arm `desk_watch.py`.

`desk_watch.py` also has two extra exits for a pipeline built from inbox folders (see `pipeline/tools/README.md`):

- **Exit 5:** a chat's inbox waiter is dead while an item has waited more than 15 minutes. It watches
  `coordinator/inbox`, each `lanes/<slug>/inbox` and each role folder `lanes/<slug>/inbox/<role>`.
  - With the shipped `pipeline/tools/wait_inbox.py`, a waiter is unavailable when its `.waiter.pid` is missing or names a
    process whose creation time differs, has ended, or cannot be verified. PID-only legacy registrations are unknown;
    re-arm them to create `.waiter.identity`. The creation-time check is supported on Windows.
  - An item is handled once its file name is in that inbox's `.seen`.
  - A chat that works on one item for more than 15 minutes without touching `.seen` also trips it: the recovery message
    then just waits in its queue.
  - Exit 5 needs `--pipeline-root` (or the `PIPELINE_ROOT` environment variable); without it, it stays off and prints a
    warning.
- **Exit 6:** a chat that announced a self-clear has not written a `RESUMED` line 15 minutes later. It reads only the
  desk files, so it works without a pipeline root.

For exits 5 and 6, record the printed `key=<key>` in `<desk root>/recovery-sent.md` before sending a recovery message.
Use `sending <key> <UTC>` while attempting delivery, then `ok <key> <UTC>` or `failed <key> <UTC>` when the attempt
ends. Keep it append-only. The watcher suppresses duplicate alerts for recorded keys, with one stuck alert when a
sent recovery has not produced activity after 15 minutes. This is delivery bookkeeping, not approval to resume
paused work. Check the relevant chat's status and scope before any resume message.

## Tools and tests

```
python -B -I desk/tools/desk_read.py [--peek] [--root DIR]
python -B -I desk/tools/desk_watch.py [--interval 15] [--max-seconds 6900] [--root DIR] [--pipeline-root DIR]
python -B -I desk/tools/limit_waker.py --at 2026-01-01T15:05:00Z --label "desk chat"
python -B -I desk/tools/test_desk_tools.py
python -B -I desk/tools/test_desk_watch_exits.py
python -B -I desk/tools/test_desk_watch_pipeline.py
```

`--root` defaults to the folder holding `tools/` (the desk root). The test files run in temporary folders and touch no
live desk. `test_desk_watch_pipeline.py` drives exit 5 with the real `pipeline/tools/send_item.py` and `wait_inbox.py`.
