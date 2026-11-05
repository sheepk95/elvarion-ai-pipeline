"""ask_librarian.py: any agent's side of the quick-librarian mailbox. Ask the long-lived Skill Librarian session which
skills fit a task; it answers from the full catalogue it already holds in context.

Python stdlib only.

Usage:
  python -I -B <LIBRARIAN_ROOT>/ask_librarian.py [--from LABEL] [--timeout S] [--mailbox DIR] "<brief>"
  python -I -B .../ask_librarian.py --brief-file PATH [--from LABEL]
  ... [--have NAME[,NAME...]] [--have-file PATH] "<brief>"
  python -I -B .../ask_librarian.py --status
  python -I -B .../ask_librarian.py --late ID [--late-wait S]   (late answers, below; run it in the background)
  python -I -B .../ask_librarian.py --finds [RID]   (skills.sh finder waiter; run it in the background, a chat only)
  ... --no-finder "<brief>"   (or env LIBRARIAN_NO_FINDER=1): never screen this ask for skills.sh candidates

--have / --have-file: skills the asker already holds, for example the skill list a handed-over chat
  inherited (a skills-in-use list beside its handover file). Each item is a skill name, a SKILL.md path, or a
  "- name | path | ..." line; blank and # lines are skipped. The librarian is told not to pick them, and any it still
  names are stripped from the answer here, with one NOTE line saying so. An unreadable --have-file never blocks the ask.
  The librarian is sent at most the first 80 names (librarian_inbox.HAVE_MAX), but every listed name (up to
  HAVE_LOCAL_MAX) is stripped here, on the librarian's late paths too (a skills.sh finder find keeps only the first 80:
  finder/skillsh_finder.py queue_job), and a NOTE says when the list sent was cut.
  python -I -B .../ask_librarian.py --stop            (dry run only: tells a DRYRUN librarian to stop)

Exit 0: the answer is printed (PICKS:/MAYBE:/ALSO GREP:/NOTE: lines, then the end marker); read the named SKILL.md files.
Exit 3: one line "LIBRARIAN_UNAVAILABLE (<reason>): grep ... INDEX.md ... as usual." -- do exactly that; never block.
  It falls back AT ONCE when the heartbeat is missing, says not loaded, or is older than 70 minutes, when an earlier
  ask timed out and the librarian has not run since, or when the librarian woke on requests over 180 s ago and has
  not answered; and after --timeout seconds (default 90, under the tools' 120 s kill) without a complete answer.
  If this command is killed or times out in your tool, grep INDEX.md as usual.
  Late answers: an ask that falls back while the librarian is live (this ask timed
  out, an earlier one did, or the librarian is busy answering) is still answered. The request stays in the mailbox (it
  is no longer withdrawn) and the fallback output names its id and a `--late ID` command. Run that command with
  run_in_background: it waits up to --late-wait seconds (default 3000) and prints the librarian's answer when it comes,
  which wakes your chat; then read the picks you have not already read. In a chat (CLAUDE_CODE_HOST_SESSION_ID set) a
  late answer not yet shown is also printed at the top of that chat's next ask, once, possibly to another agent of
  the same chat. When no librarian is live (no heartbeat, not loaded, heartbeat over 70 minutes old or unreadable)
  the ask falls back WITHOUT filing the request, so a new librarian never inherits dead asks.
  Asleep librarian: an account switch or app restart kills the watcher, and the Skill Librarian chat then gets no turn on its
  own. The ask counts the librarian as asleep when no watcher holds mailbox/watcher.lock AND either the heartbeat has
  been silent for 180 s, or this ask waited at least 90 s and nothing claimed its request. Then it
  adds a LIBRARIAN_ASLEEP line: send the Skill Librarian chat one wake message with your SendMessage tool, and carry
  on with the grep. The line addresses the librarian chat by the session id its own session commands record in
  heartbeat.json (an id reaches a chat that is not running, e.g. after a PC restart), else by the
  name "Skill Librarian". When the heartbeat rule fires at the start and the librarian is otherwise live, the ask
  files the request, falls back at once (no 90 s wait) and prints the --late command before the wake line; after a
  wait, the wake line also follows the --late command. With no live librarian (heartbeat over 70 minutes old, not
  loaded or unreadable) it files nothing and prints no --late command, only the wake line. A turn over 180 s with no
  watcher armed can also look asleep (0 of 70 measured turns ran that long); a needless wake costs one cheap
  librarian turn.
Exit 2: empty brief or bad arguments.
"""
import argparse, glob, os, re, secrets, sys, threading, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)  # python -I leaves the script's folder off sys.path
import librarian_inbox as LI  # noqa: E402

