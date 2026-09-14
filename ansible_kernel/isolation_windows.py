"""Fail-closed Windows Sandbox profile description and capability probe.

This module does not launch Windows Sandbox or enable any runner. It generates a
fixed trusted .wsb configuration and records whether the host exposes the current
Sandbox CLI. A live hostile-code negative probe is still required before this
profile can become qualified.
"""
from __future__ import annotations

import hashlib
import html
import os
from pathlib import Path
import platform
import shutil
import stat

from . import VERSION
from .state import StateError, plain

PROFILE_CONTRACT = "ansible.isolation.windows-sandbox.v1"
PROFILE_VERSION = 1
MAX_BINARY_BYTES = 64 * 1024 * 1024


class WindowsIsolationError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _ordinary_directory(path: Path, code: str) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise WindowsIsolationError(code)
    try:
        plain(path)
        resolved = path.resolve(strict=True)
        plain(resolved)
        info = resolved.stat()
    except (OSError, StateError) as exc:
        raise WindowsIsolationError(code) from exc
    if not stat.S_ISDIR(info.st_mode):
        raise WindowsIsolationError(code)
    return resolved


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BINARY_BYTES:
                    raise WindowsIsolationError("WINDOWS_SANDBOX_CLI_TOO_LARGE")
                hasher.update(chunk)
    except OSError as exc:
        raise WindowsIsolationError("WINDOWS_SANDBOX_CLI_UNAVAILABLE") from exc
    return hasher.hexdigest()


def profile_fingerprint() -> str:
    raw = Path(__file__).resolve().read_bytes()
    return hashlib.sha256(b"isolation_windows.py\0" + raw).hexdigest()


def windows_sandbox_config(candidate: Path, reference: Path, result: Path) -> str:
    """Generate the fixed profile from trusted host directories only."""
    candidate = _ordinary_directory(candidate, "CANDIDATE_ROOT_INVALID")
    reference = _ordinary_directory(reference, "REFERENCE_ROOT_INVALID")
    result = _ordinary_directory(result, "RESULT_ROOT_INVALID")

    def mapped(host: Path, sandbox: str, readonly: bool) -> str:
        return ("<MappedFolder><HostFolder>" + html.escape(str(host)) + "</HostFolder>"
                "<SandboxFolder>" + sandbox + "</SandboxFolder><ReadOnly>"
                + ("true" if readonly else "false") + "</ReadOnly></MappedFolder>")

    return ("<Configuration>"
            "<VGpu>Disable</VGpu>"
            "<Networking>Disable</Networking>"
            "<AudioInput>Disable</AudioInput>"
            "<VideoInput>Disable</VideoInput>"
            "<ProtectedClient>Enable</ProtectedClient>"
            "<PrinterRedirection>Disable</PrinterRedirection>"
            "<ClipboardRedirection>Disable</ClipboardRedirection>"
            "<MemoryInMB>4096</MemoryInMB>"
            "<MappedFolders>"
            + mapped(candidate, r"C:\candidate", True)
            + mapped(reference, r"C:\reference", True)
            + mapped(result, r"C:\result", False)
            + "</MappedFolders></Configuration>")


def availability() -> dict:
    report = {"profile_contract": PROFILE_CONTRACT, "profile_version": PROFILE_VERSION,
              "implementation_version": VERSION, "profile_fingerprint": profile_fingerprint(),
              "platform": platform.system(), "available": False, "profile_qualified": False,
              "runner_activation": False, "real_agent_qualified": False,
              "deployment_qualified": False}
    if platform.system() != "Windows":
        return {**report, "reason": "PROFILE_PLATFORM_UNSUPPORTED"}
    found = shutil.which("wsb") or shutil.which("wsb.exe")
    if not found:
        return {**report, "reason": "WINDOWS_SANDBOX_CLI_UNAVAILABLE"}
    try:
        path = Path(found).absolute().resolve(strict=True)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
            raise WindowsIsolationError("WINDOWS_SANDBOX_CLI_UNAVAILABLE")
        digest = _sha256(path)
    except (OSError, WindowsIsolationError) as exc:
        return {**report, "reason": getattr(exc, "code", "WINDOWS_SANDBOX_CLI_UNAVAILABLE")}
    return {**report, "available": True,
            "mechanism": {"path": str(path), "sha256": digest},
            "reason": "WINDOWS_LIVE_NEGATIVE_PROBE_NOT_RUN"}
