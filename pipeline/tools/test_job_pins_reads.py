"""test_job_pins_reads.py: offline tests for the `Reads:` pins of job_pins.py. Standard
library only.

  python -I -B <PIPELINE_ROOT>/tools/test_job_pins_reads.py [--log <file>] [--target <a job_pins.py copy>]

Stage 1 runs every test against job_pins.py through its real command line, in a scratch pipeline root. Every expected
value comes from the fixture (hashlib over the bytes this file wrote, literal lines), never from the tool. Stage 2 writes
each PLANT (one exact-anchor mutation of a job_pins.py copy, anchor found exactly once) and runs the test it names: that
test must go red. Tests marked control are the no-Reads cases a change must leave alone; a plant that over-applies the
change is what reddens them. --target runs stage 1 only against that file (for example a copy from before the change, to show the
change undone going red). The scratch folder is this run's own and is deleted at the end; nothing else is deleted.
Exit 0 = stage 1 green and every plant red; 1 otherwise.
"""
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, 'job_pins.py')
SC_TEXT = b'# SCORE CARD test\n'
WORK_TEXT = b'contract v1\n'
READ_A = b'other lane contract A\n'
READ_B = b'other lane contract B\n'


def sha12(data):
    return hashlib.sha256(data).hexdigest()[:12]


class Bad(Exception):
    pass


def need(ok, why):
    if not ok:
        raise Bad(why)


class Pipe:
    """One scratch pipeline root with a document job d-1, its records in step, and two other lanes' documents."""

    def __init__(self, root, target):
        self.root, self.target = root, target
        os.makedirs(os.path.join(root, 'tools'))
        shutil.copyfile(target, os.path.join(root, 'tools', 'job_pins.py'))
        self.sc = self.put('score/SCORE-CARD.md', SC_TEXT)
        self.work = self.put('lanes/d/contracts/W.md', WORK_TEXT)
        self.a = self.put('lanes/x/contracts/A doc.md', READ_A)
        self.b = self.put('lanes/y/contracts/B.md', READ_B)
        self.put('lanes/d/LANE.md', b'# LANE: Doc lane (test)\n')

    def put(self, rel, data):
        p = os.path.join(self.root, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data)
        return p

    def card(self, extra='', crlf=False, job='d-1'):
        """Writes JOB.md and the records whose pins match it. extra is the card text after the Scorecard line."""
        text = ('# JOB %s (document job)\nSystems: weather\nWork: file | %s\nAttempt log: jobs\\%s\\ATTEMPTS.jsonl\n'
                'Scorecard: `%s` v1\n%s' % (job, self.work, job, self.sc, extra))
        data = (text.replace('\n', '\r\n') if crlf else text).encode('utf-8')
        self.put('jobs/%s/JOB.md' % job, data)
        self.line = 'pins: card %s | scorecard %s | work %s' % (sha12(data), sha12(SC_TEXT), sha12(WORK_TEXT))
        for rec in ('REVIEW-1', 'TEST-1', 'GATE-1'):
            self.put('jobs/%s/%s.md' % (job, rec), ('# %s\n%s\nGATE PASS avg 7.0\n' % (rec, self.line)).encode('utf-8'))
        return self.line

    def run(self, *args):
        p = subprocess.run([sys.executable, '-I', '-B', os.path.join(self.root, 'tools', 'job_pins.py')] + list(args),
                           cwd=os.path.dirname(self.root), capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=120)
        return p.returncode, p.stdout.replace('\r\n', '\n'), p.stderr


def rows(pipe, a=None, b=None):
    a = a or sha12(READ_A)
    b = b or sha12(READ_B)
    return '\nReads:\n- %s | %s\n- %s | %s\n\n' % (pipe.a, a, pipe.b, b)


def t_print_no_reads(p):
    line = p.card()
    rc, out, err = p.run('d-1')
    need(rc == 0 and out == '%s\nnext: put this line in your item or record (top 5 lines); the receiver runs: job_pins.py '
         'd-1\n' % line, 'output changed: %r' % out)


def t_card_only_no_reads(p):
    p.card()
    rc, out, err = p.run('d-1', '--card-only')
    want = ('pins: card %s | scorecard %s | work none\nnext: put this line in the JOB item; the builder sends the full '
            'pins line (job_pins.py d-1) in its first REVIEW-ASK\n' % (p.line.split()[2], sha12(SC_TEXT)))
    need(rc == 0 and out == want, 'output changed: %r' % out)


