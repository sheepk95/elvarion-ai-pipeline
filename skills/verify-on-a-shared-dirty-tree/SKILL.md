---
name: verify-on-a-shared-dirty-tree
description: Prove what a commit would actually contain when the working tree also carries other agents' uncommitted work. Use before staging or committing in a repo several agents are editing, when a review finding cites a file:line you cannot reproduce at HEAD, when a type-check or test run must judge "HEAD plus my hunks" rather than the tree in front of you, when reversing your own edit inside a file that is dirty for someone else, and when deciding whether a batch of changes can land partially. Covers the HEAD-plus-mine configuration, staging blobs without touching the tree, the foreign-symbol completeness gate, byte-exact restores on Windows, and plumbing-only test merges.
---

# Verify on a shared dirty tree

Written from a code-upgrade sprint where three agents' uncommitted work sat in the same files. Every rule below is
one that produced a wrong answer first.

The problem this skill exists for: **the tree in front of you is not what your commit would contain, and every tool you
have (the compiler, the test runner, a reviewer's `file:line`) answers about the tree.**

---

## 1. A review finding's `file:line` is against the tree the reviewer read

Three work-order rows named symbols with **zero occurrences at `HEAD`**. They were real symbols in another agent's
uncommitted work, and the rows written against them had no premise.

```bash
git -C <repo> grep -n "<symbol>" HEAD        # not `grep`, and not the working tree
```

> **Rule.** A line number that resolves in your tree proves nothing about what a commit would contain. Premise-check
> every inherited row against `HEAD` before you spend a work window on it.

The mirror-image error: **"0 production callers" is not "dead".** Four helpers with zero callers under the source folder
had 20+ under the test folder, and deleting them would have bought speed with coverage. Grep the test tree separately,
and say which set is empty.

---

## 2. Build the configuration your commit would create, and type-check THAT

Two configurations, both checked, both reported:

| config | contents | what it answers |
|---|---|---|
| **A** | `HEAD` snapshots of every dirty tracked file, **plus** your own edited files, **minus** every untracked file | "does my commit compile?" |
| **B** | the working tree as it stands | "does the machine currently compile?" |

Measured on the sprint: A = 127 sources / 575 types, clean. B = 143 sources / 894 types, clean. Two different questions,
two different answers, and only A is about the commit.

> **Rule for building A: drop UNTRACKED files and put EVERY dirty tracked file at HEAD.** Substituting HEAD for only
> *some* of the dirty files produces phantom errors from the dependents you kept; a mixed control did exactly that and
> reported 12 errors that belonged to nobody.

Judge A **differentially** against a pristine control, never absolutely: identical error counts on both sides means
delta zero, which is the verdict.

### 2a. A differential check is only differential if both sides sit in the SAME place

A compile-check script treated sources **inside** the project's `Assets/` folder differently from sources outside it
(for in-project files it dropped the owning assembly's DLL from the reference set, sensibly, or every type would
collide with itself). Pointing it at 4 of that assembly's ~100 files **in place** reported 270 errors, all of the form
"type X could not be found". That reads exactly like a catastrophic edit. The same 4 files copied to a scratch folder
reported 0.

> **Rule.** Put the control and the subject in the **same location**, and re-run the CONTROL at the moment the subject
> looks bad. The control coming back clean is what turns "my change broke everything" into "the two configurations
> differ". Never compare an in-project run against an out-of-project run.

**Corollary.** A built-assembly cache (`Library/ScriptAssemblies/*.dll` in Unity) is only as fresh as the editor's last
recompile. With an editor open and no recompile since, the DLL predated the agent's edits by 74 minutes, which is *why*
a standalone check of new test code reported the new members as missing. That is information, not a failure: when
**every** error names a member you know you added, the expected-missing-only pattern has just validated every OTHER API
call in a file you wrote blind.

---

## 3. The foreign-symbol grep is a BATCH-COMPLETENESS gate

Building Config A is how you find out that your change does not stand alone. Two rows in the sprint edited code that
**existed only in another agent's uncommitted work**; the check that found it also proved that agent's batch could not
land partially.

```bash
# every symbol your hunks touch, checked against HEAD
for s in $SYMBOLS; do
  printf '%-40s %s\n' "$s" "$(git -C "$REPO" grep -c "$s" HEAD -- '*.cs' | wc -l)"
done
```

> **Rule.** Any symbol your edit references that has zero occurrences at `HEAD` is a dependency on somebody else's
> uncommitted work. Your row is blocked on their commit, and *their* batch is now all-or-nothing. Report both facts; do
> not quietly reorder your own work around it.

---

## 4. Stage the bytes you mean, without touching the tree

When your edit sits **inside** another agent's uncommitted block, you cannot check out the file and you must not
overwrite it. Write the blob you intend and stage it directly:

```bash
BLOB=$(git -C "$REPO" hash-object -w path/to/head-plus-my-hunks.cs)
git -C "$REPO" update-index --cacheinfo 100644,"$BLOB",src/Worker.cs
```

The index now holds exactly the bytes of record; the working tree keeps the other agent's version untouched. Record the
blob hash beside the source file in your manifest so the commit's contents are reproducible from the record rather than
from anyone's memory of what the tree looked like.

Never `git add -A` / `git add .` here. Stage by explicit path, after reading `git status`.

---

## 5. Reversing your own edit, byte-exactly, on Windows

Two ways the obvious restore silently fails:

- **`git show HEAD:<path> | Set-Content -Encoding utf8` is NOT byte-exact.** PowerShell 5.1 adds a BOM and converts LF
  to CRLF, so the path still shows modified after the "restore". Route it through Git Bash, which is byte-exact:

  ```bash
  git -C "$REPO" show HEAD:src/Foo.cs > src/Foo.cs
  ```

- **Reverse-editing a CRLF file with an editing tool leaves an endings-only delta**: `git status` says `M`, `git diff`
  shows nothing. For a file that carries ONLY your own edit, `git restore` is the correct reversal. For a file that
  carries anyone else's, it is the worst possible one.

> **Rule.** Restore = apply the exact reverse of your own edit. **Never a whole-file copy**: a snapshot encodes "the file
> as I first saw it", which in a shared tree is stale the moment another agent writes. One such restore deleted a peer's
> 21 uncommitted hunks and left the tree non-compiling.

After any restore or re-apply, **grep for your own symbols** before trusting a compile or a suite run. Keep multi-hunk
patches as re-runnable, idempotent scripts so recovery is one command. When the honest boundary is genuinely
unrecoverable by hand, a per-edit-batch backup store is a per-agent undo log: if the diff between the newest snapshot and
the working tree is *exactly* your own edits, that snapshot is proven to be "their state minus yours" two ways at once.

**An integrity check that compares a file with the snapshot its own tool took can only confirm itself.** A peer's
snapshot restore deleted all 21 hunks of a patch and nothing flagged it.

---

## 6. Rule the SCOPE on a measurement, not on a hunch

Parsing `duration` per `test-case` out of the baseline results XML and bucketing by file ownership (clean /
foreign-dirty / held / untracked) showed that one row's target needed **88 % of the suite** while the agent could touch
**12 %**. That is a scope ruling made on evidence in five minutes, instead of a row discovered to be impossible at its
own gate hours later.

> **Rule.** Before accepting a row on a shared tree, census what it needs against what you are allowed to touch, and put
> the percentages in the report.

---

## 7. Interference is about FILES PRESENT, not just runs in flight

An agent's truthful "no tracked file modified" still let an unverified **untracked** test file ride into a peer's
full-suite baseline: the engine imports and executes whatever is on disk, and `git status` is not the boundary it sees.
A latent compile error in that file would have presented as the peer's own work breaking.

- Interference checks ask "what NEW files of yours are on disk under the project?"
- An agent authoring into the project is inside the run-window protocol from its first **write**, not its first launch.
- A live run on the project path freezes writes for **every** agent, whoever's window it nominally is; census the path
  immediately before any write, not just before a launch.
- Holding runs is half a protocol; the other half is holding **edits**.
- A **queued or armed launcher counts as a run in flight**, and it is the one nobody censuses. A launcher armed as "wait
  for the other chain, then go when the census is clear" fired two minutes after the scheduling rule changed to explicit
  grants: correct under the rule it was armed under, wrong under the rule in force when it ran. List armed launchers in
  the message that arms them, and stop the queue **before** acknowledging a scheduling change, not after.

---

## 8. Attribute a red suite on a shared tree with a "mine reverted" copy

A full suite came back 77/78. The red check belonged to a page another agent was editing (its files changed during the
runs). A plausibility argument is not attribution, so it was measured:

- Copy the project's code, scripts and tests (without evidence and screenshots) to a short temp path. In that copy, put
  only YOUR files back to their pre-change bytes, with sha256 checks against the backup. The other agent's files keep the
  live bytes; confirm by hash.
- Run the real binary against the copy (an environment variable pointed it at the copy's root). A log line showed it
  started the copy's server script, so the copy really was the thing served.
- The same check failed with the same message, so the change did not cause it. A grep backed this up: no other page used
  the module's CSS class names, so its stylesheet could not reach them.

> **Rule.** Before you report "the red is not mine", rerun the red check in a copy where ONLY your files are reverted and
> everything else is byte-identical to the live tree. Prove the copy was the one served (a log line or a hash), and report
> both runs.

### Compile a trial merge without touching any checkout

A clean `git merge-tree` result only says the texts merged. It does not say the merged code compiles. You can compile the
merge itself without writing to the main checkout or to your worktree:

1. Write the merged tree to the object store only: `T=$(git -C <wt> merge-tree --write-tree --name-only <main> HEAD | head -1)`.
   The exit is 0 when the merge is clean; when it is not, the paths after the first line are the conflicts.
2. Extract only the compile inputs into scratch:
   `git -C <wt> archive $T -- ':(glob)Project/Assets/**/*.cs' ':(glob)Project/Assets/**/*.asmdef' | tar -x -C <scratch>/merged`.
   A glob that matches nothing aborts the whole archive with "pathspec did not match", so list only patterns that exist.
3. Point the offline compile tool at `<scratch>/merged/Project`. The run gives all-zero exits or names the semantic
   conflict.

### Build a test merge or a red-control commit when every worktree is busy

Make the commits a test run needs with git plumbing. Nothing is checked out; no index or working file changes.
- **Test merge:** `git merge-tree --write-tree <main> <branch>` prints the merged tree id, or lists conflicts and exits
  non-zero (Git 2.38+). Then `git commit-tree <tree> -p <main> -p <branch> -F msg.txt` (message from a file, "TEST ONLY,
  not for main" first). Give it a branch name with `git branch test/<name> <sha>` so the runner can resolve it.
- **Red control (one file put back):** `GIT_INDEX_FILE=<scratch>/tmp.index git read-tree <merge>`, then
  `GIT_INDEX_FILE=... git update-index --cacheinfo 100644,$(git rev-parse <old>:<path>),<path>`, then
  `GIT_INDEX_FILE=... git write-tree` and `git commit-tree <tree> -p <merge> -F msg.txt`. `git diff --stat <merge> <red>`
  must show only that file.
- Run both as ordinary commits: the guard must go green on the merge and red on the control.

---

## 9. Traps found the hard way

- **One failed config command turned a sparse worktree into a full 12 GB checkout.** The plan was `git worktree add
  --no-checkout`, then `core.sparseCheckout`, then `read-tree -mu`. A `git config --worktree` step failed (the
  `extensions.worktreeConfig` setting was not enabled; a bare `true` printed for another key had been misread as that
  setting), `set -e` did not stop the chain in that shell tool, and `read-tree -mu HEAD` wrote the whole tree: 31,222
  files, 12.24 GB, in about a minute.
  - Print config as key=value, never a bare value: `git config --show-origin --get core.autocrlf`, and
    `git config --get extensions.worktreeConfig || echo worktreeConfig=unset`.
  - Before a heavy step, give each earlier step its own `|| exit 1`, or run one command per call. Do not rely on `set -e`.
  - You rarely need a checkout. Build commits with plumbing (a temp `GIT_INDEX_FILE`, `read-tree`, `hash-object -w`,
    `update-index --cacheinfo`, `write-tree`, `commit-tree`, then `git branch`) and export files for an offline compile
    with `git archive` or `git show <sha>:<path>`. Plumbing skips hooks, so run any backup hook by hand.
  - If it happens anyway: delete nothing, record it in the task report, and say what disk it used. Removing the worktree
    needs the owner's OK.
- **Staged copies of live files other agents keep editing.** Build staged copies with a script that applies anchored
  hunks to the live file and records its sha256; have the approval/diff emitters assert the live sha still equals the
  build's base. In one job the live file changed three times in ten minutes and the assert caught each one before a stale
  approval file was written. Run build, diffs, approval and tests as ONE chained command so the window between them is
  seconds, and re-hash again at apply time. A killed run can leave a builder script half-edited: before redoing work, mine
  the dead agent's transcript for the edits it made instead of trusting the last report.
- **Importing another agent's script can run it.** Importing a library script to reuse one function ran its unguarded
  top-level `main()` and rebuilt an index file another agent owned. Before importing any shared script, grep its tail for a
  bare `main()` or other top-level calls; if there is no `if __name__ == "__main__":` guard, do not import it. Read the
  source, strip the top-level call lines, exec only the definitions into a fresh module, and hash the owner's output file
  before and after your check to prove it stayed untouched.

---

## Related

- `edit-a-shared-contract` (in this repo): the other half of sharing files, when what you edit is pinned by digest.
- `guards-that-can-fail` (in this repo): making the check you run on a shared tree able to fail.
