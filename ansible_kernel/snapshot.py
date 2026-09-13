"""Exact inert Git snapshot preparation for later isolated execution.

This module deliberately does not perform checkout, merge, submodule, LFS, hook,
filter, credential-helper or remote operations. It reads exact local commit/tree/blob
objects from an operator-approved repository and publishes only verified bytes under
private Ansible state.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import uuid

from .contract import canonical
from .state import Lock, StateError, plain, sync_directory, write_once
from .snapshot_common import (SNAPSHOT_VERSION, SnapshotError, _git_environment,
                              _git_executable, _ids, _private_directory, _repository,
                              _command, _run_bounded, MAX_TREE_BYTES)
from .snapshot_git import _extract_blobs, _tree_entries
from .snapshot_verify import _verify

class SnapshotManager:
    """Prepare and remove exact inert repository snapshots under private state."""

    def __init__(self, state_root: Path):
        self.state_root = Path(state_root).absolute()
        try:
            plain(self.state_root)
            self.state_root = self.state_root.resolve(strict=True)
        except (OSError, StateError) as exc:
            raise SnapshotError("STATE_ROOT_INVALID") from exc
        if not self.state_root.is_dir():
            raise SnapshotError("STATE_ROOT_INVALID")
        if os.name == "posix" and self.state_root.stat().st_mode & 0o077:
            raise SnapshotError("STATE_ROOT_PERMISSIONS_TOO_BROAD")
        self.root = self.state_root / "worktrees"
        _private_directory(self.root)
        self.lock_path = self.root / "snapshot.lock"

    def _path(self, job_id: str, repository_id: str, commit_sha: str) -> Path:
        return self.root / job_id / repository_id / commit_sha

    def verify(self, job_id: str, repository_id: str, commit_sha: str) -> dict:
        _ids(job_id, repository_id, commit_sha)
        return _verify(self._path(job_id, repository_id, commit_sha),
                       job_id, repository_id, commit_sha)

    def prepare(self, job_id: str, repository_id: str, repository_path: Path,
                commit_sha: str) -> dict:
        _ids(job_id, repository_id, commit_sha)
        repository = _repository(Path(repository_path))
        git = _git_executable()
        final = self._path(job_id, repository_id, commit_sha)
        with Lock(self.lock_path, timeout=5):
            if os.path.lexists(final):
                marker = _verify(final, job_id, repository_id, commit_sha)
                return {**marker, "snapshot_root": str(final),
                        "content_root": str(final / "content"), "idempotent": True}

            stage = self.root / f".prepare-{uuid.uuid4().hex}"
            _private_directory(stage)
            scratch = stage / "git-home"
            hooks = stage / "empty-hooks"
            content = stage / "content"
            _private_directory(scratch)
            _private_directory(hooks)
            _private_directory(content)
            try:
                env = _git_environment(scratch, git)
                command = _command(git, repository, hooks, "cat-file", "-t", commit_sha)
                if _run_bounded(command, env, 64).strip() != b"commit":
                    raise SnapshotError("NON_COMMIT_OBJECT_REFUSED")
                tree_raw = _run_bounded(
                    _command(git, repository, hooks, "ls-tree", "-r", "-z", "--full-tree",
                             commit_sha), env, MAX_TREE_BYTES)
                entries = _tree_entries(tree_raw)
                manifest, total = _extract_blobs(git, repository, hooks, env, entries, content)
                # The Git scratch area and hook override are host scaffolding, never
                # part of the published snapshot.
                shutil.rmtree(scratch)
                shutil.rmtree(hooks)
                marker = {
                    "snapshot_version": SNAPSHOT_VERSION,
                    "job_id": job_id,
                    "repository_id": repository_id,
                    "commit_sha": commit_sha,
                    "file_count": len(entries),
                    "total_bytes": total,
                    "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                }
                write_once(stage / "manifest.jsonl", manifest)
                write_once(stage / "snapshot.json", canonical(marker) + b"\n")
                _verify(stage, job_id, repository_id, commit_sha)
                _private_directory(final.parent)
                if os.path.lexists(final):
                    existing = _verify(final, job_id, repository_id, commit_sha)
                    shutil.rmtree(stage)
                    return {**existing, "snapshot_root": str(final),
                            "content_root": str(final / "content"), "idempotent": True}
                os.replace(stage, final)
                sync_directory(final.parent)
                return {**marker, "snapshot_root": str(final),
                        "content_root": str(final / "content"), "idempotent": False}
            except Exception:
                if stage.exists():
                    try:
                        plain(stage)
                        if stage.parent == self.root and stage.name.startswith(".prepare-"):
                            shutil.rmtree(stage)
                    except (OSError, StateError):
                        pass
                raise

    def cleanup(self, job_id: str, repository_id: str, commit_sha: str) -> bool:
        _ids(job_id, repository_id, commit_sha)
        final = self._path(job_id, repository_id, commit_sha)
        with Lock(self.lock_path, timeout=5):
            if not os.path.lexists(final):
                return False
            _verify(final, job_id, repository_id, commit_sha)
            try:
                plain(final)
                if final.parent.parent.parent != self.root:
                    raise SnapshotError("SNAPSHOT_CLEANUP_BOUNDARY")
                shutil.rmtree(final)
                sync_directory(final.parent)
                for parent in (final.parent, final.parent.parent):
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                return True
            except StateError as exc:
                raise SnapshotError("SNAPSHOT_CLEANUP_BOUNDARY") from exc