MAX_BRIEF = 6000
# A --have-file over 80 names was cut silently, so held skills past
# the 80th came back as PICKS. The request still carries at most LI.HAVE_MAX names (the librarian's prompt stays
# small); the local list keeps up to HAVE_LOCAL_MAX, so drop_held strips every listed skill.
HAVE_LOCAL_MAX = 2000
DEFAULT_TIMEOUT = 90.0  # under the Bash/PowerShell tools' 120 s kill (dry-run max 35.7 s for a burst of 8)
FALLBACK = ("LIBRARIAN_UNAVAILABLE (%s): grep " + LI.DEF_INDEX.replace("%", "%%") + " "
            "(case-insensitive, 2-4 task words) as usual.")
LATE_HINT = ("\nLIBRARIAN_LATE: request %s stays queued and will still be answered. Do your INDEX grep now, and also "
             "run this with run_in_background so the late answer wakes you; then read any picks you have not read: "
             "python -I -B %s --late %s%s")
LATE_WAIT = 3000.0  # 50 min; a background command has no 2-minute kill
# An account
# switch restarts the app, the librarian's watcher dies and its chat gets no turn until a message reaches it. The
# asking chat is awake, so it carries the wake.
# SendMessage sends a subagent's message under its parent chat's address, so subagents and workflow
# agents send the wake themselves; a Desktop session reports nothing back, so send once and never wait for a reply.
# the address (%(to)s, filled by wake_hint) is the librarian chat's recorded session id when one is
# recorded, else its name. Measured after a PC restart: the bare name did not
# resolve (SendMessage resolves names only for running chats), while the session id was delivered and started a turn.
WAKE_HINT = ("\nLIBRARIAN_ASLEEP (%(reason)s): an account switch or app restart stops the librarian's watcher, and the "
             "Skill Librarian chat gets no turn until a message reaches it. Wake it now: send ONE message with your "
             "SendMessage tool (load it with ToolSearch \"select:SendMessage\" if it is not loaded) to %(to)s, "
             "text \"wake: librarian requests waiting\". Subagents and workflow agents send it too (it "
             "goes to the librarian, not to the desk chat or the owner). Do not wait for a reply; with no SendMessage tool, or "
             "if the send is refused, skip it. Either way, carry on with the grep above.")
WAKE_TO_ID = ("\"%s\" (the Skill Librarian chat's session id: send to the id, not the chat name, because the id "
              "reaches that chat even when it is not running, e.g. after a PC restart)")
WAKE_TO_NAME = "\"Skill Librarian\""
HOST_RE = LI.HOST_RE  # one pattern for the asking chat's id and the librarian's recorded id
RID_RE = LI.RID_RE  # one pattern for the ids make_id() files and the ids librarian_inbox.py accepts
# heartbeat_problem() reasons that still mean a LIVE librarian (it will answer later), so the request is
# filed for a late answer. Every other reason (no heartbeat, not loaded, stale, unreadable) files nothing.
LIVE_PROBLEMS = ("an ask timed out", "librarian woke on requests")
# Optional skills.sh finder (finder/hook.py, not shipped here): after an ask, a lazy,
# time-boxed screen in finder/hook.py. It prints at most ONE extra line after the unchanged output; exit codes never
# change; any failure there (missing file, syntax error, slow disk) only skips the finder.
FINDER_DIR = os.path.join(HERE, "finder")
FINDER_JOIN_S = 2.0


