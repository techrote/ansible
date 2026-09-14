from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from ansible_kernel import isolation_bwrap as iso

BWRAP = shutil.which("bwrap")


class IsolationProfileUnitTests(unittest.TestCase):
    def test_unknown_probe_is_refused_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = root / "a", root / "b"
            a.mkdir(); b.mkdir()
            with self.assertRaisesRegex(iso.IsolationError, "UNKNOWN_QUALIFICATION_PROBE"):
                iso.build_command("arbitrary-command", a, b, root / "secret")

    def test_non_linux_is_explicitly_unsupported(self):
        with mock.patch.object(iso.sys, "platform", "win32"):
            value = iso.availability()
        self.assertFalse(value["available"])
        self.assertEqual(value["reason"], "PROFILE_PLATFORM_UNSUPPORTED")

    def test_setup_failure_classifier_is_bounded_and_typed(self):
        self.assertEqual(iso._classify_setup_failure(b"bwrap: Creating new namespace failed: Operation not permitted"),
                         "USER_NAMESPACE_DENIED")
        self.assertEqual(iso._classify_setup_failure(b"bwrap: unknown option --future"),
                         "BWRAP_FEATURE_UNAVAILABLE")
        self.assertEqual(iso._classify_setup_failure(b"opaque failure"), "SANDBOX_SETUP_FAILED")

    def test_shared_boundary_builder_contains_fixed_security_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inp, out = root / "input", root / "output"
            inp.mkdir(); out.mkdir()
            with mock.patch.object(iso, "_bwrap_executable", return_value=Path("/usr/bin/bwrap")), \
                    mock.patch.object(iso, "_probe_python"), \
                    mock.patch.object(iso, "_system_mounts", return_value=["--ro-bind", "/usr", "/usr"]), \
                    mock.patch.object(iso, "_ordinary_directory", side_effect=lambda path, code: Path(path)):
                command = iso._boundary_command(inp, out)
        joined = "\0".join(command)
        for token in ("--unshare-user", "--disable-userns", "--unshare-pid", "--unshare-net",
                      "--unshare-ipc", "--unshare-uts", "--clearenv", "--new-session",
                      "--die-with-parent", "--cap-drop", "--ro-bind", "--bind"):
            self.assertIn(token, command)
        self.assertIn("/input", command)
        self.assertIn("/output", command)
        self.assertNotIn("--share-net", command)
        self.assertNotIn("GH_TOKEN", joined)
        self.assertNotIn("GITHUB_TOKEN", joined)

    def test_standalone_probe_delegates_to_shared_boundary(self):
        with mock.patch.object(iso, "_boundary_command", return_value=["bwrap", "--fixed"]) as boundary:
            command = iso.build_command("baseline", Path("/trusted/input"),
                                        Path("/trusted/output"), Path("/host/secret"))
        boundary.assert_called_once()
        self.assertEqual(command[:2], ["bwrap", "--fixed"])
        self.assertEqual(command[-3:], ["/probe.py", "baseline", "/host/secret"])

    @unittest.skipUnless(os.name == "posix", "symlink semantics require POSIX")
    def test_input_redirection_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(iso.IsolationError):
                iso._ordinary_directory(link, "INPUT_ROOT_INVALID")

    @unittest.skipUnless(sys.platform.startswith("linux") and BWRAP, "Bubblewrap Linux host required")
    def test_command_contains_fixed_security_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inp, out = root / "input", root / "output"
            inp.mkdir(); out.mkdir()
            command = iso.build_command("baseline", inp, out, root / "secret")
        joined = "\0".join(command)
        for token in ("--unshare-user", "--disable-userns", "--unshare-pid", "--unshare-net",
                      "--unshare-ipc", "--unshare-uts", "--clearenv", "--new-session",
                      "--die-with-parent", "--cap-drop", "--ro-bind", "--bind"):
            self.assertIn(token, command)
        self.assertIn("/probe.py", command)
        self.assertIn("/input", command)
        self.assertIn("/output", command)
        self.assertNotIn("--share-net", command)
        self.assertNotIn("GH_TOKEN", joined)
        self.assertNotIn("GITHUB_TOKEN", joined)


@unittest.skipUnless(sys.platform.startswith("linux") and BWRAP, "Bubblewrap Linux host required")
class IsolationProfileLiveTests(unittest.TestCase):
    def test_live_negative_qualification(self):
        with tempfile.TemporaryDirectory(prefix="bwrap-profile-test-") as directory:
            root = Path(directory)
            os.chmod(root, 0o700)
            report = iso.qualify(root)
        self.assertTrue(report["available"], report)
        self.assertTrue(report["profile_qualified"], report)
        self.assertFalse(report["real_agent_qualified"])
        self.assertFalse(report["runner_activation"])
        self.assertTrue(all(item["passed"] for item in report["checks"]), report)
        names = {item["name"] for item in report["checks"]}
        self.assertEqual(names, {"filesystem_network_credentials_pid", "output_bound",
                                 "deadline_descendant_containment", "memory_limit", "cpu_limit"})


if __name__ == "__main__":
    unittest.main()
