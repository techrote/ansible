"""Exact Git tree/blob extraction and snapshot verification."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import threading

from .contract import canonical
from .state import plain, sync_directory
from .snapshot_common import (
    MAX_FILES, MAX_FILE_BYTES, MAX_MANIFEST_BYTES, MAX_TOTAL_BYTES, MAX_TREE_BYTES,
    GIT_TIMEOUT_SECONDS, OID_RE, SnapshotError, _Entry, _ids, _popen,
    _repository_relative_path, _command,
)

def _tree_entries(raw: bytes) -> list[_Entry]:
    if len(raw) > MAX_TREE_BYTES:
        raise SnapshotError("TREE_LISTING_TOO_LARGE")
    if raw and not raw.endswith(b"\0"):
        raise SnapshotError("MALFORMED_TREE_LISTING")
    entries: list[_Entry] = []
    keys: list[str] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        if b"\t" not in record:
            raise SnapshotError("MALFORMED_TREE_LISTING")
        metadata, raw_path = record.split(b"\t", 1)
        fields = metadata.split(b" ")
        if len(fields) != 3:
            raise SnapshotError("MALFORMED_TREE_LISTING")
        raw_mode, raw_type, raw_oid = fields
        try:
            path = raw_path.decode("ascii")
            mode = raw_mode.decode("ascii")
            object_type = raw_type.decode("ascii")
            oid = raw_oid.decode("ascii")
        except UnicodeDecodeError as exc:
            raise SnapshotError("UNSAFE_TREE_PATH") from exc
        _repository_relative_path(path)
        if OID_RE.fullmatch(oid) is None:
            raise SnapshotError("INVALID_GIT_OBJECT_ID")
        if mode == "120000":
            raise SnapshotError("SYMLINK_ENTRY_REFUSED")
        if mode == "160000" or object_type == "commit":
            raise SnapshotError("GITLINK_ENTRY_REFUSED")
        if mode not in {"100644", "100755"} or object_type != "blob":
            raise SnapshotError("UNSUPPORTED_TREE_ENTRY")
        entries.append(_Entry(path, mode, oid))
        keys.append("/".join(part.casefold() for part in path.split("/")))
        if len(entries) > MAX_FILES:
            raise SnapshotError("TOO_MANY_SNAPSHOT_FILES")
    ordered = sorted(keys)
    for previous, current in zip(ordered, ordered[1:]):
        if current == previous or current.startswith(previous + "/"):
            raise SnapshotError("CASE_OR_PREFIX_COLLISION")
    return entries


def _safe_file_open(path: Path):
    plain(path)
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_BINARY", 0))
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SnapshotError("SNAPSHOT_FILE_INVALID")
        return os.fdopen(fd, "wb")
    except BaseException:
        os.close(fd)
        raise


def _extract_blobs(git: str, repository: Path, hooks: Path, env: dict[str, str],
                   entries: list[_Entry], content: Path) -> tuple[bytes, int]:
    command = _command(git, repository, hooks, "cat-file", "--batch")
    process = _popen(command, env, stdin=subprocess.PIPE)
    errors: list[BaseException] = []
    manifest = bytearray()
    total = 0

    def work() -> None:
        nonlocal total
        try:
            assert process.stdin is not None and process.stdout is not None
            for entry in entries:
                process.stdin.write(entry.oid.encode("ascii") + b"\n")
                process.stdin.flush()
                header = process.stdout.readline(256)
                if not header.endswith(b"\n") or len(header) >= 256:
                    raise SnapshotError("MALFORMED_CAT_FILE_HEADER")
                parts = header[:-1].split(b" ")
                if len(parts) != 3:
                    raise SnapshotError("MALFORMED_CAT_FILE_HEADER")
                raw_oid, object_type, raw_size = parts
                if raw_oid.decode("ascii", "strict") != entry.oid or object_type != b"blob":
                    raise SnapshotError("GIT_OBJECT_IDENTITY_MISMATCH")
                try:
                    size = int(raw_size)
                except ValueError as exc:
                    raise SnapshotError("MALFORMED_CAT_FILE_HEADER") from exc
                if size < 0 or size > MAX_FILE_BYTES:
                    raise SnapshotError("SNAPSHOT_FILE_TOO_LARGE")
                if total + size > MAX_TOTAL_BYTES:
                    raise SnapshotError("SNAPSHOT_TOTAL_TOO_LARGE")

                target = content / Path(entry.path)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                plain(target.parent)
                digest = hashlib.sha256()
                remaining = size
                with _safe_file_open(target) as handle:
                    while remaining:
                        chunk = process.stdout.read(min(65536, remaining))
                        if not chunk:
                            raise SnapshotError("TRUNCATED_GIT_BLOB")
                        handle.write(chunk)
                        digest.update(chunk)
                        remaining -= len(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                if process.stdout.read(1) != b"\n":
                    raise SnapshotError("MALFORMED_CAT_FILE_BODY")
                os.chmod(target, 0o700 if entry.mode == "100755" else 0o600)
                sync_directory(target.parent)
                total += size
                line = canonical({"path": entry.path, "mode": entry.mode,
                                  "blob_oid": entry.oid, "size": size,
                                  "sha256": digest.hexdigest()}) + b"\n"
                if len(manifest) + len(line) > MAX_MANIFEST_BYTES:
                    raise SnapshotError("SNAPSHOT_MANIFEST_TOO_LARGE")
                manifest.extend(line)
            process.stdin.close()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(GIT_TIMEOUT_SECONDS)
    if thread.is_alive():
        process.kill()
        thread.join(2)
        for stream in (process.stdin, process.stdout):
            if stream is not None and not stream.closed:
                stream.close()
        raise SnapshotError("GIT_TIMEOUT")
    if errors:
        process.kill()
        process.wait(timeout=2)
        for stream in (process.stdin, process.stdout):
            if stream is not None and not stream.closed:
                stream.close()
        error = errors[0]
        if isinstance(error, SnapshotError):
            raise error
        raise SnapshotError("SNAPSHOT_IO_FAILURE") from error
    try:
        returncode = process.wait(timeout=2)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait(timeout=2)
        raise SnapshotError("GIT_TIMEOUT") from exc
    finally:
        for stream in (process.stdin, process.stdout):
            if stream is not None and not stream.closed:
                stream.close()
    if returncode != 0:
        raise SnapshotError("GIT_COMMAND_FAILED")
    return bytes(manifest), total

