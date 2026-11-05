# Recipe hook

A Claude Code hook that hands every new chat and every new helper (subagent) the same short "recipe" at the moment it
starts. A helper begins with an empty context and does not reliably remember a rule that lives only in a long
instruction file. The hook puts the few lines that matter (how to recall shared memory, how to save a lesson, which
checks to run) straight into its context.

The recipe lives in one place: the text between two marker lines in a file you choose, for example a `SKILL.md`:

```
<!-- INJECT-START -->
1. At the start, recall what the project already knows about this task.
2. After verified work, save each lasting fact once, with its evidence.
3. Ask the skill librarian which skills fit before you start.
<!-- INJECT-END -->
```

Edit the block and every new chat and helper gets the change; nothing else needs updating.

## Install

1. Put the recipe block in a file and point the hook at it with `INJECT_RECIPE_PATH` (default `~/.claude/recipe.md`).
2. Add the two hook entries from `settings.example.json` to your Claude `settings.json` (the user file
   `~/.claude/settings.json` applies everywhere; a project's `.claude/settings.json` applies to that project). Replace
   `<PROJECT_ROOT>` with the folder that holds this repository. Use **forward slashes** in Windows paths inside
   JSON, for example `C:/Projects/AI Pipeline`; backslashes would need JSON escaping (`\\`). Keep the example's
   escaped double quotes around the script path. If Python is not on PATH, quote its full path too:
   `"command": "\"C:/Python 3.11/python.exe\" -I -B \"C:/Projects/AI Pipeline/hooks/inject_recipe.py\" session-start"`.
   Validate the edited file with `python -m json.tool <settings-file>` before starting a chat.
3. Start a new chat. The recipe appears in its context.

The hook never edits a settings file by itself.

## What it does

- Reads the hook's JSON from stdin (`cwd`, `agent_type`, `source`) and prints one JSON object whose `additionalContext`
  is the recipe. ASCII only, at most 6000 characters.
- **Scope.** `INJECT_RECIPE_ROOTS` limits the recipe to chats whose working folder is under the listed folders;
  `INJECT_RECIPE_EXCLUDE` skips folders under them (for example a personal side project). Unset roots mean every folder.
- **Lookup-only helpers** (`explore`, `plan`, `claude-code-guide`, `statusline-setup`) get nothing, because they do no
  project work and the recipe would only cost them tokens. Change the list with `INJECT_RECIPE_SKIP_AGENTS`.
- **Optional reminder.** `INJECT_RECIPE_NUDGE_FILE` names a text file whose content is added for a fresh chat only
  (`source` is `startup` or `clear`), never for a helper, a resumed chat or a compacted one. For example, a pipeline can use it for
  "ask the skill librarian which skills fit before your first task".
- **Fails soft.** Always exits 0. If the recipe file or its markers are missing, it prints a one-line fallback. It never
  touches the network and writes only its log (`INJECT_RECIPE_LOG`, trimmed past 200 KB).

## Environment variables

| Variable | Default |
|---|---|
| `INJECT_RECIPE_PATH` | `~/.claude/recipe.md` |
| `INJECT_RECIPE_START`, `INJECT_RECIPE_END` | `<!-- INJECT-START -->`, `<!-- INJECT-END -->` |
| `INJECT_RECIPE_MAX_CHARS` | `6000` |
| `INJECT_RECIPE_ROOTS` | unset (every folder); separate several with `;` |
| `INJECT_RECIPE_EXCLUDE` | unset |
| `INJECT_RECIPE_SKIP_AGENTS` | `explore,plan,claude-code-guide,statusline-setup` |
| `INJECT_RECIPE_NUDGE_FILE` | unset |
| `INJECT_RECIPE_LOG` | `~/.claude/inject-recipe.log` |

Environment variables can be set in the `env` block of `settings.json`, or in the command itself.

## Test

`python -I -B test_inject_recipe.py` runs checks in a temporary folder with its own recipe file and log, including the
example commands from a repository path containing spaces; it reads and
writes no real settings. Every expected value is a literal in the test, and the guard cases (scope, lookup helpers) go
red if the matching code is removed.
