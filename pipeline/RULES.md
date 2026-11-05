# RULES: the lane pipeline (read at start and after every compaction or clear)

[PIPELINE.md](PIPELINE.md) is the design; this file is how it runs. All paths are relative to the pipeline root (the
folder holding this file). Where a card, a hand-over note or an old item disagrees with this file, this file wins.

## Roles
- **Coordinator** (large model, high): writes job cards, starts and pauses chats, paces lanes, keeps `coordinator/BOARD.md`.
  Card: `coordinator/COORDINATOR.md`. Only it talks to the desk chat (the one chat the owner reads).
- **Per lane:** a continuing **builder** (medium) and **reviewer** (high), and optionally a standing **tester** (mid
  model, medium) that runs the slow or environment-bound tests. Each lane has a charter: `lanes/<slug>/LANE.md`.
- **Gate:** a fresh extra-high subagent per finished job, started by the reviewer from `coordinator/GATE-BRIEF.md`.
- **Integrator** merges passed jobs. **Player tester** plays merged work with real input; it reports, never fixes.
- Effort never goes to max; reviewers and helpers stay at or below extra-high ([docs/picking-agents.md](../docs/picking-agents.md)).

## Items: how chats talk
- One Markdown file per message in the receiver's inbox folder, written by `tools/send_item.py` (it closes a unique
  temporary file, then publishes a no-overwrite hard link, so a reader never sees half an item or loses an existing
  one to a collision). Use a filesystem supporting hard links. File `<UTC>-<from>-<n>.md`; header lines `id:`, `kind:`,
  `from:`, `refs:`, then the body.
- Inboxes: `lanes/<slug>/inbox/builder`, `.../reviewer`, `.../tester`, `coordinator/inbox`,
  `lanes/integrator/inbox/builder`, `lanes/player-tester/inbox/builder`. Send to a leaf folder, never to a folder
  holding role subfolders (`send_item.py` refuses).
