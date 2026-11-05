# LANE: Example (builder, reviewer, tester)

Copy this folder to `lanes/<slug>/` for each lane and fill it in. Read RULES.md first; it wins over this card.

## Chats
- `Example builder`: continuing builder (medium). Inbox `lanes/example-lane/inbox/builder`.
- `Example reviewer`: continuing reviewer (high). Inbox `lanes/example-lane/inbox/reviewer`.
- `Example tester` (optional): standing tester (mid model, medium) that runs the slow or environment-bound tests and
  sends WORKS or NOT WORKS before the gate. Inbox `lanes/example-lane/inbox/tester`.
- A fresh extra-high gate per finished job (`coordinator/GATE-BRIEF.md`), started by the reviewer.

The loop is RULES.md 'The job loop'.

## What this lane owns
<One sentence on the area, then the concrete things it owns. Be specific enough that two lanes can never both claim a
file.>
- <module, folder or document>
- <the contract other lanes read from this lane, and where it lives>

## What this lane does not own
- <neighbouring areas and which lane owns each>
- Merging: the integrator only.

## Context to read (by path; read only)
- Work list (what to build, in order, with dependencies): `<path>`
- The owner's answers that bind this lane: `<path>`
- Scorecard (acceptance criteria base for every job, with its pass bar): `<path>`. Never edit it; send the coordinator
  a Q if a criterion cannot be applied or measured.
- Contracts this lane reads from other lanes (pin each on the job card under `Reads:`): `<paths>`

## Skills
- At setup, each role asks the skill librarian once for its role in this lane and keeps the picks in
  `lanes/example-lane/<ROLE>-SKILLS.md` (`- <name> | <SKILL.md path> | why`, one per line). Re-read the list after
  every clear.
- At each new job from the coordinator, ask again for that job only.

## Hand-over notes
`lanes/example-lane/HANDOVER-builder.md`, `HANDOVER-reviewer.md`, `HANDOVER-tester.md` (RULES.md 'Context,
compaction and hand-over').
