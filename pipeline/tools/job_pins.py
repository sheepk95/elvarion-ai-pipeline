"""Pins for one 11-lane pipeline job: the card, the score card and the work, in one line (RULES.md 'Items').

A pins line is `pins: card <sha12> | scorecard <sha12> | work <commit12 or file sha12>`. Every JOB, REVIEW-ASK,
FINDINGS, TEST-ASK, WORKS / NOT-WORKS, gate prompt, DONE and READY carries it, and so do the top 5 lines of every
REVIEW-, TEST- and GATE- file. A JOB item carries `work none` (--card-only: a new job's worktree may not exist yet);
the builder's first REVIEW-ASK carries the full line, and --check never accepts `work none`. A receiver runs this script again before it acts; a pin that differs means the card,
the score card or the work changed since the sender looked.

Reads pins: a card may list the other lanes' documents the job reads, in a `Reads:` section, one row per
file: `- <path> | <sha12>` (sha12 = the first 12 hex of the file's sha256; a relative path is under the pipeline root).
The print modes then add one `reads: <sha12> "<path>"` line per row after the pins line, with ` | DIFFERS: file now
<sha12>` when the file has moved; --check gives exit 1 naming the file. `Reads: none`, or no such section, changes
nothing: the output is what it always was. The pins line itself never carries them; the card pin covers the rows.

Usage:
  python -I -B <PIPELINE_ROOT>/tools/job_pins.py <job> [--work <commit-ish | file path>] [--root <dir>]
  python -I -B <PIPELINE_ROOT>/tools/job_pins.py <job> --card-only [--root <dir>]
  python -I -B <PIPELINE_ROOT>/tools/job_pins.py <job> --check [--ready <READY item file>] [--root <dir>]
  python -I -B <PIPELINE_ROOT>/tools/job_pins.py --self-test
Exit: 0 printed / pins OK (a print with a DIFFERS line is still 0); 1 MISMATCH (--check); 2 a record, line or file is
missing or unreadable (a Reads: row that does not parse, or a file it names, too), git failed, or the worktree is not on
the card's branch. Stdlib only. A sibling tool that wants to reuse it can load this file by path (python -I drops the
script's folder from sys.path).
"""
import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import time

