from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ansible_kernel import isolation_composition as composition


class CompositionRefusalEvidenceTests(unittest.TestCase):
    def test_hash_mismatch_carries_only_bounded_observed_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b"print('self-reporting replacement')\n"
            (root / composition.ENTRYPOINT).write_bytes(raw)
            observed = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(composition.CompositionError) as caught:
                composition._entrypoint(root)
        self.assertEqual(caught.exception.code, "COMPOSITION_ENTRYPOINT_HASH_MISMATCH")
        self.assertEqual(caught.exception.entrypoint_sha256, observed)
        self.assertNotEqual(observed, composition.TRUSTED_ENTRYPOINT_SHA256)

    def test_refusal_cli_reports_all_negative_authority_axes_and_probe_identities(self):
        observed = "a" * 64
        error = composition.CompositionError(
            "COMPOSITION_ENTRYPOINT_HASH_MISMATCH", entrypoint_sha256=observed)
        root = Path.cwd().resolve()
        stdout = io.StringIO()
        with mock.patch.object(composition, "qualify", side_effect=error), redirect_stdout(stdout):
            code = composition.cli([
                "--state-root", str(root),
                "--repository-id", "dashminimix",
                "--repository-path", str(root),
                "--commit-sha", "0" * 40,
            ])
        value = json.loads(stdout.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(value["composition_qualified"])
        self.assertFalse(value["deployment_qualified"])
        self.assertFalse(value["runner_activation"])
        self.assertFalse(value["real_agent_qualified"])
        self.assertEqual(value["expected_entrypoint_sha256"],
                         composition.TRUSTED_ENTRYPOINT_SHA256)
        self.assertEqual(value["entrypoint_sha256"], observed)
        self.assertEqual(value["reason"], "COMPOSITION_ENTRYPOINT_HASH_MISMATCH")
        self.assertNotIn("source", value)

    def test_composition_error_rejects_unbounded_probe_identity(self):
        with self.assertRaises(ValueError):
            composition.CompositionError("TEST", entrypoint_sha256="not-a-sha256")


if __name__ == "__main__":
    unittest.main()
