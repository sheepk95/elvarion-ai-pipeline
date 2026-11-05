# Security policy

## Supported versions

Only the latest release (v0.1.2) and `main` get fixes. This is an experimental toolkit, so older versions get no
backports.

## Reporting a vulnerability

Please report it privately, not in a public issue. Open the repository's **Security** tab and choose
**Report a vulnerability**, which uses GitHub's private vulnerability reporting.

Include:
- the tool;
- the exact command;
- what you expected and what happened;
- a minimal reproduction in a temporary folder.

Leave out credentials, private transcripts and real inbox contents. One person maintains this project, so replies are
best effort and there is no bounty.

## What counts

Examples that matter here:
- forging or overwriting an inbox item, or forging its header lines;
- making `job_pins.py --check` accept REVIEW, TEST or GATE records that do not match the gate;
- getting two GPU-lease clients to hold the ledger lock at once, or getting a claim past admission;
- making the skill index mark a package `vetted` without an owner `TRUST.json` that matches every file;
- making `run_sam3db.py` load a checkpoint that fails verification without `--trust-unverified-checkpoint`;
- getting code to run from a file the tools only read.

Out of scope:
- **Third-party software.** Report problems in Meta's SAM 3D Body, Blender, Auto-Rig Pro or the Claude desktop app to
  their owners.
- **Trusted participants.** The file-based protocols are cooperative and assume every participant is trusted. A local
  user who can write to the pipeline's folders can already do anything the tools do.
