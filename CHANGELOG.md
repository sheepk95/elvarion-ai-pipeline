# Changelog

## v0.1.2 (unreleased): fixes from two independent reviews of v0.1.1

A Codex CLI review (GPT-6 Astra, extra-high) and a fresh Opus 5.5 review (extra-high) both rated v0.1.1 ready at
7.5/10, with no blocker or major defects. This version fixes every minor defect and improvement they reported. Each
behaviour fix has a test that fails on v0.1.1 and passes here.

### Job pins
- A REVIEW, TEST or GATE record that holds a different pins line anywhere in the file is refused (exit 2), not only
  in its first five lines.
- A dirty-worktree refusal names the first changed paths and warns against `git clean` on proof media; the checker's
  git calls use `--no-optional-locks`, so it never takes the index lock from a builder.
- When a scoped re-gate does not accept an older TEST, a NOTE line says which condition failed. A READY mismatch is
  printed once. Exit 2 for a dirty worktree is documented, as is the `tester not re-run: <why>` line a scoped re-gate
  needs (GATE-BRIEF.md, RULES.md, tools/README.md).

### Inbox and census
- `--refs` is refused when any line separator Python's `splitlines()` knows (not only CR and LF) or NUL is in it.
  A filesystem without hard links gives one clear error and leaves no item or temporary file.
- `switch_census.py` warns and carries on for a damaged `archived-sessions.idx`, a damaged `--account-pairs` file, or
  a session file that is not a JSON object or has the wrong field types. Its Windows-only message shows even where
  `ctypes` cannot load.

### GPU lease
- The ledger lock wait is 120 s, more than two telemetry samples at their timeouts; a claim holds the lock for one
  sample. `run` returns its job's exit code even when the final release cannot get the lock.
- With `--wait`, a telemetry failure before the deadline counts as "busy" and keeps the queue place; without
  `--wait`, or at the deadline, it is still refused. Off Windows a claim refuses at once and says process scanning is
  Windows-only.
- SKILL.md no longer promises that a flag is never left behind or that a killed wrapper's job stays booked for five
  minutes.

### Librarian
- `--simulate-install` checks TRUST.json against the candidate folder's files, so it predicts the row the real install
  gets. `--after-install` passes for one row at the expected path whatever its status and reports that status
  (`installed-unverified` means review pending), so a fresh install no longer fails.
- Heartbeat times that are huge, infinite, NaN or far in the future count as unreadable everywhere (status, freshness,
  asks). A blank TRUST provenance never counts as approval. The README says the catalogue's trust is a build-time
  snapshot: editing a package or revoking trust needs an INDEX rebuild.

### Animation kit
- A missing checkpoint file exits 2 like every other checkpoint refusal (it exited 1).

### Tests
- New guards for each item above, including mutants the reviewers showed were unguarded in v0.1.1 (first-pin-only
  scan, scoped header end anchor, queue-ticket start time, blank provenance). The wait-ticket cleanup test no longer
  depends on timing.

## v0.1.1: reliability fixes from three independent reviews

The CPU-only checks in `tools/run_checks.py` cover the behaviours their suites exercise (each suite is listed in
`SUITES` there). Each new guard was shown to fail on the v0.1 code, or with the fix removed, before it was accepted.
The pinned animation install (`PINNED=1`) and everything under "Not covered by the checks" below are not exercised
by those suites.

### Job pins (`pipeline/tools/job_pins.py`)
- `--check` now requires REVIEW, TEST and GATE records (a missing review used to pass) and compares each record's
  full card, scorecard and work pins with the gate, not only the work pin.
- A scoped re-gate may reuse an older TEST only when its whole pins line matches the earlier gate it names, the gate
  says `tester not re-run: <why>`, and the TEST's card and scorecard still match the current gate. A record holding
  two different pins lines in its first five lines is rejected (v0.1.2 extends this to the whole record).
- A current code-work pin refuses a worktree with tracked or untracked (non-ignored) changes.
- The success line no longer says "merge": matching pins are not a gate PASS or the owner's GO.

### Inbox (`send_item.py`, `switch_census.py`)
- Items are published with a no-overwrite hard link, so two senders in the same second can no longer overwrite each
  other. A cleanup warning after publishing is not reported as a failed send.
- `--refs` with a line break is refused (it could forge header lines); `--help` shows usage and exit codes.
- Off Windows the waiter check reports "unknown" instead of crashing after the item was written.
- `switch_census.py` reports, instead of crashing, when `LOCALAPPDATA`, the session folder or a session file is
  missing or damaged, and says plainly that it is Windows and desktop-app only.

### GPU lease (`gpu-lease/`)
- The ledger lock is an OS file lock released when its holder dies, replacing the stale-lock takeover that could let
  two agents hold it at once. **Update every client sharing a ledger together** (see `gpu-lease/SKILL.md`).
- A waiting `--yields` job no longer blocks ordinary claims. Admission refuses when process or GPU telemetry is
  missing, and samples it after taking the lock.
- Bookings and queue tickets record their process start time, so a reused process id cannot keep a dead job's booking.
- `run` passes the booking id to its command as `GPU_LEASE_ID` and returns 127 (not 3, "busy") when the command cannot
  start. Exit codes are documented correctly.

### Desk and librarian
- The desk watcher no longer reports a warning from an earlier poll as current, names an unreadable lane file instead
  of skipping it silently, and survives a corrupt `read-offsets.json` (it keeps a `.corrupt-<UTC>` copy).
- The librarian skips request files whose names are not valid ids (a crafted name could forge `list` output) and no
  longer crashes `status` on a damaged heartbeat. It has a round-trip test.
- The skill index marks a skill `vetted` only when an owner `TRUST.json` matches every file in the package;
  everything else is `installed-unverified`.

### Animation kit
- `run_sam3db.py` verifies the checkpoint against Meta's published sizes and hashes before torch or Meta's code is
  imported, and refuses a mismatch (`--trust-unverified-checkpoint` is the explicit, logged override).
- `PINNED=1 bash install_venv.sh` installs the tested Windows/Python 3.11 freeze. Defaults and wording from the
  original project are now neutral. Meta's `src/` clone is git-ignored.
- `check_review.py` enforces the minimum picture count even when every item is N/A.

### Docs, setup and CI
- New: [quick start](docs/quickstart.md), `tools/demo_job.py`, `tools/run_checks.py`, CONTRIBUTING.md, a Windows CI
  workflow (Python 3.11 and 3.13, pinned actions, read-only permissions), and templates for the grill, hand-over and
  tried-and-failed files.
- The docs say plainly that the multi-chat workflow needs the Claude desktop app's chat tools; CLI users get the file
  tools and must start and wake chats themselves.
- Hook examples quote paths with spaces; the desk docs cover the recovery keys and the self-clear hand-over line.

### Not covered by the checks
Live desktop wake-ups, real GPU admission under load, POSIX runtime behaviour, SAM / Blender inference and animation
quality still need their own acceptance runs.