- Kinds: JOB (coordinator to builder), REVIEW-ASK (builder to reviewer), FINDINGS (reviewer or tester to builder),
  TEST-ASK (reviewer to tester), WORKS / NOT-WORKS (tester to reviewer), DONE, Q, UP (to the coordinator), GO (owner's
  yes, coordinator to reviewer), READY (reviewer to integrator), MERGED (integrator to coordinator and reviewer), PLAY,
  RETEST (integrator to player tester), FAULT (player tester to integrator), BUG (to a lane's builder), RESUME / PAUSE
  (coordinator to any chat).
- **Waking.** Every chat ends each waiting turn with `tools/wait_inbox.py <its inbox>` running in the background, as the
  LAST tool call. A new item makes the waiter exit, which wakes the chat. After handling an item, append its file name
  to `<inbox>/.seen`; until then it counts as unread.
- `send_item.py` prints `WAITER DEAD`, `WAITER STATUS UNKNOWN`, or `NO WAITER FILE` when a waiter cannot be confirmed: tell the coordinator by Q. Legacy PID-only waiters must be re-armed to record their process identity.
  After an app restart or account switch, `tools/switch_census.py` lists the chats whose waiter died and have unread items.
- **Pins.** Job items and every REVIEW-, TEST- and GATE- file carry `pins: card <sha12> | scorecard <sha12> | work
  <sha12>` from `tools/job_pins.py <job>`. A receiver re-runs it before acting; a differing pin means something changed
  since the sender looked: read what changed first. Before merge, `job_pins.py <job> --check` compares the current
  identity with the REVIEW, TEST and GATE records. Current commit pins require a clean worktree. An explicitly named
  scoped re-gate can reuse older TEST work only when its card/scorecard match the current gate and its entire tuple
  matches that earlier gate, and the gate file holds a `tester not re-run: <why>` line. Identity checks do not establish a PASS verdict or the owner's permission: read those
  separately, keep source fixed during verification, and merge the exact accepted commit.

## Account switch
An app restart or account switch kills every chat's inbox waiter. The coordinator runs `tools/switch_census.py` and
wakes the chats it lists. A woken chat re-reads this file, its job card and its HANDOVER note, then re-arms its
waiter. A PAUSED chat notes new items in its HANDOVER note and `.seen` and does not re-arm.

## Job cards
No build starts without a card: `jobs/<lane>-<n>/JOB.md` from `coordinator/JOB-TEMPLATE.md`. It holds the task, the
`Systems:`, `Work:`, `Attempt log:` and `Scorecard:` lines, what it waits on, rollback, the acceptance criteria with an
"applies / why not" line for every scorecard criterion, keep-or-revert measures, and the tried-and-failed rows that
match. Step 0 is a grill: the builder lists only the design questions the card does not settle; non-blocking ones go
ahead on its recommended answer, marked "assumed". Before changing a card a lane is working on, copy it to
`JOB.md.pre-<UTC>`.

## The job loop
1. **Build.** Plan, build, run the offline tests (fast checks that need no heavy environment; each must be able to fail),
   commit on the job's branch, send REVIEW-ASK: what changed, tests with commands and results, what could not be tested.
2. **Review.** The reviewer reviews the whole job against the card, re-runs any test it doubts, and writes
   `jobs/<job>/REVIEW-<n>.md`: line 1 is `round <n> | sent back by: first|review|tester|gate|owner | required open <k> |
   closed since round <n-1> <c> | new <m>`, then the pins line, then findings as five-part fix recipes
   ([docs/review-ladder.md](../docs/review-ladder.md)). First review only: up to 3 improvements with benefit and effort,
   and the one it recommends.
3. **Fix.** The builder fixes every required item, makes the recommended improvement (or records why not), and writes
   `jobs/<job>/FIXES-<n>.md`: one line per finding id, `done` / `done differently, because ...` / `could not apply,
   because ...`, plus the check's output. Then REVIEW-ASK again.
4. **Recheck.** The same reviewer re-runs each "how to check", marks `fixed` or `still wrong`, then reviews what the
   fixes touch. After round 2, if every open fix is mechanical, the checks alone settle them.
5. **Test.** Clean review: TEST-ASK to the tester, which runs the job's real tests and writes `jobs/<job>/TEST-<n>.md`
   with WORKS or NOT WORKS and proof. NOT WORKS goes back to step 3.
6. **Gate.** WORKS: the reviewer starts a fresh gate (`GATE-BRIEF.md`, file `jobs/<job>/GATE-<n>.md`). PASS: DONE to
   the coordinator, which asks the owner. The owner's yes comes back as GO; the reviewer sends READY. FAIL: the builder
   fixes only the gate's must-fixes (`FIXES-<n>-gate.md`, with an `Impact:` line under each), the reviewer does a scoped
   check, and a fresh scoped re-gate looks at the fix and what it touches. A second FAIL, or a fix that turns into a
   redesign, gets a full fresh gate.
7. **Integrate.** The integrator merges only READY jobs, sends MERGED, and asks for a play where a player would see the
   change. A job is done at MERGED; a player-facing job is accepted only after the play passes on the merged build.

## Attempts and TRIED-AND-FAILED
An attempt is one change with one idea, committed alone, with the numbers it must not make worse. If a test fails or a
measured number moves past its tolerance, revert at once (`git revert`, never a reset or force) and never fix on top
of a worse version; a small breakage gets up to 3 quick fixes, then a revert. Every failed idea is written down with
why it failed. A failure stays with its job until it fails the same way in 2 jobs or its cause is clearly general; then
the coordinator moves it to the shared `TRIED-AND-FAILED.md`, which every new card checks. A retry of a listed idea must
say why its case differs. **v0.1 does not ship the attempt engine** that enforces this; keep the log by hand.

## Escalation
After 2-3 rounds with required findings still open, or a round that closed nothing, the reviewer sends UP. The
coordinator picks one: raise the chat's effort (context kept), add one specialist with a short hand-off, or change the
approach. A stuck job can first get a stuck-only advisor (`coordinator/ADVISOR-BRIEF.md`).

## Context, compaction and hand-over
Clear a chat between unrelated jobs or when its context gets large. First write `lanes/<slug>/HANDOVER-<role>.md`
(job and step, done and verified, half done and next step, open item ids, branch and commit, background jobs; state,
not rule text) and tell the coordinator: a cleared chat cannot wake itself. After a clear: re-read this file, your
card and your note, act on any unseen item, restart your waiter.

## Usage pacing
Run 2-4 build lanes at once. Only the coordinator reads the usage meter: at its hold point nothing new starts and the
step in hand finishes; at its pause point everything pauses. Near a short window's limit: no new gate, commit what is
green, write the hand-over note.

## Work rules
One code job = one branch in its own worktree. Back up every file you author. Questions for the owner go to the
coordinator as Q items with options and a recommended answer; carry on with reversible choices marked "assumed".
