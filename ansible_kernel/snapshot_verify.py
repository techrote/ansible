"""Verification for published inert Git snapshots."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

from .contract import decode
from .state import StateError, plain, read_bytes
from .snapshot_common import (MAX_FILES, MAX_FILE_BYTES, MAX_MANIFEST_BYTES,
                              MAX_TOTAL_BYTES, OID_RE, SNAPSHOT_VERSION,
                              SnapshotError, _ids, _repository_relative_path)

def _marker(raw: bytes) -> dict:
    try:
        value = decode(raw)
    except Exception as exc:
        raise SnapshotError("SNAPSHOT_METADATA_INVALID") from exc
    keys = {"snapshot_version", "job_id", "repository_id", "commit_sha",
            "file_count", "total_bytes", "manifest_sha256"}
    if type(value) is not dict or set(value) != keys:
        raise SnapshotError("SNAPSHOT_METADATA_INVALID")
    if value["snapshot_version"] != SNAPSHOT_VERSION:
        raise SnapshotError("SNAPSHOT_METADATA_INVALID")
    try:
        _ids(value["job_id"], value["repository_id"], value["commit_sha"])
    except SnapshotError as exc:
        raise SnapshotError("SNAPSHOT_METADATA_INVALID") from exc
    if (type(value["file_count"]) is not int or not 0 <= value["file_count"] <= MAX_FILES
            or type(value["total_bytes"]) is not int
            or not 0 <= value["total_bytes"] <= MAX_TOTAL_BYTES
            or type(value["manifest_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["manifest_sha256"]) is None):
        raise SnapshotError("SNAPSHOT_METADATA_INVALID")
    return value


def _manifest(raw: bytes) -> list[dict]:
    if len(raw) > MAX_MANIFEST_BYTES or (raw and not raw.endswith(b"\n")):
        raise SnapshotError("SNAPSHOT_MANIFEST_INVALID")
    result = []
    keys = {"path", "mode", "blob_oid", "size", "sha256"}
    path_keys = []
    for line in raw.splitlines():
        try:
            item = decode(line)
        except Exception as exc:
            raise SnapshotError("SNAPSHOT_MANIFEST_INVALID") from exc
        if type(item) is not dict or set(item) != keys:
            raise SnapshotError("SNAPSHOT_MANIFEST_INVALID")
        try:
            _repository_relative_path(item["path"])
        except SnapshotError as exc:
            raise SnapshotError("SNAPSHOT_MANIFEST_INVALID") from exc
        if (item["mode"] not in {"100644", "100755"}
                or type(item["blob_oid"]) is not str or OID_RE.fullmatch(item["blob_oid"]) is None
                or type(item["size"]) is not int or not 0 <= item["size"] <= MAX_FILE_BYTES
                or type(item["sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise SnapshotError("SNAPSHOT_MANIFEST_INVALID")
        result.append(item)
        path_keys.append("/".join(p.casefold() for p in item["path"].split("/")))
        if len(result) > MAX_FILES:
            raise SnapshotError("SNAPSHOT_MANIFEST_INVALID")
    ordered = sorted(path_keys)
    for previous, current in zip(ordered, ordered[1:]):
        if current == previous or current.startswith(previous + "/"):
            raise SnapshotError("SNAPSHOT_MANIFEST_INVALID")
    return result


def _hash_file(path: Path, expected_size: int) -> str:
    try:
        plain(path)
        info = path.lstat()
    except (OSError, StateError) as exc:
        raise SnapshotError("SNAPSHOT_CONTENT_INVALID") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size != expected_size
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise SnapshotError("SNAPSHOT_CONTENT_INVALID")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _verify(snapshot: Path, job_id: str, repository_id: str, commit_sha: str) -> dict:
    try:
        plain(snapshot)
        if not snapshot.is_dir():
            raise SnapshotError("SNAPSHOT_NOT_FOUND")
        names = {child.name for child in snapshot.iterdir()}
        if names != {"content", "manifest.jsonl", "snapshot.json"}:
            raise SnapshotError("SNAPSHOT_CONTENT_INVALID")
        marker_raw = read_bytes(snapshot / "snapshot.json", 65536)
        marker = _marker(marker_raw)
        if (marker["job_id"], marker["repository_id"], marker["commit_sha"]) != (
                job_id, repository_id, commit_sha):
            raise SnapshotError("SNAPSHOT_OWNERSHIP_MISMATCH")
        manifest_raw = read_bytes(snapshot / "manifest.jsonl", MAX_MANIFEST_BYTES)
        if hashlib.sha256(manifest_raw).hexdigest() != marker["manifest_sha256"]:
            raise SnapshotError("SNAPSHOT_MANIFEST_HASH_MISMATCH")
        manifest = _manifest(manifest_raw)
        if len(manifest) != marker["file_count"]:
            raise SnapshotError("SNAPSHOT_CONTENT_INVALID")
        if sum(item["size"] for item in manifest) != marker["total_bytes"]:
            raise SnapshotError("SNAPSHOT_CONTENT_INVALID")
        content = snapshot / "content"
        plain(content)
        if not content.is_dir():
            raise SnapshotError("SNAPSHOT_CONTENT_INVALID")
        expected_files = {item["path"] for item in manifest}
        expected_dirs = set()
        for item in manifest:
            parts = item["path"].split("/")[:-1]
            for index in range(1, len(parts) + 1):
                expected_dirs.add("/".join(parts[:index]))
            target = content / Path(item["path"])
            if _hash_file(target, item["size"]) != item["sha256"]:
                raise SnapshotError("SNAPSHOT_CONTENT_HASH_MISMATCH")
            if os.name == "posix":
                executable = bool(target.stat().st_mode & 0o111)
                if executable != (item["mode"] == "100755"):
                    raise SnapshotError("SNAPSHOT_MODE_MISMATCH")
        expected_sizes = {item["path"]: item["size"] for item in manifest}
        actual_files, actual_dirs = set(), set()
        for root, dirs, files in os.walk(content, topdown=True, followlinks=False):
            root_path = Path(root)
            plain(root_path)
            for name in dirs:
                child = root_path / name
                plain(child)
                info = child.lstat()
                if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise SnapshotError("SNAPSHOT_CONTENT_INVALID")
                actual_dirs.add(child.relative_to(content).as_posix())
            for name in files:
                child = root_path / name
                rel = child.relative_to(content).as_posix()
                if rel not in expected_sizes:
                    raise SnapshotError("SNAPSHOT_CONTENT_INVALID")
                _hash_file(child, expected_sizes[rel])
                actual_files.add(rel)
                if len(actual_files) > MAX_FILES:
                    raise SnapshotError("SNAPSHOT_CONTENT_INVALID")
        if actual_files != expected_files or actual_dirs != expected_dirs:
            raise SnapshotError("SNAPSHOT_CONTENT_INVALID")
        return marker
    except FileNotFoundError as exc:
        raise SnapshotError("SNAPSHOT_NOT_FOUND") from exc
    except StateError as exc:
        raise SnapshotError("SNAPSHOT_CONTENT_INVALID") from exc

