"""Fixed trusted subprocess only. Not an untrusted-code sandbox."""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import threading

from .contract import canonical, decode, Refusal
from .state import Store, StateError, write_once


class WindowsJob:
    """Hard committed-memory/user-CPU limits and kill-on-close, no breakaway."""
    def __init__(self, memory_mb: int, cpu_seconds: int):
        from ctypes import wintypes as w
        size = ctypes.c_size_t
        u64 = ctypes.c_uint64

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", w.DWORD), ("min_ws", size), ("max_ws", size),
                        ("active", w.DWORD), ("affinity", size),
                        ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, u64) for name in ("read_ops", "write_ops", "other_ops",
                                                 "read_bytes", "write_bytes", "other_bytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", size),
                        ("job_memory", size), ("peak_process", size), ("peak_job", size)]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.api.SetInformationJobObject.restype = w.BOOL
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.AssignProcessToJobObject.restype = w.BOOL
        self.api.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.api.TerminateJobObject.restype = w.BOOL
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CREATE_JOB_FAILED")
        limits = Extended()
        limits.basic.process_time = cpu_seconds * 10_000_000
        limits.basic.flags = 0x2 | 0x8 | 0x100 | 0x200 | 0x2000
        limits.basic.active = 1
        limits.process_memory = limits.job_memory = memory_mb * 1024 * 1024
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError("SET_JOB_LIMITS_FAILED")

    def assign(self, process: subprocess.Popen) -> None:
        # Popen's Windows process handle stays live until the Popen is released.
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError("ASSIGN_JOB_FAILED")

    def terminate(self) -> None:
        if not self.api.TerminateJobObject(self.handle, 137):
            raise OSError("TERMINATE_JOB_FAILED")

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def clean_environment(work: Path) -> dict[str, str]:
    env = {"HOME": str(work), "USERPROFILE": str(work), "TMP": str(work),
           "TEMP": str(work), "TMPDIR": str(work), "LANG": "C.UTF-8"}
    if os.name == "nt":
        root = os.environ.get("SystemRoot")
        if not root or not Path(root).is_absolute():
            raise OSError("SYSTEM_ROOT_UNAVAILABLE")
        env["SystemRoot"] = root
    return env


def terminate(process: subprocess.Popen, job: WindowsJob | None) -> None:
    if process.poll() is not None:
        return
    if job is not None:
        job.terminate()
    elif os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()


class Capture:
    """Bound controller memory while continuously draining both child pipes."""
    def __init__(self, stream, overflow, limit=32768):
        self.data = bytearray()
        self.limit = limit
        self.error = False
        self.stream, self.overflow = stream, overflow
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            while True:
                chunk = self.stream.read(4096)
                if not chunk:
                    return
                available = self.limit - len(self.data)
                self.data.extend(chunk[:available])
                if len(chunk) > available:
                    self.overflow.set()
        except OSError:
            self.error = True
        finally:
            self.stream.close()

    def finish(self):
        self.thread.join(2)
        if self.thread.is_alive() or self.error:
            raise OSError("CAPTURE_FAILED")
        return bytes(self.data)


