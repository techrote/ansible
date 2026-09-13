"""Shared policy and bounded Git plumbing for inert snapshots."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from .config import KNOWN_REPOSITORIES
from .state import StateError, plain

SNAPSHOT_VERSION = "ansible.snapshot.v1"
JOB_RE = re.compile(r"[0-9a-f]{32}\Z")
OID_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_FILES = 20_000
MAX_TREE_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 60


_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
_WINDOWS_FORBIDDEN = frozenset('<>:"|?*')


def _repository_relative_path(value: str) -> str:
    """Cross-platform conservative Git-tree path, distinct from task path policy."""
    if type(value) is not str or not 1 <= len(value) <= 260:
        raise SnapshotError("UNSAFE_TREE_PATH")
    if value.startswith("/") or value.endswith("/") or "\\" in value:
        raise SnapshotError("UNSAFE_TREE_PATH")
    if any(ord(char) < 32 or ord(char) > 126 or char in _WINDOWS_FORBIDDEN for char in value):
        raise SnapshotError("UNSAFE_TREE_PATH")
    parts = value.split("/")
    for part in parts:
        if (not part or part in {".", ".."} or len(part) > 255
                or part.endswith((".", " "))
                or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED):
            raise SnapshotError("UNSAFE_TREE_PATH")
        if part.casefold() == ".git":
            raise SnapshotError("GIT_PATH_COMPONENT_REFUSED")
    return value


class SnapshotError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _Entry:
    path: str
    mode: str
    oid: str


def _ids(job_id: str, repository_id: str, commit_sha: str) -> None:
    if type(job_id) is not str or JOB_RE.fullmatch(job_id) is None:
        raise SnapshotError("INVALID_SNAPSHOT_JOB")
    if repository_id not in KNOWN_REPOSITORIES:
        raise SnapshotError("UNKNOWN_REPOSITORY_IDENTIFIER")
    if type(commit_sha) is not str or OID_RE.fullmatch(commit_sha) is None:
        raise SnapshotError("INVALID_COMMIT_ID")


def _private_directory(path: Path) -> None:
    plain(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    plain(path)
    if not path.is_dir():
        raise SnapshotError("SNAPSHOT_DIRECTORY_INVALID")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise SnapshotError("SNAPSHOT_PERMISSIONS_TOO_BROAD")


def _repository(path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise SnapshotError("REPOSITORY_PATH_NOT_ABSOLUTE")
    try:
        plain(path)
        path = path.resolve(strict=True)
        plain(path)
    except (OSError, StateError) as exc:
        raise SnapshotError("REPOSITORY_PATH_INVALID") from exc
    if not path.is_dir():
        raise SnapshotError("REPOSITORY_PATH_INVALID")
    git_dir = path / ".git"
    try:
        plain(git_dir)
    except StateError as exc:
        raise SnapshotError("GIT_METADATA_REDIRECTION_REFUSED") from exc
    # v1 intentionally supports ordinary clones only. A linked-worktree .git file
    # can redirect metadata outside the approved checkout and is therefore refused.
    if not git_dir.is_dir():
        raise SnapshotError("GIT_METADATA_LAYOUT_UNSUPPORTED")
    for component in (git_dir / "objects", git_dir / "objects" / "info",
                      git_dir / "objects" / "pack"):
        if component.exists():
            try:
                plain(component)
            except StateError as exc:
                raise SnapshotError("GIT_METADATA_REDIRECTION_REFUSED") from exc
    for alternate in (git_dir / "objects" / "info" / "alternates",
                      git_dir / "objects" / "info" / "http-alternates"):
        if os.path.lexists(alternate):
            raise SnapshotError("ALTERNATE_OBJECT_DATABASE_REFUSED")
    return path


def _git_executable() -> str:
    value = shutil.which("git")
    if not value:
        raise SnapshotError("GIT_UNAVAILABLE")
    try:
        return str(Path(value).resolve(strict=True))
    except OSError as exc:
        raise SnapshotError("GIT_UNAVAILABLE") from exc


def _git_environment(scratch: Path, git: str) -> dict[str, str]:
    _private_directory(scratch)
    env = {
        "HOME": str(scratch),
        "XDG_CONFIG_HOME": str(scratch),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": str(Path(git).parent),
    }
    if os.name == "nt":
        root = os.environ.get("SystemRoot")
        if not root or not Path(root).is_absolute():
            raise SnapshotError("SYSTEM_ROOT_UNAVAILABLE")
        env.update({"SystemRoot": root, "WINDIR": root, "TEMP": str(scratch),
                    "TMP": str(scratch)})
    else:
        env["TMPDIR"] = str(scratch)
    return env


def _command(git: str, repository: Path, hooks: Path, *args: str) -> list[str]:
    return [git, "--no-optional-locks", "-c", f"core.hooksPath={hooks}",
            "-c", "submodule.recurse=false", "-C", str(repository), *args]


def _popen(command: list[str], env: dict[str, str], *, stdin) -> subprocess.Popen:
    return subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=env, shell=False,
                            close_fds=True, start_new_session=os.name == "posix",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                            if os.name == "nt" else 0)


def _run_bounded(command: list[str], env: dict[str, str], maximum: int,
                 timeout: int = 15) -> bytes:
    process = _popen(command, env, stdin=subprocess.DEVNULL)
    data = bytearray()
    overflow = threading.Event()
    read_failed = threading.Event()

    def reader() -> None:
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    return
                available = maximum + 1 - len(data)
                if available > 0:
                    data.extend(chunk[:available])
                if len(data) > maximum:
                    overflow.set()
                    return
        except OSError:
            read_failed.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    while process.poll() is None and not overflow.is_set():
        if time.monotonic() >= deadline:
            timed_out = True
            break
        time.sleep(0.01)
    if timed_out or overflow.is_set():
        process.kill()
    try:
        returncode = process.wait(timeout=2)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait(timeout=2)
        raise SnapshotError("GIT_TIMEOUT") from exc
    finally:
        thread.join(2)
        if process.stdout is not None and not process.stdout.closed:
            process.stdout.close()
    if thread.is_alive() or read_failed.is_set():
        raise SnapshotError("GIT_CAPTURE_FAILED")
    if timed_out:
        raise SnapshotError("GIT_TIMEOUT")
    if overflow.is_set():
        raise SnapshotError("GIT_OUTPUT_LIMIT")
    if returncode != 0:
        raise SnapshotError("GIT_COMMAND_FAILED")
    return bytes(data)

