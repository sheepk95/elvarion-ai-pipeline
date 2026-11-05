"""build_index.py: the ONLY writer of <SKILL_LIBRARY>/INDEX.md and REJECTED.md (stdlib only, no model calls).

WARNING: a run without --check REWRITES the live INDEX.md and REJECTED.md of the library it is pointed at. Point it at a
test library first (SKILL_LIBRARY and SKILLS_DIR below) and use --check or --simulate-install to look without writing.

Environment (all optional):
  SKILL_LIBRARY   folder of the skill library (INDEX.md, REJECTED.md, installed skills; default ~/skill-library)
  SKILLS_DIR      folder of the live skills, one folder per skill with a SKILL.md (default ~/.claude/skills)
  SKILL_CORE_FILE text file listing the core skill names, one per line (default <SKILL_LIBRARY>/CORE.txt; none = no core)
  SKILL_RECORDS   folder of the optional append-only record files named below (default <SKILL_LIBRARY>/_records)
Sources (all read-only, append-only records): SKILL.md frontmatter of SKILLS_DIR and the library (frontmatter only,
never the body); <SKILL_RECORDS>/INSTALLS.jsonl + REVIEWS.jsonl + VERDICTS.jsonl + external-catalogue.jsonl +
sweep2.jsonl + gate-folders.json and <SKILL_LIBRARY>/catalogue.jsonl (a feeder, optional); a missing record file counts as
empty. Unvetted rows use catalogue METADATA only (descriptions from those records); no unvetted
SKILL.md body is read. Writes a temp file then os.replace (atomic).
Row: | name | status | description(<=200) | path | source | verdict |   (a pipe inside text is escaped with a backslash)

Version 2:
- Every vetted row points at the REAL skill: <SKILLS_DIR>/<name>/SKILL.md, or <SKILL_LIBRARY>/<name>/SKILL.md for a
  library install (a folder with no live original that is not an A-library copy, or that INSTALLS.jsonl says was installed
  there). A-library copies (_manifests/<name>.json) and anything under skill-library/_snapshot-* are copies, never rows.
  The old "library copy if its manifest says match" branch is gone: that flag was frozen at copy time.
- The disk is re-read on every build, so a new install (in either root) gets its row on the next build. The
  installer runs `--after-install <name>`, which rebuilds and refuses (exit 4) unless that name has exactly one vetted
  row whose path is its live SKILL.md.
- App-managed skills (plugins, synced claude.ai skills, Codex .system, shared brain skills) come from the gate list
  (<SKILL_RECORDS>/gate-folders.json) as status `app` rows: always available natively,
  never hidden, never installed or edited by us. ~/.codex files are never opened (existence check only).
- main() is guarded, so importing this file no longer rebuilds the INDEX (trap: an import used to rebuild it).
Usage: python -I -B build_index.py [--check] [--gate GATE.json] [--allow-empty]
       (--allow-empty: write an empty INDEX even when SKILLS_DIR holds SKILL.md files but the build found 0 vetted rows;
        without it that case exits 1 with an ERROR and writes nothing. -h / --help prints this text and exits 0.)
       python -I -B build_index.py --after-install <name>          (rebuild, then verify that name's row; JSON out)
       python -I -B build_index.py --simulate-install <name>=<dir>  (dry run: build in memory as if <dir> were installed
                                                                     at skill-library/<name>; writes nothing)
"""
import hashlib, json, os, re, sys, time


class T:
    """The few folder settings the original shared helper module held, now read from the environment."""
    HOME = os.path.expanduser("~")
    SRC = os.environ.get("SKILLS_DIR") or os.path.join(HOME, ".claude", "skills")
    LIB = os.environ.get("SKILL_LIBRARY") or os.path.join(HOME, "skill-library")
    CORE_FILE = os.environ.get("SKILL_CORE_FILE") or os.path.join(LIB, "CORE.txt")
    SKIP_TOP = {"synced"}  # desktop copies, no top-level SKILL.md

    @staticmethod
    def core_names():
        out = set()
        if os.path.isfile(T.CORE_FILE):
            for l in open(T.CORE_FILE, encoding="utf-8"):
                l = l.strip()
                if l and not l.startswith("#"):
                    out.add(l)
        return out


