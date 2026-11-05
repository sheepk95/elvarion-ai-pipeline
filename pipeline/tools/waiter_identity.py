"""Identify a waiter by PID and Windows process creation time, not PID alone.

The numeric .waiter.pid remains compatible with older readers. A missing, malformed
or unreadable identity is UNKNOWN: legacy waiters must be re-armed to identify them.
"""
import json
import os
import tempfile


def creation(pid):
    """Return (state, creation FILETIME). Permission/API failures are unknown."""
    if os.name != "nt":
        return "UNKNOWN", None
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return ("DEAD" if ctypes.get_last_error() == 87 else "UNKNOWN"), None
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)):
            return "UNKNOWN", None
        if code.value != 259:
            return "DEAD", None
        born, end, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not k.GetProcessTimes(h, ctypes.byref(born), ctypes.byref(end), ctypes.byref(kernel), ctypes.byref(user)):
            return "UNKNOWN", None
        return "LIVE", (born.dwHighDateTime << 32) | born.dwLowDateTime
    finally:
        k.CloseHandle(h)


def register(inbox):
    pid = os.getpid()
    state, born = creation(pid)
    if state != "LIVE":
        return None
    record = {"pid": pid, "creation": born}
    fd, tmp = tempfile.mkstemp(prefix=".waiter-identity-", dir=inbox)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f)
        os.replace(tmp, os.path.join(inbox, ".waiter.identity"))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return record


def status(inbox):
    try:
        with open(os.path.join(inbox, ".waiter.pid"), encoding="utf-8") as f:
            pid = int(f.read().strip())
        if not 0 < pid <= 0xffffffff:
            return "UNKNOWN"
    except FileNotFoundError:
        return "NONE"
    except (OSError, ValueError):
        return "UNKNOWN"
    try:
        with open(os.path.join(inbox, ".waiter.identity"), encoding="utf-8") as f:
            record = json.load(f)
        if (not isinstance(record, dict) or type(record.get("pid")) is not int or
                type(record.get("creation")) is not int or record["pid"] != pid):
            return "UNKNOWN"
    except (OSError, ValueError):
        return "UNKNOWN"
    state, born = creation(pid)
    if state == "DEAD" or (state == "LIVE" and born != record["creation"]):
        return "DEAD"
    return "ARMED" if state == "LIVE" else "UNKNOWN"
