"""build_full_catalogue.py: write the skill catalogue as PART FILES, one entry per VETTED skill in
skill-library/INDEX.md, with its name, SKILL.md path, a size class (LARGE / refused-whole / MISSING, never an exact
byte count) and the full frontmatter description (+ when_to_use). Read-only on INDEX.md and every SKILL.md.

Output is split into part files small enough for ONE Read call each. Part files carry no timestamp (so their sha256
changes only when their content does), and a manifest.json records the INDEX sha256 and each part's sha256.

Read-tool limits measured in October 2026 (Claude Code desktop, Read tool):
  - a file over 256 KiB (262,144 bytes) is refused whole ("File content (303.2KB) exceeds maximum allowed size
    (256KB)");
  - a file under that but over 25,000 tokens is shown as a PARTIAL view with a "[Truncated: PARTIAL view ...]" banner
    (a 239,520 byte file = 95,631 tokens, about 2.5 bytes per token, showed lines 1-530 of 2389).
  So a SKILL.md over LARGE_BYTES = 50,000 bytes is flagged LARGE, and part files are capped at PART_MAX_BYTES = 45,000
  bytes (about 18k tokens even at 2.5 bytes per token). Why 50,000 and not 60,000: a 58,678 byte, 734 line skill
  marked `read: whole` would be about 23.5k tokens (2.5 B/token, measured on the catalogue), and the Read tool adds a
  line-number prefix of about 7 bytes per line (+5 kB there), so it could cross the 25,000-token cap. At 50,000 B a
  file is about 20k tokens, plus about 2k for prefixes: 3k (12%) of margin.
  Also: each catalogued SKILL.md's size and mtime go into manifest.json (skill_stats) so catalogue-check can see an
  edited skill, and keep_old survives a parallel rebuild that moved the file first.
  Catalogue churn: an entry carries no exact SKILL.md byte count (exact sizes stay in manifest.json), so a body edit
  leaves its entry unchanged; part headers carry no catalogue-wide total; the split keeps the previous build's part
  boundaries while every part fits (split_groups), and a fresh split fills parts to 90% of the cap; part_entries()
  parses a part back into entries for catalogue-check's delta; manifest.json records entry_format.

Environment: SKILL_LIBRARY (folder holding INDEX.md; default ~/skill-library), LIBRARIAN_ROOT (default: beside this file).
Usage: python -I -B build_full_catalogue.py [--index <INDEX.md>] [--catalogue-dir <dir>] [--part-max-bytes N] [--quiet]
Exit 0 ok, 2 bad input (no vetted rows / duplicate names / an unknown flag). Prints one JSON line with counts.
-h / --help prints this text and exits 0 before reading or writing anything.
Trap: a Bash-tool heredoc collapses backslashes; this file was written with the Write tool. Run with python -W error to
catch a lost backslash.
"""
import bisect, hashlib, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("LIBRARIAN_ROOT") or HERE  # folder holding catalogue/ (default: beside this file)
DEF_INDEX = os.path.join(os.environ.get("SKILL_LIBRARY") or os.path.join(os.path.expanduser("~"), "skill-library"),
                         "INDEX.md").replace("\\", "/")
DEF_CATDIR = os.path.join(ROOT, "catalogue").replace("\\", "/")
PART_MAX_BYTES = 45000
LARGE_BYTES = 50000
READ_REFUSE_BYTES = 262144
PART_PREFIX = "CATALOGUE-PART-"
ENTRY_FORMAT = 3  # refresh older catalogues whose stdlib fallback lost block descriptions
FILL_RATIO = 0.9  # a fresh split fills parts to 90% of the cap so later additions keep the boundaries


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def split_row(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.rstrip("\n"))]