def _finder_hook():
    import importlib.util
    spec = importlib.util.spec_from_file_location("librarian_finder_hook", os.path.join(FINDER_DIR, "hook.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def finder_hint(mb, brief, frm, info, have, no_finder=False):
    """One hint line when the finder queued a job for this ask, else None. Never raises, never waits over 2 s."""
    if no_finder or os.environ.get("LIBRARIAN_NO_FINDER") == "1":
        return None
    if os.path.normcase(os.path.abspath(mb)) != os.path.normcase(os.path.abspath(LI.DEF_MAILBOX)):
        return None  # DRYRUN and test mailboxes are never screened
    box = []

    def run():
        try:
            line = _finder_hook().screen(brief, frm, (info or {}).get("id"), host_session(), have,
                                         os.path.abspath(__file__).replace("\\", "/"))
            if isinstance(line, str) and line and "\n" not in line and "\r" not in line:
                box.append(line[:600])
        except BaseException:  # noqa: B036 - the finder must never break an ask
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(FINDER_JOIN_S)
    return box[0] if box else None


def finder_finds(mb, rid):
    """--finds [RID]: the opt-in waiter (polls finder/result/RID.json up to 3,600 s), or this chat's inbox."""
    if rid and not RID_RE.match(rid):
        print("ask_librarian: --finds needs a request id like 20260101T000000000000Z-1234-0123abcd")
        return 2
    try:
        code, text = _finder_hook().finds(mb, rid, host_session(), take_late, find_answer, drop_held, late_block)
    except BaseException as e:  # noqa: B036
        code, text = 3, "SKILLS.SH FINDER: unavailable (%s); any find shows at your next ask" % type(e).__name__
    print(text)
    return code


def have_name(item):
    """A skill name from a name, a SKILL.md path or a '- name | path | ...' line; '' when nothing usable."""
    s = str(item).strip()
    if not s or s.startswith("#"):
        return ""
    if s.startswith("- "):
        s = s[2:].strip()
    if "|" in s:
        s = s.split("|")[0].strip()
    s = s.strip("`'\"").replace("\\", "/").rstrip("/")
    if s.lower().endswith("/skill.md"):
        s = s[:-len("/skill.md")]
    if "/" in s:
        s = s.rsplit("/", 1)[1]
    return s if LI.HAVE_NAME_RE.match(s) else ""


def parse_have(values=(), file_text=""):
    """Held skill names from --have values (comma/semicolon separated) and --have-file lines; deduped, capped at
    HAVE_LOCAL_MAX (submit() sends only the first LI.HAVE_MAX to the librarian)."""
    items = []
    for v in values or ():
        items.extend(str(v).replace(";", ",").split(","))
    items.extend((file_text or "").splitlines())
    out, seen = [], set()
    for it in items:
        n = have_name(it)
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:HAVE_LOCAL_MAX]


def drop_held(text, have):
    """Backstop for picking rule 9: remove PICKS/MAYBE lines naming a held skill. Returns (text, dropped names)."""
    held = {h.lower() for h in have or ()}
    if not held:
        return text, []
    lines = text.rstrip().splitlines()
    marker = lines.pop() if lines and lines[-1].strip() == LI.END_MARKER else None
    kept, dropped, section = [], [], None
    for ln in lines:
        st = ln.strip()
        if st.startswith("PICKS:") or st.startswith("MAYBE:"):
            section = st[:5]
        elif st.startswith("- ") and section:
            f = [x.strip() for x in st[2:].split(" | ")]
            names = {have_name(f[0]).lower()} | ({have_name(f[1]).lower()} if len(f) > 1 else set())
            if names & held:
                dropped.append(f[0])
                continue
        else:
            section = None
        kept.append(ln)
    if not dropped:
        return text, []
    out = []
    for i, ln in enumerate(kept):  # a header left with no items: PICKS becomes "PICKS: none", MAYBE goes
        st = ln.strip()
        empty = st in ("PICKS:", "MAYBE:") and not (i + 1 < len(kept) and kept[i + 1].strip().startswith("- "))
        if empty and st == "MAYBE:":
            continue
        out.append("PICKS: none" if empty else ln)
    out.append("NOTE: ask_librarian.py left out %d skill(s) you already hold: %s" % (len(dropped), ", ".join(dropped)))
    if marker is not None:
        out.append(marker)
    return "\n".join(out), dropped


def make_id():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return "%s-%d-%s" % (ts, os.getpid(), secrets.token_hex(4))


def cap_brief(brief):
    if len(brief) <= MAX_BRIEF:
        return brief, False
    return (brief[:MAX_BRIEF] + "\n[brief truncated by ask_librarian.py: %d of %d chars kept]" % (MAX_BRIEF, len(brief)),
            True)


def wake_hint(mb, reason):
    """the LIBRARIAN_ASLEEP line, addressed to the librarian chat's recorded session id
    (LI.librarian_session: its last session command's CLAUDE_CODE_HOST_SESSION_ID, checked with HOST_RE), else to the
    name "Skill Librarian"."""
    sid = LI.librarian_session(mb)
    return WAKE_HINT % {"reason": reason, "to": WAKE_TO_ID % sid if sid else WAKE_TO_NAME}


def host_session():
    """The asking chat's desktop session id (local_<uuid>), or None. Subagents and workflow agents share their chat's."""
    h = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID", "")
    return h if HOST_RE.match(h) else None


def submit(mb, brief, frm="unknown", kind="ask", timeout=None, have=None):
    LI.ensure(mb)
    rid = make_id()
    brief, trunc = cap_brief(brief)
    now = time.time()
    d = {"id": rid, "kind": kind, "from": frm, "created_utc": LI.utc(now), "created_epoch": now, "brief": brief,
         "truncated": trunc, "requester_pid": os.getpid(), "timeout_s": timeout, "reply_to": host_session()}
    if have:
        d["have"] = list(have)[:LI.HAVE_MAX]
    p = os.path.join(mb, "requests", rid + ".json")
    LI.write_json_atomic(p, d)  # tmp file + os.replace: the watcher never sees half a request
    return rid, trunc


def ends_with_marker(text):
    lines = text.rstrip().splitlines()
    return bool(lines) and lines[-1].strip() == LI.END_MARKER


def try_collect(mb, rid):
    """Return the answer text if answers/<id>.md is complete (ends with the end marker), and move it to done/."""
    p = os.path.join(mb, "answers", rid + ".md")
    try:
        with open(p, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    if not ends_with_marker(text):
        return None  # still being written, or malformed: never return a partial answer
    try:
        os.replace(p, os.path.join(mb, "done", rid + ".md"))
    except OSError:
        pass
    return text


def wait_answer(mb, rid, timeout, poll=0.5):
    t0 = time.time()
    while True:
        text = try_collect(mb, rid)
        if text is not None:
            return text
        if time.time() - t0 >= timeout:
            return None
        time.sleep(poll)


def late_path(mb, rid):
    return os.path.join(mb, "late", rid + ".json")


def mark_late(mb, rid, frm, reason, have=None, required=False):
    """Late answers: the requester stopped waiting, but the request stays queued and is answered."""
    now = time.time()
    try:
        os.makedirs(os.path.join(mb, "late"), exist_ok=True)
        LI.write_json_atomic(late_path(mb, rid), {"id": rid, "from": frm, "reply_to": host_session(),
                                                  "reason": reason, "utc": LI.utc(now), "epoch": now,
                                                  "have": list(have or [])[:HAVE_LOCAL_MAX]})
    except OSError:
        if required:
            raise


def find_answer(mb, rid):
    """A complete answer for rid wherever it is (answers/, or done/ after a collect or housekeeping), else None."""
    text = try_collect(mb, rid)  # a finished answer in answers/ moves to done/<id>.md
    if text is not None:
        return text  # complete even when the move to done/ failed (a reader held the file)
    for p in (os.path.join(mb, "done", rid + ".md"), os.path.join(mb, "done", rid + ".uncollected.md")):
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        if ends_with_marker(text):
            return text
    return None


def shown_path(mb, rid):
    return os.path.join(mb, "late", "seen", rid + ".shown")


def take_late(mb, rid):
    """Show-once: True for exactly one caller. the gate is an exclusive create (O_EXCL) of
    late/seen/<id>.shown, because a rename is not exclusive on NTFS (see LI.take_claim: 2-3 of 4 concurrent renames of
    one file succeeded). The move of late/<id>.json to late/seen/ after it is bookkeeping only."""
    os.makedirs(os.path.join(mb, "late", "seen"), exist_ok=True)
    try:
        fd = os.open(shown_path(mb, rid), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    identity = os.fstat(fd)
    try:
        data = ("shown %s pid %d\n" % (LI.utc(), os.getpid())).encode("utf-8")
        if os.write(fd, data) != len(data):
            raise OSError("short write of acknowledgement marker")
    except BaseException as error:
        try:
            os.close(fd)
        except OSError:
            pass
        _remove_failed_marker(mb, rid, identity, error)
        raise
    try:
        os.close(fd)
    except OSError as error:
        _remove_failed_marker(mb, rid, identity, error)
        raise
    LI.move_retry(late_path(mb, rid), os.path.join(mb, "late", "seen", rid + ".json"))
    return True


def _remove_failed_marker(mb, rid, identity, original):
    """Only remove the marker created by this call, while its delivery lock is held."""
    path = shown_path(mb, rid)
    try:
        current = os.stat(path)
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise OSError("acknowledgement marker was replaced")
        os.unlink(path)
    except OSError as cleanup:
        raise RuntimeError("acknowledgement failed (%s); could not remove incomplete marker %s: %s" %
                           (original, path, cleanup)) from cleanup


def late_block(rid, d, text, own=True):
    """own=False: shown on a later ask, which may be another agent of the same chat."""
    note = "" if own else ("; the answer to an EARLIER ask of this chat, maybe by another agent: use it only if it "
                           "fits your task")
    return "=== LIBRARIAN LATE ANSWER id=%s from=%s (asked %s%s) ===\n%s" % (
        rid, LI.one_line(d.get("from", "?")), d.get("utc", "?"), note, text.rstrip())


def unread_late(mb, me, with_ids=False):
    """Preview ready late answers. Reading alone does not acknowledge delivery."""
    if not me:
        return []
    out = []
    for p in sorted(glob.glob(os.path.join(mb, "late", "*.json"))):
        d = LI.read_json(p) or {}
        rid = os.path.basename(p)[:-5]
        if d.get("reply_to") != me:
            continue
        text = find_answer(mb, rid)
        if text is not None and not os.path.exists(shown_path(mb, rid)):
            text, _ = drop_held(text, d.get("have"))  # merge: held skills are stripped on the late path too
            block = late_block(rid, d, text, own=False)
            out.append((rid, block) if with_ids else block)
    return out


def delivery_lock(mb, rid, timeout=0):
    os.makedirs(os.path.join(mb, "late", "seen"), exist_ok=True)
    lock = LI.OsLock(os.path.join(mb, "late", "seen", rid + ".delivery.lock"))
    return lock if lock.acquire(timeout=timeout) else None


def output_late(mb, text, ids):
    """Caller holds delivery lock; acknowledge only after stdout accepts and flushes the answer."""
    print(text)
    sys.stdout.flush()
    for rid in ids:
        if not take_late(mb, rid):
            raise RuntimeError("late answer acknowledgement already exists: " + rid)


def deliver_unread(mb, me, own_id=None):
    if not me:
        return
    for p in sorted(glob.glob(os.path.join(mb, "late", "*.json"))):
        rid = os.path.basename(p)[:-5]
        if rid == own_id:
            continue
        lock = delivery_lock(mb, rid)
        if lock is None:
            continue
        try:
            d = LI.read_json(p) or {}
            if d.get("reply_to") != me or os.path.exists(shown_path(mb, rid)):
                continue
            answer = find_answer(mb, rid)
            if answer is not None:
                answer, _ = drop_held(answer, d.get("have"))
                output_late(mb, late_block(rid, d, answer, own=False) + "\n", [rid])
        finally:
            lock.release()


def wait_late(mb, rid, wait, poll=2.0, deliver=False):
    """Preview a late answer; deliver=True prints, flushes and acknowledges under an OS lock."""
    t0 = time.time()
    seen = os.path.join(mb, "late", "seen", rid + ".json")
    while True:
        lock = delivery_lock(mb, rid)
        if lock is None:
            if time.time() - t0 >= wait:
                return 3, "LIBRARIAN_LATE: answer %s is being delivered; retry later." % rid
            time.sleep(min(poll, max(0.0, wait - (time.time() - t0))))
            continue
        try:
            d = LI.read_json(late_path(mb, rid))
            if d is None or os.path.exists(shown_path(mb, rid)):
                if os.path.exists(shown_path(mb, rid)) or os.path.isfile(seen):
                    return 0, "LIBRARIAN_LATE: answer %s was already shown (on another ask from this chat)." % rid
                return 2, "LIBRARIAN_LATE: no late request %s in %s" % (rid, mb)
            text = find_answer(mb, rid)
            if text is not None:
                text, _ = drop_held(text, d.get("have"))
                text = late_block(rid, d, text)
                if deliver:
                    output_late(mb, text, [rid])
                    return 0, None
                return 0, text
        finally:
            lock.release()
        if time.time() - t0 >= wait:
            then = ("will be shown at the top of this chat's next ask" if d.get("reply_to") else
                    "run this --late command again later to see it")  # no chat id, no next-ask path
            return 3, "LIBRARIAN_LATE: no answer to %s after %ds; it stays queued and %s." % (rid, wait, then)
        time.sleep(poll)


def abandon(mb, rid):
    """Legacy API: withdraw an unclaimed request. Current ask() instead preserves it for a late answer."""
    lock = LI.OsLock(os.path.join(mb, "claimed", rid + ".lock"))
    if not lock.acquire():
        return  # a claimer or recovery attempt is handling the request
    try:
        if not LI.take_claim(mb, rid, "abandoned-by-requester"):
            return  # the librarian claimed it first; its late answer is handled by housekeeping
        if LI.move_retry(os.path.join(mb, "requests", rid + ".json"), os.path.join(mb, "done", rid + ".timeout.json")):
            LI.move_retry(os.path.join(mb, "claimed", rid + ".claim"), os.path.join(mb, "done", rid + ".timeout.claim"))
        # A failed request move keeps the abandonment marker for claim recovery.
    finally:
        lock.release()


def ask(mb, brief, frm="unknown", timeout=DEFAULT_TIMEOUT, poll=0.5, have=None):
    """Returns (exit_code, text, info). info: id, truncated, latency_s, reason, dropped (held skills stripped)."""
    if not brief or not brief.strip():
        return 2, "ask_librarian: refused an empty brief (say what the task is).", {"reason": "empty brief"}
    code, text, info = _ask(mb, brief, frm, timeout, poll, have)
    late = unread_late(mb, host_session())  # late answers to this chat's earlier asks, shown once, first
    if late:
        text = "\n\n".join(late + [text])
    return code, text, info


def _ask(mb, brief, frm, timeout, poll, have=None):
    prob = LI.heartbeat_problem(mb)
    asleep = LI.librarian_asleep(mb)
    if prob and not prob.startswith(LIVE_PROBLEMS):
        # no live librarian (never started, retired, gone over 70 min, unreadable heartbeat). Nothing
        # would answer soon, so file nothing: a librarian started later must not inherit a backlog of dead asks.
        return 3, FALLBACK % prob + (wake_hint(mb, asleep) if asleep else ""), {"reason": prob, "asleep": bool(asleep)}
    t0 = time.time()
    rid, trunc = submit(mb, brief, frm, "ask", timeout, have)
    if not prob and asleep:
        prob = "librarian asleep"  # nobody would answer within the wait: file it, fall back now, ask for the wake
    waited = False
    if not prob:
        waited = True
        text = wait_answer(mb, rid, timeout, poll)
        if text is None:
            text = find_answer(mb, rid)  # last look: an answer that landed as the wait ended is returned, not late
        if text is not None:
            text, dropped = drop_held(text, have)
            note = "\n[ask_librarian.py: your brief was truncated to %d chars]" % MAX_BRIEF if trunc else ""
            return 0, text.rstrip() + note, {"id": rid, "truncated": trunc, "latency_s": time.time() - t0,
                                             "dropped": dropped}
        prob = "no answer in %ds" % timeout
        LI.mark_timeout(mb, rid)  # later asks fall back at once (still filed for a late answer)
    # Live but busy, or this ask timed out: fall back now, but keep the request queued for a late answer.
    mark_late(mb, rid, frm, prob, have)
    me = os.path.abspath(__file__).replace("\\", "/")
    mbarg = "" if os.path.normcase(os.path.abspath(mb)) == os.path.normcase(os.path.abspath(LI.DEF_MAILBOX)) else \
        ' --mailbox "%s"' % mb.replace("\\", "/")
    asleep = asleep or LI.librarian_asleep(mb)  # look again: it may have gone quiet during the wait
    if not asleep and waited and time.time() - t0 >= LI.UNPICKED_S and LI.request_unpicked(mb, rid):
        # the switch can land just after the watcher's last heartbeat (an earlier incident: the first two asks
        # looked again at 89 s and 178 s). A full wait with this request never claimed and no watcher
        # armed means nobody is answering, whatever the heartbeat's age.
        if LI.librarian_asleep(mb, quiet_s=0.0):
            asleep = "no mailbox watcher is armed and nothing claimed this request in %d s" % (time.time() - t0)
    return 3, FALLBACK % prob + LATE_HINT % (rid, me, rid, mbarg) + (wake_hint(mb, asleep) if asleep else ""), \
        {"id": rid, "truncated": trunc, "reason": prob, "late": True, "asleep": bool(asleep)}


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brief", nargs="?")
    ap.add_argument("--brief-file")
    ap.add_argument("--from", dest="frm", default=os.environ.get("CLAUDE_SESSION_TITLE", "unknown"))
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    ap.add_argument("--mailbox", default=LI.DEF_MAILBOX)
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--late", metavar="ID", help="wait for the late answer to an earlier ask (run it in the background)")
    ap.add_argument("--late-wait", type=float, default=LATE_WAIT)
    ap.add_argument("--have", action="append", default=[], help="skills you already hold (names or SKILL.md paths)")
    ap.add_argument("--have-file", help="file listing skills you already hold, one per line")
    ap.add_argument("--no-finder", action="store_true", help="never screen this ask for skills.sh candidates")
    ap.add_argument("--finds", nargs="?", const="", default=None, metavar="RID",
                    help="wait for the skills.sh finder result of an ask (run it in the background)")
    return ap


def main(argv=None):
    LI.utf8_stdio()  # a brief or answer with e.g. U+2192 must not crash the print under a pipe
    a = build_parser().parse_args(argv)
    mb = a.mailbox.replace("\\", "/")
    if a.status:
        print("\n".join(LI.status_lines(mb)))
        return 0
    if a.late:
        if not RID_RE.match(a.late):
            print("ask_librarian: --late needs a request id like 20260101T000000000000Z-1234-0123abcd")
            return 2
        code, text = wait_late(mb, a.late, a.late_wait, deliver=True)
        if text is not None:
            print(text)
        return code
    if a.finds is not None:
        return finder_finds(mb, a.finds)
    if a.stop:
        rid, _ = submit(mb, "STOP", a.frm, "stop")
        print("STOP SENT %s" % rid)
        return 0
    brief = a.brief
    if a.brief_file:
        try:
            with open(a.brief_file, encoding="utf-8") as f:
                brief = f.read()
        except OSError as e:
            print("ask_librarian: cannot read --brief-file: %s" % e)
            return 2
    have_text, have_err = "", ""
    if a.have_file:
        try:
            with open(a.have_file, encoding="utf-8") as f:
                have_text = f.read()
        except OSError as e:
            have_err = "\nNOTE: ask_librarian.py could not read --have-file (%s); only --have names were left out" % e
    have = parse_have(a.have, have_text)
    if len(have) > LI.HAVE_MAX:
        have_err += ("\nNOTE: you listed %d held skills; the librarian was sent the first %d, and all %d are stripped "
                     "from this answer here" % (len(have), LI.HAVE_MAX, len(have)))
    if not brief or not brief.strip():
        code, text, info = 2, "ask_librarian: refused an empty brief (say what the task is).", {"reason": "empty brief"}
    else:
        code, text, info = _ask(mb, brief, a.frm, a.timeout, 0.5, have=have)
    own_id = info.get("id") if code == 0 else None
    me = host_session()
    if own_id:
        lock = delivery_lock(mb, own_id, timeout=30)
        if lock is None:
            print("LIBRARIAN_LATE: answer %s is being delivered; retry later." % own_id)
            return 3
        try:
            mark_late(mb, own_id, a.frm, "answer awaiting output", have, required=True)
            deliver_unread(mb, me, own_id)
            if os.path.exists(shown_path(mb, own_id)):
                print("LIBRARIAN_LATE: answer %s was already shown." % own_id)
            else:
                output_late(mb, text + have_err, [own_id])
        finally:
            lock.release()
    else:
        if code != 2:
            deliver_unread(mb, me)
        print(text + (have_err if code == 0 else ""))
    if code != 2:
        hint = finder_hint(mb, brief or "", a.frm, info, have, a.no_finder)
        if hint:
            sys.stdout.flush()
            print(hint)
    return code


if __name__ == "__main__":
    sys.exit(main())