def t_check_no_reads(p):
    line = p.card()
    rc, out, err = p.run('d-1', '--check')
    need(rc == 0 and out == ('pins OK: %s\nnext: send DONE / READY with this pins line. Matching pins prove only that '
                             'the records name the same card, scorecard and work; they are not a gate PASS or the '
                             "owner's GO: the integrator checks both before any merge\n") % line,
         'output changed: %r' % out)


def t_reads_none_is_no_reads(p):
    line = p.card('\nReads: none, because this job reads no other lane\n\n## Task\nbody\n')
    rc, out, err = p.run('d-1')
    need(rc == 0 and 'reads:' not in out and out.startswith(line + '\n'), out)
    rc, out, err = p.run('d-1', '--check')
    need(rc == 0 and 'reads' not in out.lower(), out)


def t_print_shows_pins(p):
    line = p.card(rows(p))
    rc, out, err = p.run('d-1')
    ls = out.splitlines()
    need(rc == 0 and ls[0] == line, 'line 1 must stay the pins line (a tool that reads the pins reads line 1): %r' % ls[:1])
    need(ls[1] == 'reads: %s "%s"' % (sha12(READ_A), p.a) and ls[2] == 'reads: %s "%s"' % (sha12(READ_B), p.b), out)
    need(ls[3].startswith('next: ') and len(ls) == 4, out)


def t_card_only_shows_pins(p):
    p.card(rows(p))
    rc, out, err = p.run('d-1', '--card-only')
    need(rc == 0 and 'reads: %s "%s"' % (sha12(READ_B), p.b) in out and out.splitlines()[0].endswith('work none'), out)


def t_check_clean(p):
    line = p.card(rows(p))
    rc, out, err = p.run('d-1', '--check')
    need(rc == 0 and 'pins OK: ' + line in out and 'reads OK: 2 pinned' in out, out)


def t_check_moved_first_row(p):
    p.card(rows(p))
    p.put('lanes/x/contracts/A doc.md', b'moved\n')
    rc, out, err = p.run('d-1', '--check')
    need(rc == 1 and 'MISMATCH reads "%s"' % p.a in out and sha12(READ_A) in out and sha12(b'moved\n') in out, out)
    need(p.b not in out and 'pins OK' not in out, out)
    need(out.splitlines()[-1].startswith('next: ') and 'Reads: pin moves' in out, out)


def t_check_moved_second_row(p):
    p.card(rows(p))
    p.put('lanes/y/contracts/B.md', b'moved\n')
    rc, out, err = p.run('d-1', '--check')
    need(rc == 1 and 'MISMATCH reads "%s"' % p.b in out, out)


def t_print_flags_moved(p):
    line = p.card(rows(p))
    p.put('lanes/x/contracts/A doc.md', b'moved\n')
    rc, out, err = p.run('d-1')
    need(rc == 0 and out.splitlines()[0] == line, out)
    need('reads: %s "%s" | DIFFERS: file now %s' % (sha12(READ_A), p.a, sha12(b'moved\n')) in out, out)
    need('DIFFERS' not in [x for x in out.splitlines() if p.b in x][0], out)


def t_missing_file(p):
    p.card(rows(p))
    os.remove(p.b)
    for args in (('d-1',), ('d-1', '--check'), ('d-1', '--card-only')):
        rc, out, err = p.run(*args)
        need(rc == 2 and 'B.md' in out and 'pins:' not in out.split('ERROR')[0], '%s: %s %s' % (args, rc, out))


def t_bad_rows(p):
    for bad in ('- %s | %s' % (p.a, sha12(READ_A)[:11]), '- %s | %sa' % (p.a, sha12(READ_A)),
                '- %s | %s (the warning table)' % (p.a, sha12(READ_A)), '- %s' % p.a):
        p.card('\nReads:\n%s\n\n' % bad)
        for args in (('d-1',), ('d-1', '--check')):
            rc, out, err = p.run(*args)
            need(rc == 2 and 'does not parse' in out, '%r %s: %s %s' % (bad, args, rc, out))


def t_empty_section(p):
    p.card('\n## Reads\n\n## Task\nbody\n')
    rc, out, err = p.run('d-1', '--check')
    need(rc == 2 and 'no rows' in out, '%s %s' % (rc, out))


def t_row_forms(p):
    """Heading form, blank line after the head, backticks, a relative path, `sha12` word, upper-case hex, CRLF card."""
    p.card('\n## Reads:\n\n- `lanes/x/contracts/A doc.md` | sha12 %s\n* lanes\\y\\contracts\\B.md %s\n\n## Task\nbody\n'
           % (sha12(READ_A).upper(), sha12(READ_B)), crlf=True)
    rc, out, err = p.run('d-1', '--check')
    need(rc == 0 and 'reads OK: 2 pinned' in out, out)
    p.put('lanes/y/contracts/B.md', b'moved\n')
    rc, out, err = p.run('d-1', '--check')
    need(rc == 1 and 'contracts' in out and 'B.md' in out, out)