JOB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*-\d+[a-z]?$")
PINS_RE = re.compile(r"^pins: card ([0-9a-f]{12}) \| scorecard ([0-9a-f]{12}) \| work ([0-9a-f]{12})$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
READS_HEAD_RE = re.compile(r"^(?:#+\s*)?\*{0,2}reads\s*:\s*\*{0,2}\s*(.*)$|^#+\s*reads\s*$", re.I)
READS_ROW_RE = re.compile(r"^(?:[-*]\s+)?(.+?)[\s|]+(?:sha12[\s:=]+)?`?([0-9a-fA-F]{12})`?$")

EXAMPLES = r"""examples:
  the JOB item (Coordinator): card and score card only; the work pin starts with the builder's first REVIEW-ASK:
    python -I -B <PIPELINE_ROOT>/tools/job_pins.py economy-9 --card-only
  print the pins line for a document job (put it in your item or record):
    python -I -B <PIPELINE_ROOT>/tools/job_pins.py atmosphere-7
  print it for one commit of a code job (worktree and branch come from the card's Work: line):
    python -I -B <PIPELINE_ROOT>/tools/job_pins.py economy-1 --work 3f2a9c1
  before DONE: what was tested is what was gated, and the card has not changed since:
    python -I -B <PIPELINE_ROOT>/tools/job_pins.py atmosphere-7 --check
  a card with a Reads: section: the same commands; print adds reads: lines, and --check names a read file that moved:
    python -I -B <PIPELINE_ROOT>/tools/job_pins.py shell-2 --check
  before a merge (Integrator): the READY item's pins equal the gate's:
    python -I -B <PIPELINE_ROOT>/tools/job_pins.py economy-1 --check --ready "<PIPELINE_ROOT>/lanes/integrator/inbox/builder/<READY item>.md"
  self-test (born red: a planted mismatch must fail):
    python -I -B <PIPELINE_ROOT>/tools/job_pins.py --self-test
exit: 0 ok; 1 MISMATCH (--check); 2 missing or unreadable record, git error, wrong branch
"""


class PinError(Exception):
    """A missing, unreadable or unparsable record: exit 2, never a pass."""


def q(p):
    return '"%s"' % p


def default_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lane_of(job):
    return job.rsplit("-", 1)[0]


def lane_title(root, lane):
    p = os.path.join(root, "lanes", lane, "LANE.md")
    try:
        with open(p, encoding="utf-8-sig") as fh:
            head = fh.readline()
    except OSError:
        return lane
    m = re.match(r"#\s*LANE:\s*(.+?)\s*\(", head)
    return m.group(1) if m else lane


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    try:
        with open(p, "rb") as fh:
            return sha_bytes(fh.read())
    except OSError as e:
        raise PinError("cannot read %s: %s" % (q(p), e))


def _clean(s):
    return s.strip().strip("`").strip('"').strip("'").strip()


def parse_work(v, root):
    parts = [x.strip() for x in v.split("|")]
    kind = parts[0].lower()
    if kind == "commit" and len(parts) == 3 and parts[1].startswith("worktree ") and parts[2].startswith("branch "):
        b = _clean(parts[2][len("branch "):])
        if len(b.split()) != 1:      # a note after the branch would read as part of its name
            raise PinError("the Work: line has text after the branch name: %r; put notes on their own line "
                           "(JOB-TEMPLATE.md)" % b)
        return {"kind": "commit", "worktree": _clean(parts[1][len("worktree "):]), "branch": b}
    if kind == "file" and len(parts) == 2:
        files = [_clean(x) for x in parts[1].split(";") if _clean(x)]
        files = [f if os.path.isabs(f) else os.path.join(root, f) for f in files]
        if files:
            return {"kind": "file", "files": files}
    raise PinError("the card's Work: line does not parse: %r (want 'Work: commit | worktree <path> | branch <name>' "
                   "or 'Work: file | <path>[ ; <path>]')" % v)


def read_card(root, job):
    """JOB.md of <job>, parsed. Raises PinError when it is missing or unreadable."""
    if not JOB_RE.match(job or ""):
        raise PinError("bad job id %r (want <lane>-<n>, e.g. atmosphere-7)" % job)
    p = os.path.join(root, "jobs", job, "JOB.md")
    try:
        with open(p, "rb") as fh:
            data = fh.read()
        text = data.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise PinError("cannot read the card %s: %s" % (q(p), e))
    lines = text.splitlines()
    card = {"job": job, "lane": lane_of(job), "root": root, "path": p, "dir": os.path.dirname(p), "bytes": data,
            "lines": lines, "scorecard": None, "systems": None, "work": None, "work_line": None,
            "attempt_log_none": False, "offline_none": "Offline tests: none, because" in text, "measures": [],
            "reads": None}
    in_measures = False
    for ln in lines:
        if ln.startswith("#"):
            in_measures = ln.startswith("## Keep-or-revert measures")
        elif in_measures and (ln.lstrip().startswith(("-", "`")) or "|" in ln):     # any row form
            mn = ln.lstrip("- ").strip().strip("`").split("|")[0].strip()
            if mn and not mn.lower().startswith("none"):
                card["measures"].append(mn)
        if ln.startswith("Scorecard:") and card["scorecard"] is None:
            m = re.search(r"`([^`]+)`", ln)
            if m:
                sc = m.group(1).strip()
                card["scorecard"] = sc if os.path.isabs(sc) else os.path.join(root, sc)
        elif ln.startswith("Systems:") and card["systems"] is None:
            v = ln[len("Systems:"):].strip()
            if v and not v.startswith("<"):
                card["systems"] = [s.strip().lower() for s in v.split(",") if s.strip()]
        elif ln.startswith("Work:") and card["work_line"] is None:
            card["work_line"] = ln[len("Work:"):].strip()
        elif ln.startswith("Attempt log:"):
            card["attempt_log_none"] = ln[len("Attempt log:"):].strip().lower().startswith("none")
    return card


def need_work(card):
    if card["work"] is None:
        if not card["work_line"]:
            raise PinError("the card %s has no 'Work:' line: the card is incomplete (see JOB-TEMPLATE.md); its receiver sends the Coordinator a Q and does not start"
                           % q(card["path"]))
        card["work"] = parse_work(card["work_line"], card["root"])
    return card["work"]


def need_reads(card):
    """The card's Reads: rows as [(path, sha12)]; [] with no section or `Reads: none`. A section is the rows after its
    head, up to a heading or the first blank line after a row. Lazy like need_work. A row that does not parse is a
    PinError, never a skipped pin."""
    if card["reads"] is None:
        out, lines, i = [], card["lines"], 0
        while i < len(lines):
            m = READS_HEAD_RE.match(lines[i].strip())
            i += 1
            if not m:
                continue
            rows = [m.group(1).strip()] if (m.group(1) or "").strip() else []
            while i < len(lines) and not lines[i].lstrip().startswith("#"):
                s = lines[i].strip()
                i += 1
                if s:
                    rows.append(s)
                elif rows:
                    break
            if len(rows) == 1 and rows[0].lower().startswith("none"):
                continue
            if not rows:
                raise PinError("the card %s has a Reads: section with no rows (want '- <path> | <sha12>', or 'Reads: "
                               "none')" % q(card["path"]))
            for s in rows:
                mr = READS_ROW_RE.match(s)
                if not mr or not _clean(mr.group(1)):
                    raise PinError("the card's Reads: row does not parse: %r (want '- <path> | <sha12>', one row per "
                                   "file, 12 hex, nothing after them; JOB-TEMPLATE.md)" % s)
                f = _clean(mr.group(1))
                out.append((f if os.path.isabs(f) else os.path.join(card["root"], f), mr.group(2).lower()))
        card["reads"] = out
    return card["reads"]


def reads_state(card):
    """[(path, pinned sha12, sha12 now)] of the card's Reads: rows. A file that cannot be read is a PinError (exit 2)."""
    return [(p, s, sha_file(p)[:12]) for p, s in need_reads(card)]


def reads_lines(card):
    """The `reads:` lines that follow the pins line; none for a card with no Reads: rows."""
    return ["reads: %s %s%s" % (pin, q(p), "" if pin == cur else " | DIFFERS: file now %s" % cur)
            for p, pin, cur in reads_state(card)]


def git_run(wt, *args):
    """(returncode, stdout, stderr) of `git -C <wt> <args>`; never raises."""
    try:
        p = subprocess.run(["git", "-C", wt] + list(args), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 99, "", str(e)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def git(wt, *args):
    rc, out, err = git_run(wt, *args)
    if rc:
        raise PinError("git -C %s %s failed: %s" % (q(wt), " ".join(args), (err or out)[:300]))
    return out


def work_state(card, override=None):
    """('commit', full sha) or ('file', full sha256) of the job's work now (or of --work)."""
    w = need_work(card)
    if override:
        if HEX_RE.match(override):
            if w["kind"] == "commit":
                return "commit", git(w["worktree"], "rev-parse", "--verify", override + "^{commit}")
            if len(override) < 12:
                raise PinError("--work %s: give at least 12 hex characters for a document job" % override)
            return "file", override.lower()
        if os.path.isfile(override):
            return "file", sha_file(override)
        raise PinError("--work %s is neither a 7-40 character hex commit nor an existing file" % q(override))
    if w["kind"] == "commit":
        br = git(w["worktree"], "rev-parse", "--abbrev-ref", "HEAD")
        if br != w["branch"]:
            raise PinError("worktree %s is on branch %s; the card says %s" % (q(w["worktree"]), br, w["branch"]))
        return "commit", git(w["worktree"], "rev-parse", "HEAD")
    shas = [sha_file(f) for f in w["files"]]
    return "file", shas[0] if len(shas) == 1 else sha_bytes("\n".join(shas).encode("ascii"))


def card_pins(card):
    """(card sha12, scorecard sha12) now."""
    if not card["scorecard"]:
        raise PinError("the card %s has no 'Scorecard:' line with a `path`" % q(card["path"]))
    return sha_bytes(card["bytes"])[:12], sha_file(card["scorecard"])[:12]


def pins_line(card, work_full):
    c, s = card_pins(card)
    return "pins: card %s | scorecard %s | work %s" % (c, s, work_full[:12])


def find_pins(path, top=5):
    """(card, scorecard, work) from the top 5 lines of a REVIEW-, TEST- or GATE- record, or None. top=None reads a
    whole item (send_item.py writes 5 header lines first, so an item's pins line is line 6 or later); two different
    pins lines in one item are ambiguous (PinError). Raises PinError when unreadable."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        raise PinError("cannot read %s: %s" % (q(path), e))
    found = []
    for ln in (lines if top is None else lines[:top]):
        m = PINS_RE.match(ln.strip())
        if m and m.groups() not in found:
            found.append(m.groups())
            if top is not None:
                break
    if len(found) > 1:
        raise PinError("%s holds %d different pins lines; an item carries exactly one" % (q(path), len(found)))
    return found[0] if found else None


def newest(jobdir, prefix):
    best = None
    try:
        names = os.listdir(jobdir)
    except OSError:
        return None
    for f in names:
        m = re.match(r"^%s-(\d+)\.md$" % prefix, f)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), os.path.join(jobdir, f))
    return best[1] if best else None


def same_work(a, b):
    return a == b


def older_gate_works(card, newest_gate):
    """Work pins of the job's GATE files other than the newest (a skipped tester must have tested some gate's work)."""
    out = []
    for f in sorted(os.listdir(card["dir"])):
        p = os.path.join(card["dir"], f)
        if re.match(r"^GATE-\d+\.md$", f) and os.path.normcase(p) != os.path.normcase(newest_gate):
            fp = find_pins(p)
            if fp:
                out.append(fp[2])
    return out


# >>> COMMANDS
def cmd_print(root, job, work):
    card = read_card(root, job)
    _, full = work_state(card, work)
    rl = reads_lines(card)
    print(pins_line(card, full))
    for x in rl:
        print(x)
    print("next: put this line in your item or record (top 5 lines); the receiver runs: job_pins.py %s" % job)
    return 0


def cmd_card_only(root, job):
    card = read_card(root, job)
    c, sc = card_pins(card)
    rl = reads_lines(card)
    print("pins: card %s | scorecard %s | work none" % (c, sc))
    for x in rl:
        print(x)
    print("next: put this line in the JOB item; the builder sends the full pins line (job_pins.py %s) in its first "
          "REVIEW-ASK" % job)
    return 0


def cmd_check(root, job, ready):
    card = read_card(root, job)
    jd = card["dir"]
    recs = [("REVIEW", newest(jd, "REVIEW")), ("TEST", newest(jd, "TEST")), ("GATE", newest(jd, "GATE"))]
    missing = []
    for name, p in recs[1:]:
        if p is None:
            missing.append(("MISSING %s-<n>.md in %s: none found (nothing to check is never a pass)" % (name, q(jd)),
                            os.path.join(jd, "%s-<n>.md" % name)))
    if ready:
        recs.append(("READY", ready))
    pins = {}
    if not missing:
        for name, p in recs:
            if p is None:
                continue
            t = find_pins(p, None if name == "READY" else 5)
            if t is None:
                missing.append(("MISSING %s: no pins line%s" % (q(p), "" if name == "READY" else " in its top 5 lines"),
                                p))
            else:
                pins[name] = t
    if missing:
        for msg, _ in missing:
            print(msg)
        print("next: add the pins line (job_pins.py %s) to %s, or write the missing record" % (job, q(missing[0][1])))
        return 2
    cur_c, cur_s = card_pins(card)
    cur_w = work_state(card)[1][:12]
    gp = pins["GATE"]
    with open(dict(recs)["GATE"], "rb") as fh:     # a skipped tester is a scoped re-gate's own line
        gtxt = fh.read(4000).decode("utf-8-sig", errors="replace")[:2000]
    scoped = re.search(r"(?m)^#?\s*SCOPED RE-GATE of GATE-\d+", gtxt)
    skip = re.search(r"(?m)^tester not re-run: .+", gtxt)
    bad, notes = [], []
    for name in ("REVIEW", "TEST", "READY"):
        if name in pins and not same_work(pins[name][2], gp[2]):
            if (name == "TEST" and scoped and skip and
                    any(same_work(pins[name][2], x) for x in older_gate_works(card, dict(recs)["GATE"]))):
                notes.append("TEST older than GATE: tester not re-run: %s" % skip.group(0).strip())
            else:
                bad.append("MISMATCH work %s vs GATE: %s vs %s" % (name, pins[name][2], gp[2]))
    if gp[0] != cur_c:
        bad.append("MISMATCH card GATE vs JOB.md now: %s vs %s (read the newest JOB.md.pre-* copy)" % (gp[0], cur_c))
    if gp[1] != cur_s:
        bad.append("MISMATCH scorecard GATE vs score card now: %s vs %s" % (gp[1], cur_s))
    if not same_work(cur_w, gp[2]):
        bad.append("MISMATCH work now vs GATE: %s vs %s" % (cur_w, gp[2]))
    if "READY" in pins and pins["READY"] != gp:
        bad.append("MISMATCH READY pins line vs GATE: %s vs %s" % (" | ".join(pins["READY"]), " | ".join(gp)))
    rs = reads_state(card)
    moved = [(p, pin, cur) for p, pin, cur in rs if pin != cur]
    for p, pin, cur in moved:
        bad.append("MISMATCH reads %s: card pin %s vs file now %s" % (q(p), pin, cur))
    if moved and len(moved) == len(bad):
        for b in bad:
            print(b)
        print("next: read what changed in the file(s) named above; a Reads: pin moves only by a card edit, which needs "
              "a TEST-ASK and a new gate on the current pins (RULES.md step 5)")
        return 1
    if bad:
        for b in bad:
            print(b)
        print("next: read what changed (newest JOB.md.pre-* copy; git -C <worktree> diff <gate work>..HEAD), then "
              "TEST-ASK and a new gate on the current pins (RULES.md step 5)")
        return 1
    for n in notes:
        print(n)
    print("pins OK: pins: card %s | scorecard %s | work %s" % gp)
    if rs:
        print("reads OK: %d pinned file(s) match the card" % len(rs))
    print("next: send DONE / READY with this pins line (Integrator: merge)")
    return 0
# <<< COMMANDS


# ---------------------------------------------------------------- self-test (P1-P11)
def _rmtree(path):
    """Remove a self-test folder; git leaves read-only object files, so clear the flag and retry."""
    def onerr(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=onerr)
    else:
        shutil.rmtree(path, onerror=onerr)


def self_test():
    base = os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or ".", "job_pins-selftest-%s-p%d" % (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))
    tmp, k = base, 1
    while True:                  # parallel self-tests never share a folder
        try:
            os.makedirs(os.path.join(tmp, "tools"))
            break
        except FileExistsError:
            k += 1
            tmp = "%s-%d" % (base, k)
    me = os.path.join(tmp, "tools", "job_pins.py")
    shutil.copyfile(os.path.abspath(__file__), me)
    print("self-test folder: %s (removed when every check passes, kept on a failure)" % q(tmp))
    res = []

    def check(name, ok, out=""):
        res.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  | " + out.strip().replace("\n", " / ")[-400:]))

    def run(*args):
        p = subprocess.run([sys.executable, "-I", "-B", me] + list(args), cwd=os.path.dirname(tmp),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = p.stdout + p.stderr
        return p.returncode, out

    def last_next(out):
        ls = [x for x in out.splitlines() if x.strip()]
        return bool(ls) and ls[-1].startswith("next: ")

    def w(path, text, crlf=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as fh:
            fh.write(text)

    def g(wt, *args):
        return subprocess.run(["git", "-c", "user.name=selftest", "-c", "user.email=selftest@invalid", "-c",
                               "core.autocrlf=false", "-C", wt] + list(args), capture_output=True, text=True,
                              check=True).stdout.strip()

    def pins_of(out):
        for ln in out.splitlines():
            if PINS_RE.match(ln.strip()):
                return ln.strip()
        return ""

    sc = os.path.join(tmp, "score", "SCORE-CARD.md")
    w(sc, "# SCORE CARD test\n")
    w(os.path.join(tmp, "lanes", "d", "LANE.md"), "# LANE: Doc lane (test)\n")
    work = os.path.join(tmp, "lanes", "d", "contracts", "W.md")
    w(work, "contract v1\n")
    card_d = os.path.join(tmp, "jobs", "d-1", "JOB.md")
    w(card_d, "# JOB d-1 (document job)\nSystems: weather\nWork: file | %s\nAttempt log: jobs\\d-1\\ATTEMPTS.jsonl\n"
              "Scorecard: `%s` v1\n" % (work, sc), crlf=True)
    wt = os.path.join(tmp, "wt dir", "t")
    os.makedirs(wt)
    subprocess.run(["git", "init", "-q", "-b", "job/t-2", wt], check=True, capture_output=True)
    w(os.path.join(wt, "f.txt"), "one\n")
    g(wt, "add", "f.txt")
    g(wt, "commit", "-q", "-m", "first")
    w(os.path.join(tmp, "jobs", "t-2", "JOB.md"), "# JOB t-2 (code job)\nSystems: econ\nWork: commit | worktree %s | "
      "branch job/t-2\nScorecard: `%s` v1\n" % (wt, sc))

    # P1 print, document job (CRLF JOB.md)
    rc, out = run("d-1")
    line = pins_of(out)
    with open(card_d, "rb") as fh:
        card_bytes = fh.read()
    with open(work, "rb") as fh:
        work12 = sha_bytes(fh.read())[:12]
    check("P1 print doc job (CRLF JOB.md): exit 0, pins line, work = file sha12, card = JOB.md sha12, next: line",
          rc == 0 and line.endswith("work " + work12) and ("card " + sha_bytes(card_bytes)[:12]) in line
          and b"\r\n" in card_bytes and last_next(out), out)
    # P2 print, code job (worktree path with a space)
    head = g(wt, "rev-parse", "HEAD")
    rc, out = run("t-2")
    ok1 = rc == 0 and pins_of(out).endswith("work " + head[:12]) and last_next(out)
    g(wt, "switch", "-q", "-c", "other")
    rc2, out2 = run("t-2")
    g(wt, "switch", "-q", "job/t-2")
    check("P2 print code job: work = HEAD sha12; on another branch exit 2", ok1 and rc2 == 2 and last_next(out2),
          out + out2)
    jd = os.path.join(tmp, "jobs", "d-1")
    good = line or "pins: card 000000000000 | scorecard 000000000000 | work 000000000000"
    w(os.path.join(jd, "REVIEW-1.md"), "round 1 | sent back by: first | required open 0 | closed since round 0 0 | "
      "new 0\n%s\nfindings\n" % good)
    w(os.path.join(jd, "TEST-1.md"), "# TEST-1 WORKS\n%s\n" % good)
    w(os.path.join(jd, "GATE-1.md"), "# GATE-1\n%s\nGATE PASS avg 7.0\n" % good)
    # P3 clean check
    rc, out = run("d-1", "--check")
    check("P3 clean check: exit 0, pins OK", rc == 0 and "pins OK" in out and last_next(out), out)
    # P4 TEST work differs (the born-red case)
    bad = good[:-12] + "aaaaaaaaaaaa"
    w(os.path.join(jd, "TEST-2.md"), "# TEST-2 WORKS\n%s\n" % bad)
    rc, out = run("d-1", "--check")
    check("P4 newest TEST has another work pin: exit 1 MISMATCH", rc == 1 and "MISMATCH" in out and last_next(out), out)
    w(os.path.join(jd, "TEST-3.md"), "# TEST-3 WORKS\n%s\n" % good)
    rc, out = run("d-1", "--check")
    check("P4b a newer TEST with the gated pins: exit 0 again", rc == 0, out)
    # P5 JOB.md edited after GATE
    with open(card_d, "ab") as fh:
        fh.write(b"edited after the gate\r\n")
    rc, out = run("d-1", "--check")
    with open(card_d, "wb") as fh:
        fh.write(card_bytes)
    check("P5 JOB.md edited after GATE: exit 1 MISMATCH card", rc == 1 and "MISMATCH card" in out, out)
    # P6 work file changed after GATE
    w(work, "contract v2\n")
    rc, out = run("d-1", "--check")
    w(work, "contract v1\n")
    check("P6 work file changed after GATE: exit 1 MISMATCH work", rc == 1 and "MISMATCH work" in out, out)
    # P7 GATE without a pins line; a job with no GATE file
    w(os.path.join(jd, "GATE-2.md"), "# GATE-2 (no pins line)\nGATE PASS avg 7.0\n")
    rc, out = run("d-1", "--check")
    w(os.path.join(tmp, "jobs", "t-2", "TEST-1.md"), "# TEST-1\n%s\n" % pins_of(run("t-2")[1]))
    rc2, out2 = run("t-2", "--check")
    check("P7 GATE without pins line exit 2 (MISSING); no GATE file exit 2",
          rc == 2 and "MISSING" in out and rc2 == 2 and last_next(out) and last_next(out2), out + out2)
    # P8 --ready
    w(os.path.join(jd, "GATE-3.md"), "# GATE-3\n%s\nGATE PASS avg 7.0\n" % good)
    head = "id: Doc lane builder-20261101T000000Z-1\nkind: READY\nfrom: Doc lane builder\nrefs: d-1\n\n"  # send_item.py
    ready_bad = os.path.join(tmp, "ready bad.md")
    w(ready_bad, head + "READY d-1\n%s\n" % ("pins: card bbbbbbbbbbbb" + good[len("pins: card ") + 12:]))
    ready_ok = os.path.join(tmp, "ready ok.md")
    w(ready_ok, head + "READY d-1: gate PASS, tester WORKS\n%s\nIDEAS: none\n" % good)
    ready_two = os.path.join(tmp, "ready two.md")
    w(ready_two, head + "%s\n%s\n" % (good, bad))
    ready_none = os.path.join(tmp, "ready none.md")
    w(ready_none, head + "READY d-1 (forgot the pins line)\n")
    rc, out = run("d-1", "--check", "--ready", ready_bad)
    rc2, out2 = run("d-1", "--check", "--ready", ready_ok)
    rc3, out3 = run("d-1", "--check", "--ready", ready_two)
    rc4, out4 = run("d-1", "--check", "--ready", ready_none)
    check("P8 --ready (send_item.py header, pins on line 6+): other pins exit 1; the gate's pins exit 0; two different "
          "pins lines exit 2; none exit 2", rc == 1 and rc2 == 0 and rc3 == 2 and rc4 == 2, out + out2 + out3 + out4)
    # P10 scoped re-gate with the tester not re-run
    jd10 = os.path.join(tmp, "jobs", "d-10")
    work10 = os.path.join(tmp, "lanes", "d", "contracts", "W10.md")
    w(work10, "v0\n")
    w(os.path.join(jd10, "JOB.md"), "# JOB d-10 (document job)\nSystems: weather\nWork: file | %s\nAttempt log: "
      "jobs\\d-10\\ATTEMPTS.jsonl\nScorecard: `%s` v1\n" % (work10, sc))
    w(work10, "v1\n")
    p1 = pins_of(run("d-10")[1])
    w(os.path.join(jd10, "REVIEW-1.md"), "round 1\n%s\n" % p1)
    w(os.path.join(jd10, "TEST-1.md"), "# TEST-1 WORKS\n%s\n" % p1)
    w(os.path.join(jd10, "GATE-1.md"), "# GATE-1\n%s\nGATE FAIL avg 6.1: 1 must-fix\n" % p1)
    w(work10, "v2\n")
    p2 = pins_of(run("d-10")[1])
    w(os.path.join(jd10, "REVIEW-2.md"), "round 2\n%s\ntester not re-run: fix touches nothing tested\n" % p2)
    gp10 = os.path.join(jd10, "GATE-2.md")
    w(gp10, "# SCOPED RE-GATE of GATE-1\n%s\ntester not re-run: fix touches nothing tested\nGATE PASS avg 7.2\n" % p2)
    rc, out = run("d-10", "--check")
    rtest = os.path.join(jd10, "TEST-1.md")
    w(rtest, "# TEST-1 WORKS\n%s\n" % (p1.rsplit(" ", 1)[0] + " " + "0" * 12))
    rc4, out4 = run("d-10", "--check")
    w(rtest, "# TEST-1 WORKS\n%s\n" % p1)
    w(gp10, "# SCOPED RE-GATE of GATE-1\n%s\nGATE PASS avg 7.2\n" % p2)
    rc2, out2 = run("d-10", "--check")
    w(gp10, "# GATE-2\n%s\ntester not re-run: fix touches nothing tested\nGATE PASS avg 7.2\n" % p2)
    rc3, out3 = run("d-10", "--check")
    check("P10 scoped re-gate with 'tester not re-run': exit 0 with the note; no such line exit 1; the line under a "
          "normal gate header exit 1; a TEST pin of no gate exit 1", rc == 0 and "TEST older than GATE" in out and
          rc2 == 1 and rc3 == 1 and rc4 == 1, out + out2 + out3 + out4)
    # P11 a job id with a letter
    w(os.path.join(tmp, "jobs", "d-10b", "JOB.md"), "# JOB d-10b (document job)\nSystems: weather\nWork: file | %s\n"
      "Attempt log: jobs\\d-10b\\ATTEMPTS.jsonl\nScorecard: `%s` v1\n" % (work10, sc))
    rc, out = run("d-10b")
    check("P11 a job id with a letter prints its pins", rc == 0 and "pins: card " in out, out)
    # P2b a note after the branch name
    w(os.path.join(tmp, "jobs", "t-11", "JOB.md"), "# JOB t-11 (code job)\nSystems: econ\nWork: commit | worktree %s | "
      "branch job/t-2 (the scripts live on it)\nScorecard: `%s` v1\n" % (wt, sc))
    rc, out = run("t-11")
    check("P2b a note after the branch: exit 2 naming it", rc == 2 and "text after the branch name" in out, out)
    # P9 --card-only: a new code job whose worktree does not exist yet
    w(os.path.join(tmp, "jobs", "n-9", "JOB.md"), "# JOB n-9 (code job)\nSystems: econ\nWork: commit | worktree %s | "
      "branch job/n-9\nScorecard: `%s` v1\n" % (os.path.join(tmp, "wt dir", "not made yet n-9"), sc))
    rc, out = run("n-9")
    rc2, out2 = run("n-9", "--card-only")
    rc3, out3 = run("n-9", "--card-only", "--check")
    check("P9 --card-only: a code job with no worktree yet: plain print 2; --card-only 0 with 'work none' and the "
          "builder hint; with --check 2; PINS_RE never takes 'work none'",
          rc == 2 and rc2 == 0 and re.search(r"^pins: card [0-9a-f]{12} \| scorecard [0-9a-f]{12} \| work none$", out2,
                                             re.M) is not None and "first REVIEW-ASK" in out2 and last_next(out2) and
          rc3 == 2 and not PINS_RE.match("pins: card %s | scorecard %s | work none" % ("a" * 12, "b" * 12)),
          out + out2 + out3)
    rc, out = run("--help")
    check("help: usage and one example per mode", rc == 0 and out.count("python -I -B") >= 6, out)
    print("ALL PASS (%d)" % len(res) if all(res) else "SOME FAILED (%d of %d)" % (res.count(False), len(res)))
    if all(res):
        _rmtree(tmp)
    else:
        print("self-test folder kept: %s" % q(tmp))
    print("next: %s" % ("nothing; the script is ready" if all(res) else "fix the FAIL lines above, then run --self-test again"))
    return 0 if all(res) else 1


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print("ERROR: %s" % message)
        print("next: run job_pins.py --help for the usage and an example per command")
        sys.exit(2)


def main(argv=None):
    ap = _Parser(prog="job_pins.py", description="Print or check the pins line of one pipeline job (RULES.md 'Items').",
                 epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job", nargs="?", help="job id, e.g. atmosphere-7")
    ap.add_argument("--work", help="print mode: a commit-ish (7-40 hex) or a file path instead of the work now")
    ap.add_argument("--check", action="store_true", help="check REVIEW / TEST / GATE (and --ready) pins and the live state")
    ap.add_argument("--ready", help="with --check: the READY item file whose pins must equal the gate's")
    ap.add_argument("--card-only", action="store_true", help="the JOB item: card and score card pins, `work none`")
    ap.add_argument("--root", default=default_root(), help="pipeline root (default: the parent of tools\\)")
    ap.add_argument("--self-test", action="store_true", help="run P1-P11 in %%TEMP%%")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.job:
        ap.error("give a job id, e.g. job_pins.py atmosphere-7")
    if a.ready and not a.check:
        ap.error("--ready needs --check")
    if a.check and a.work:
        ap.error("--work is for print mode only")
    if a.card_only and (a.check or a.work):
        ap.error("--card-only is for the JOB item: no --check or --work")
    try:
        if a.card_only:
            return cmd_card_only(a.root, a.job)
        return cmd_check(a.root, a.job, a.ready) if a.check else cmd_print(a.root, a.job, a.work)
    except PinError as e:
        print("ERROR: %s" % e)
        print("next: fix the card or record named above, then run job_pins.py %s again" % a.job)
        return 2


if __name__ == "__main__":
    sys.exit(main())