def frontmatter(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        t = fh.read().lstrip("\ufeff")
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", t, re.S)
    if not m:
        return None, "no frontmatter"
    try:
        import yaml
        d = yaml.safe_load(m.group(1))
        return (d if isinstance(d, dict) else None), "ok"
    except Exception as e:  # no PyYAML or bad YAML: reuse the index's scalar/block metadata parser
        if HERE not in sys.path:
            sys.path.insert(0, HERE)  # python -I leaves the script's folder off sys.path
        from build_index import parse_frontmatter
        d = parse_frontmatter(t)
        if d.get("description"):
            return d, "stdlib fallback: %s" % type(e).__name__
        return None, "yaml error: %s" % type(e).__name__


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def size_note(nbytes):
    """The entry carries only the SKILL.md's size CLASS (missing / LARGE / LARGE and refused
    whole / normal), never its exact byte count, so a body edit that keeps the description, path and class leaves the
    entry, its part and the catalogue token unchanged. Exact sizes stay in manifest.json (skill_stats)."""
    if nbytes < 0:
        return " (SKILL.md MISSING at this path)"
    if nbytes > READ_REFUSE_BYTES:
        return " (LARGE - read in parts with offset/limit; Read refuses it whole: over 256 KB)"
    if nbytes > LARGE_BYTES:
        return " (LARGE - read in parts with offset/limit)"
    return ""


def skill_stat(path):
    """[size, mtime_ns] of a SKILL.md, or [-1, 0] when it is missing."""
    try:
        s = os.stat(path)
        return [s.st_size, s.st_mtime_ns]
    except OSError:
        return [-1, 0]


def stats_changed(man):
    """Names of catalogued skills whose SKILL.md size or mtime differs from the manifest (all, if none recorded)."""
    ss = (man or {}).get("skill_stats")
    if not ss:
        return ["(manifest has no skill_stats)"]
    return [n for n, v in ss.items() if skill_stat(v[0]) != [v[1], v[2]]]


def entries_from_index(index):
    rows = []
    with open(index, encoding="utf-8") as fh:
        for line in fh:
            c = split_row(line)
            if len(c) >= 8 and c[2] == "vetted":
                rows.append((c[1], c[4], c[3]))
    names = [r[0] for r in rows]
    if not rows or len(names) != len(set(names)):
        return None, {"why": "no vetted rows or duplicate names", "rows": len(rows)}
    notes, entries = {}, []
    for name, path, row_desc in sorted(rows):
        st = skill_stat(path)  # taken BEFORE reading, so an edit during the build shows as a change next check
        exists = os.path.isfile(path)
        d, note = (frontmatter(path) if exists else (None, "SKILL.md missing at row path"))
        s = None
        if d:
            s = d.get("description")
            s = str(s) if s is not None and not isinstance(s, str) else s
            w = d.get("when_to_use")
            if isinstance(w, str) and w.strip():
                s = (s or "") + " " + w.strip()
        if note != "ok":
            notes[name] = note
        s = " ".join(s.split()) if s else row_desc.replace("\\|", "|") + " [INDEX row text; no frontmatter description]"
        nbytes = os.path.getsize(path) if exists else -1
        entries.append({"name": name, "path": path, "bytes": nbytes, "stat": st,
                        "text": "- **%s** `%s`%s\n  %s" % (name, path, size_note(nbytes), s)})
    return entries, notes


def part_entries(text):
    """{name: entry text} parsed from one part file's text (catalogue-check hashes and diffs entries)."""
    out, name, buf = {}, None, []
    for ln in text.splitlines():
        if ln.startswith("- **") and "**" in ln[4:]:
            if name is not None:
                out[name] = "\n".join(buf).rstrip("\n")
            name, buf = ln[4:].split("**", 1)[0], [ln]
        elif name is not None:
            buf.append(ln)
    if name is not None:
        out[name] = "\n".join(buf).rstrip("\n")
    return out


def split_groups(entries, part_max, prev):
    """A STABLE split. Keep the previous build's part start names as boundaries while every part stays
    non-empty and under the cap, so one added skill changes only its own part. Otherwise split afresh, greedily, but
    fill each part only to FILL_RATIO of the cap, leaving room for later additions."""
    size = lambda e: len(e["text"].encode("utf-8")) + 1
    cap = part_max - 600  # a part header is about 400 bytes
    prev = prev or {}
    starts = sorted(v["first"] for v in prev.get("parts", {}).values())[1:]
    if prev.get("parts") and prev.get("entry_format") == ENTRY_FORMAT and prev.get("part_max_bytes") == part_max:
        groups = [[] for _ in range(len(starts) + 1)]
        for e in entries:
            groups[bisect.bisect_right(starts, e["name"])].append(e)
        if all(g and sum(map(size, g)) <= cap for g in groups):
            return groups
    groups, cur, cur_b = [], [], 0
    for e in entries:
        b = size(e)
        if cur and cur_b + b > cap * FILL_RATIO:
            groups.append(cur)
            cur, cur_b = [], 0
        cur.append(e)
        cur_b += b
    if cur:
        groups.append(cur)
    return groups


def replace_retry(src, dst, tries=20):
    """os.replace, retried on PermissionError: on Windows a reader holding the target (the librarian's Read, another
    check hashing it) refuses the replace for a moment. FileNotFoundError is raised at once."""
    for i in range(tries - 1):
        try:
            return os.replace(src, dst)
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    return os.replace(src, dst)


def write_atomic(p, text):
    tmp = "%s.tmp-%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    replace_retry(tmp, p)


def keep_old(catdir, fname, stamp):
    """Move an existing file aside as old/<name>.pre-rebuild-<UTC> (never delete)."""
    src = os.path.join(catdir, fname)
    if os.path.exists(src):
        od = os.path.join(catdir, "old")
        os.makedirs(od, exist_ok=True)
        try:  # pid in the name: two rebuilds in the same second never overwrite each other's kept copy
            replace_retry(src, os.path.join(od, "%s.pre-rebuild-%s-%d" % (fname, stamp, os.getpid())))
        except FileNotFoundError:
            pass  # a parallel rebuild (rollover overlap) moved it aside first; its copy is kept



def build(index=DEF_INDEX, catdir=DEF_CATDIR, part_max=PART_MAX_BYTES):
    entries, notes = entries_from_index(index)
    if entries is None:
        return None, notes
    os.makedirs(catdir, exist_ok=True)
    n_total = len(entries)
    try:
        with open(os.path.join(catdir, "manifest.json"), encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        prev = None
    groups = split_groups(entries, part_max, prev if isinstance(prev, dict) else None)
    n = len(groups)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    index_sha = sha256_file(index)
    parts = {}
    want = set()
    for i, g in enumerate(groups, 1):
        fname = "%s%d-of-%d.md" % (PART_PREFIX, i, n)
        want.add(fname)
        # no catalogue-wide total in a part header, or every added skill would change every part
        head = ("# Skill catalogue part %d of %d: %s .. %s (%d vetted skills in this part)\n"
                "# Generated by librarian/build_full_catalogue.py from skill-library/INDEX.md; do not edit by hand.\n"
                "# Entry: name, SKILL.md path, (LARGE - read in parts with offset/limit) when the SKILL.md is over "
                "%s bytes, full description.\n\n"
                % (i, n, g[0]["name"], g[-1]["name"], len(g), format(LARGE_BYTES, ",")))
        body = head + "\n".join(e["text"] for e in g) + "\n"
        p = os.path.join(catdir, fname)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    same = f.read() == body
            except FileNotFoundError:  # a parallel rebuild moved it aside between the check and the open
                same = True
            if not same:
                keep_old(catdir, fname, stamp)
        if not os.path.exists(p):
            write_atomic(p, body)
        parts[fname] = {"sha256": sha256_file(p), "bytes": os.path.getsize(p), "first": g[0]["name"],
                        "last": g[-1]["name"], "skills": len(g)}
    for f in os.listdir(catdir):  # parts of an older split (other n) move aside
        if f.startswith(PART_PREFIX) and f.endswith(".md") and f not in want:
            keep_old(catdir, f, stamp)
    man = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "index": index,
           "index_sha256": index_sha, "vetted": n_total, "parts": parts, "part_max_bytes": part_max,
           "entry_format": ENTRY_FORMAT,
           "large_bytes": LARGE_BYTES, "read_refuse_bytes": READ_REFUSE_BYTES,
           "large_skills": [e["name"] for e in entries if e["bytes"] > LARGE_BYTES],
           "missing_skill_md": [e["name"] for e in entries if e["bytes"] < 0], "frontmatter_notes": notes,
           "total_bytes": sum(v["bytes"] for v in parts.values()),
           "skill_stats": {e["name"]: [e["path"], e["stat"][0], e["stat"][1]] for e in entries}}
    write_atomic(os.path.join(catdir, "manifest.json"), json.dumps(man, indent=1))
    return man, None


FLAGS = {"--index": 1, "--catalogue-dir": 1, "--part-max-bytes": 1, "--quiet": 0}


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


def main():
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)           # before anything is read or written
        return 0
    bad = bad_flag(sys.argv[1:])
    if bad is None and arg("--part-max-bytes") is not None and not arg("--part-max-bytes").isdigit():
        bad = "--part-max-bytes needs a whole number of bytes"
    if bad is not None:
        print("ERROR: %s" % bad, file=sys.stderr)
        print("Usage: python -I -B build_full_catalogue.py [--index <INDEX.md>] [--catalogue-dir <dir>] "
              "[--part-max-bytes N] [--quiet]", file=sys.stderr)
        print("(--help prints the full description)", file=sys.stderr)
        return 2
    man, err = build(arg("--index", DEF_INDEX), arg("--catalogue-dir", DEF_CATDIR),
                     int(arg("--part-max-bytes", PART_MAX_BYTES)))
    if man is None:
        print(json.dumps({"ok": False, **err}))
        return 2
    if "--quiet" not in sys.argv:
        print(json.dumps({"ok": True, "vetted": man["vetted"], "parts": {k: v["bytes"] for k, v in man["parts"].items()},
                          "total_bytes": man["total_bytes"], "est_tokens_at_4B": round(man["total_bytes"] / 4),
                          "large": len(man["large_skills"]), "missing": man["missing_skill_md"],
                          "frontmatter_notes": man["frontmatter_notes"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
