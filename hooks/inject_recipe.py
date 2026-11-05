"""Claude Code hook: put a short "recipe" into every new chat and every new helper (subagent).

Why: a rule that lives only in a long instruction file gets forgotten by helpers, which start with an empty context. A
hook can hand each new chat and each new helper the same few lines at the moment it starts. The recipe lives in ONE
place: the text between two markers in a file you choose (for example a SKILL.md), so you edit it there and every new
chat gets the change.

settings.json runs this at SessionStart and SubagentStart (see settings.example.json):
    python -I -B inject_recipe.py session-start | subagent-start
It reads the hook's JSON on stdin (fields used: cwd, agent_type, source) and prints ONE JSON object that carries the
recipe as additionalContext. It always exits 0, never touches the network, and fails soft (a one-line fallback). Output
is ASCII only.

Environment variables (all optional):
  INJECT_RECIPE_PATH         file holding the recipe between the markers below (default: ~/.claude/recipe.md)
  INJECT_RECIPE_START/END    the two marker lines (default: <!-- INJECT-START --> and <!-- INJECT-END -->)
  INJECT_RECIPE_MAX_CHARS    longest recipe sent (default 6000)
  INJECT_RECIPE_ROOTS        folders (separated by ; or the OS path separator) the recipe applies under. A chat whose
                             cwd is elsewhere gets nothing. Empty or unset: every folder.
  INJECT_RECIPE_EXCLUDE      folders under the roots that are skipped (same separators). Default: none.
  INJECT_RECIPE_SKIP_AGENTS  comma-separated helper types that get no recipe (lookup-only helpers do no project work, so
                             the recipe would only cost them tokens). Default: explore,plan,claude-code-guide,statusline-setup
  INJECT_RECIPE_NUDGE_FILE   optional text file; its content is appended at SessionStart for a fresh chat (source
                             "startup" or "clear"), never for a helper, a resume or a compaction. Use it for a
                             one-line reminder such as "ask the skill librarian before your first task".
  INJECT_RECIPE_LOG          log file (default: ~/.claude/inject-recipe.log); trimmed to its last 200 lines past 200 KB

Test it without Claude: echo {"cwd": "/some/folder", "source": "startup"} | python -I -B inject_recipe.py session-start
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
SKILL = os.environ.get("INJECT_RECIPE_PATH") or os.path.join(HOME, ".claude", "recipe.md")
LOG = os.environ.get("INJECT_RECIPE_LOG") or os.path.join(HOME, ".claude", "inject-recipe.log")
START = os.environ.get("INJECT_RECIPE_START") or "<!-- INJECT-START -->"
END = os.environ.get("INJECT_RECIPE_END") or "<!-- INJECT-END -->"
try:
    MAX_CHARS = int(os.environ.get("INJECT_RECIPE_MAX_CHARS") or 6000)
except ValueError:
    MAX_CHARS = 6000
EVENTS = {"session-start": "SessionStart", "subagent-start": "SubagentStart"}
SKIP_AGENTS = {a.strip().lower() for a in (os.environ.get("INJECT_RECIPE_SKIP_AGENTS")
                                          or "explore,plan,claude-code-guide,statusline-setup").split(",") if a.strip()}
FALLBACK = ("RECIPE: the recipe file could not be read. Follow the shared rules in the project's instruction file at the "
            "start of your task.")


def norm(path):
    """Lower case, forward slashes, no trailing slash; a Git Bash /c/... path becomes c:/..."""
    p = str(path or "").replace("\\", "/").strip().lower()
    if len(p) > 2 and p[0] == "/" and p[2] == "/":
        p = p[1] + ":" + p[2:]
    return p.rstrip("/")


def folders(value):
    out = []
    for part in str(value or "").replace(";", os.pathsep).split(os.pathsep):
        if part.strip():
            out.append(norm(os.path.expanduser(part.strip())))
    return tuple(out)


ROOTS = folders(os.environ.get("INJECT_RECIPE_ROOTS"))
EXCLUDE = folders(os.environ.get("INJECT_RECIPE_EXCLUDE"))


def under(p, bases):
    return any(p == b or p.startswith(b + "/") for b in bases)


def in_scope(cwd):
    """True when the recipe applies in this folder: under a root (or no roots set) and not under an excluded folder."""
    return (not ROOTS or under(cwd, ROOTS)) and not under(cwd, EXCLUDE)


def ascii_only(s):
    return str(s).encode("ascii", "replace").decode("ascii")


def log(line):
    try:
        os.makedirs(os.path.dirname(LOG) or ".", exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > 200000:
            with open(LOG, "r", encoding="ascii", errors="replace") as f:
                tail = f.readlines()[-200:]
            with open(LOG, "w", encoding="ascii", errors="replace") as f:
                f.writelines(tail)
        with open(LOG, "a", encoding="ascii", errors="replace") as f:
            f.write(line + "\n")
    except Exception:
        pass


def recipe():
    """(text, how): the block between the markers, or the one-line fallback when it cannot be read."""
    try:
        with open(SKILL, "r", encoding="utf-8") as f:
            text = f.read()
        a = text.index(START) + len(START)
        b = text.index(END, a)
        block = ascii_only(text[a:b].strip())
        if not block:
            raise ValueError("empty block")
        return block[:MAX_CHARS], "recipe"
    except Exception as e:
        return FALLBACK, "fallback(%s)" % type(e).__name__


def nudge():
    """The optional fresh-chat reminder from INJECT_RECIPE_NUDGE_FILE, or ''."""
    path = os.environ.get("INJECT_RECIPE_NUDGE_FILE")
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return ascii_only(f.read().strip())[:MAX_CHARS]
    except Exception:
        return ""


def main():
    t0 = time.time()
    name = EVENTS.get(sys.argv[1] if len(sys.argv) > 1 else "")
    if not name:
        return
    data = {}
    try:
        if not sys.stdin.isatty():
            data = json.loads(sys.stdin.read() or "{}")
            if not isinstance(data, dict):
                data = {}
    except Exception:
        data = {}
    cwd = norm(data.get("cwd") or os.getcwd())
    agent = str(data.get("agent_type") or "")
    source = str(data.get("source") or "")
    text = ""
    if not in_scope(cwd):
        why = "skip:out-of-scope"
    elif name == "SubagentStart" and agent.lower() in SKIP_AGENTS:
        why = "skip:lookup-agent"
    else:
        text, why = recipe()
    # The optional reminder goes to a fresh chat only: never a helper, a resumed chat or a compacted one.
    if name == "SessionStart" and source in ("startup", "clear") and in_scope(cwd):
        extra = nudge()
        if extra:
            text = (text + "\n\n" if text else "") + extra
            why += "+nudge"
    chars = 0
    if text:
        chars = len(text)
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}) + "\n")
        sys.stdout.flush()
    log("%s %s agent=%s source=%s cwd=%s -> %s chars=%d ms=%d" % (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), name, ascii_only(agent) or "-",
        ascii_only(source) or "-", ascii_only(cwd)[:120], why, chars, int((time.time() - t0) * 1000)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never block a session or a helper
        log("%s ERROR %s" % (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), type(exc).__name__))
    sys.exit(0)
