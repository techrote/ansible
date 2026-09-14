from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from ansible_kernel import isolation_composition as composition
from ansible_kernel import isolation_bwrap as bwrap
from ansible_kernel.contract import REGISTRY

GIT = shutil.which("git")
BWRAP = shutil.which("bwrap")
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "isolation_snapshot_probe.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output([GIT, "-C", str(repo), *args], text=True).strip()


@unittest.skipUnless(GIT, "git required")
class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="composition-test-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run([GIT, "init", "-q", str(self.repo)], check=True)
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Composition Test")
        shutil.copyfile(FIXTURE, self.repo / composition.ENTRYPOINT)
        git(self.repo, "add", composition.ENTRYPOINT)
        git(self.repo, "commit", "-qm", "probe")
        self.commit = git(self.repo, "rev-parse", "HEAD")
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        if os.name == "posix":
            os.chmod(self.state, 0o700)

    def tearDown(self):
        self.temp.cleanup()

    def test_registry_is_not_widened(self):
        self.assertEqual(set(REGISTRY), {"noop_v1", "omp_blind_review_v1"})
        self.assertFalse(REGISTRY["omp_blind_review_v1"].enabled)

    def test_fixed_snapshot_command_has_no_task_authority(self):
        with mock.patch.object(bwrap, "_bwrap_executable", return_value=Path("/usr/bin/bwrap")), \
             mock.patch.object(bwrap, "_probe_python"), \
             mock.patch.object(bwrap, "_system_mounts", return_value=["--ro-bind", "/usr", "/usr"]), \
             mock.patch.object(bwrap, "_ordinary_directory", side_effect=lambda path, code: Path(path)):
            out = self.root / "out"; out.mkdir()
            command = composition._build_command("baseline", self.repo, out, self.root / "secret")
        joined = "\0".join(command)
        self.assertIn("/input/" + composition.ENTRYPOINT, command)
        self.assertIn("--unshare-net", command)
        self.assertIn("--clearenv", command)
        self.assertNotIn("--share-net", command)
        for secret in ("GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY"):
            self.assertNotIn(secret, joined)
        with self.assertRaisesRegex(composition.CompositionError, "UNKNOWN_COMPOSITION_PROBE"):
            composition._build_command("arbitrary", self.repo, out, self.root / "secret")

    def test_invalid_identity_and_state_location_fail_before_execution(self):
        with self.assertRaisesRegex(composition.CompositionError, "COMPOSITION_IDENTITY_INVALID"):
            composition.qualify(self.state, "dashminimix", self.repo, self.commit[:12])
        inside = self.repo / "state"
        with self.assertRaisesRegex(composition.CompositionError, "STATE_ROOT_INSIDE_REPOSITORY"):
            composition.qualify(inside.absolute(), "dashminimix", self.repo.absolute(), self.commit)
        self.assertFalse(inside.exists())
        with self.assertRaisesRegex(composition.CompositionError, "UNKNOWN_REPOSITORY_IDENTIFIER"):
            composition.qualify(self.state.absolute(), "unknown", self.repo.absolute(), self.commit)

    def test_missing_entrypoint_fails_closed(self):
        (self.repo / composition.ENTRYPOINT).unlink()
        git(self.repo, "add", "-u")
        git(self.repo, "commit", "-qm", "remove")
        commit = git(self.repo, "rev-parse", "HEAD")
        with mock.patch.object(composition, "_mechanism", return_value={"available": True}):
            with self.assertRaisesRegex(composition.CompositionError, "COMPOSITION_ENTRYPOINT_INVALID"):
                composition.qualify(self.state.absolute(), "dashminimix", self.repo.absolute(), commit)

    def test_unsupported_profile_is_typed_not_success(self):
        with mock.patch.object(composition, "_mechanism", return_value={"available": False, "reason": "NOPE"}):
            result = composition.qualify(self.state.absolute(), "dashminimix", self.repo.absolute(), self.commit)
        self.assertFalse(result["composition_qualified"])
        self.assertEqual(result["reason"], "NOPE")
        self.assertFalse(result["runner_activation"])
        self.assertFalse(result["real_agent_qualified"])

    def test_malformed_and_oversized_results_are_refused(self):
        path = self.root / "bad-report"
        path.write_text('{"input_read":true}', encoding="ascii")
        with self.assertRaisesRegex(composition.CompositionError, "COMPOSITION_REPORT_INVALID"):
            composition._report_file(path)
        path.write_bytes(b"{" + b"x" * (composition.MAX_REPORT_BYTES + 1))
        with self.assertRaisesRegex(composition.CompositionError, "COMPOSITION_REPORT_INVALID"):
            composition._report_file(path)

    def test_snapshot_tampering_during_execution_fails_closed(self):
        original = bwrap._run_command
        calls = {"count": 0}
        def tamper(mode, command, wall):
            calls["count"] += 1
            # No live bwrap is required: tamper after preparation and force the
            # trusted post-run snapshot verifier to reject the changed bytes.
            snapshots = list((self.state / "worktrees").glob("*/*/*/content/" + composition.ENTRYPOINT))
            self.assertEqual(len(snapshots), 1)
            snapshots[0].write_text("tampered\n", encoding="ascii")
            return {"returncode": 0, "termination": "natural", "stdout": b"",
                    "stderr": b"", "surviving_descendants": [], "setup_error": None,
                    "elapsed_ms": 1, "mode": mode}
        with mock.patch.object(composition, "_mechanism", return_value={"available": True}), \
             mock.patch.object(composition, "_build_command", return_value=["fixed"]), \
             mock.patch.object(bwrap, "_run_command", side_effect=tamper):
            result = composition.qualify(self.state.absolute(), "dashminimix", self.repo.absolute(), self.commit)
        self.assertFalse(result["composition_qualified"])
        self.assertTrue(any(item["name"] == "composition_runtime" and not item["passed"]
                            for item in result["checks"]))
        self.assertEqual(calls["count"], 1)

    @unittest.skipUnless(sys.platform.startswith("linux") and BWRAP, "Bubblewrap Linux host required")
    def test_live_pinned_snapshot_composition(self):
        report = composition.qualify(self.state.absolute(), "dashminimix", self.repo.absolute(), self.commit)
        self.assertTrue(report["composition_qualified"], report)
        self.assertEqual(report["commit_sha"], self.commit)
        self.assertEqual(report["snapshot"]["commit_sha"], self.commit)
        self.assertEqual(report["snapshot"]["file_count"], 1)
        self.assertFalse(report["runner_activation"])
        self.assertFalse(report["real_agent_qualified"])
        self.assertTrue(all(item["passed"] for item in report["checks"]), report)
        self.assertEqual({item["name"] for item in report["checks"]}, {
            "snapshot_filesystem_network_credentials_pid", "output_bound",
            "deadline_descendant_containment", "memory_limit", "cpu_limit",
            "snapshot_identity_preserved", "ownership_bounded_cleanup"})


if __name__ == "__main__":
    unittest.main()