RECORDS = os.environ.get("SKILL_RECORDS") or os.path.join(T.LIB, "_records")
INSTALLS = os.path.join(RECORDS, "INSTALLS.jsonl")
REVIEWS = os.path.join(RECORDS, "REVIEWS.jsonl")
VERDICTS = os.path.join(RECORDS, "VERDICTS.jsonl")
CATALOGUE = os.path.join(T.LIB, "catalogue.jsonl")
EXT = os.path.join(RECORDS, "external-catalogue.jsonl")
SWEEP2 = os.path.join(RECORDS, "sweep2.jsonl")
GATE = os.path.join(RECORDS, "gate-folders.json")
HEADER_LINES = 30


def jl(p):
    if not os.path.isfile(p):
        return []
    out = []
    for l in open(p, encoding="utf-8"):
        l = l.strip()
        if l:
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    return out


def frontmatter(path):
    """name, description, origin from the YAML frontmatter only (simple parser: scalars, quoted, > and | blocks)."""
    try:
        txt = open(path, encoding="utf-8", errors="replace").read(20000)
    except OSError:
        return {}
    if not txt.startswith("---"):
        return {}
    end = txt.find("\n---", 3)
    lines = txt[3:end if end > 0 else len(txt)].splitlines()
    fm, i = {}, 0
    while i < len(lines):
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        k, v = m.group(1), m.group(2).strip()
        i += 1
        if v in (">", "|", ">-", "|-", ">+", "|+"):
            buf = []
            while i < len(lines) and (lines[i].startswith(" ") or not lines[i].strip()):
                buf.append(lines[i].strip())
                i += 1
            v = " ".join(x for x in buf if x)
        else:
            buf = []
            while i < len(lines) and lines[i].startswith(" ") and not re.match(r"^\s*[\w-]+:\s", lines[i]):
                buf.append(lines[i].strip())
                i += 1
            quoted = len(v) > 1 and v[0] == v[-1] and v[0] in "\"'"
            if buf and not quoted:
                v = (v + " " + " ".join(buf)).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            q = v[0]
            v = v[1:-1]
            if q == '"':
                v = v.replace('\\"', '"')
        fm[k] = v
    return fm


def cell(s, n=None):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if n and len(s) > n:
        s = s[: n - 3].rstrip() + "..."
    return s.replace("|", "\\|")


def row(name, status, desc, path, source, verdict):
    return "| " + " | ".join([cell(name), status, cell(desc, 200), cell(path), cell(source, 160), cell(verdict, 200)]) + " |"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:60]


def unvetted_name(it):
    u = it.get("url") or ""
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)(?:/(?:tree|blob)/[^/]+/(.+))?", u)
    if m and it.get("kind") in (None, "skill", "skill-collection", "plugin"):
        last = (m.group(3) or m.group(2)).rstrip("/").split("/")[-1]
        return "community-" + slug(m.group(1)) + "-" + slug(last)
    m = re.match(r"https?://(?:www\.)?skills\.sh/([^/]+)/[^/]+/([^/?#]+)", u)
    if m:
        return "community-" + slug(m.group(1)) + "-" + slug(m.group(2))
    return slug(it.get("name") or it.get("id") or "item")


