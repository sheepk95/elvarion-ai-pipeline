# Overview: how the setup fits together

I make a game alone, with AI agents doing most of the planning, building, reviewing and testing. The agents are
Claude Code chats (plus the odd Codex helper) on one Windows PC. They coordinate through plain files: no server, no
database of their own, nothing that cannot be read in a text editor.

This page is the map. Each part links to the page or folder that holds its detail.

```
You
 |
 v
Desk chat            the one chat you talk to; every other chat sends questions and updates here
 |
 v
Coordinator chat     writes job cards, starts and paces lanes, answers or forwards questions
 |
 v
Lanes (any number)   each: builder chat + reviewer chat (+ optional tester chat)
 |                   + a fresh gate reviewer per finished job
 v
Integrator chat      merges passed jobs
 |
 v
Player testing       plays the merged build with real keyboard and mouse input
```

## The parts

**Desk.** You keep one chat open. Every other chat writes its questions and loop updates to a file the desk reads,
and the desk brings them to you in one place, with a recommended answer for each. A chat that can carry on with a
reversible choice does so and marks it "assumed, owner can overrule". See [desk.md](desk.md) and `desk/`.

**Coordinator.** Splits the work into jobs, writes a job card with acceptance criteria before any build starts,
keeps a board of what each lane is doing, and decides when a stuck job needs more effort, a specialist or a new
approach. See [`pipeline/coordinator/COORDINATOR.md`](../pipeline/coordinator/COORDINATOR.md).

**Lanes.** A lane owns one area of the project (a subsystem, a tool, the docs). Each has a continuing builder and a
continuing reviewer that keep their context across a job and its fixes. Work items travel only as inbox files (the
only direct messages are short wake-ups and the one copy of a question sent to the desk chat): one Markdown item
per message, written by `send_item.py`, picked up by a background `wait_inbox.py` that wakes the
receiving chat. See [`pipeline/RULES.md`](../pipeline/RULES.md) and the example lane charter in
[`pipeline/lanes/example-lane/LANE.md`](../pipeline/lanes/example-lane/LANE.md).

**Review ladder and gates.** Each reviewer works one reasoning step above the work it checks, and writes findings as
fix recipes. When a job is finished, a fresh gate reviewer that never saw the builder's reasoning checks it against
the card and decides pass or fail. See [review-ladder.md](review-ladder.md).

**Picking agents.** Every agent gets the lightest model and effort that does its job at full quality, and steps up
one level only when it fails. See [picking-agents.md](picking-agents.md).

**Integrator and player testing.** Only the integrator merges, and only after a gate pass and the owner's yes.
Code tests, integration checks and what a player actually saw are reported separately. A feature a player touches is
accepted only after someone plays it with real input on the merged build.

**Shared memory.** Decisions, rulings and lessons go into a shared memory server that every chat reads at start.
I use [GBrain](https://github.com/garrytan/gbrain); it is not included here. A small hook (`hooks/`) adds a short
memory recipe to every new chat and subagent so none of them forgets to look.

**Skill librarian.** I keep a library of small skill files (one procedure each). Rather than load hundreds, a chat
asks the librarian once per task and reads only the picks it returns. See `librarian/`.

**GPU booking.** Several chats share one GPU. Before any GPU job (a game engine run, a render, a local model) an agent
books it in a shared lease ledger and releases it after; a busy GPU means wait or do other work. See `gpu-lease/`.

**Backups as a practice.** Agents back up every file they author as they go, and a session never relies on its own
context surviving: before a usage limit, an app restart or a context clear, it writes a hand-over note with the job,
the step, what is done and verified, and what is half done. The backup script itself is not in this repo; use
whatever backup tool you trust.

## Terms

| Term | Meaning |
|---|---|
| desk | The one chat the owner talks to; other chats send it questions and loop updates as files. |
| lane | One area of the project with its own builder, reviewer and optional tester chat. |
| item | One Markdown message file dropped into a chat's inbox folder by `send_item.py`. |
| pin | A short hash (12 hex characters) of the card, the score card or the work, so a receiver can tell whether anything changed since the sender looked. |
| gate | The final check of a finished job by a fresh, extra-high reviewer, who passes or fails it. |
| job card | `JOB.md`: the task, the acceptance criteria and the pins for one job, written before any build starts. |
| GRILL | Step 0 of a job: a file of the design questions the card does not settle, answered before building. |
| IDEAS | A line on a DONE or READY item that lists the "later" findings and parked ideas of the job. |

Item kinds (`kind:` in the item header; the full list and who sends each is in [`pipeline/RULES.md`](../pipeline/RULES.md)):

| Kind | Meaning |
|---|---|
| JOB | The coordinator gives a builder a job card. |
| REVIEW-ASK | The builder asks the reviewer to review. |
| FINDINGS | The reviewer or tester sends findings to the builder. |
| TEST-ASK, WORKS, NOT-WORKS | The reviewer asks the tester to run the real tests; the tester answers. |
| DONE | The gate passed; the coordinator is told. |
| Q | A question, with options and a recommended answer. |
| UP | A lane reports it is stuck and asks the coordinator to escalate. |
| GO | The owner's yes (via the coordinator) to merge a gated job. |
| READY | The reviewer tells the integrator a job may be merged. |
| MERGED | The integrator reports the merge. |
| PLAY, RETEST, FAULT | The integrator asks for a play, or a replay, and the player tester reports a fault. |
| BUG | A bug report for a lane's builder. |
| RESUME, PAUSE | The coordinator wakes or pauses a chat. |

## What is in this repo (v0.1.2)

- These docs, including a [quick start](quickstart.md) that runs the tools in a temporary folder first.
- `pipeline/`: the brief (`PIPELINE.md`), the rules, the coordinator card, the job, gate, grill, hand-over and
  tried-and-failed templates, an example lane charter, a worked example with fake content, and four tools in
  `pipeline/tools/`: `send_item.py`, `wait_inbox.py`, `switch_census.py`, `job_pins.py`, each with tests.
- `tools/`: `run_checks.py` (every offline check) and `demo_job.py` (one job end to end in a temporary folder).
- `desk/`: the desk's file tools.
- `gpu-lease/`: the GPU booking ledger tool.
- `librarian/`: the skill librarian's tools.
- `hooks/`: the memory-recipe hook.
- A few in-house skills and the animation remap kit, where the top-level README lists them.

## What is not in this repo

- The game: code, art, models, animations, bought assets.
- My memory database, chat transcripts, decision logs, boards, inboxes and job folders.
- GBrain itself (linked above) and every third-party skill (listed in THIRD-PARTY.md, not copied).
- The keep-or-revert attempt engine. The rules describe attempts and a shared TRIED-AND-FAILED list; v0.1 does not
  ship the script that enforces them, so keep them by hand.
- The hand-over-after-N-compactions hook, the decision-ledger tools and the backup script.

Paths in these docs use `<USER_HOME>` (your home folder) and `<PROJECT_ROOT>` (the folder that holds your project
and its agent workspace). The pipeline's own paths are relative to the pipeline root, the folder holding
`RULES.md`.
