# How to start the pipeline

Start ONE chat by hand; it starts the rest.

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
4. Stop any older setup that writes the same files, so two pipelines never edit the same work.

Copy `tools/` from this repo into the pipeline root. `send_item.py`, `switch_census.py` and `job_pins.py` take the
parent of `tools/` as the root by default (each has `--root` to override); `wait_inbox.py` takes the inbox path.
Each script prints its usage with `--help`.
