# Changelog

## v0.1.5 (2026-11-05): follow-up review fixes

- Desk questions only count as answered copies when they end with a complete answered marker. Mentions of earlier
  answers inside an unanswered question no longer suppress its wake-up.
- The animation checklist gate retains the selected master's item prompts, section placement and section 10
  questions, and refuses duplicate item IDs. Hidden comments and code blocks do not count as checklist items.
  Keep prompts on their checkbox lines and add evidence underneath; see the documented Markdown subset.
- Built-in librarian delivery uses per-request locks and flushes output before writing shown markers. Blocked
  output cannot hold up unrelated requests, and acknowledgement failures are reported. CLI recovery is prepared
  before requests are published, covering on-time answers as well. A broken pipe leaves the answer available for retry.
  Late-answer preview helpers do not move or acknowledge answers;
  a crash between successful flush and acknowledgement can cause a duplicate, and the unshipped external finder
  hook remains outside this delivery guarantee.
- Regression checks cover the original failures, valid checklist copies, competing delivery and progress while a
  different late answer is pending. Live desktop, model, GPU and animation acceptance remains separate.

## v0.1.4 (2026-11-05): review, routing and recovery fixes

- The desk reader flushes its output before acknowledging messages, preserving unread work when output fails.
- Visual review evidence accepts quoted image paths with spaces, rejects non-image paths and unrelated printed
  paths, and requires a separate reason for N/A items. Codex evidence supports the literal call forms documented
  in the animation README; it records a tool call, not proof that the call succeeded or the image was observed.
- The account-switch census requires an explicit `--account-pairs` mapping for `CLAUDE_CODE_USER_EMAIL` and an
  unambiguous title, inbox and workspace path before suggesting a wake. It never guesses the current account from
  stored session folders. Damaged routing metadata refuses the census.
- Waiter registration and cleanup share an OS lock. A second waiter cannot replace an existing live or potentially
  live unverified registration. Recovery keys distinguish separate registrations, including episodes without process identity.
  Re-arm existing waiters after upgrading; older clients do not participate in the registration lock protocol.
- Failed librarian request moves become retryable after the recovery backoff. Per-request OS locks serialize
  claims, and heartbeat writes refuse a busy lock instead of updating without it. Upgrade mailbox clients together.
  The legacy abandonment helper retains its marker after a failed move and uses the same request lock.
- GPU admission includes recognized GPU programs in the caller's ancestry. The Windows timeout wrapper contains
  commands in a Job Object before starting them and waits for its processes to terminate before returning.
  Descendants are also terminated when the parent exits normally; restrictive enclosing jobs may refuse startup.
- The animation source converter finds its default checkpoint under the kit root; the environment override remains.
- CPU regression coverage includes competing processes, broken output pipes, failed moves and Windows descendant
  termination. Live desktop wake-ups, GPU admission under load, SAM/Blender inference, animation quality and POSIX
  runtime behaviour remain separate acceptance checks.

## v0.1.3 (2026-11-05): dependency, process identity and animation output fixes

- Job pins no longer mistake a dependency path beginning with `none` for an empty Reads section.
- Inbox waiters record process creation identity; a reused Python PID cannot establish that the receiver is armed.
  Restart existing waiters after updating so they write the new identity record.
- The account-switch census returns a nonzero result when unread work has no matching open chat.
- Adopted GPU process trees are excluded from unbooked detection only while their recorded creation identity matches.
  Re-adopt still-running processes from older ledgers after checking their identity; see `gpu-lease/SKILL.md`.
- Animation runs require a fresh output folder, preserving older takes instead of mixing skipped or leftover frames.
  An exclusive claim prevents simultaneous runs from sharing that output; failed runs keep the claim for diagnosis.
  The source converter reads and sorts complete numeric frame indices, including those above 9999.
- The skill catalogue's standard-library fallback preserves multiline descriptions and `when_to_use` text.
  Existing catalogues refresh on the next `catalogue-check`.
- Add CPU regression coverage for these cases. Live desktop wake-ups, GPU admission under load, SAM/Blender inference
  and animation quality remain separate acceptance checks; this release does not claim those have been verified.

## v0.1.2 (2026-11-05): fixes from two independent reviews of v0.1.1

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
- The GPU-lease hardware self-test (`gpu-lease/scripts/selftest.py`) passed all 48 checks on an RTX 3090.

### Repository
- New SECURITY.md: report a vulnerability privately through the Security tab.

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
