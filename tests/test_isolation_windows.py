from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import platform
import tempfile
import unittest
from unittest.mock import patch

from ansible_kernel import cli
from ansible_kernel.isolation_profiles import PROFILE_CONTRACTS, REGISTRY_CONTRACT, host_report
from ansible_kernel.isolation_windows import (
    PROFILE_CONTRACT,
    WindowsIsolationError,
    availability,
    windows_sandbox_config,
)


class WindowsIsolationProfileTests(unittest.TestCase):
    def test_registry_includes_existing_linux_and_windows_without_activation(self):
        self.assertIn("ansible.isolation.linux-bwrap.v1", PROFILE_CONTRACTS)
        self.assertIn(PROFILE_CONTRACT, PROFILE_CONTRACTS)
        with patch("ansible_kernel.isolation_profiles.platform.system", return_value="Other"):
            report = host_report()
        self.assertEqual(report["registry_contract"], REGISTRY_CONTRACT)
        self.assertFalse(report["runner_activation"])
        self.assertFalse(report["real_agent_qualified"])

    def test_windows_config_explicitly_disables_risky_redirections(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate, reference, result = (root / name for name in ("candidate", "reference", "result"))
            for directory in (candidate, reference, result):
                directory.mkdir()
            xml = windows_sandbox_config(candidate, reference, result)
        for fragment in (
            "<VGpu>Disable</VGpu>", "<Networking>Disable</Networking>",
            "<AudioInput>Disable</AudioInput>", "<VideoInput>Disable</VideoInput>",
            "<ProtectedClient>Enable</ProtectedClient>",
            "<PrinterRedirection>Disable</PrinterRedirection>",
            "<ClipboardRedirection>Disable</ClipboardRedirection>",
        ):
            self.assertIn(fragment, xml)
        self.assertEqual(xml.count("<ReadOnly>true</ReadOnly>"), 2)
        self.assertEqual(xml.count("<ReadOnly>false</ReadOnly>"), 1)
        self.assertNotIn("<Networking>Enable", xml)

    def test_windows_config_refuses_relative_or_redirected_host_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "candidate"; candidate.mkdir()
            reference = root / "reference"; reference.mkdir()
            result = root / "result"; result.mkdir()
            with self.assertRaises(WindowsIsolationError):
                windows_sandbox_config(Path("relative"), reference, result)
            link = root / "candidate-link"
            try:
                link.symlink_to(candidate, target_is_directory=True)
            except OSError:
                return
            with self.assertRaises(WindowsIsolationError):
                windows_sandbox_config(link, reference, result)

    def test_missing_windows_cli_is_explicitly_unqualified(self):
        with patch("ansible_kernel.isolation_windows.platform.system", return_value="Windows"), \
             patch("ansible_kernel.isolation_windows.shutil.which", return_value=None):
            report = availability()
        self.assertEqual(report["profile_contract"], PROFILE_CONTRACT)
        self.assertFalse(report["available"])
        self.assertFalse(report["profile_qualified"])
        self.assertFalse(report["deployment_qualified"])
        self.assertFalse(report["real_agent_qualified"])
        self.assertEqual(report["reason"], "WINDOWS_SANDBOX_CLI_UNAVAILABLE")

    def test_present_cli_still_does_not_claim_live_qualification(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "wsb.exe"
            binary.write_bytes(b"fixed-test-wsb")
            binary.chmod(0o700)
            with patch("ansible_kernel.isolation_windows.platform.system", return_value="Windows"), \
                 patch("ansible_kernel.isolation_windows.shutil.which", return_value=str(binary)):
                report = availability()
        self.assertTrue(report["available"])
        self.assertFalse(report["profile_qualified"])
        self.assertFalse(report["runner_activation"])
        self.assertEqual(report["reason"], "WINDOWS_LIVE_NEGATIVE_PROBE_NOT_RUN")
        self.assertEqual(report["mechanism"]["sha256"], hashlib.sha256(b"fixed-test-wsb").hexdigest())

    def test_generic_cli_reports_capability_without_creating_runner_authority(self):
        value = {"registry_contract": REGISTRY_CONTRACT, "implementation_version": "0.2.5",
                 "profile_contract": PROFILE_CONTRACT, "platform": "Windows",
                 "available": False, "profile_qualified": False,
                 "runner_activation": False, "real_agent_qualified": False,
                 "deployment_qualified": False, "reason": "WINDOWS_SANDBOX_CLI_UNAVAILABLE"}
        with patch.object(cli, "isolation_host_report", return_value=value), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = cli.main(["isolation"])
        self.assertEqual(code, 0)
        actual = json.loads(output.getvalue())
        self.assertFalse(actual["profile_qualified"])
        self.assertFalse(actual["runner_activation"])

    def test_linux_generic_status_delegates_to_existing_profile_availability(self):
        existing = {"profile_contract": "ansible.isolation.linux-bwrap.v1",
                    "available": True, "platform": "Linux", "kernel": "test-kernel",
                    "bwrap_path": "/usr/bin/bwrap", "bwrap_version": "bubblewrap 0.9.0"}
        with patch("ansible_kernel.isolation_profiles.platform.system", return_value="Linux"), \
             patch("ansible_kernel.isolation_profiles.linux_availability", return_value=existing):
            report = host_report()
        self.assertTrue(report["available"])
        self.assertFalse(report["profile_qualified"])
        self.assertTrue(report["qualification_not_run"])
        self.assertEqual(report["qualification_command"], "run_isolation.py qualify")
        self.assertFalse(report["runner_activation"])


if __name__ == "__main__":
    unittest.main()
