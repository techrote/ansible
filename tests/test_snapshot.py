from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from ansible_kernel.snapshot import SnapshotError, SnapshotManager
from ansible_kernel.snapshot_git import _tree_entries

GIT = shutil.which("git")
JOB = "a" * 32


def run_git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run([GIT, "-C", str(repo), *args], input=input_bytes,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return result.stdout.strip()


@unittest.skipUnless(GIT, "git required")
class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="snapshot-test-")
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        subprocess.run([GIT, "init", "-q", str(self.repo)], check=True)
        run_git(self.repo, "config", "user.email", "test@example.invalid")
        run_git(self.repo, "config", "user.name", "Snapshot Test")
        (self.repo / "plain.txt").write_bytes(b"exact bytes\n")
        (self.repo / "script.sh").write_bytes(b"#!/bin/sh\necho ok\n")
        run_git(self.repo, "add", "plain.txt", "script.sh")
        run_git(self.repo, "update-index", "--chmod=+x", "script.sh")
        run_git(self.repo, "commit", "-qm", "base")
        self.commit = run_git(self.repo, "rev-parse", "HEAD").decode()
        self.state = self.base / "state"
        self.state.mkdir(mode=0o700)
        if os.name == "posix":
            os.chmod(self.state, 0o700)
        self.manager = SnapshotManager(self.state)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_bytes_mode_provenance_idempotence_and_cleanup(self):
        first = self.manager.prepare(JOB, "dashminimix", self.repo, self.commit)
        content = Path(first["content_root"])
        self.assertEqual((content / "plain.txt").read_bytes(), b"exact bytes\n")
        self.assertEqual((content / "script.sh").read_bytes(), b"#!/bin/sh\necho ok\n")
        marker = self.manager.verify(JOB, "dashminimix", self.commit)
        self.assertEqual(marker["commit_sha"], self.commit)
        self.assertEqual(marker["file_count"], 2)
        self.assertFalse(first["idempotent"])
        if os.name == "posix":
            self.assertTrue((content / "script.sh").stat().st_mode & 0o111)
            self.assertFalse((content / "plain.txt").stat().st_mode & 0o111)
        marker_before = (Path(first["snapshot_root"]) / "snapshot.json").read_bytes()
        second = self.manager.prepare(JOB, "dashminimix", self.repo, self.commit)
        self.assertTrue(second["idempotent"])
        self.assertEqual((Path(first["snapshot_root"]) / "snapshot.json").read_bytes(), marker_before)
        sibling = self.manager.root / "do-not-delete"
        sibling.write_text("sentinel", encoding="ascii")
        self.assertTrue(self.manager.cleanup(JOB, "dashminimix", self.commit))
        self.assertTrue(sibling.exists())
        self.assertFalse(self.manager.cleanup(JOB, "dashminimix", self.commit))

    def test_checkout_filter_and_hook_configuration_are_never_invoked(self):
        (self.repo / ".gitattributes").write_text("*.txt filter=evil\n", encoding="ascii")
        run_git(self.repo, "add", ".gitattributes")
        run_git(self.repo, "commit", "-qm", "attributes")
        commit = run_git(self.repo, "rev-parse", "HEAD").decode()
        run_git(self.repo, "config", "filter.evil.smudge", "ansible-command-that-must-not-exist")
        run_git(self.repo, "config", "filter.evil.required", "true")
        hooks = self.base / "hooks"
        hooks.mkdir()
        hook = hooks / "post-checkout"
        hook.write_text("#!/bin/sh\nexit 97\n", encoding="ascii")
        if os.name == "posix":
            hook.chmod(0o700)
        run_git(self.repo, "config", "core.hooksPath", str(hooks))
        prepared = self.manager.prepare(JOB, "dashminimix", self.repo, commit)
        self.assertEqual((Path(prepared["content_root"]) / "plain.txt").read_bytes(), b"exact bytes\n")

    def _commit_tree(self, listing: bytes) -> str:
        tree = run_git(self.repo, "mktree", input_bytes=listing).decode()
        return run_git(self.repo, "commit-tree", tree, "-m", "synthetic").decode()

    def test_symlink_and_gitlink_entries_are_refused(self):
        blob = run_git(self.repo, "hash-object", "-w", "--stdin", input_bytes=b"target").decode()
        symlink_commit = self._commit_tree(f"120000 blob {blob}\tlink\n".encode())
        with self.assertRaisesRegex(SnapshotError, "SYMLINK_ENTRY_REFUSED"):
            self.manager.prepare(JOB, "dashminimix", self.repo, symlink_commit)
        gitlink_commit = self._commit_tree(f"160000 commit {self.commit}\tsubmodule\n".encode())
        with self.assertRaisesRegex(SnapshotError, "GITLINK_ENTRY_REFUSED"):
            self.manager.prepare(JOB, "dashminimix", self.repo, gitlink_commit)

    def test_case_collision_is_refused_before_writes(self):
        blob = run_git(self.repo, "hash-object", "-w", "--stdin", input_bytes=b"x").decode()
        commit = self._commit_tree(
            f"100644 blob {blob}\tA.txt\n100644 blob {blob}\ta.txt\n".encode())
        with self.assertRaisesRegex(SnapshotError, "CASE_OR_PREFIX_COLLISION"):
            self.manager.prepare(JOB, "dashminimix", self.repo, commit)

    def test_wrong_identifiers_noncommit_and_oversized_blob_fail_closed(self):
        with self.assertRaisesRegex(SnapshotError, "INVALID_COMMIT_ID"):
            self.manager.prepare(JOB, "dashminimix", self.repo, self.commit[:12])
        with self.assertRaisesRegex(SnapshotError, "UNKNOWN_REPOSITORY_IDENTIFIER"):
            self.manager.prepare(JOB, "other", self.repo, self.commit)
        blob = run_git(self.repo, "hash-object", "-w", "--stdin", input_bytes=b"blob-only").decode()
        with self.assertRaisesRegex(SnapshotError, "NON_COMMIT_OBJECT_REFUSED"):
            self.manager.prepare(JOB, "dashminimix", self.repo, blob)
        with mock.patch("ansible_kernel.snapshot_git.MAX_FILE_BYTES", 4):
            with self.assertRaisesRegex(SnapshotError, "SNAPSHOT_FILE_TOO_LARGE"):
                self.manager.prepare("b" * 32, "dashminimix", self.repo, self.commit)

    def test_alternate_object_database_and_linked_metadata_are_refused(self):
        info = self.repo / ".git" / "objects" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "alternates").write_text(str(self.base), encoding="ascii")
        with self.assertRaisesRegex(SnapshotError, "ALTERNATE_OBJECT_DATABASE_REFUSED"):
            self.manager.prepare(JOB, "dashminimix", self.repo, self.commit)
        (info / "alternates").unlink()
        fake = self.base / "linked"
        fake.mkdir()
        (fake / ".git").write_text("gitdir: ../repo/.git\n", encoding="ascii")
        with self.assertRaisesRegex(SnapshotError, "GIT_METADATA_LAYOUT_UNSUPPORTED"):
            self.manager.prepare(JOB, "dashminimix", fake, self.commit)

    def test_tampered_marker_blocks_cleanup(self):
        prepared = self.manager.prepare(JOB, "dashminimix", self.repo, self.commit)
        marker_path = Path(prepared["snapshot_root"]) / "snapshot.json"
        value = json.loads(marker_path.read_text(encoding="ascii"))
        value["job_id"] = "b" * 32
        marker_path.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
                               encoding="ascii")
        with self.assertRaises(SnapshotError):
            self.manager.cleanup(JOB, "dashminimix", self.commit)
        self.assertTrue(Path(prepared["snapshot_root"]).exists())

    def test_manifest_or_content_tampering_blocks_idempotence(self):
        prepared = self.manager.prepare(JOB, "dashminimix", self.repo, self.commit)
        content = Path(prepared["content_root"])
        (content / "plain.txt").write_bytes(b"changed\n")
        with self.assertRaises(SnapshotError):
            self.manager.prepare(JOB, "dashminimix", self.repo, self.commit)

    def test_malformed_tree_parser_and_git_path_component_are_refused(self):
        with self.assertRaisesRegex(SnapshotError, "MALFORMED_TREE_LISTING"):
            _tree_entries(b"not-a-record\0")
        oid = "1" * 40
        with self.assertRaisesRegex(SnapshotError, "GIT_PATH_COMPONENT_REFUSED"):
            _tree_entries(f"100644 blob {oid}\t.git/config\0".encode())

    def test_dotfiles_spaces_and_prefix_collision_policy(self):
        oid = "1" * 40
        entries = _tree_entries(
            f"100644 blob {oid}\t.gitattributes\0".encode()
            + f"100644 blob {oid}\tdir/file name.txt\0".encode())
        self.assertEqual([entry.path for entry in entries], [".gitattributes", "dir/file name.txt"])
        with self.assertRaisesRegex(SnapshotError, "CASE_OR_PREFIX_COLLISION"):
            _tree_entries(
                f"100644 blob {oid}\tDir\0".encode()
                + f"100644 blob {oid}\tdir/file.txt\0".encode())

    def test_hardlinked_content_blocks_cleanup_when_supported(self):
        prepared = self.manager.prepare(JOB, "dashminimix", self.repo, self.commit)
        content = Path(prepared["content_root"])
        victim = content / "plain.txt"
        victim.unlink()
        try:
            os.link(content / "script.sh", victim)
        except OSError:
            self.skipTest("hard links unavailable")
        with self.assertRaises(SnapshotError):
            self.manager.cleanup(JOB, "dashminimix", self.commit)
        self.assertTrue(Path(prepared["snapshot_root"]).exists())


if __name__ == "__main__":
    unittest.main()
