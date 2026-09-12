"""Single-writer, append-only state with OS locks and fail-closed replay.

The OS user and local checkout are trusted. This is not a defence against a
malicious process already running as that user; see docs/SECURITY.md.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import os
from pathlib import Path
import re
import stat
import time
import uuid

from .contract import canonical, check, decode, Refusal


class StateError(RuntimeError):
    pass


def plain(path: Path) -> None:
    path = path.absolute()
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise StateError("PATH_REDIRECTION_REFUSED")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise StateError("HARDLINK_REFUSED")


def opened(path: Path, flags: int):
    plain(path)
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise StateError("NONREGULAR_STATE_FILE")
    return fd


def sync_directory(path: Path) -> None:
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def read_bytes(path: Path, maximum: int = 65536) -> bytes:
    fd = opened(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as handle:
        raw = handle.read(maximum + 1)
    if len(raw) > maximum:
        raise StateError("STATE_SIZE_LIMIT")
    return raw


def write_once(path: Path, raw: bytes) -> None:
    fd = opened(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    sync_directory(path.parent)


class Lock(AbstractContextManager):
    def __init__(self, path: Path, timeout: float = 0):
        self.path, self.fd, self.timeout = path, None, timeout

    def __enter__(self):
        self.fd = opened(self.path, os.O_CREAT | os.O_RDWR)
        if os.fstat(self.fd).st_size == 0:
            os.write(self.fd, b"0")
            os.fsync(self.fd)
        os.lseek(self.fd, 0, os.SEEK_SET)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() < deadline:
                    time.sleep(0.005)
                    continue
                os.close(self.fd)
                self.fd = None
                raise StateError("LOCK_BUSY") from exc
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None


def journal(path: Path) -> list[dict]:
    try:
        raw = read_bytes(path, 16 * 1024 * 1024)
    except FileNotFoundError:
        return []
    if raw and not raw.endswith(b"\n"):
        raise StateError("TORN_JOURNAL")
    rows, previous = [], "0" * 64
    try:
        for number, line in enumerate(raw.splitlines(), 1):
            row = decode(line)
            if (type(row) is not dict or set(row) != {"seq", "prev", "event", "sha256"}
                    or type(row["seq"]) is not int or row["seq"] != number
                    or row["prev"] != previous or type(row["event"]) is not dict):
                raise StateError("INVALID_JOURNAL")
            payload = {key: row[key] for key in ("seq", "prev", "event")}
            expected = hashlib.sha256(canonical(payload)).hexdigest()
            if row["sha256"] != expected:
                raise StateError("JOURNAL_HASH_MISMATCH")
            previous = expected
            rows.append(row["event"])
    except (Refusal, KeyError, TypeError) as exc:
        raise StateError("INVALID_JOURNAL") from exc
    return rows


def append(path: Path, event: dict) -> None:
    rows = journal(path)
    previous = "0" * 64
    if rows:
        previous = decode(read_bytes(path, 16 * 1024 * 1024).splitlines()[-1])["sha256"]
    payload = {"seq": len(rows) + 1, "prev": previous, "event": event}
    line = canonical({**payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()}) + b"\n"
    if len(line) > 65536:
        raise StateError("EVENT_TOO_LARGE")
    if path.exists() and path.stat().st_size + len(line) > 16 * 1024 * 1024:
        raise StateError("JOURNAL_CAPACITY_REACHED")
    fd = opened(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    with os.fdopen(fd, "ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    sync_directory(path.parent)


TERMINAL = frozenset({"completed", "failed", "cancelled", "contained", "timeout", "rejected"})
TRANSITIONS = {
    None: {"created"}, "created": {"validated", "rejected", "failed"},
    "validated": {"admitted", "rejected", "failed"},
    "admitted": {"starting", "failed", "cancelled", "contained"},
    "starting": {"running", "failed", "cancelled", "contained", "timeout"},
    "running": {"cancelling", "completed", "failed", "cancelled", "contained", "timeout"},
    "cancelling": {"cancelled", "contained", "failed", "timeout"},
}


class Store:
    def __init__(self, root: Path | None = None):
        if root is None:
            if os.name == "nt":
                local = os.environ.get("LOCALAPPDATA")
                if not local:
                    raise StateError("LOCALAPPDATA_UNAVAILABLE")
                root = Path(local) / "techrote-ansible"
            else:
                root = Path.home() / ".local" / "state" / "techrote-ansible"
        self.root = Path(root).absolute()
        plain(self.root)
        self.root = self.root.resolve()
        checkout = Path(__file__).resolve().parent.parent
        if self.root.is_relative_to(checkout):
            raise StateError("STATE_INSIDE_TRUSTED_CHECKOUT")
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if os.name == "posix" and self.root.stat().st_mode & 0o077:
            raise StateError("STATE_PERMISSIONS_TOO_BROAD")
        self.runs = self.root / "runs"
        plain(self.runs)
        self.runs.mkdir(mode=0o700, exist_ok=True)
        self.ledger = self.root / "ledger.jsonl"

    def lock(self) -> Lock:
        return Lock(self.root / "kernel.lock")

    def job(self, job_id: str) -> Path:
        if type(job_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise StateError("INVALID_JOB_ID")
        path = self.runs / job_id
        plain(path)
        return path

    def new_job(self, metadata: dict) -> str:
        job_id = uuid.uuid4().hex
        path = self.job(job_id)
        path.mkdir(mode=0o700)
        (path / "work").mkdir(mode=0o700)
        write_once(path / "metadata.json", canonical(metadata) + b"\n")
        self.transition(job_id, "created")
        return job_id

    def events(self, job_id: str) -> list[dict]:
        rows = journal(self.job(job_id) / "status.jsonl")
        previous = None
        for row in rows:
            if (not {"state", "time_ns"} <= row.keys()
                    or row.keys() - {"state", "time_ns", "result"}
                    or type(row["state"]) is not str
                    or type(row["time_ns"]) is not int
                    or row["time_ns"] <= 0
                    or row["state"] not in TRANSITIONS.get(previous, set())):
                raise StateError("INVALID_LIFECYCLE_RECORD")
            if "result" in row and row["state"] not in TERMINAL:
                raise StateError("PREMATURE_RESULT_RECORD")
            previous = row["state"]
        return rows

    def transition(self, job_id: str, state: str, **details) -> None:
        rows = self.events(job_id)
        old = rows[-1]["state"] if rows else None
        if state not in TRANSITIONS.get(old, set()):
            raise StateError("INVALID_STATE_TRANSITION")
        append(self.job(job_id) / "status.jsonl",
               {"state": state, "time_ns": time.time_ns(), **details})

    def control_lock(self, job_id: str) -> Lock:
        if not self.job(job_id).is_dir():
            raise StateError("UNKNOWN_JOB")
        return Lock(self.job(job_id) / "control.lock", timeout=2)

    def stop_reason(self, job_id: str) -> str | None:
        for name, result in (("contain", "contained"), ("cancel", "cancelled")):
            try:
                data = read_bytes(self.job(job_id) / name, 16)
            except FileNotFoundError:
                continue
            if data != b"":
                raise StateError("INVALID_CONTROL_RECORD")
            return result
        return None

    def control(self, job_id: str, action: str) -> str:
        if action not in ("cancel", "contain"):
            raise StateError("UNKNOWN_CONTROL")
        with self.control_lock(job_id):
            rows = self.events(job_id)
            if not rows or rows[-1]["state"] in TERMINAL:
                raise StateError("JOB_NOT_ACTIVE")
            try:
                write_once(self.job(job_id) / action, b"")
            except FileExistsError:
                pass
        # Receipt is NOT proof that the process was terminated.
        return "requested"

    def verify_evidence(self, job_id: str) -> str:
        path = self.job(job_id)
        try:
            manifest = decode(read_bytes(path / "manifest.json"))
            if type(manifest) is not dict or set(manifest) != {"worker.json", "provider.json"}:
                return "invalid"
            for name, expected in manifest.items():
                if hashlib.sha256(read_bytes(path / name)).hexdigest() != expected:
                    return "invalid"
            return "complete"
        except FileNotFoundError:
            return "missing"
        except (Refusal, StateError, OSError):
            return "invalid"

    def result(self, job_id: str) -> dict | None:
        rows = self.events(job_id)
        if not rows or rows[-1]["state"] not in TERMINAL:
            return None
        result = rows[-1].get("result")
        try:
            check(result, "result-v1.schema.json")
        except Refusal as exc:
            raise StateError("INVALID_TERMINAL_RECORD") from exc
        if result["job_id"] != job_id:
            raise StateError("WRONG_JOB_RESULT")
        if result["worker_outcome"] == "success":
            evidence = self.verify_evidence(job_id)
            if evidence != "complete":
                return {**result, "worker_outcome": "invalid_result", "evidence": evidence,
                        "reason": "EVIDENCE_REVALIDATION_FAILED"}
        return result

    def statuses(self) -> list[dict]:
        values = []
        for path in sorted(self.runs.iterdir()):
            if not re.fullmatch(r"[0-9a-f]{32}", path.name):
                continue
            try:
                rows = self.events(path.name)
                values.append({"job_id": path.name, "state": rows[-1]["state"] if rows else "unknown",
                               "result": self.result(path.name), "time_ns": rows[-1].get("time_ns", 0) if rows else 0})
            except (StateError, OSError):
                values.append({"job_id": path.name, "state": "unreadable", "result": None})
        return values
