from __future__ import annotations

import hashlib
import json
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
        with mock.patch.object(bwrap, "_boundary_command",
                               return_value=["bwrap", "--fixed-boundary"]) as boundary:
            out = self.root / "out"; out.mkdir()
            command = composition._build_command("baseline", self.repo, out, self.root / "secret")
        boundary.assert_called_once_with(self.repo, out)
        self.assertEqual(command[:2], ["bwrap", "--fixed-boundary"])
        self.assertIn("/input/" + composition.ENTRYPOINT, command)
        self.assertEqual(command[-1], str((self.root / "secret").absolute()))
        with self.assertRaisesRegex(composition.CompositionError, "UNKNOWN_COMPOSITION_PROBE"):
            composition._build_command("arbitrary", self.repo, out, self.root / "secret")

    def test_trusted_probe_digest_matches_repository_fixture(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                         composition.TRUSTED_ENTRYPOINT_SHA256)

    def test_substituted_self_reporting_probe_is_refused_before_execution(self):
        target = self.repo / composition.ENTRYPOINT
        target.write_text(
            "from pathlib import Path\n"
            "Path('/output/report.json').write_text('\"fake\"')\n",
            encoding="ascii")
        git(self.repo, "add", composition.ENTRYPOINT)
        git(self.repo, "commit", "-qm", "substitute probe")
        commit = git(self.repo, "rev-parse", "HEAD")
        with mock.patch.object(composition, "_mechanism", return_value={"available": True}), \
                mock.patch.object(bwrap, "_run_command") as runner:
            with self.assertRaisesRegex(composition.CompositionError,
                                        "COMPOSITION_ENTRYPOINT_HASH_MISMATCH"):
                composition.qualify(self.state.absolute(), "dashminimix",
                                    self.repo.absolute(), commit)
        runner.assert_not_called()


    def test_invalid_identity_and_state_location_fail_before_execution(self):
        with self.assertRaisesRegex(composition.CompositionError, "COMPOSITION_IDENTITY_INVALID"):
            composition.qualify(self.state, "dashminimix", self.repo, self.commit[:12])
        inside = self.repo / "state"
        with self.assertRaisesRegex(composition.CompositionError, "STATE_ROOT_INSIDE_REPOSITORY"):
            composition.qualify(inside.absolute(), "dashminimix", self.repo.absolute(), self.commit)
        self.assertFalse(inside.exists())
        with self.assertRaisesRegex(composition.CompositionError, "UNKNOWN_REPOSITORY_IDENTIFIER"):
            composition.qualify(self.state.absolute(), "unknown", self.repo.absolute(), self.commit)
        trusted_ancestor = composition.Path(__file__).resolve().parents[2]
        with self.assertRaisesRegex(composition.CompositionError,
                                    "TRUSTED_CHECKOUT_INSIDE_STATE_ROOT"):
            composition._private_root(trusted_ancestor, self.repo.absolute())

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

    def test_setup_failure_cannot_qualify_with_incomplete_check_set(self):
        with mock.patch.object(composition, "_mechanism", return_value={"available": True}), \
                mock.patch.object(composition, "_build_command", return_value=["fixed"]), \
                mock.patch.object(bwrap, "_run_command",
                                  side_effect=bwrap.IsolationError("SANDBOX_SETUP_FAILED")):
            result = composition.qualify(self.state.absolute(), "dashminimix",
                                         self.repo.absolute(), self.commit)
        self.assertFalse(result["composition_qualified"])
        self.assertTrue(any(item["name"] == "composition_runtime" and not item["passed"]
                            for item in result["checks"]))
        self.assertNotEqual({item["name"] for item in result["checks"]},
                            composition.REQUIRED_CHECKS)

    def test_surviving_descendant_cannot_qualify(self):
        calls = []

        def fake_run(mode, command, wall):
            calls.append(mode)
            out = Path(command[command.index("--bind") + 1])
            if mode == "baseline":
                report = {key: True for key in composition.REQUIRED_BASELINE}
                (out / "report.json").write_text(json.dumps(report, sort_keys=True),
                                                  encoding="ascii")
                return {"returncode": 0, "termination": "natural", "stdout": b"",
                        "stderr": b"", "surviving_descendants": [], "setup_error": None,
                        "elapsed_ms": 1, "mode": mode}
            if mode == "flood":
                return {"returncode": -9, "termination": "output_limit", "stdout": b"",
                        "stderr": b"", "surviving_descendants": [], "setup_error": None,
                        "elapsed_ms": 1, "mode": mode}
            if mode == "hang":
                return {"returncode": -9, "termination": "timeout", "stdout": b"",
                        "stderr": b"", "surviving_descendants": [12345], "setup_error": None,
                        "elapsed_ms": 1, "mode": mode}
            if mode == "memory":
                return {"returncode": 42, "termination": "natural", "stdout": b"memory_limited\n",
                        "stderr": b"", "surviving_descendants": [], "setup_error": None,
                        "elapsed_ms": 1, "mode": mode}
            return {"returncode": -24, "termination": "natural", "stdout": b"cpu_probe_ready\n",
                    "stderr": b"", "surviving_descendants": [], "setup_error": None,
                    "elapsed_ms": 1, "mode": mode}

        def fake_build(mode, input_root, output_root, secret_path):
            return ["fixed", "--bind", str(output_root), "/output", mode]

        with mock.patch.object(composition, "_mechanism", return_value={"available": True}), \
                mock.patch.object(composition, "_build_command", side_effect=fake_build), \
                mock.patch.object(bwrap, "_run_command", side_effect=fake_run):
            result = composition.qualify(self.state.absolute(), "dashminimix",
                                         self.repo.absolute(), self.commit)
        self.assertEqual(calls, ["baseline", "flood", "hang", "memory", "cpu"])
        self.assertFalse(result["composition_qualified"])
        check = next(item for item in result["checks"]
                     if item["name"] == "deadline_descendant_containment")
        self.assertFalse(check["passed"])

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
        self.assertEqual(report["expected_entrypoint_sha256"],
                         composition.TRUSTED_ENTRYPOINT_SHA256)
        self.assertEqual(report["entrypoint_sha256"], composition.TRUSTED_ENTRYPOINT_SHA256)
        self.assertFalse(report["runner_activation"])
        self.assertFalse(report["real_agent_qualified"])
        self.assertFalse(report["deployment_qualified"])
        self.assertTrue(all(item["passed"] for item in report["checks"]), report)
        self.assertEqual({item["name"] for item in report["checks"]},
                         composition.REQUIRED_CHECKS)


if __name__ == "__main__":
    unittest.main()
