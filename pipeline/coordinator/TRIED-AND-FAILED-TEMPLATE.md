# TRIED-AND-FAILED

Copy this file to the pipeline root as `TRIED-AND-FAILED.md`. Only the coordinator writes it (RULES.md 'Attempts and
TRIED-AND-FAILED'). A failed idea moves here from its job's attempt log once it has failed the same way in 2 jobs, or
its cause is clearly general. Every new card pastes the rows whose `systems` match its `Systems:` line, or
`none matching`. A retry of a listed idea must say why its case differs.

One row per failed idea. Keep the cause to one line; link the evidence instead of copying it.

| id | systems | idea | how it failed (the number or test that moved) | cause, one line | evidence | jobs |
|---|---|---|---|---|---|---|
| TF-1 | `<comma list matching card Systems: lines>` | `<the one change that was tried>` | `<test name, or metric before -> after vs tolerance>` | `<why it failed>` | `<path to the job's attempt log or REVIEW file>` | `<lane>-<n>, <lane>-<m>` |

Example (fictional):

| id | systems | idea | how it failed | cause, one line | evidence | jobs |
|---|---|---|---|---|---|---|
| TF-1 | csv-import, parser | stream rows instead of loading the whole file | `test_quoted_newlines` red; 2 of 40 fixtures split mid-field | the stream reader splits on raw newlines inside quoted fields | `jobs/import-3/ATTEMPTS.md` | import-3, import-5 |
