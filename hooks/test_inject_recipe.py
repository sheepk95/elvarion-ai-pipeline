"""Tests for inject_recipe.py. Standard library only; everything runs in a temporary folder and sets the
INJECT_RECIPE_* variables itself, so no real Claude settings, recipe file or log is read or written.

    python -I -B test_inject_recipe.py

Every expectation is a literal written here (the recipe text, the folders), never read back from the tool's output, so
a hook that always printed the same thing, or always printed nothing, would fail some case. Exit 0 = all pass.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "inject_recipe.py")
TMP = tempfile.mkdtemp(prefix="inject-recipe-test-")
RECIPE_FILE = os.path.join(TMP, "recipe.md")
MISSING_FILE = os.path.join(TMP, "no-such-recipe.md")
NUDGE_FILE = os.path.join(TMP, "nudge.txt")
LOG = os.path.join(TMP, "hook.log")
PROJECT = os.path.join(TMP, "project").replace("\\", "/")
PERSONAL = PROJECT + "/personal"
OTHER = os.path.join(TMP, "elsewhere").replace("\\", "/")
RECIPE = "Recall first. Save one fact per call. Verify with a separate recall."
NUDGE = "Ask the librarian before your first task."
with open(RECIPE_FILE, "w", encoding="utf-8") as f:
    f.write("# a skill\nintro text that must NOT be injected\n<!-- INJECT-START -->\n%s\n<!-- INJECT-END -->\nafter text\n" % RECIPE)
with open(NUDGE_FILE, "w", encoding="utf-8") as f:
    f.write(NUDGE + "\n")
fails = []


def run(event, stdin, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("INJECT_RECIPE_")}
    e.update(INJECT_RECIPE_PATH=RECIPE_FILE, INJECT_RECIPE_LOG=LOG, INJECT_RECIPE_ROOTS=PROJECT,
             INJECT_RECIPE_EXCLUDE=PERSONAL)
    e.update(env)
    p = subprocess.run([sys.executable, "-I", "-B", HOOK, event], input=stdin, capture_output=True, text=True,
                       encoding="utf-8", env=e, timeout=60)
    return p.returncode, p.stdout, p.stderr


def context(out):
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  | " + str(detail)[:300]))
    if not ok:
        fails.append(name)


def msg(cwd, **kw):
    return json.dumps(dict({"cwd": cwd}, **kw))


rc, out, err = run("session-start", msg(PROJECT + "/game", source="startup"))
check("in-scope session start prints exactly the recipe block", rc == 0 and context(out) == RECIPE, out)
check("the event name is echoed", json.loads(out)["hookSpecificOutput"]["hookEventName"] == "SessionStart", out)
check("text outside the markers is not injected", "must NOT" not in out and "after text" not in out, out)

rc, out, err = run("session-start", msg(OTHER, source="startup"))
check("a chat outside the roots gets nothing, exit 0", rc == 0 and out == "", out)
rc, out, err = run("session-start", msg(PERSONAL + "/x", source="startup"))
check("an excluded folder under the roots gets nothing", rc == 0 and out == "", out)
rc, out, err = run("session-start", msg(OTHER, source="startup"), INJECT_RECIPE_ROOTS="")
check("no roots set: every folder is in scope", rc == 0 and context(out) == RECIPE, out)

rc, out, err = run("subagent-start", msg(PROJECT, agent_type="general-purpose"))
check("a working helper gets the recipe", rc == 0 and context(out) == RECIPE and "SubagentStart" in out, out)
rc, out, err = run("subagent-start", msg(PROJECT, agent_type="Explore"))
check("a lookup-only helper (any case) gets nothing", rc == 0 and out == "", out)
rc, out, err = run("subagent-start", msg(PROJECT, agent_type="Explore"), INJECT_RECIPE_SKIP_AGENTS="other")
check("the skip list is configurable", rc == 0 and context(out) == RECIPE, out)

rc, out, err = run("session-start", msg(PROJECT, source="startup"), INJECT_RECIPE_PATH=MISSING_FILE)
check("a missing recipe file gives the one-line fallback, exit 0", rc == 0 and "could not be read" in context(out)
      and RECIPE not in out, out)

rc, out, err = run("session-start", msg(PROJECT, source="startup"), INJECT_RECIPE_NUDGE_FILE=NUDGE_FILE)
check("a fresh chat gets recipe then nudge", rc == 0 and context(out) == RECIPE + "\n\n" + NUDGE, out)
rc, out, err = run("session-start", msg(PROJECT, source="resume"), INJECT_RECIPE_NUDGE_FILE=NUDGE_FILE)
check("a resumed chat gets the recipe but no nudge", rc == 0 and context(out) == RECIPE, out)
rc, out, err = run("subagent-start", msg(PROJECT, agent_type="general-purpose"), INJECT_RECIPE_NUDGE_FILE=NUDGE_FILE)
check("a helper never gets the nudge", rc == 0 and context(out) == RECIPE, out)

rc, out, err = run("session-start", "this is not json", )
check("garbage on stdin: exit 0, no traceback", rc == 0 and "Traceback" not in err, err)
rc, out, err = run("unknown-event", msg(PROJECT))
check("an unknown event prints nothing, exit 0", rc == 0 and out == "", out)
rc, out, err = run("session-start", msg(PROJECT, source="startup"), INJECT_RECIPE_MAX_CHARS="10")
check("the recipe is cut to the configured length", rc == 0 and context(out) == RECIPE[:10], out)

with open(LOG, encoding="ascii") as f:
    log_text = f.read()
check("every run is logged", log_text.count("\n") >= 10 and "skip:out-of-scope" in log_text and "skip:lookup-agent" in log_text,
      log_text[-300:])

print("RESULT %s (%d failed)" % ("FAIL" if fails else "PASS", len(fails)))
if fails:
    print("test folder kept: %s" % TMP)       # an uncaught error also leaves it in place
else:
    shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fails else 0)
