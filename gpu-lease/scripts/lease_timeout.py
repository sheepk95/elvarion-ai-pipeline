"""Time-limit a command inside a GPU lease (Windows, standard library only).

The command starts suspended and is assigned to a Windows job before it can spawn
children. All descendants are terminated when the command ends, times out, or this
wrapper exits. Job assignment may fail under restrictive parent jobs; in that case
no command is run. A timeout returns 124 only after the job is empty. If termination
or verification fails, the wrapper stays alive and retries so its enclosing lease is
not deliberately released while GPU processes may still be running (lease expiry still depends on heartbeat).
"""
import ctypes
from ctypes import wintypes
import math
import subprocess
import sys
import time


class Accounting(ctypes.Structure):
    _fields_ = [('total_user', ctypes.c_longlong), ('total_kernel', ctypes.c_longlong),
                ('period_user', ctypes.c_longlong), ('period_kernel', ctypes.c_longlong),
                ('page_faults', wintypes.DWORD), ('total_processes', wintypes.DWORD),
                ('active_processes', wintypes.DWORD), ('terminated_processes', wintypes.DWORD)]


class BasicLimits(ctypes.Structure):
    _fields_ = [('user_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                ('active_limit', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IoCounters), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


class Job:
    def __init__(self):
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.k.CreateJobObjectW.restype = wintypes.HANDLE
        self.k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            err = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise err

    def assign(self, process):
        if not self.k.AssignProcessToJobObject(self.handle, wintypes.HANDLE(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def resume(self, process):
        ntdll = ctypes.WinDLL('ntdll')
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtResumeProcess.restype = ctypes.c_long
        status = ntdll.NtResumeProcess(wintypes.HANDLE(process._handle))
        if status < 0:
            raise OSError('NtResumeProcess failed: 0x%08X' % (status & 0xffffffff))

    def drain(self):
        """Fail closed: do not return while the job may still contain processes."""
        reported = False
        while True:
            self.k.TerminateJobObject(self.handle, 1)
            info = Accounting()
            queried = self.k.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None)
            if queried and info.active_processes == 0:
                return
            if not reported:
                sys.stderr.write('lease_timeout: job termination/verification failed or still pending; keeping wrapper alive and retrying\n')
                reported = True
            time.sleep(1)

    def close(self):
        self.k.CloseHandle(self.handle)


def main(argv):
    if len(argv) < 3:
        sys.stderr.write('usage: lease_timeout.py <seconds> <command> [args...]\n')
        return 125
    try:
        secs = float(argv[1])
        if not math.isfinite(secs) or secs < 0:
            raise ValueError()
    except ValueError:
        sys.stderr.write('lease_timeout: seconds must be a finite nonnegative number\n')
        return 125
    try:
        job = Job()
    except (OSError, AttributeError) as e:
        sys.stderr.write('lease_timeout: cannot create Windows containment job: %s\n' % e)
        return 125
    try:
        try:
            p = subprocess.Popen(argv[2:], creationflags=0x00000004)  # CREATE_SUSPENDED
        except OSError as e:
            sys.stderr.write('lease_timeout: cannot start %s: %s\n' % (argv[2], e))
            return 127
        try:
            job.assign(p)
        except OSError as e:
            # The process is still suspended and cannot have created children.
            sys.stderr.write('lease_timeout: cannot contain command: %s\n' % e)
            while p.poll() is None:
                try:
                    p.kill()
                    p.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    sys.stderr.write('lease_timeout: suspended command still present; retrying termination\n')
                    time.sleep(1)
            return 125
        try:
            job.resume(p)
            try:
                rc = p.wait(timeout=secs)
            except subprocess.TimeoutExpired:
                rc = 124
                sys.stderr.write('lease_timeout: %g s ran out; terminating job\n' % secs)
        except OSError as e:
            sys.stderr.write('lease_timeout: cannot resume command: %s\n' % e)
            rc = 125
        finally:
            job.drain()
            p.wait()
        if rc < 0 or rc > 255:
            sys.stderr.write('lease_timeout: %s ended with code %d (0x%X)\n' % (argv[2], rc, rc & 0xFFFFFFFF))
            return 255
        return rc
    finally:
        job.close()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
