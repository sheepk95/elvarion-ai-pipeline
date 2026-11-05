# JOB TEMPLATE (writer: the Coordinator). Copy to jobs/<lane>-<n>/JOB.md and fill every <...>.
# Keep the field names at the start of their lines: tools/job_pins.py reads `Scorecard:`, `Systems:`, `Work:`,
# `Attempt log:`, the `Reads:` section and the 'Keep-or-revert measures' section.

# JOB <lane>-<n>: <one-line task> (<code job | document job | script job>)
Written by the Coordinator <UTC stamp from `date -u`>. Lane: <Lane>. Work items: <ids from the lane's work list>.
Systems: <comma list of the parts and tools this job touches; matched against TRIED-AND-FAILED rows>
Work: <code job: commit | worktree <absolute worktree path> | branch <branch>; document job: file | <absolute path>[ ; <absolute path>]; nothing after the last path or branch>
Attempt log: <jobs/<lane>-<n>/ATTEMPTS.md | none, because <reason> (only for a job that changes no file)>
Scorecard: `<path to the lane's scorecard>`
Reads: <another lane's document this job relies on, one row each: `- <path> | <sha12>`; or `Reads: none`>

## Step 0: GRILL (every new card)
Before building, read this card, the lane's scorecard and the owner's past answers for this lane, then write
`jobs/<lane>-<n>/GRILL-<n>.md` with only the design questions those do not settle: numbered, 2-3 options each, a
recommended answer with one line of why, `blocking: yes|no`. Send ONE Q item to `coordinator/inbox` naming the file.
blocking: no -> carry on with your recommendation, marked "assumed, owner can overrule"; only blocking: yes pauses
the parts it touches. Nothing open -> the file says "none open", no Q item, start at once.
Already answered (do not re-ask): <refs>. Likely topics (hints, not answers): <topics>.

## Skills (do this first)
Ask your skill librarian once for this job and read the picks. Picks the Coordinator already got: <list or none>.

## Task
<what, which files or area>

## Order of work
<numbered steps>

## Waits on
<jobs (gate PASS and merged), items, owner's answers; or "nothing">

## Rollback
<how to undo>
Last good: a code job's base commit on its branch (git revert, never reset --hard or force); a document job's copy in
`jobs/<lane>-<n>/good/`.

## Acceptance criteria
Kind: **<the scorecard's kind name>**. Bar: <e.g. average 7.0, every part 6.0, no open defect>. Hard bars (measured,
never scored): <list>.
### Criteria, applies / why not (EVERY criterion on the scorecard)
- C<n> `<id>`: <heading line>. APPLIES | WHY NOT: <reason>.
### Owner's answers that bind this job (quote them)
### Own checkable lines (spec rules by number, commands that must pass)

## Offline tests
Builder, before REVIEW-ASK: <the fast checks for this job: compile or lint, unit tests, scripted data checks; OR
`Offline tests: none, because <reason>`>. Each test must be able to fail. REVIEW-ASK gives commands, results and what
cannot be tested offline (for the tester). Reviewer: a missing test where one makes sense, a wrong "none", or a test
that cannot fail, is a finding.

## Keep-or-revert measures
<one line per number this job must not make worse: `<name> | <command that prints it> | bar <op><value> | tolerance <abs> | <higher|lower> is better`; OR `none: tests and review verdicts only, because <reason>`>

## Tried and failed (pasted by the Coordinator, <UTC>)
<matching rows from TRIED-AND-FAILED.md and this lane's failed attempts, or `none matching`>

## Tester and owner's gate
Clean review -> the reviewer sends TEST-ASK (job, branch, commit, worktree, offline results, the not-tested-offline
list) to `lanes/<lane>/inbox/tester`. The tester writes `jobs/<lane>-<n>/TEST-<n>.md` (pins line in the top 5 lines)
with WORKS or NOT WORKS and proof. <What the tester runs for this job; for a document job, the scripted checks.>
WORKS -> the fresh gate (GATE-BRIEF.md). Gate PASS -> DONE to `coordinator/inbox` with the pins line, IDEAS, the gate
file and the evidence path. Only the owner's yes, relayed as GO, sends READY.

## Not in this job
<next jobs, out-of-scope items>

## Done
On GO, the reviewer sends READY to `lanes/integrator/inbox/builder` with: branch and accepted commit (no branch:
`none: <file> sha256 <hash>`), gate file, TEST file, evidence path, GO item id, play request (paths to play, or `none:
nothing player-facing`), IDEAS (every `later` finding of every gate and every idea parked in later review rounds,
each with its file), and the pins line from `tools/job_pins.py <lane>-<n>`. Never READY before the owner's yes.
