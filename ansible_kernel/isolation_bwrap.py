"""Fail-closed Linux Bubblewrap isolation profile qualification.

This module does not expose a general task-controlled command surface. It constructs
all Bubblewrap arguments in trusted code and executes only the fixed qualification
probe. A real runner remains separately gated behind #13/#14.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

from . import VERSION
from .contract import decode
from .provider import Capture
from .state import StateError, plain

PROFILE_CONTRACT = "ansible.isolation.linux-bwrap.v1"
PROFILE_VERSION = 1
MAX_CAPTURE = 32768
MEMORY_MB = 384
CPU_SECONDS = 2
WALL_SECONDS = 5.0
MODES = frozenset({"baseline", "flood", "hang", "memory", "cpu"})
ROOT = Path(__file__).resolve().parent.parent
PROBE = Path(__file__).resolve().with_name("isolation_probe.py")


class IsolationError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def profile_fingerprint() -> str:
    hasher = hashlib.sha256()
    for path in (Path(__file__).resolve(), PROBE, ROOT / "run_isolation.py"):
        hasher.update(path.name.encode("ascii"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _ordinary_directory(path: Path, code: str) -> Path:
    path = Path(path).absolute()
    try:
        plain(path)
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except (OSError, StateError) as exc:
        raise IsolationError(code) from exc
    if not stat.S_ISDIR(info.st_mode):
        raise IsolationError(code)
    return resolved


def _bwrap_executable() -> Path:
    if not sys.platform.startswith("linux"):
        raise IsolationError("PROFILE_PLATFORM_UNSUPPORTED")
    found = shutil.which("bwrap")
    if not found:
        raise IsolationError("BWRAP_UNAVAILABLE")
    path = Path(found).absolute().resolve(strict=True)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise IsolationError("BWRAP_UNAVAILABLE")
    return path


def _probe_python() -> Path:
    path = Path("/usr/bin/python3")
    if not path.exists() or not path.is_file():
        raise IsolationError("SYSTEM_PYTHON_UNAVAILABLE")
    return path


def _system_mounts() -> list[str]:
    if not Path("/usr").is_dir():
        raise IsolationError("SYSTEM_RUNTIME_UNAVAILABLE")
    args = ["--ro-bind", "/usr", "/usr"]
    for raw in ("/bin", "/lib", "/lib64"):
        path = Path(raw)
        if not os.path.lexists(path):
            continue
        if path.is_symlink():
            target = os.readlink(path)
            if "\x00" in target or not target:
                raise IsolationError("SYSTEM_RUNTIME_UNAVAILABLE")
            args += ["--symlink", target, raw]
        elif path.is_dir():
            args += ["--ro-bind", raw, raw]
        else:
            raise IsolationError("SYSTEM_RUNTIME_UNAVAILABLE")
    return args


def build_command(mode: str, input_root: Path, output_root: Path, secret_path: Path) -> list[str]:
    if mode not in MODES:
        raise IsolationError("UNKNOWN_QUALIFICATION_PROBE")
    bwrap = _bwrap_executable()
    _probe_python()
    input_root = _ordinary_directory(input_root, "INPUT_ROOT_INVALID")
    output_root = _ordinary_directory(output_root, "OUTPUT_ROOT_INVALID")
    secret_path = Path(secret_path).absolute()
    args = [str(bwrap),
            "--unshare-user", "--disable-userns", "--unshare-ipc", "--unshare-pid",
            "--unshare-net", "--unshare-uts", "--unshare-cgroup-try",
            "--cap-drop", "ALL", "--new-session", "--die-with-parent",
            "--clearenv", "--setenv", "HOME", "/home/sandbox",
            "--setenv", "USER", "sandbox", "--setenv", "LOGNAME", "sandbox",
            "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8",
            "--setenv", "TMPDIR", "/tmp", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--dir", "/home", "--dir", "/home/sandbox", "--dir", "/run",
            "--dir", "/input", "--dir", "/output", "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp"]
    args += _system_mounts()
    args += ["--ro-bind", str(PROBE), "/probe.py",
             "--ro-bind", str(input_root), "/input",
             "--bind", str(output_root), "/output",
             "--chdir", "/input", "--hostname", "ansible-sandbox",
             "/usr/bin/python3", "-I", "-S", "-B", "/probe.py", mode, str(secret_path)]
    return args


def _limit_child() -> None:
    import resource
    memory = MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))


def _descendants(pid: int) -> set[int]:
    found, pending = set(), [pid]
    while pending:
        current = pending.pop()
        children_file = Path(f"/proc/{current}/task/{current}/children")
        try:
            text = children_file.read_text(encoding="ascii")
        except OSError:
            continue
        for token in text.split():
            try:
                child = int(token)
            except ValueError:
                continue
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _kill_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run(mode: str, input_root: Path, output_root: Path, secret_path: Path,
         wall_seconds: float = WALL_SECONDS) -> dict:
    command = build_command(mode, input_root, output_root, secret_path)
    overflow = threading.Event()
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd="/", env={"LANG": "C", "LC_ALL": "C"},
                               close_fds=True, start_new_session=True, preexec_fn=_limit_child)
    stdout_capture = Capture(process.stdout, overflow)
    stderr_capture = Capture(process.stderr, overflow)
    started = time.monotonic()
    termination = "natural"
    observed_descendants = set()
    try:
        while process.poll() is None:
            if overflow.is_set():
                termination = "output_limit"
                observed_descendants |= _descendants(process.pid)
                _kill_group(process)
                break
            if time.monotonic() - started >= wall_seconds:
                termination = "timeout"
                observed_descendants |= _descendants(process.pid)
                _kill_group(process)
                break
            time.sleep(0.01)
        process.wait(timeout=2)
    finally:
        _kill_group(process)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired as exc:
            raise IsolationError("SANDBOX_TERMINATION_FAILED") from exc
    stdout = stdout_capture.finish()
    stderr = stderr_capture.finish()
    survivors = sorted(pid for pid in observed_descendants if Path(f"/proc/{pid}").exists())
    return {"mode": mode, "returncode": process.returncode, "termination": termination,
            "stdout": stdout, "stderr": stderr, "surviving_descendants": survivors,
            "elapsed_ms": int((time.monotonic() - started) * 1000)}


def availability() -> dict:
    if not sys.platform.startswith("linux"):
        return {"profile_contract": PROFILE_CONTRACT, "available": False,
                "reason": "PROFILE_PLATFORM_UNSUPPORTED", "platform": platform.system()}
    try:
        bwrap = _bwrap_executable()
        _probe_python()
        version = subprocess.run([str(bwrap), "--version"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env={"LANG": "C", "LC_ALL": "C"}, timeout=2, check=False)
        if version.returncode != 0 or len(version.stdout) > 1024:
            raise IsolationError("BWRAP_VERSION_UNAVAILABLE")
        max_userns = Path("/proc/sys/user/max_user_namespaces")
        if not max_userns.exists() or int(max_userns.read_text(encoding="ascii").strip()) < 2:
            raise IsolationError("USER_NAMESPACE_UNAVAILABLE")
        return {"profile_contract": PROFILE_CONTRACT, "available": True,
                "platform": platform.system(), "kernel": platform.release(),
                "bwrap_path": str(bwrap), "bwrap_version": version.stdout.decode("ascii", errors="strict").strip()}
    except (IsolationError, OSError, ValueError, UnicodeError) as exc:
        return {"profile_contract": PROFILE_CONTRACT, "available": False,
                "reason": getattr(exc, "code", "PROFILE_UNAVAILABLE"), "platform": platform.system()}


def qualify(state_root: Path) -> dict:
    available = availability()
    report = {"profile_contract": PROFILE_CONTRACT, "profile_version": PROFILE_VERSION,
              "implementation_version": VERSION, "profile_fingerprint": profile_fingerprint(),
              "real_agent_qualified": False, **available}
    if not available.get("available"):
        return {**report, "profile_qualified": False, "checks": []}
    root = Path(state_root).absolute()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name == "posix":
        os.chmod(root, 0o700)
    root = _ordinary_directory(root, "STATE_ROOT_INVALID")
    stage = Path(tempfile.mkdtemp(prefix="bwrap-qualify-", dir=root))
    os.chmod(stage, 0o700)
    input_root, secret = stage / "input", stage / "host-secret.txt"
    input_root.mkdir(mode=0o700)
    (input_root / "readable.txt").write_text("visible\n", encoding="ascii")
    secret.write_text("must-not-be-visible\n", encoding="ascii")
    checks = []
    try:
        def run_mode(mode: str, wall: float = WALL_SECONDS) -> tuple[dict, Path]:
            out = stage / ("out-" + mode)
            out.mkdir(mode=0o700)
            return _run(mode, input_root, out, secret, wall), out

        baseline, out = run_mode("baseline")
        try:
            observed = decode((out / "report.json").read_bytes())
        except Exception as exc:
            raise IsolationError("BASELINE_REPORT_INVALID") from exc
        required = ("input_read", "input_write_blocked", "host_secret_blocked", "credential_env_absent",
                    "network_blocked", "home_private", "pid_namespace", "child_confined_write")
        baseline_ok = baseline["returncode"] == 0 and baseline["termination"] == "natural" and all(observed.get(k) is True for k in required)
        checks.append({"name": "filesystem_network_credentials_pid", "passed": baseline_ok})

        flood, _ = run_mode("flood", 2.0)
        checks.append({"name": "output_bound", "passed": flood["termination"] == "output_limit" and not flood["surviving_descendants"]})

        hang, _ = run_mode("hang", 0.75)
        checks.append({"name": "deadline_descendant_containment", "passed": hang["termination"] == "timeout" and not hang["surviving_descendants"]})

        memory, _ = run_mode("memory", 3.0)
        checks.append({"name": "memory_limit", "passed": memory["returncode"] != 0 and memory["termination"] == "natural"})

        cpu, _ = run_mode("cpu", 4.0)
        checks.append({"name": "cpu_limit", "passed": cpu["returncode"] != 0 and b"cpu_probe_ready" in cpu["stdout"] and cpu["termination"] == "natural"})
        qualified = all(item["passed"] for item in checks)
        return {**report, "profile_qualified": qualified, "checks": checks,
                "limits": {"memory_mb": MEMORY_MB, "cpu_seconds": CPU_SECONDS,
                           "wall_seconds": WALL_SECONDS, "capture_bytes_per_stream": MAX_CAPTURE},
                "runner_activation": False}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Qualify the fixed Linux Bubblewrap isolation profile")
    parser.add_argument("command", choices=("availability", "qualify"))
    parser.add_argument("--state-root", type=Path)
    args = parser.parse_args(argv)
    if args.command == "availability":
        value = availability()
        print(json.dumps(value, sort_keys=True, indent=2))
        return 0 if value.get("available") else 2
    if args.state_root is None:
        parser.error("qualify requires --state-root")
    value = qualify(args.state_root)
    print(json.dumps(value, sort_keys=True, indent=2))
    return 0 if value.get("profile_qualified") else 2
