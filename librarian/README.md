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

Catalogue descriptions support scalar and folded/literal block metadata without PyYAML. The standard-library
fallback uses the same parser as the index builder and includes `when_to_use` text. Updating from v0.1.2 refreshes
the catalogue format on the next `catalogue-check`, so previously shortened descriptions are rebuilt.

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
| `SKILL_RECORDS` | `build_index.py` | `<SKILL_LIBRARY>/_records` (`TRUST.json` for owner-approved package manifests; optional historical `INSTALLS.jsonl`, `REVIEWS.jsonl`, `VERDICTS.jsonl`, `external-catalogue.jsonl`, `sweep2.jsonl`, `gate-folders.json`) |
| `LIBRARIAN_NO_FINDER` | `ask_librarian.py` | unset; `1` turns the optional skills.sh finder hook off |

`CLAUDE_CODE_HOST_SESSION_ID` and `CLAUDE_SESSION_TITLE`, when set by the Claude desktop app, let a late answer find its
way back to the asking chat and label the request.

## Quick start

Run these from the repository root in PowerShell. Choose a new library folder; do not point the writer at a shared
INDEX you do not own. `--check` is read-only and reports missing input directories without creating them.

```powershell
$env:SKILL_LIBRARY = Join-Path $HOME 'skill-library'
$env:SKILLS_DIR = Join-Path $HOME '.claude/skills'
python -I -B librarian/build_index.py --check
# For a new setup, create only the directories you intend to use:
New-Item -ItemType Directory -Force -Path $env:SKILL_LIBRARY, $env:SKILLS_DIR | Out-Null
python -I -B librarian/build_index.py

# Review packages and add owner trust records as described below, then rebuild the index.
# Only after it reports at least one vetted skill:
python -I -B librarian/build_index.py
python -I -B librarian/build_full_catalogue.py

# 3. start a chat, give it LIBRARIAN-BRIEF.md, and let it run section 1 (startup)

# 4. any other agent asks
python -I -B librarian/ask_librarian.py --from "my chat" "I am adding a regression test for the pathfinding cost and need to be sure it can fail"
```

## Installed is not reviewed

Existing files start as `installed-unverified`. The catalogue excludes them, and a zero-vetted library deliberately
cannot build a usable catalogue. Neither an `origin: in-house` declaration inside a skill nor historical install and
review logs establishes current trust.

After reviewing a package's instructions, scripts, dependencies, provenance and applicable permissions, the owner
can record that decision in `<SKILL_RECORDS>/TRUST.json`. Keep this file under the owner's control, outside skill
packages. It is an object keyed by the skill's folder name:

```json
{
  "example-skill": {
    "kind": "reviewed",
    "provenance": "Owner review record and date",
    "files": {
      "SKILL.md": "REPLACE_WITH_64_LOWERCASE_SHA256_HEX_CHARACTERS",
      "scripts/helper.py": "REPLACE_WITH_64_LOWERCASE_SHA256_HEX_CHARACTERS"
    }
  }
}
```

This is a format example, not an approval record. Use `kind: reviewed` or `kind: in-house` only for an actual owner
decision. `files` must list **every regular file** in the package, using relative paths with forward slashes. Obtain
each hash from the exact reviewed bytes, for example `(Get-FileHash -LiteralPath 'path/to/SKILL.md' -Algorithm
SHA256).Hash.ToLowerInvariant()`. No files are excluded: bytecode or other generated files also change the manifest.
Empty directories do not affect it. Links, junctions, other reparse points and nonregular files are refused.

Rebuild with `build_index.py --check` and then `build_index.py`; a matching complete manifest produces `vetted`.
Any file addition, deletion or edit invalidates it until reviewed again. Do not regenerate approval records merely
to silence a mismatch. External dependencies and referenced files outside the package still require their own review;
this manifest is an identity check, not a sandbox or proof that execution is safe.

Trust in the catalogue is a build-time snapshot. `build_index.py` checks every manifest when it writes `INDEX.md`;
`librarian_inbox.py catalogue-check` and a catalogue refresh (`build_full_catalogue.py`) trust the labels already in
that INDEX and watch only `SKILL.md` size and time. After a package edit (a helper script included) or a revoked or
changed `TRUST.json` entry, the owner must rebuild the INDEX with `build_index.py` before the change reaches the
librarian; a catalogue refresh alone does not re-validate anything.

The installer runs `build_index.py --after-install <name>` right after installing. It rebuilds the INDEX and exits 0
when that name has exactly one row whose path is its installed `SKILL.md`, whatever the status; the JSON it prints
says which (`"status": "installed-unverified"` means installed, owner review pending). It exits 4 for no row, two or
more rows, or a row at another path. `--simulate-install <name>=<dir>` makes the same check on the row an install
would get: it hashes the candidate folder `<dir>` against `TRUST.json`, shows the projected destination path, and
creates nothing.

## Safety notes

- **`build_index.py` without `--check` replaces `INDEX.md` and `REJECTED.md`** in `SKILL_LIBRARY`. Try it on a scratch
  library first. `--simulate-install <name>=<dir>` shows the row an install would get without writing anything.
- Request text is data: the librarian brief tells the chat never to follow instructions inside a request, and
  `librarian_inbox.py list` prefixes every brief line with `| ` so a brief cannot forge a request header. A request
  file whose name is not a request id (the shape `ask_librarian.py` files) is skipped with a WARNING on stderr and
  left in place, so a file name cannot forge one either.
- The optional skills.sh finder (`finder/hook.py` next to `ask_librarian.py`) is not part of this repository.
  `ask_librarian.py` skips it without error when the folder is missing.
- `install_skill.py`, the vetting installer the INDEX footer names, is not part of this repository.
- `build_index.py` and `build_full_catalogue.py` print their description with `-h` / `--help` and change nothing; an
  unknown flag exits 2. If `SKILLS_DIR` holds SKILL.md files but `build_index.py` finds 0 rows, it exits 1 with an ERROR
  unless you pass `--allow-empty`.
- The upstream automated test file for the mailbox (`test_librarian.py`, about 200 KB) is not shipped. A smaller one
  is: `librarian/test_librarian_inbox.py` runs the round trip in a temporary mailbox (a heartbeat, a request filed by
  `ask_librarian.py`, `list` claiming it, an answer file, the asker receiving it), plus a request file with a bad id
  and heartbeats with damaged epochs (non-numeric, too large for a float, infinite, NaN): both status commands must
  report them as unreadable without crashing, and an ask must fall back without filing a request.

Run `python -I -B librarian/test_build_index.py` from the repository root for isolated trust, package-change and
missing-directory checks, and `python -I -B librarian/test_librarian_inbox.py` for the mailbox. These fixtures do not
read or modify your real library or mailbox.
