# Contributing

Open an issue with the tool name, operating system, Python version, exact command, expected result and actual
result. Use a temporary reproduction folder and remove credentials, private transcripts and real inbox contents
from anything you share. Report a possible security issue privately: open the Security tab and choose "Report a
vulnerability" (see [SECURITY.md](SECURITY.md)). Never put exploit details or secrets in a public issue.

Keep pull requests focused. Explain the failure, the resulting behavior, compatibility changes and validation.
Add a regression that fails against the old behavior and a control that still succeeds. Concurrency changes need
a controlled competing-process test; a sequence of successful single-process calls is insufficient.

From the repository root on Windows, with Python 3.11+ and Git on PATH:

```powershell
python -I -B tools/run_checks.py
```

This uses temporary fixtures, standard-library Python and no GPU jobs or live chats. It parses the repository's
Python files, runs the shipped CPU suites and records full logs and a JSON summary in a new temporary folder.
`--only <suite>` selects a focused check; `--help` lists the names. A nonzero result fails the run, even if a later
suite passes. CI uses the same runner from a checkout path containing spaces.

The separate `gpu-lease/scripts/selftest.py` reads real NVIDIA free memory and requires at least 19 GB free. Do not
put it in ordinary hosted CI. Blender/SAM inference, real GPU admission, and a live chat exchange are separate
acceptance checks; describe them accurately rather than treating a CPU fixture as an end-to-end run.

Do not commit model weights, downloaded third-party source, generated media, runtime inboxes or credentials.
Preserve the licences and provenance of dependencies. Changing a skill's contents requires a fresh review record
before the librarian should treat it as vetted. GitHub settings, releases and visibility changes belong to the
repository owner; a patch does not perform them.
