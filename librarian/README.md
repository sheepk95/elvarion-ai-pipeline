# Skill librarian

A pattern for keeping a growing skill library usable. Hundreds of skills cannot all be listed at the start of every
chat, so each agent would have to search for the right one itself. Instead, one long-lived chat (the **Skill Librarian**)
reads the whole catalogue once and keeps it in context. Any other agent sends it a short description of its task through
a file mailbox and gets back the few skills it should read first. Standard-library Python, Windows tested.

```
INDEX.md  --build_index.py-->  INDEX.md (one row per skill)
INDEX.md  --build_full_catalogue.py-->  catalogue/CATALOGUE-PART-*.md  (what the librarian chat reads)
asker  --ask_librarian.py-->  mailbox/requests/<id>.json
librarian chat  --librarian_inbox.py (wait / list / heartbeat / catalogue-check)-->  mailbox/answers/<id>.md
asker  <--ask_librarian.py-- the answer (PICKS / MAYBE / ALSO GREP / NOTE)
```

If the librarian is not live, `ask_librarian.py` says so at once (exit 3) and the asker greps `INDEX.md` instead, so a
missing librarian never blocks work.

## Files

| File | What it does |
|---|---|
| `LIBRARIAN-BRIEF.md` | The standing instructions for the librarian chat: startup, the wake loop, the answer format, the picking rules, safety, rollover. Paste it (or point the chat at it) when you start the librarian. |
| `librarian_inbox.py` | The librarian's side of the mailbox: `wait`, `list`, `heartbeat`, `catalogue-check`, `status`. Claims each request exactly once, tracks which catalogue parts the chat has loaded, and produces small DELTA files so a changed library is cheap to reload. |
| `ask_librarian.py` | The asker's side: `ask_librarian.py --from "<who>" "<what the task is, 2-10 lines>"`. Also `--status`, `--late ID`, `--have name,name` (skills you already hold are stripped from the answer). |
| `build_full_catalogue.py` | Turns `INDEX.md` into part files small enough for one Read call each, with a LARGE flag on SKILL.md files over 50,000 bytes and a manifest of hashes. |
| `build_index.py` | Builds `INDEX.md` and `REJECTED.md` from the SKILL.md frontmatter of a skills folder and a library folder, plus optional record files. **It rewrites the INDEX of the library it points at**, see below. |

## Environment variables

| Variable | Used by | Default |
|---|---|---|
| `LIBRARIAN_ROOT` | `librarian_inbox.py`, `ask_librarian.py`, `build_full_catalogue.py` | the folder holding the scripts; `mailbox/` and `catalogue/` live under it |
| `SKILL_LIBRARY` | all four | `~/skill-library` (holds `INDEX.md`, `REJECTED.md`, installed skills) |
| `SKILLS_DIR` | `build_index.py` | `~/.claude/skills` |
| `SKILL_CORE_FILE` | `build_index.py` | `<SKILL_LIBRARY>/CORE.txt` (skills that are always listed; none if the file is missing) |
| `SKILL_RECORDS` | `build_index.py` | `<SKILL_LIBRARY>/_records` (optional `INSTALLS.jsonl`, `REVIEWS.jsonl`, `VERDICTS.jsonl`, `external-catalogue.jsonl`, `sweep2.jsonl`, `gate-folders.json`) |
| `LIBRARIAN_NO_FINDER` | `ask_librarian.py` | unset; `1` turns the optional skills.sh finder hook off |

`CLAUDE_CODE_HOST_SESSION_ID` and `CLAUDE_SESSION_TITLE`, when set by the Claude desktop app, let a late answer find its
way back to the asking chat and label the request.

## Quick start

```
# 1. build the index of your skills (look first with --check, which writes nothing)
python -I -B build_index.py --check      # uses ~/skill-library and ~/.claude/skills unless the variables above are set
python -I -B build_index.py

# 2. build the catalogue parts the librarian will read
python -I -B build_full_catalogue.py

# 3. start a chat, give it LIBRARIAN-BRIEF.md, and let it run section 1 (startup)

# 4. any other agent asks
python -I -B ask_librarian.py --from "my chat" "I am adding a regression test for the pathfinding cost and need to be sure it can fail"
```

## Safety notes

- **`build_index.py` without `--check` replaces `INDEX.md` and `REJECTED.md`** in `SKILL_LIBRARY`. Try it on a scratch
  library first. `--simulate-install <name>=<dir>` shows the row an install would get without writing anything.
- Request text is data: the librarian brief tells the chat never to follow instructions inside a request, and
  `librarian_inbox.py list` prefixes every brief line with `| ` so a brief cannot forge a request header.
- The optional skills.sh finder (`finder/hook.py` next to `ask_librarian.py`) is not part of this repository.
  `ask_librarian.py` skips it without error when the folder is missing.
- `install_skill.py`, the vetting installer the INDEX footer names, is not part of this repository.
- `build_index.py` and `build_full_catalogue.py` print their description with `-h` / `--help` and change nothing; an
  unknown flag exits 2. If `SKILLS_DIR` holds SKILL.md files but `build_index.py` finds 0 rows, it exits 1 with an ERROR
  unless you pass `--allow-empty`.
- The upstream automated test file for the mailbox (`test_librarian.py`, about 200 KB) is not shipped. The scripts were
  exercised here with a temporary `LIBRARIAN_ROOT`: a fake heartbeat, a request filed by `ask_librarian.py`, `list`
  claiming it, a hand-written answer file, and the asker receiving it.