def run(job_id: str, request: dict, store: Store, on_running) -> tuple:
    """Only kernel-validated noop requests may reach this trusted-code API."""
    work = store.job(job_id) / "work"
    limits = request["resources"]
    worker = Path(__file__).resolve().with_name("worker.py")
    command = [sys.executable, "-I", "-S", "-B", str(worker),
               str(limits["memory_mb"]), str(limits["cpu_seconds"]), str(os.getpid())]
    process, job, stop, stdout, stderr = None, None, None, b"", b""
    captures = []
    overflow = threading.Event()
    metadata = {"provider_id": "trusted_local_v1", "isolation": "trusted_code_only",
                "requested_limits": limits, "limits_applied": False,
                "environment": "allowlist_without_credentials", "termination": "none"}
    started = time.monotonic()
    try:
        if os.name == "nt":
            job = WindowsJob(limits["memory_mb"], limits["cpu_seconds"])
        elif not sys.platform.startswith("linux"):
            raise OSError("PLATFORM_NOT_QUALIFIED")
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=work, env=clean_environment(work),
                                   shell=False, close_fds=True, start_new_session=os.name == "posix",
                                   creationflags=0x08000000 if os.name == "nt" else 0)
        if job is not None:
            job.assign(process)
        captures = [Capture(process.stdout, overflow), Capture(process.stderr, overflow)]
        # Trusted child blocks on stdin; no task is delivered before Windows assignment.
        on_running()
        input_bytes = canonical({"job_id": job_id, "duration_ms": request["parameters"]["duration_ms"]})
        try:
            process.stdin.write(input_bytes)
            process.stdin.close()
        except BrokenPipeError:
            pass
        cancel_deadline = None
        while process.poll() is None:
            if overflow.is_set():
                stop = "contained"
                metadata["error"] = "OUTPUT_LIMIT"
                metadata["termination"] = "output_limit"
                terminate(process, job)
                break
            requested = store.stop_reason(job_id)
            if requested == "contained":
                stop = "contained"
                metadata["termination"] = "emergency"
                terminate(process, job)
            elif requested == "cancelled" and stop is None:
                stop = "cancelled"
                metadata["termination"] = "cooperative"
                write_once(work / "stop", b"cancel\n")
                cancel_deadline = time.monotonic() + 0.5
            if stop is None and time.monotonic() - started >= request["timeout_seconds"]:
                stop = "timeout"
                metadata["termination"] = "deadline"
                terminate(process, job)
            if cancel_deadline is not None and time.monotonic() >= cancel_deadline:
                metadata["termination"] = "cancel_escalated"
                terminate(process, job)
            time.sleep(0.02)
        process.wait(timeout=2)
        stdout, stderr = [capture.finish() for capture in captures]
        if overflow.is_set():
            stop = "contained"
            metadata["error"] = "OUTPUT_LIMIT"
            metadata["termination"] = "output_limit"
        infra = {"state": "completed" if process.returncode == 0 else "terminated",
                 "exit_code": process.returncode, "controller_completed": True}
        normalized = None
        if overflow.is_set():
            infra["state"] = "environment_failed"
            metadata["error"] = "OUTPUT_LIMIT"
        else:
            lines = stdout.splitlines()
            if len(lines) == 2:
                ready = decode(lines[0])
                expected = "windows_job" if os.name == "nt" else "linux_rlimit"
                if ready == {"ready": True, "enforcement": expected}:
                    metadata["limits_applied"] = True
                    metadata["enforcement"] = expected
                    normalized = lines[1]
                else:
                    infra["state"] = "environment_failed"
                    metadata["error"] = "INVALID_READY"
            elif stdout:
                normalized = stdout
                infra["state"] = "environment_failed"
                metadata["error"] = "MALFORMED_WORKER_OUTPUT"
            elif stop is None:
                infra["state"] = "environment_failed"
                metadata["error"] = "WORKER_DID_NOT_START"
        metadata["stdout_sha256"] = hashlib.sha256(stdout).hexdigest()
        metadata["stderr_sha256"] = hashlib.sha256(stderr).hexdigest()
        return normalized, infra, stop, metadata
    except (OSError, Refusal, StateError, ValueError) as exc:
        metadata["error"] = "PROVIDER_SETUP_OR_IO_FAILURE"
        return None, {"state": "environment_failed", "exit_code": None,
                      "controller_completed": True}, stop, metadata
    finally:
        try:
            if process is not None:
                terminate(process, job)
                process.wait(timeout=2)
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                if captures:
                    for capture in captures:
                        capture.finish()
                else:
                    for stream in (process.stdout, process.stderr):
                        if stream:
                            stream.close()
        finally:
            if job is not None:
                job.close()
