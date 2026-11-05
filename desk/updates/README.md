# Desk files: one per lane chat

Every lane chat keeps one file here, named after its own session id: `<session id>.md`. Only that chat writes it. The
desk chat only reads it (`../tools/desk_read.py`).

## What goes in
Append lines. Never rewrite or delete earlier lines. Use UTF-8, end every line with a newline, use absolute paths, and
take times from the clock (`date -u`), never from memory.

- At the end of each loop, one entry of 1-3 lines, each line starting with the tag:
  `[DESK UPDATE] <your title> loop N | <UTC> | <result in one line> | <absolute path to the full report>`
- Each question for the owner, as one line:
  `[DESK Q] <your title> | blocking: yes|no | <question> | Options: A ... / B ... | Recommended: <answer> because <one line> | Assumed and continuing: yes|no | Needs: <files, record ids> | <your session id>`
- When your chat hands over to a new chat, the NEW chat, as its first desk act, writes one line in its own new desk
  file, and copies the old file's open questions into it:
  `[DESK HANDOVER] <title> | old <session id> -> new <session id> | <UTC> | compactions at handover: N | <absolute path to the handover file>`
  A chat that clears itself in place writes the same line with `self-clear, same chat <session id>` in the second field,
  and a `[DESK UPDATE] <title> RESUMED ...` line once it is working again (`desk_watch.py` raises exit 6 if that line
  does not appear within 15 minutes).

## Questions also go by message
Send every question to the desk chat in ONE message as well (its session id is in `../DESK.json`). Chat apps may stop a
chat's messages to other chats after a number of sends without a human reply in that chat. If a send fails that way, the
line in this file is enough: the desk chat's watcher (`desk_watch.py`) wakes it when a new `[DESK Q]` line lands here.
Loop updates go here only, not by message.

## Where answers appear
The desk chat logs every question and its answer in `../QUEUE.md`, and messages the answer back when it can. No row yet
means not read yet. An answer in QUEUE.md counts, message or not.

When you copy a question that already has an answer (a QUEUE.md row or a reply), end its line with `(answered DQ-nnn)`
or `(answered: <source>)`, so the desk's waiter does not wake for it.
