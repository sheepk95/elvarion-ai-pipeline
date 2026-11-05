# First local run

Start with the file tools before wiring live chats. You need Windows 10/11, Python 3.11+ and Git on PATH. Clone this
repository into your own working folder and open PowerShell there. Quoted paths support folders containing spaces.
No model subscription, GPU, memory server or Blender installation is needed for these local checks.

```powershell
python --version
git --version
python -I -B tools/demo_job.py
python -I -B tools/run_checks.py
```

The demo creates a fresh temporary workspace, sends an inbox item using the real sender, receives it with the real
waiter, and verifies that a changed deliverable invalidates its earlier pins. It prints `DEMO PASS` only after both
the successful check and the deliberate rejection. Its review/test/gate records are labelled fixtures; no AI review
or human approval is claimed. The folder is retained for inspection and its absolute path is printed.

The test runner prints each suite's result and a path to full logs plus `summary.json`. A failed suite gives a
nonzero exit code. Do not connect live work until the relevant checks pass.

## Host requirements

| Component | What is supplied | What you must supply |
|---|---|---|
| Inbox, pins, desk and librarian tools | Python file protocols and bounded waiters | Writable local directories and a process runner |
| Claude desktop multi-chat workflow | Prompts and file conventions | A desktop host exposing chat creation, messaging and background-completion wake-ups |
| Claude Code CLI | File tools and recipe-hook example | Separate CLI sessions and your own supervisor or manual wake-ups; desktop session census does not discover these |
| Codex helpers | File formats can be shared | Your host's helper/session control; no Codex wake-up adapter is included |
| Shared memory | A hook recipe | Your own configured memory server, permissions and scoped recipe |
| GPU/animation | Booking and remap scripts | NVIDIA telemetry, compatible hardware, model access, Blender and any required add-ons |

Check the actual capabilities in your host instead of assuming that a prompt grants tools. For a live wake-up
acceptance check, start one receiver chat with its waiter in the background, send a harmless test item from a
second chat, and confirm the receiver starts a new turn and handles that exact item without a manual prompt.
If only the Python process finishes, the file protocol works but the host's wake-up integration is still missing.

## Start one lane

1. Choose a separate pipeline workspace and copy `pipeline/` into it. Keep the existing `tools/` hierarchy.
2. Copy `lanes/example-lane/` to `lanes/demo/`, fill in its charter, and create leaf inboxes for its builder and
   reviewer plus `coordinator/inbox`. Add tester/integrator inboxes only for roles you use.
3. Write a small acceptance scorecard, then a job card using `coordinator/JOB-TEMPLATE.md`. Set `Work:` and
   `Scorecard:` to real paths. Commit code before producing current-work pins; tracked or untracked non-ignored
   changes prevent a current commit pin from claiming an immutable test target.
4. Start the coordinator using [START-COORDINATOR.md](../pipeline/START-COORDINATOR.md). Create/message the other
   chats through your host's supported tools, or manually if those capabilities are absent.
5. Try one small job through builder, reviewer and gate. Check the full pins before acting. Pin equality establishes
   identity, not a PASS verdict or the owner's approval: the integrator must read both separately.
6. Add the [desk](desk.md), [librarian](../librarian/README.md) and [recipe hook](../hooks/README.md) after that exchange
   works. Keep one writer per lane inbox acknowledgement file and per authored source file.

Keep the [worked example](../pipeline/examples/README.md) as a format reference. Its project, commits and outcomes
are fictional; it is not an executable acceptance record for your work.
