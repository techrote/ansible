import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("ci_evidence", Path(__file__).resolve().parents[1] / "tools" / "ci_evidence.py")
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


class CIEvidenceTests(unittest.TestCase):
    def test_exit_code_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(ci.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(ci.capture("tests", root), 7)
            record = json.loads((root / "ci-evidence/tests.exit.json").read_text())
            self.assertEqual(record, {"mode": "tests", "exit_code": 7})

    def test_launch_error_is_not_success(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(ci.subprocess, "run", side_effect=OSError("private path")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ci.capture("qualify", Path(temp)), 125)
            self.assertNotIn("private path", (Path(temp) / "ci-evidence/qualify.stderr.txt").read_text())

    def test_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(ci.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 480)):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ci.capture("tests", Path(temp)), 124)

    def test_only_fixed_commands(self):
        with self.assertRaises(ValueError):
            ci.capture("shell")

    def test_sha_field_is_not_arbitrary_environment(self):
        self.assertEqual(ci.safe_sha("a" * 40), "a" * 40)
        for value in ("", "A" * 40, "secret-token", "a" * 40 + "\n"):
            self.assertIsNone(ci.safe_sha(value))

    def test_bundle_provenance_and_fixed_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "ci-evidence"
            output.mkdir()
            (output / "source.tar").write_bytes(b"tracked source")
            (output / "secret.txt").write_text("do not include")
            with patch.object(ci.subprocess, "check_output", return_value="a" * 40 + "\n"), patch.object(ci.subprocess, "run") as run:
                with patch.dict(ci.os.environ, {"ANSIBLE_CI_HEAD_SHA": "b" * 40, "TOKEN": "secret"}):
                    ci.bundle(root)
            provenance = json.loads((output / "provenance.json").read_text())
            self.assertEqual(provenance["checkout_sha"], "a" * 40)
            self.assertEqual(provenance["requested_head_sha"], "b" * 40)
            self.assertFalse(provenance["real_agent_qualified"])
            self.assertNotIn("TOKEN", provenance)
            hashes = json.loads((output / "checksums.json").read_text())
            self.assertEqual(set(hashes), {"source.tar", "provenance.json"})
            self.assertEqual(hashes["source.tar"], hashlib.sha256(b"tracked source").hexdigest())
            self.assertEqual(run.call_args_list[-1].args[0][:3], ["git", "archive", "--format=tar"])

    def test_dirty_checkout_blocks_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(ci.subprocess, "check_output", return_value="a" * 40), patch.object(ci.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "git diff")):
                with self.assertRaises(subprocess.CalledProcessError):
                    ci.bundle(Path(temp))
            self.assertFalse((Path(temp) / "ci-evidence/provenance.json").exists())

class CIIsolationEvidenceTests(unittest.TestCase):
    def test_bundle_hashes_only_fixed_isolation_reports_when_present(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "ci-evidence"
            output.mkdir()
            (output / "isolation-linux-bwrap.json").write_bytes(b"linux")
            (output / "isolation-platform.json").write_bytes(b"platform")
            (output / "secret-isolation.json").write_bytes(b"secret")
            with patch.object(ci.subprocess, "check_output", return_value="a" * 40 + "\n"), \
                 patch.object(ci.subprocess, "run"):
                ci.bundle(root)
            hashes = json.loads((output / "checksums.json").read_text())
            self.assertIn("isolation-linux-bwrap.json", hashes)
            self.assertIn("isolation-platform.json", hashes)
            self.assertNotIn("secret-isolation.json", hashes)
