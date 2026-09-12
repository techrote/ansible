"""Standalone fixed noop worker. No plugin loading, shell, network, or task paths.

Invoked by the trusted provider with -I -S -B. The only task parameter is a
bounded sleep duration. This script must never become a general agent host.
"""
import json
import os
from pathlib import Path
import re
import sys
import time


def apply_linux_limits(memory_mb, cpu_seconds, parent_pid):
    import ctypes
    import resource
    import signal
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                          ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        raise OSError("PARENT_GUARD_FAILED")
    resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))


def main():
    memory_mb, cpu_seconds, parent_pid = map(int, sys.argv[1:])
    if not 64 <= memory_mb <= 256 or not 1 <= cpu_seconds <= 2:
        return 70
    if sys.platform.startswith("linux"):
        apply_linux_limits(memory_mb, cpu_seconds, parent_pid)
        enforcement = "linux_rlimit"
    elif os.name == "nt":
        enforcement = "windows_job"
    else:
        return 70
    raw = sys.stdin.buffer.read(1025)
    if len(raw) > 1024:
        return 65
    data = json.loads(raw)
    if (type(data) is not dict or set(data) != {"job_id", "duration_ms"}
            or type(data["job_id"]) is not str or not re.fullmatch(r"[0-9a-f]{32}", data["job_id"])
            or type(data["duration_ms"]) is not int or not 0 <= data["duration_ms"] <= 5000):
        return 65
    print(json.dumps({"ready": True, "enforcement": enforcement}), flush=True)
    deadline = time.monotonic() + data["duration_ms"] / 1000
    cancelled = False
    while True:
        if Path("stop").exists():
            cancelled = True
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    print(json.dumps({"contract_version": "ansible.worker.v1", "job_id": data["job_id"],
                      "outcome": "cancelled" if cancelled else "success",
                      "transport": "not_applicable",
                      "final_output": None if cancelled else "trusted noop complete",
                      "error_class": "none", "retry_exhausted": False, "tool_calls": 0,
                      "implementation_activity": False}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, MemoryError):
        # No exception strings or inherited environment are written to evidence.
        raise SystemExit(70)
