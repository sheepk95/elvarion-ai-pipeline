"""Time-limit a command without taking it out of a gpu_lease booking (Windows; standard library only).

Why: gpu_lease counts a GPU program (blender.exe, an nvenc ffmpeg, Unity) as booked only when walking its parent pids
reaches a lease's `run` process. Git's timeout.exe is an MSYS program. Started from a Git-bash script, or starting
bash itself, MSYS's fork and exec leave a dead process in the chain, so the program under it is counted as unbooked
"seen" (4-6 GB) while its script's lease is open, and exclusive claims still wait. This helper is a native Windows
python, so its child stays in the chain. Found on booked Blender runs started from Git-bash scripts; a process-tree test showed that
several wrappers lose the chain while this helper keeps it.

Use it inside a script that runs under `gpu_lease.py run ... -- "<GIT_DIR>/usr/bin/bash.exe" script.sh`,
in place of `timeout <seconds>`:
    python -B <SKILL_DIR>/scripts/lease_timeout.py 900 "$B" -b in.blend ...
Straight after `run ... --`, Git's timeout.exe named in full is fine (python -> timeout.exe -> program keeps it).

Exit: the command's own code; 124 when the time ran out (the command and its children are killed), as Git's timeout;
125 on a usage error; 127 when the command cannot start; 255 when the command's code does not fit 0-255 (a crash such
as 0xC0000005; the raw code goes to stderr).
"""
import subprocess
import sys


def main(argv):
    if len(argv) < 3:
        sys.stderr.write('usage: lease_timeout.py <seconds> <command> [args...]\n')
        return 125
    try:
        secs = float(argv[1])
    except ValueError:
        sys.stderr.write('lease_timeout: seconds must be a number, got %r\n' % argv[1])
        return 125
    try:
        p = subprocess.Popen(argv[2:])
    except OSError as e:
        sys.stderr.write('lease_timeout: cannot start %s: %s\n' % (argv[2], e))
        return 127
    try:
        rc = p.wait(timeout=secs)
    except subprocess.TimeoutExpired:
        subprocess.call(['taskkill', '/T', '/F', '/PID', str(p.pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
        sys.stderr.write('lease_timeout: %g s ran out; killed %s (pid %d) and its children\n' % (secs, argv[2], p.pid))
        return 124
    except KeyboardInterrupt:
        p.kill()
        raise
    if rc < 0 or rc > 255:
        sys.stderr.write('lease_timeout: %s ended with code %d (0x%X)\n' % (argv[2], rc, rc & 0xFFFFFFFF))
        return 255
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv))
