from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from ansible_kernel.contract import canonical, slot
from ansible_kernel.slot_transport import validate_snapshot

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "intrallm_slot_migration_preview", ROOT / "tools" / "intrallm_slot_migration_preview.py"
)
assert SPEC and SPEC.loader
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class IntrallmMigrationPreviewTests(unittest.TestCase):
    def test_generation_two_candidate_is_current_schema_idle_only(self):
        values = preview.candidate_slots(2)
        self.assertEqual(len(values), 4)
        for number, value in enumerate(values, 1):
            self.assertEqual(slot(canonical(value), number), value)
            self.assertEqual(value["generation"], 2)
            self.assertEqual(value["state"], "idle")
            self.assertEqual(set(value), {"schema_version", "slot", "generation", "state", "task_id", "label"})

    def test_repository_floor_is_not_silently_reused(self):
        for generation in (1, 0, -1):
            with self.subTest(generation=generation), self.assertRaisesRegex(
                ValueError, "GENERATION_NOT_ABOVE_RECORDED_FLOOR"
            ):
                preview.candidate_slots(generation)

    def test_synthetic_git_graph_passes_production_transport_verifier(self):
        values = preview.candidate_slots(2)
        snapshot, reads = preview.synthetic_transport_snapshot(values)
        self.assertEqual(reads, 8)
        self.assertEqual(validate_snapshot(snapshot), snapshot)
        self.assertEqual(snapshot["slots"], values)
        self.assertEqual(snapshot["provenance"]["commit_sha"], preview.SYNTHETIC_COMMIT_SHA)

    def test_publication_simulation_preserves_once_claim_and_is_idempotent(self):
        snapshot, _ = preview.synthetic_transport_snapshot(preview.candidate_slots(2))
        result = preview.simulate_publication(snapshot)
        self.assertEqual(result["baseline_generations"], [1, 1, 1, 1])
        self.assertTrue(result["baseline_once_completed"])
        self.assertTrue(result["generation_1_once_reserved_before"])
        self.assertTrue(result["first_refresh_changed"])
        self.assertFalse(result["repeat_refresh_changed"])
        self.assertTrue(result["repeat_refresh_ledger_unchanged"])
        self.assertTrue(result["generation_1_once_preserved"])
        self.assertEqual(result["current_generations"], [2, 2, 2, 2])
        self.assertTrue(result["all_current_slots_idle"])

    def test_report_keeps_external_deployment_unclaimed(self):
        report = preview.build_report(2)
        self.assertTrue(report["deployment_generation_check_required"])
        self.assertFalse(report["producer_write_performed"])
        self.assertFalse(report["credential_used"])
        self.assertFalse(report["authenticated_remote_refresh_performed"])
        self.assertEqual(report["transport_preview"]["attestation"], "synthetic_in_memory_git_graph")
        self.assertEqual(report["transport_preview"]["fixed_reads"], 8)


if __name__ == "__main__":
    unittest.main()