def arg(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        sys.exit("usage: %s needs a value" % flag)
    return None


def norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def package_manifest(skill_file):
    """Hash every regular package file without following links or reparse points.

    No paths are excluded. An unsafe or unreadable entry invalidates the whole package.
    """
    root = os.path.dirname(skill_file)
    manifest = {}

    def unsafe(st):
        return bool(getattr(st, 'st_file_attributes', 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT

    root_stat = os.lstat(root)
    if os.path.islink(root) or unsafe(root_stat):
        raise ValueError('package root is a link or reparse point')

    def visit(folder, prefix=''):
        with os.scandir(folder) as entries:
            for entry in entries:
                relative = prefix + entry.name
                st = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or unsafe(st):
                    raise ValueError('link or reparse point: ' + relative)
                if entry.is_dir(follow_symlinks=False):
                    visit(entry.path, relative + '/')
                elif entry.is_file(follow_symlinks=False):
                    with open(entry.path, 'rb') as f:
                        manifest[relative] = hashlib.file_digest(f, 'sha256').hexdigest()
                else:
                    raise ValueError('not a regular file: ' + relative)

    visit(root)
    if 'SKILL.md' not in manifest:
        raise ValueError('missing SKILL.md')
    return manifest


def library_installs(installs):
    """Folders INSTALLS.jsonl says the installer put inside skill-library (a library install)."""
    out = set()
    for r in installs.values():
        lp = r.get("library") or ""
        if lp and r.get("action", "install") == "install" and norm(os.path.dirname(lp)) == norm(T.LIB):
            out.add(os.path.basename(lp))
    return out


def scan_skills(installs, simulate=None):
    """name -> (SKILL.md path, frontmatter, root kind). Real skills only; copies never count. simulate = (name, dir)."""
    vetted, warn = {}, []
    for root in (T.SRC, T.LIB):
        if not os.path.isdir(root):
            warn.append("missing directory: %s (treated as empty; create it before writing an index)" % root)
    for n in sorted(os.listdir(T.SRC) if os.path.isdir(T.SRC) else []):
        p = os.path.join(T.SRC, n)
        sk = os.path.join(p, "SKILL.md")
        if n in T.SKIP_TOP or n.startswith("_") or not os.path.isdir(p) or not os.path.isfile(sk):
            continue
        fm = frontmatter(sk)
        if (fm.get("name") or n) != n:
            warn.append("name != folder: %s %s" % (n, fm.get("name")))
        vetted[n] = (sk, fm, "claude")
    lib_inst = library_installs(installs)
    for n in sorted(os.listdir(T.LIB) if os.path.isdir(T.LIB) else []):
        p = os.path.join(T.LIB, n)
        sk = os.path.join(p, "SKILL.md")
        if n.startswith("_") or not os.path.isdir(p) or not os.path.isfile(sk):
            continue
        if n in vetted:
            # a live <SKILLS_DIR>/<name> always wins; a library folder of the same name is a copy
            warn.append("library folder %s is ignored: the live skill is in the live skills folder (%s)" % (n, n))
            continue
        if os.path.isfile(os.path.join(T.LIB, "_manifests", n + ".json")) and n not in lib_inst:
            warn.append("library folder %s is an A-library copy with no live original: not a skill, no row" % n)
            continue
        vetted[n] = (sk, frontmatter(sk), "library")
    if simulate:
        n, d = simulate
        if n in vetted:
            warn.append("simulate: %s already has a skill at %s; the installer would refuse" % (n, vetted[n][0]))
        else:
            vetted[n] = (os.path.join(T.LIB, n, "SKILL.md"), frontmatter(os.path.join(d, "SKILL.md")), "library (simulated)")
    return vetted, warn


def app_rows(gate_path, taken):
    """Status `app` rows for app-managed skills in the gate list (plugin, synced, Codex .system, ~/.agents)."""
    rows, warn, names = [], [], []
    try:
        g = json.load(open(gate_path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return rows, ["gate list unreadable (%s): no app rows" % e], names
    for e in g.get("skills", []):
        if e.get("kind") in ("claude", "library-only", "project"):
            continue
        n, rp = e["name"], e.get("real_path", "")
        if n in taken:
            warn.append("app name %s clashes with a skill row: skipped" % n)
            continue
        codex = norm(rp).startswith(norm(os.path.join(T.HOME, ".codex")))
        if codex:  # never open .codex files: existence check of the folder only
            path, desc = rp, ""
            if not os.path.isdir(rp):
                warn.append("app %s: %s is gone" % (n, rp))
                continue
        else:
            sk = os.path.join(rp, "SKILL.md")
            path = sk if os.path.isfile(sk) else rp
            if not os.path.exists(path):
                warn.append("app %s: %s is gone" % (n, rp))
                continue
            desc = frontmatter(sk).get("description", "") if os.path.isfile(sk) else ""
        kind = e.get("managed_by") or e.get("kind")
        rows.append(row(n, "app", desc or kind, path.replace("\\", "/"), kind,
                        "app-managed: always available natively; never hide, edit or reinstall" +
                        ("; never hide (gbrain-shared)" if e.get("never_hide") else "")))
        names.append(n)
        taken.add(n)
    return rows, warn, names


def build(simulate=None, gate_path=GATE):
    core = T.core_names()
    installs = {}
    for r in jl(INSTALLS):
        installs[r.get("name") or r.get("planned_name")] = r
    reviews = {}
    for r in jl(REVIEWS):
        reviews[(r.get("source_id"), r.get("commit"))] = r
    vetted, warn = scan_skills(installs, simulate)
    trust_path = os.path.join(RECORDS, "TRUST.json")
    try:
        with open(trust_path, encoding="utf-8") as f:
            trust = json.load(f)
        if not isinstance(trust, dict):
            raise ValueError("expected an object")
    except FileNotFoundError:
        trust = {}
    except (OSError, ValueError) as e:
        trust = {}
        warn.append("invalid TRUST.json: %s; all installed skills require review" % e)
    rows = []
    for n in sorted(vetted):
        sk, fm, where = vetted[n]
        inst = installs.get(n)
        rv = reviews.get((inst.get("source_id"), inst.get("commit")), {}) if inst else {}
        entry = trust.get(n)
        approved = False
        if isinstance(entry, dict) and entry.get("kind") in ("reviewed", "in-house") and isinstance(entry.get("provenance"), str) and entry["provenance"].strip():
            try:
                approved = isinstance(entry.get("files"), dict) and entry["files"] == package_manifest(sk)
            except (OSError, ValueError):
                pass
        status = "vetted" if approved else "installed-unverified"
        if inst:
            rv = reviews.get((inst.get("source_id"), inst.get("commit")), {})
            src = "community %s@%s %s" % (inst.get("source_id"), (inst.get("commit") or "")[:7], inst.get("trust") or "")
            vd = "%s install_skill.py %s %s" % ((inst.get("utc") or "")[:10], inst.get("approval_path"), json.dumps(rv.get("verdicts", {}), separators=(",", ":")))
        elif fm.get("origin") == "community" or n.startswith("community-"):
            src, vd = "community (provenance in folder)", "installed before the install log; origin community"
        elif n.startswith("anthropic-"):
            src, vd = "anthropic (bundled copy)", "installed before the install log"
        else:
            src, vd = "unknown", "no recorded install provenance"
        if where != "claude":
            src += "; " + where + " install"
        if n in core:
            vd += "; CORE (always listed)"
        if status == "installed-unverified":
            vd += "; no matching owner TRUST.json package manifest and provenance; do not use before review"
        else:
            vd += "; owner trust: %s %s" % (entry["kind"], entry["provenance"])
        rows.append(row(n, status, fm.get("description", ""), sk.replace("\\", "/"), src, vd))
    taken = set(vetted)
    app, w2, app_names = app_rows(gate_path, taken)
    warn += w2
    meta = {}
    for it in jl(EXT) + jl(SWEEP2):
        meta[it.get("id")] = it
    unv, rej, used = [], [], set(taken)

    def add(lst, status, it, src, vd):
        nm = unvetted_name(it)
        base, k = nm, 2
        while nm in used:
            nm = "%s-%d" % (base, k)
            k += 1
        used.add(nm)
        kind = "[%s] " % it["kind"] if it.get("kind") else ""
        lst.append(row(nm, status, kind + (it.get("description") or it.get("name") or ""), "-", src, vd))

    seen = set()
    last = {}  # supersede: VERDICTS.jsonl is append-only, so the NEWEST row per id wins (a dict keeps an id at its first position)
    for v in jl(VERDICTS):
        last[v["id"]] = v
    for v in last.values():
        if v.get("verdict") == "installed":
            continue
        seen.add(v["id"])
        it = dict(meta.get(v["id"], {}))
        it.setdefault("id", v["id"])
        it.setdefault("url", v.get("url"))
        it.setdefault("name", v.get("name"))
        if not it.get("description"):
            it["description"] = v.get("reason", "")
        stars = it.get("stars") if it.get("stars") is not None else "?"
        src = "%s stars=%s" % (it.get("url") or v["id"], stars)
        vd = "%s scout %s: %s" % (v.get("date"), v["verdict"], v.get("reason", ""))
        if v["verdict"] == "reference":
            if unvetted_name(it) in vetted:  # installed since the scout row; no "-2" duplicate
                continue
            add(unv, "unvetted", it, src, vd)
        else:
            add(rej, "rejected", it, src, vd)
    for c in jl(CATALOGUE):  # feeder rows, append-only
        key = c.get("id") or c.get("name")
        if not c.get("name") or c["name"] in used or key in seen:
            continue
        seen.add(key)
        used.add(c["name"])
        src = "%s installs=%s stars=%s" % (c.get("url", ""), c.get("installs", "?"), c.get("stars", "?"))
        unv.append(row(c["name"], "unvetted", c.get("description", ""), "-", src, c.get("verdict") or "feeder found"))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    head = [
        "# Skill INDEX (generated by build_index.py at %s; do not edit by hand)" % now,
        "Find a skill: grep -i 2-4 task words. Read only vetted skills; installed-unverified skills require review first.",
        "Row: | name | status | description (200 chars) | path | source | verdict |",
        "status vetted = owner TRUST.json matches every package file. installed-unverified = review before use.",
        "status unvetted = catalogue metadata only, never installed:",
        "  before using one, check REJECTED.md (same folder), then vet and install it (install_skill.py request, check, review, install) with --library <SKILL_LIBRARY>; never use an unvetted skill's files first.",
        "status rejected rows live in REJECTED.md so they do not drown a grep. Open source first: look for an existing tool before building one.",
        "Paths: a vetted row points at the live folder (<SKILLS_DIR>/<name>, or <SKILL_LIBRARY>/<name> for a library install).",
        "status app = app-managed (plugins, synced claude.ai skills, Codex .system, brain-managed shared skills): available natively; never hide, edit or reinstall.",
        "skill-library/_snapshot-*/ folders hold dated copies: never read, edit or cite a copy; write lessons into the skill at its row's path.",
        "Core (always listed in every session, %d): " % len(core) + ", ".join(sorted(core)),
        "Rows: vetted=%d installed-unverified=%d app=%d unvetted=%d (rejected=%d in REJECTED.md)." % (sum('| vetted |' in x for x in rows), sum('| installed-unverified |' in x for x in rows), len(app), len(unv), len(rej)),
        "",
    ]
    assert len(head) <= HEADER_LINES
    cols = "| name | status | description | path | source | verdict |"
    sep = "|---|---|---|---|---|---|"
    idx = "\n".join(head + [cols, sep] + rows + app + unv) + "\n"
    rjx = "\n".join(["# Skill REJECTED list (generated by build_index.py at %s; see INDEX.md header)" % now,
                     "Check here before vetting a catalogue find: each was judged once (scout/triage). Grep, never Read whole.", "", cols, sep] + rej) + "\n"
    return {"idx": idx, "rjx": rjx, "vetted": vetted, "rows": rows, "app": app, "app_names": app_names, "unv": unv,
            "rej": rej, "warn": warn}


def parse_index(text):
    out = {}
    for l in text.splitlines():
        if l.startswith("| ") and not l.startswith("| name |"):
            c = [x.strip() for x in re.split(r"(?<!\\)\|", l)[1:-1]]
            if len(c) >= 6:
                out.setdefault(c[0], []).append((c[1], c[3]))
    return out


def verify_name(text, name, expect_path):
    rr = parse_index(text).get(name, [])
    vet = [p for s, p in rr if s == "vetted"]
    ok = len(rr) == 1 and len(vet) == 1 and norm(vet[0]) == norm(expect_path) and os.path.isfile(vet[0])
    return {"name": name, "rows": len(rr), "vetted_rows": len(vet), "path": vet[0] if vet else None,
            "expected": expect_path.replace("\\", "/"), "path_exists": bool(vet) and os.path.isfile(vet[0]), "ok": ok}


def write(b):
    for fn, body in (("INDEX.md", b["idx"]), ("REJECTED.md", b["rjx"])):
        p = os.path.join(T.LIB, fn)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        os.replace(tmp, p)


FLAGS = {"--check": 0, "--gate": 1, "--after-install": 1, "--simulate-install": 1, "--allow-empty": 0}


def bad_flag(argv):
    """An error text for the first argument that is not a known flag, or a value flag with no value; else None."""
    i = 0
    while i < len(argv):
        if argv[i] not in FLAGS:
            return "unknown argument %r" % argv[i]
        if FLAGS[argv[i]] and (i + 1 >= len(argv) or argv[i + 1].startswith("--")):
            return "%s needs a value" % argv[i]
        i += 1 + FLAGS[argv[i]]
    return None


def has_skill_files(root, depth=4):
    """True when a SKILL.md sits anywhere in the first `depth` levels under root (a nested layout counts)."""
    for here, dirs, files in os.walk(root):
        if "SKILL.md" in files:
            return True
        if here[len(root):].count(os.sep) + 1 >= depth:
            dirs[:] = []
    return False


def main():
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)           # before anything is read or written
        return 0
    bad = bad_flag(sys.argv[1:])
    if bad is not None:
        print("ERROR: %s" % bad, file=sys.stderr)
        print("Usage: python -I -B build_index.py [--check] [--gate GATE.json] [--allow-empty]", file=sys.stderr)
        print("       python -I -B build_index.py --after-install <name>", file=sys.stderr)
        print("       python -I -B build_index.py --simulate-install <name>=<dir>", file=sys.stderr)
        print("(--help prints the full description)", file=sys.stderr)
        return 2
    gate_path = arg("--gate") or GATE
    sim = arg("--simulate-install")
    after = arg("--after-install")
    if sim:
        name, _, d = sim.partition("=")
        if not name or not os.path.isfile(os.path.join(d, "SKILL.md")):
            sys.exit("usage: --simulate-install <name>=<dir with SKILL.md>")
        b = build((name, d), gate_path)
        rr = parse_index(b["idx"]).get(name, [])
        expected = os.path.join(T.LIB, name, "SKILL.md")
        res = {"rows": len(rr), "status": rr[0][0] if len(rr) == 1 else None,
               "path": rr[0][1] if len(rr) == 1 else None, "expected": expected.replace("\\", "/"),
               "path_exists": "n/a (dry run: nothing installed)"}
        res["ok"] = len(rr) == 1 and norm(res["path"] or "") == norm(expected)
        line = [l for l in b["idx"].splitlines() if l.startswith("| %s |" % name)]
        print(json.dumps({"dry_run": True, "wrote": False, "row": line, "check": res,
                          "counts": {"vetted": sum('| vetted |' in x for x in b['rows']),
                                     "installed-unverified": sum('| installed-unverified |' in x for x in b['rows']),
                                     "app": len(b["app"]), "unvetted": len(b["unv"])},
                          "warnings": b["warn"]}, indent=1))
        return 0 if res["ok"] else 4
    b = build(None, gate_path)
    for w in b["warn"]:
        print("WARN", w, file=sys.stderr)
    if not b["rows"] and "--allow-empty" not in sys.argv and has_skill_files(T.SRC):
        print("ERROR: %s holds SKILL.md files but the build found 0 vetted rows; nothing was written. Check SKILLS_DIR and "
              "SKILL_LIBRARY, or pass --allow-empty if an empty INDEX is what you want." % T.SRC, file=sys.stderr)
        return 1
    if "--check" in sys.argv:
        print("rows vetted=%d installed-unverified=%d app=%d unvetted=%d rejected=%d bytes=%d/%d" % (sum('| vetted |' in x for x in b['rows']), sum('| installed-unverified |' in x for x in b['rows']), len(b["app"]), len(b["unv"]), len(b["rej"]), len(b["idx"]), len(b["rjx"])))
        return 0
    if not os.path.isdir(T.LIB):
        print("ERROR: create SKILL_LIBRARY directory before writing: %s" % T.LIB, file=sys.stderr)
        return 1
    write(b)
    print("wrote INDEX.md (vetted=%d installed-unverified=%d app=%d unvetted=%d) REJECTED.md (%d)" % (sum('| vetted |' in x for x in b['rows']), sum('| installed-unverified |' in x for x in b['rows']), len(b["app"]), len(b["unv"]), len(b["rej"])))
    if after:
        if after not in b["vetted"]:
            print(json.dumps({"after_install": after, "ok": False, "why": "no skill folder named %s in the live skills folder or the skill library (copies do not count)" % after}))
            return 4
        res = verify_name(open(os.path.join(T.LIB, "INDEX.md"), encoding="utf-8").read(), after, b["vetted"][after][0])
        res["after_install"] = after
        print(json.dumps(res))
        return 0 if res["ok"] else 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
