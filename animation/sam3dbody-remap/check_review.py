"""check_review.py: refuse a REVIEW checklist copy that does not prove each look was made.

Why: agents asked to review a clip wrote their own short copies of the checklist and ticked "look" items from numbers,
without naming a picture. Run this on every REVIEW copy before a clip goes to the person who decides; a FAIL means the
clip does not go.

  python -I -B check_review.py <REVIEW copy.md> [--checklist <master>] [--transcript auto|<file.jsonl>[,...]]
                               [--blend <the .blend reviewed>] [--final yes|no] [--min-words 5]
                               [--sheets <dir>[,<dir>]] [--min-pictures 4]

Environment (optional): REVIEW_CHECKLIST = the master checklist (default: REVIEW-CHECKLIST.example.md beside this
script; --checklist wins). CLAUDE_PROJECTS_DIR = where Claude Code keeps session transcripts (default
<USER_HOME>/.claude/projects). The LOOK set below is the list of item numbers of the example checklist that are judged
by eye: if you change the checklist's numbering, change LOOK to match.

What it checks (each problem prints one CHECK_REVIEW line):
  1. The master's numbered item text and section, and section 10 question text and multiplicity, are retained;
     duplicate IDs fail. No box is blank `[ ]` (section 11 may stay blank until `--final yes`).
  2. A box is `[x]`, `[!]` or `[-]`. `[-]` needs a separate indented `reason:` line (3+ words). `[!]` needs video frames (f12, f30-48).
  3. LOOK items (judged by eye: LOOK below) that are `[x]` or `[!]` carry at least one proof line:
         see: <picture path> f<frames>: <what the picture shows at those frames>
     Quote paths with spaces in backticks, single or double quotes. The picture is a .png/.jpg/.jpeg/.webp/.gif that exists (absolute, or relative to the copy's folder), newer than
     `--blend` when given; the description has `--min-words` words or more and is not pasted on 3+ items.
  4. Proof of the look: each named picture was opened with the Read tool in the agent's own transcript (or one of its
     subagents'). `--transcript auto` finds the session(s) whose tool calls name the copy's path, under
     CLAUDE_PROJECTS_DIR/*/; pass the file(s) yourself if auto finds none. A Codex agent passes its own session file
     (<USER_HOME>/.codex/sessions/<y>/<m>/<d>/rollout-*.jsonl): a literal path in a supported view_image call counts. Unknown exec syntax receives no credit.
     This records the call, not whether it succeeded or the image was actually observed.
  5. At least `--min-pictures` (4) different pictures across the look items, and with `--sheets <dir>[,<dir>]`
     EVERY picture in those folders opened (frame by frame, every angle: pass each sheet folder).
Ends `CHECK_REVIEW VERDICT PASS|FAIL`; exit 1 on FAIL, 2 on a usage error. Reads only; writes nothing.
"""
import glob, json, os, re, sys
from collections import Counter

LOOK = set("""2.2 3.0 3.1 3.2 3.3 3.4 3.5 3.6 3.7 4.1 4.2 4.3 4.4 4.5 4.6 5.1 5.1b 5.2 5.3 6.1 6.2 6.3 6.4 6.5
7.1 7.2 7.3 7.4 7.5 8.1 8.2 8.3 8.4 8.5 8.6 9.6 9.9""".split())
HERE = os.path.dirname(os.path.abspath(__file__))
MASTER = os.environ.get("REVIEW_CHECKLIST", os.path.join(HERE, "REVIEW-CHECKLIST.example.md"))
PROJECTS = os.environ.get("CLAUDE_PROJECTS_DIR", os.path.join(os.path.expanduser("~"), ".claude", "projects"))
PIC = (".png", ".jpg", ".jpeg", ".webp", ".gif")
BOX = re.compile(r"^ {0,3}-\s*\[(.)\]\s*(?:\*\*)?\s*(\d+\.\d+[a-z]?)?")
SEE = re.compile(r"see:\s*(?:`([^`\n]+)`|\"([^\"\n]+)\"|'([^'\n]+)'|([^\s`\"']+))\s+(f\d+(?:\s*-\s*\d+)?(?:\s*,\s*f?\d+(?:\s*-\s*\d+)?)*)\s*:\s*(.+)", re.I)
REASON = re.compile(r"^[ \t]*reason:[ \t]*([^\r\n]+)$", re.I | re.M)
FRAMES = re.compile(r"\bf\d+", re.I)