def t_head_any_case(p):
    """A head a person might type must never read as no Reads at all."""
    for head in ('reads:', '**Reads:**', '### READS'):
        p.put('lanes/x/contracts/A doc.md', READ_A)
        p.card('\n%s\n- %s | %s\n\n' % (head, p.a, sha12(READ_A)))
        p.put('lanes/x/contracts/A doc.md', b'moved\n')
        rc, out, err = p.run('d-1', '--check')
        need(rc == 1 and 'MISMATCH reads' in out, '%s: %s %s' % (head, rc, out))


def t_two_sections(p):
    p.card('\nReads:\n- %s | %s\n\n## Task\nbody\n\nReads:\n- %s | %s\n\n' % (p.a, sha12(READ_A), p.b, sha12(READ_B)))
    p.put('lanes/y/contracts/B.md', b'moved\n')
    rc, out, err = p.run('d-1', '--check')
    need(rc == 1 and 'B.md' in out, out)


def t_section_ends(p):
    p.card('\nReads:\n- %s | %s\n\nThis prose is not a row.\n' % (p.a, sha12(READ_A)))
    rc, out, err = p.run('d-1', '--check')
    need(rc == 0, 'a blank line ends the section: %s %s' % (rc, out))
    p.card('\n## Reads\n- %s | %s\n## Task\nThis prose is not a row.\n' % (p.a, sha12(READ_A)))
    rc, out, err = p.run('d-1', '--check')
    need(rc == 0, 'a heading ends the section: %s %s' % (rc, out))


def t_moved_with_other_mismatch(p):
    p.card(rows(p))
    p.put('lanes/d/contracts/W.md', b'work moved\n')
    p.put('lanes/x/contracts/A doc.md', b'moved\n')
    rc, out, err = p.run('d-1', '--check')
    need(rc == 1 and 'MISMATCH work' in out and 'MISMATCH reads' in out, out)
    need('newest JOB.md.pre-*' in out, 'the work mismatch keeps its next line: %s' % out)


def t_card_edit_moves_card_pin(p):
    """The rows sit in JOB.md, so a re-pinned row is a card change, which needs a new gate."""
    p.card(rows(p))
    gate = os.path.join(p.root, 'jobs', 'd-1', 'GATE-1.md')
    with open(gate, 'rb') as f:
        kept = f.read()
    p.card(rows(p, a='0' * 12))
    for rec in ('REVIEW-1', 'TEST-1', 'GATE-1'):
        p.put('jobs/d-1/%s.md' % rec, kept)
    rc, out, err = p.run('d-1', '--check')
    need(rc == 1 and 'MISMATCH card' in out and 'MISMATCH reads' in out, out)


