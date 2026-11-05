# How to start the pipeline

First complete [the quick start](../docs/quickstart.md). In a desktop host with chat creation/messaging tools, start
ONE chat by hand; it can then start the rest. A CLI-only host needs you or your own supervisor to create the chats
and deliver wake-ups. A Python waiter exiting does not itself start a new agent turn in an arbitrary host.

- Title: `Coordinator`. Working folder: the pipeline root (the folder holding `RULES.md`). Model: your large model
  (with Claude, Opus). Effort: high.
- First message: "Read RULES.md, PIPELINE.md and coordinator/COORDINATOR.md, then do the Start steps in
  COORDINATOR.md."

Before you start it:

1. Create one charter per lane: copy `lanes/example-lane/` to `lanes/<slug>/` and fill in `LANE.md`.
2. Create the inbox folders the coordinator will use (`coordinator/inbox`, and `lanes/<slug>/inbox/builder`,
   `.../reviewer`, `.../tester` for each lane, plus `lanes/integrator/inbox/builder` and
   `lanes/player-tester/inbox/builder` if you use them).
3. Put each lane's acceptance scorecard where its `LANE.md` says (even a short list of criteria and a pass bar).
4. Copy `coordinator/TRIED-AND-FAILED-TEMPLATE.md` to `TRIED-AND-FAILED.md` in the pipeline root. Builders write
   step 0 from `coordinator/GRILL-TEMPLATE.md`, and every chat writes its hand-over note from
   `coordinator/HANDOVER-TEMPLATE.md`.
5. Stop any older setup that writes the same files, so two pipelines never edit the same work.

Copy `pipeline/tools/` from this repo into the pipeline root as `tools/`. `switch_census.py` and `job_pins.py` take the
parent of `tools/` as the root by default and have `--root` overrides. `send_item.py` has no `--root`: a relative
`--to` is relative to the parent of `tools/`, so use an absolute inbox path when targeting another root.
`wait_inbox.py` takes the inbox path. `switch_census.py` discovers Claude desktop session files, not CLI sessions.
Each script prints its usage with `--help`.