def usage(msg):
    print("CHECK_REVIEW USAGE", msg)
    sys.exit(2)


def parse_args(argv):
    if not argv or argv[0].startswith("--"):
        usage("first argument is the REVIEW copy")
    opt = {"--checklist": MASTER, "--transcript": "auto", "--blend": "", "--final": "no", "--min-words": "5",
           "--sheets": "", "--min-pictures": "4"}
    rest = argv[1:]
    if len(rest) % 2:
        usage("options come in pairs: " + " ".join(rest))
    for k, v in zip(rest[::2], rest[1::2]):
        if k not in opt:
            usage(f"unknown option {k} (known: {' '.join(opt)})")
        opt[k] = v
    if opt["--final"] not in ("yes", "no"):
        usage("--final yes|no")
    for key in ("--min-words", "--min-pictures"):
        try:
            value = int(opt[key])
        except ValueError:
            usage(f"{key} must be a positive integer")
        if value < 1:
            usage(f"{key} must be a positive integer")
    return argv[0], opt


def norm(p):
    return os.path.normcase(os.path.abspath(p.replace("\\", "/"))).replace("\\", "/")


def active_lines(text):
    """Yield uncommented, unfenced lines; None separates excluded content from surrounding evidence."""
    in_comment, fence = False, None
    for raw in text.splitlines():
        if fence:
            if re.match(r'^[ \t]*' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*$', raw):
                fence = None
            yield None
            continue
        if not in_comment:
            opening = re.match(r'^[ \t]*(`{3,}|~{3,})', raw)
            if opening:
                fence = (opening.group(1)[0], len(opening.group(1)))
                yield None
                continue
        line, rest = '', raw
        while rest:
            if in_comment:
                end = rest.find('-->')
                if end < 0:
                    rest = ''
                else:
                    rest = rest[end + 3:]
                    in_comment = False
            else:
                start = rest.find('<!--')
                if start < 0:
                    line += rest
                    rest = ''
                else:
                    line += rest[:start]
                    rest = rest[start + 4:]
                    in_comment = True
        if line != raw:
            yield None
        yield line


def has_html(text):
    """Refuse HTML-like tags outside fenced blocks, comments and single-line inline code spans."""
    # Comment delimiters inside code spans are ambiguous to this subset parser. Refuse them
    # rather than letting one hide subsequent active HTML from the scanner.
    if any('`' in line and ('<!--' in line or '-->' in line) for line in text.splitlines()):
        return True
    for line in active_lines(text):
        if line is None:
            continue
        line = re.sub(r'(`+)(?!`)(.*?)(?<!`)\1(?!`)', '', line)
        if re.search(r'<\s*(?:[!?]|/?\s*[A-Za-z][A-Za-z0-9-]*(?=[\s/>]|$))', line):
            return True
    return False


def items(text):
    """Parse the documented checklist subset, excluding HTML comments and fenced or indented code boxes."""
    out, cur, sec, box_indent = [], None, None, 0
    for line in active_lines(text):
        if line is None:
            cur = None
            continue
        h = re.match(r"^##\s+(\d+)\.", line)
        if h:
            sec = int(h.group(1))
            cur = None
            continue
        m = BOX.match(line)
        if m:
            cur = [m.group(2), m.group(1), line, sec]
            box_indent = len(line) - len(line.lstrip(' '))
            out.append(cur)
        elif cur is not None and re.match(r'^ {' + str(box_indent + 2) + ',' + str(box_indent + 3) + r'}\S', line):
            cur[2] += "\n" + line
        elif cur is not None and not line.strip():
            continue
        elif cur is not None:
            cur = None
    return out


def prompt(it):
    """First box line without its mark; allow surrounding whitespace, not rewritten prompts."""
    return re.sub(r"^\s*-\s*\[.\]\s*", "", it[2].splitlines()[0]).strip()


def find_transcripts(copy):
    target = norm(copy).lower()
    alt = target.replace("/", "\\\\")
    base = os.path.basename(copy).lower()
    since = os.path.getmtime(copy) - 3600
    found = []
    for f in glob.glob(PROJECTS + "/*/*.jsonl"):
        if os.path.getmtime(f) < since:
            continue
        hit = False
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                low = line.lower()
                if base in low and ('"tool_use"' in low) and (target in low.replace("\\\\", "/") or alt in low):
                    hit = True
                    break
        if hit:
            found.append(f)
            found += glob.glob(os.path.join(f[:-6], "subagents", "*.jsonl"))
    return found


# Deliberately recognize only a complete, simple functions.exec program. Do not scan
# arbitrary JavaScript: a path in a print, comment, string or unexecuted branch is not a look.
JS_VIEW = re.compile(r'^\s*(?:const|let)\s+(\w+)\s*=\s*await\s+tools\.view_image\(\s*\{\s*path\s*:\s*("(?:[^"\\]|\\.)*")\s*}\s*\)\s*;\s*image\(\s*\1\.image_url\s*\)\s*;?\s*$', re.S)


def codex_views(rec):
    """Extract only literal path arguments from recognized tool-call forms; unknown code earns no credit."""
    if not isinstance(rec, dict):
        return []
    p = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    if p.get("type") not in ("function_call", "custom_tool_call"):
        return []
    name = p.get("name", "")
    raw = p.get("arguments") or p.get("input") or ""
    if not isinstance(raw, str):
        return []
    path = None
    if name in ("view_image", "functions.view_image"):
        try:
            args = json.loads(raw)
            if isinstance(args, dict) and set(args) == {"path"}:
                path = args["path"]
        except ValueError:
            pass
    elif name in ("exec", "functions.exec"):
        match = JS_VIEW.fullmatch(raw)
        if match:
            try:
                path = json.loads(match.group(2))
            except ValueError:
                pass
    if isinstance(path, str) and path.lower().endswith(PIC):
        return [norm(path)]
    return []


def reads(files):
    """Every file_path the Read tool was given in these transcripts (normalized), plus every picture a Codex session
    file (~/.codex/sessions/.../rollout-*.jsonl, passed with --transcript) opened with view_image."""
    got = set()
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "view_image" in line:
                    try:
                        got.update(codex_views(json.loads(line)))  # CODEX_VIEW
                    except ValueError:
                        pass
                if '"Read"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                content = (rec.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Read":
                        p = (c.get("input") or {}).get("file_path")
                        if p:
                            got.add(norm(p))
    return got


def main():
    copy, opt = parse_args(sys.argv[1:])
    if not os.path.isfile(copy):
        usage(f"no such copy: {copy}")
    if not os.path.isfile(opt["--checklist"]):
        usage(f"no such checklist: {opt['--checklist']}")
    master_text = open(opt["--checklist"], encoding="utf-8", errors="replace").read()
    text = open(copy, encoding="utf-8", errors="replace").read()
    if has_html(master_text):
        usage("master checklist contains unsupported raw HTML")
    master = items(master_text)
    want_ids = [i for i, _, _, _ in master if i]
    if len(set(want_ids)) != len(want_ids):
        usage("master checklist has duplicate item IDs")
    master_by_id = {it[0]: it for it in master if it[0]}
    master_questions = [prompt(it) for it in master if it[0] is None and it[3] == 10]
    q_master = len(master_questions)
    got = items(text)
    by_id = {}
    for it in got:
        if it[0]:
            by_id.setdefault(it[0], it)
    problems = []
    P = lambda code, msg: problems.append(f"CHECK_REVIEW {code} {msg}")
    if has_html(text):
        P("HTML", "raw HTML is unsupported in the checklist copy")
    for item_id, count in Counter(it[0] for it in got if it[0]).items():
        if count > 1:
            P("DUPLICATE", f"{item_id}: appears {count} times in the copy")
    min_words = int(opt["--min-words"])
    if opt["--blend"] and not os.path.isfile(opt["--blend"]):
        usage(f"no such blend: {opt['--blend']}")
    blend_t = os.path.getmtime(opt["--blend"]) if opt["--blend"] else None
    here = os.path.dirname(os.path.abspath(copy))

    for i in want_ids:
        if i not in by_id:
            P("MISSING", f"{i}: not in the copy (fill every item of the checklist; `[-]` with a reason if it does not apply)")
        else:
            expected, actual = master_by_id[i], by_id[i]
            if actual[3] != expected[3]:
                P("SECTION", f"{i}: belongs in section {expected[3]}, not {actual[3]}")
            if prompt(actual) != prompt(expected):
                P("PROMPT", f"{i}: retain the master item text on the box line")
    q_got = [it for it in got if it[0] is None and it[3] == 10]
    if Counter(prompt(it) for it in q_got) != Counter(master_questions):
        P("QUESTION", "section 10 questions must match the master, including duplicates and wording")
    pics, descs = [], {}
    checked = list(by_id.items()) + [(f"section 10 question {n}", it) for n, it in enumerate(q_got, 1)]
    for i, it in checked:
        _, mark, block, sec = it
        if mark == " ":
            if sec == 11 and opt["--final"] == "no":
                continue
            P("BLANK", f"{i}: left blank")
            continue
        if mark not in "x!-":
            P("MARK", f"{i}: [{mark}] is not x, ! or -")
            continue
        body = re.sub(r"^\s*-\s*\[.\]\s*", "", block, count=1)
        if mark == "-":
            reason = REASON.search(block)
            if not reason or len(re.findall(r"[A-Za-z]{2,}", reason.group(1))) < 3:
                P("REASON", f"{i}: `[-]` needs a reason (why it does not apply)")
            continue
        if mark == "!" and not FRAMES.search(body):
            P("FRAMES", f"{i}: `[!]` needs the video frames of the fault")
        if i not in LOOK:
            continue
        sees = SEE.findall(block)
        if not sees:
            P("NO_LOOK", f"{i}: a look item needs `see: <picture> f<frames>: <what it shows>` (a number is not a look)")
            continue
        for quoted, double_quoted, single_quoted, bare, frames, what in sees:
            path = quoted or double_quoted or single_quoted or bare
            if not path.lower().endswith(PIC):
                P("NO_PICTURE", f"{i}: {path} is not a supported picture path")
                continue
            full = path if os.path.isabs(path.replace("\\", "/")) else os.path.join(here, path)
            n = norm(full)
            if not os.path.isfile(n):
                P("NO_PICTURE", f"{i}: {path} does not exist")
                continue
            if blend_t and os.path.getmtime(n) < blend_t:
                P("OLD_PICTURE", f"{i}: {path} is older than the blend reviewed (a picture of an earlier version)")
            words = re.findall(r"[A-Za-z]{2,}", what)
            if len(words) < min_words:
                P("THIN", f"{i}: '{what.strip()[:60]}': say what the picture shows ({min_words}+ words)")
            key = " ".join(w.lower() for w in words)
            descs.setdefault(key, []).append(i)
            pics.append((i, path, n))
    for key, ids in descs.items():
        if key and len(ids) >= 3:
            P("PASTED", f"the same description on {len(ids)} items ({', '.join(ids)}): describe each look")

    distinct = len(set(p for _, _, p in pics))
    if distinct < int(opt["--min-pictures"]):
        P("FEW_PICTURES", f"{distinct} different pictures named across the look items; at least {opt['--min-pictures']} "
                          "(body, close-up, top and real-material sheets)")
    sheets = []
    for d in [d for d in opt["--sheets"].split(",") if d]:
        if not os.path.isdir(d):
            usage(f"no such sheets folder: {d}")
        sheets += [norm(f) for f in sorted(glob.glob(os.path.join(d, "*"))) if f.lower().endswith(PIC)]
    if pics or sheets:
        if opt["--transcript"] == "auto":
            files = find_transcripts(copy)
        else:
            files = [f for f in opt["--transcript"].split(",") if f]
            for f in files:
                if not os.path.isfile(f):
                    usage(f"no such transcript: {f}")
        if not files:
            P("NO_TRANSCRIPT", "no session transcript names this copy; pass --transcript <your session .jsonl>")
        else:
            opened = reads(files)
            for i, path, n in pics:
                if n not in opened:
                    P("NOT_OPENED", f"{i}: {path} was never opened with Read in this session (look at it)")
            unread = [s for s in sheets if s not in opened]
            if unread:
                P("SHEETS_UNREAD", f"{len(unread)} of {len(sheets)} sheets never opened (every frame, every angle), "
                                   f"first: {', '.join(os.path.basename(s) for s in unread[:4])}")
            print(f"CHECK_REVIEW TRANSCRIPTS {len(files)} files, {len(opened)} files opened with Read")

    looks = sum(1 for i in by_id if i in LOOK)
    print(f"CHECK_REVIEW COUNTS master items {len(want_ids)} + {q_master} questions; copy has {len(by_id)} items, "
          f"{len(q_got)} questions; look items {looks}; pictures named {len(pics)} ({len(set(p for _, _, p in pics))} distinct)")
    for line in problems:
        print(line)
    ok = not problems
    print(f"CHECK_REVIEW VERDICT {'PASS' if ok else 'FAIL'} ({len(problems)} problems) {copy}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