def t_bad_row_stops_only_pin_commands(p):
    """A sibling tool may load this file and call read_card: a bad Reads: row must not take down its other commands."""
    p.card('\nReads:\nnot a row\n\n')
    spec = importlib.util.spec_from_file_location('pins_under_test', os.path.join(p.root, 'tools', 'job_pins.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    card = mod.read_card(p.root, 'd-1')
    need(card['work_line'] is not None, 'read_card returned no card')


def t_help_states_the_form(p):
    rc, out, err = p.run('--help')
    need(rc == 0 and 'Reads:' in out, out[-300:])
    with open(os.path.join(p.root, 'tools', 'job_pins.py'), encoding='utf-8') as f:
        head = f.read(3000)
    need('`- <path> | <sha12>`' in head and 'Reads: none' in head, 'the usage text does not state the row form')


TESTS = [
    ('T01 print, no Reads: the exact two lines of today (control)', t_print_no_reads),
    ('T02 --card-only, no Reads: the exact two lines of today (control)', t_card_only_no_reads),
    ('T03 --check, no Reads: the exact two lines of today (control)', t_check_no_reads),
    ('T04 Reads: none: no reads lines (control)', t_reads_none_is_no_reads),
    ('T05 print: pins line first and unchanged, one reads line per row', t_print_shows_pins),
    ('T06 --card-only prints the pins', t_card_only_shows_pins),
    ('T07 --check clean: exit 0, reads OK', t_check_clean),
    ('T08 --check: first row moved: exit 1 naming only that file, both sha12s', t_check_moved_first_row),
    ('T09 --check: second row moved: exit 1', t_check_moved_second_row),
    ('T10 print: moved file: exit 0, DIFFERS with both sha12s, on that row only', t_print_flags_moved),
    ('T11 a read file missing: exit 2 in every mode, no half output', t_missing_file),
    ('T12 a row that does not parse: exit 2', t_bad_rows),
    ('T13 a section with no rows: exit 2', t_empty_section),
    ('T14 row forms: heading, backticks, relative, sha12 word, upper hex, CRLF', t_row_forms),
    ('T15 a head in another case or markup is still read', t_head_any_case),
    ('T16 a second Reads section is read too', t_two_sections),
    ('T17 a blank line or a heading ends the section', t_section_ends),
    ('T18 a work mismatch and a reads mismatch: both named, the work next line', t_moved_with_other_mismatch),
    ('T19 a re-pinned row is a card change', t_card_edit_moves_card_pin),
    ('T20 read_card stays lazy on a bad row', t_bad_row_stops_only_pin_commands),
    ('T21 the usage text states the form', t_help_states_the_form),
]

BAD_ROW_RAISE = ('''                if not mr or not _clean(mr.group(1)):
                    raise PinError("the card's Reads: row does not parse: %r (want '- <path> | <sha12>', one row per "
                                   "file, 12 hex, nothing after them; JOB-TEMPLATE.md)" % s)
''')
EMPTY_RAISE = ('''            if not rows:
                raise PinError("the card %s has a Reads: section with no rows (want '- <path> | <sha12>', or 'Reads: "
                               "none')" % q(card["path"]))
''')

# (name, anchor, replacement, the test that must go red)
PLANTS = [
    ('undo --check compare', 'moved = [(p, pin, cur) for p, pin, cur in rs if pin != cur]',
     'moved = []', 'T08'),
    ('moved exit 0', '"a TEST-ASK and a new gate on the current pins (RULES.md step 5)")\n        return 1',
     '"a TEST-ASK and a new gate on the current pins (RULES.md step 5)")\n        return 0', 'T08'),
    ('only the first row checked', 'for p, s in need_reads(card)]', 'for p, s in need_reads(card)[:1]]', 'T09'),
    ('print drops the reads lines', 'print(pins_line(card, full))\n    for x in rl:\n        print(x)\n',
     'print(pins_line(card, full))\n', 'T05'),
    ('card-only drops the reads lines', '" % (c, sc))\n    for x in rl:\n        print(x)\n', '" % (c, sc))\n', 'T06'),
    ('reads go on the pins line', 'print(pins_line(card, full))\n',
     'print(pins_line(card, full) + (" | reads" if rl else ""))\n', 'T05'),
    ('reads OK line on every card', 'if rs:\n        print("reads OK', 'if True:\n        print("reads OK', 'T03'),
    ('print: the card always gets a reads line', 'for x in rl:\n        print(x)\n    print("next: put this line in your',
     'print("reads: none")\n    print("next: put this line in your', 'T01'),
    ('card-only: the card always gets a reads line', '" % (c, sc))\n    for x in rl:\n        print(x)\n',
     '" % (c, sc))\n    print("reads: none")\n', 'T02'),
    ('Reads: none not understood','if len(rows) == 1 and rows[0].lower().startswith("none"):', 'if False:', 'T04'),
    ('no DIFFERS flag', '"" if pin == cur else " | DIFFERS: file now %s" % cur', '""', 'T10'),
    ('a wrong sha length', '[(p, s, sha_file(p)[:12])', '[(p, s, sha_file(p)[:11])', 'T07'),
    ('a missing file skipped', 'for p, s in need_reads(card)]', 'for p, s in need_reads(card) if os.path.isfile(p)]',
     'T11'),
    ('a bad row skipped', BAD_ROW_RAISE,
     '                if not mr or not _clean(mr.group(1)):\n                    continue\n', 'T12'),
    ('an empty section passes', EMPTY_RAISE, '            if not rows:\n                continue\n', 'T13'),
    ('case-sensitive head', 'reads\\s*$", re.I)', 'reads\\s*$")', 'T15'),
    ('upper-case pins never match', 'mr.group(2).lower()))', 'mr.group(2)))', 'T14'),
    ('relative paths not rooted', 'f if os.path.isabs(f) else os.path.join(card["root"], f), mr', 'f, mr', 'T14'),
    ('second section ignored', 'while i < len(lines):\n            m = READS_HEAD_RE',
     'while i < len(lines) and not out:\n            m = READS_HEAD_RE', 'T16'),
    ('blank line does not end', 'elif rows:\n                    break', 'elif rows:\n                    pass', 'T17'),
    ('heading does not end', 'while i < len(lines) and not lines[i].lstrip().startswith("#"):',
     'while i < len(lines):', 'T17'),
    ('generic next hidden', 'if moved and len(moved) == len(bad):', 'if moved:', 'T18'),
    ('reads not checked once another mismatch', 'for p, pin, cur in moved:\n        bad.append',
     'for p, pin, cur in (moved if not bad else []):\n        bad.append', 'T19'),
    ('read_card parses eagerly', '    return card\n\n\ndef need_work(card):',
     '    need_reads(card)\n    return card\n\n\ndef need_work(card):', 'T20'),
    ('usage text dropped', 'file: `- <path> | <sha12>`', 'file', 'T21'),
    ('help drops the Reads example', '  a card with a Reads: section: the same commands', '  the same commands', 'T21'),
]


def run_one(fn, target, folder):
    root = os.path.join(folder, 'root')
    os.makedirs(folder)
    try:
        fn(Pipe(root, target))
        return True, ''
    except Bad as e:
        return False, str(e)
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, e)


def run_suite(target, folder):
    os.makedirs(folder)
    return {name: run_one(fn, target, os.path.join(folder, 't%02d' % i)) for i, (name, fn) in enumerate(TESTS)}


def rm_tree(path):
    def onerror(func, p, exc):
        os.chmod(p, 0o666)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    log, target = None, TARGET
    if '--log' in sys.argv:
        log = open(sys.argv[sys.argv.index('--log') + 1], 'w', encoding='utf-8')
    if '--target' in sys.argv:
        target = sys.argv[sys.argv.index('--target') + 1]

    def say(text):
        print(text)
        if log:
            log.write(text + '\n')
            log.flush()
    with open(target, 'rb') as f:
        source = f.read().decode('utf-8')
    say('test_job_pins_reads.py sha256 %s' % hashlib.sha256(open(os.path.abspath(__file__), 'rb').read()).hexdigest())
    say('%s sha256 %s' % (os.path.basename(target), hashlib.sha256(source.encode('utf-8')).hexdigest()))
    scratch = os.path.join(tempfile.gettempdir(), 'test-job-pins-reads-' + uuid.uuid4().hex)
    os.makedirs(scratch)
    ok = True
    try:
        say('STAGE 1: %d tests against %s' % (len(TESTS), os.path.basename(target)))
        r = run_suite(target, os.path.join(scratch, 'stage1'))
        for name, (passed, why) in r.items():
            say('  %s %s%s' % ('PASS' if passed else 'FAIL', name, '' if passed else ': ' + why[:300]))
        green = sum(1 for p, _ in r.values() if p)
        say('STAGE 1: %d/%d GREEN' % (green, len(TESTS)))
        ok = green == len(TESTS)
        if target == TARGET:
            say('STAGE 2: %d plants' % len(PLANTS))
            reddened, red_count = set(), 0
            for i, (name, anchor, repl, tid) in enumerate(PLANTS):
                hits = source.count(anchor)
                if hits != 1:
                    say('  PLANT %s ANCHOR FOUND %d TIMES (must be 1): NOT RUN' % (name, hits))
                    ok = False
                    continue
                pdir = os.path.join(scratch, 'plant%02d' % i)
                os.makedirs(pdir)
                mutant = os.path.join(pdir, 'job_pins.py')
                with open(mutant, 'w', encoding='utf-8', newline='') as f:
                    f.write(source.replace(anchor, repl))
                tname, fn = next((n, f2) for n, f2 in TESTS if n.startswith(tid + ' '))
                passed, why = run_one(fn, mutant, os.path.join(pdir, 't'))
                if passed:
                    ok = False
                    say('  GREEN %s: %s DID NOT GO RED (the suite misses this defect)' % (name, tid))
                else:
                    red_count += 1
                    reddened.add(tname)
                    say('  RED   %s: %s (%s)' % (name, tid, why[:120].replace('\n', ' ')))
            say('STAGE 2: %d/%d plants red' % (red_count, len(PLANTS)))
            never = [n.split()[0] for n, _ in TESTS if n not in reddened]
            say('tests reddened by a plant: %d/%d%s' % (len(TESTS) - len(never), len(TESTS),
                                                        '' if not never else ' (never red: %s)' % ', '.join(never)))
            if never:
                ok = False
    finally:
        if os.path.basename(scratch).startswith('test-job-pins-reads-'):
            rm_tree(scratch)
    say('RESULT %s' % ('ALL GREEN, EVERY PLANT RED, EXIT 0' if ok else 'FAILED, EXIT 1'))
    if log:
        log.close()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
