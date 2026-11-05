---
name: gpu-lease
description: Book the shared GPU in a lease ledger before ANY GPU job and release the booking when the job ends, so AI agents in different chats never overload one machine. Use before launching a game-engine editor or build, a 3D or image generator, a Blender render, a local model, CUDA code, or a GPU video encode; when a run fails out of memory or a launcher prints "GPU BUSY"; or when asked who is using the GPU.
---

# GPU lease: book the card before every GPU job

Several agents (Claude, Codex, scripts) work in different chats on one PC. Each of them can start a job that fills the
GPU. Two such jobs at once make both slow, or crash one of them, or power the machine off. The fix is a small shared
ledger: **book before the GPU loads, release when it stops.**

The tool is `scripts/gpu_lease.py` (standard library only; Windows is the tested platform). The ledger is a folder of
small JSON files, by default `~/.gpu-lease` (set `GPU_LEASE_DIR` to move it). Ledger changes use a kernel lock on the
persistent `.lock` file. Never delete or rename that file while clients are running.

**Upgrade:** stop all old-version clients before moving a ledger to this version, including long-running services that
import the module. Older versions rename `.lock` as a stale-lock recovery mechanism and cannot safely share a ledger
with this version. Restart clients only after they all use the new version. This change does not upgrade running clients.

## The rule

1. **Look first.** `python -B scripts/gpu_lease.py status` shows open leases, waiting claims, known GPU programs that
   nobody booked (SEEN), booked GB and the real free memory from `nvidia-smi`.
2. **Book before the job, release after.** The best form is the wrapper: it opens the lease, renews it every minute,
   and closes it when the command exits, even on failure.
   ```
   python -B scripts/gpu_lease.py run --who "<your chat title>" --what "render the LODs" --gb 6 --wait 1800 -- <command>
   ```
   For a job you start yourself, claim with its process id and release afterwards:
   ```
   python -B scripts/gpu_lease.py claim --who "<chat title>" --what "<job>" --gb 8 --pid <job pid> --wait 1800
   python -B scripts/gpu_lease.py release <lease id> --note "done"
   ```
3. **Exit 3 means busy** (the card is booked, or the request is refused). The message names who holds it. Exit 1
   with `GPU LEDGER ERROR` means required process or GPU-memory telemetry was unavailable: restore PowerShell/CIM and
   `nvidia-smi`, then retry. The job was not started. `status` still reports degraded telemetry. Wait
   (`--wait <seconds>` queues you, first come first served) or do other work. Never start the job anyway, never
   delete or rename another agent's lease, never cut someone else's job short.

## Commands

| Command | What it does |
|---|---|
| `status [--json]` | Lists leases, queue, unbooked programs, booked GB, free memory. |
| `run ... -- <command>` | Claim, run the command, release. Exit code is the command's, or 3 if the card stayed busy. |
| `claim ... [--pid N]` | Open a lease and print its id. With `--pid` the lease ends by itself when that process dies. |
| `renew <id> [--minutes M]` | Extend a lease. A `--pid` does not stop expiry: book the job's full length or renew. |
| `adopt <id> <pid>` | Count another process tree (for example one started with `Start-Process`) as part of the lease, so it is not counted twice. |
| `release <id> [--note ...]` | Close the lease. The record moves to `closed/` and is never deleted. |

Exit codes: 0 ok (including an already-closed or unknown id for idempotent `release`), 3 busy / refused or missing
lease for `renew` / `adopt`, 2 bad arguments, 1 tool or telemetry error. `run` returns its command's own exit code
(127 if the command cannot be started) and gives the command the booking id as the `GPU_LEASE_ID` environment
variable, so a launcher it starts can `adopt` its own process tree.

Each booking also records its process's start time, so a dead job whose process id the system has handed to a new
process no longer keeps the booking open (Windows, and Linux with `/proc`; elsewhere the plain pid check applies).

## How much to book (`--gb`, peak VRAM)

Bookings plus the unbooked programs the tool recognises share a budget of 21.6 GB on a 24 GB card (90%; the rest is kept
for the desktop and any always-on model server). Change it with `GPU_LEASE_BUDGET_GB`.

Rough guides: game-engine editor or test run 3-8 GB; Blender Cycles render 4-10 GB; a speech model 4 GB; for CUDA code,
measure (`torch.cuda.max_memory_allocated()`) and add 1 GB. Unsure: book high, then note the real peak.

- `--exclusive`: needs the whole card (timing runs, 3D generation, models over about 12 GB). Nothing else may be open,
  and nothing opens beside it.
- `--yields`: long background work that can stop between items. It queues behind ordinary claims, and steps aside when
  someone waits (the waiter writes a legacy `UNITY_PRIORITY` flag file that your background runner must watch).
- `--minutes M`: lease length before a renew is needed (max 480; the `run` wrapper renews for you).

## What the tool checks before it admits a claim

- No open exclusive lease; an exclusive claim needs nothing else open.
- Booked GB + recognised unbooked programs + yours is within the budget, and `nvidia-smi` shows your GB plus 0.5 GB free.
- Process enumeration and free-memory telemetry must both succeed. Admission fails closed if either is unavailable;
  process enumeration currently requires Windows and PowerShell/CIM.
- Admission samples telemetry after taking the ledger lock, so it does not reuse a snapshot from before a lock wait.
  The telemetry commands have bounded timeouts; other ledger clients may wait while they finish. This remains a
  cooperative protocol: an unbooked process can start after any snapshot, so every participating launcher must book.
- Nobody is ahead of you in the queue.
- Legacy flag files (`GPU_HEAVY`, an unexpired `UNITY_PRIORITY` written by another tool) count as someone else's
  exclusive booking. The folder is `GPU_LEASE_CONS_PORT` (default: `<temp folder>/cons-port`).
- Leases whose process died, or that expired without a renew, are reaped by the next call. Dead queue tickets are dropped.

## Environment variables

`GPU_LEASE_DIR` (ledger folder), `GPU_LEASE_CONS_PORT` (legacy flag folder), `GPU_LEASE_BUDGET_GB`, `GPU_LEASE_AGENT`
(default for `--agent`). `GPU_LEASE_SEEN_JSON` and `GPU_LEASE_TEST_HOLD_S` exist for the self-test only.

## Traps

- On Windows a rename or delete fails while any process has the file open. The tool retries for a few seconds and never
  crashes or leaves a flag behind.
- A Git-for-Windows program in front of a GPU program (`timeout`, `env`, `bash other.sh`) can break the process tree,
  so the GPU program shows as SEEN while your lease is open. For a time limit inside a booked script use
  `scripts/lease_timeout.py <seconds> <command> [args...]`, a plain Python wrapper that keeps the chain.
- A killed `run` wrapper leaves its child running unbooked once the 5-minute heartbeat lapses.

## Proof

`python -B scripts/test_gpu_safety.py` uses isolated temporary files and stubbed telemetry to check live-holder
exclusion, crash recovery, concurrent ledger updates, queue priority, telemetry failure and status reporting. It does
not access a real GPU or ledger.

`python -B scripts/selftest.py` runs against a throwaway folder (never a real ledger): shared and exclusive admission,
the budget, dead-pid and expiry reaping, the legacy flags, a reader holding a flag open during renew and release,
twelve agents racing for 3 GB each (exactly six must be admitted; with the mutex removed all twelve are), waiting
`run`s, first-come-first-served queueing, a `--yields` lease stepping aside, `adopt`, and unbooked programs being
counted and closed. It reads real free memory from `nvidia-smi`, so run it while the card has at least 19 GB free.
Removing the budget check turns several of its checks red.
