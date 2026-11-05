# Changelog

## v0.1.1 (unreleased): reliability fixes from three independent reviews

Everything below is covered by `python -I -B tools/run_checks.py` (Windows, CPU only). Each new guard was shown to
fail on the v0.1 code, or with the fix removed, before it was accepted.

### Job pins (`pipeline/tools/job_pins.py`)
- `--check` now requires REVIEW, TEST and GATE records (a missing review used to pass) and compares each record's
  full card, scorecard and work pins with the gate, not only the work pin.
- A scoped re-gate may reuse an older TEST only when its whole pins line matches the earlier gate it names, and its
  card and scorecard still match the current gate. A file holding two different pins lines is rejected.
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
