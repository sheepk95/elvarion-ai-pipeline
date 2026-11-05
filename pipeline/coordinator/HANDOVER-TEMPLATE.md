# HANDOVER-<role>: <lane> <role>, <UTC>

Write this at `lanes/<slug>/HANDOVER-<role>.md` before a clear, a usage limit, an app restart or an account switch
(RULES.md 'Context, compaction and hand-over'), then tell the coordinator: a cleared chat cannot wake itself. Record
state, not rule text. After a clear: re-read RULES.md, your card and this note, act on any unseen item, restart your
waiter.

Chat: `<title>` (session `<id>`) | model `<model>` | effort `<effort>`
State: building | reviewing | testing | waiting | PAUSED

## Job and step
`jobs/<lane>-<n>/JOB.md`, step `<n>: <name>`. Current pins: `pins: card <sha12> | scorecard <sha12> | work <sha12>`

## Done and verified
- <what is finished, and how it was checked (command, test name, file)>

## Half done
- <what is started but not finished, and exactly where it stopped>

## Next step
1. <the first thing to do after reading this note>

## Open items
- Unhandled inbox items: `<file names not yet in .seen, or none>`
- Questions waiting for an answer: `<Q item ids or GRILL-<n> numbers, or none>`

## Code
Worktree `<path>` | branch `<branch>` | commit `<sha>` | uncommitted changes: none | `<list>`

## Background jobs
| what | id / pid | output file | how to resume or restart it |
|---|---|---|---|
| inbox waiter | `<pid>` | - | `python -I -B tools/wait_inbox.py <inbox>` |

## While PAUSED
New items noted here (and in `.seen`) without acting: `<file names, or none>`
