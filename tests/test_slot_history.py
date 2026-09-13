from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ansible_kernel.contract import Refusal, canonical, make_request
from ansible_kernel.kernel import Kernel, ROOT
from ansible_kernel.state import StateError, Store, append, journal


class SlotHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "state")
        self.kernel = Kernel(self.store)
        self.directory = self.root / "incoming"
        self.directory.mkdir()

    def stage(self, values):
        for value in values:
            (self.directory / f'slot{value["slot"]}.json').write_bytes(canonical(value))

    def ledger_bytes(self):
        return self.store.ledger.read_bytes() if self.store.ledger.exists() else b""

    def claim(self, job="a" * 32, request_key="b" * 64, once_key=None):
        return {"type": "reserved", "job_id": job, "request_key": request_key,
                "request_digest": "c" * 64, "once_key": once_key}

    def test_first_refresh_cannot_rewrite_bootstrap_generation(self):
        values = self.kernel.slots()
        values[0]["label"] = "silently replaced bootstrap"
        self.stage(values)
        with self.assertRaisesRegex(Refusal, "GENERATION_CONTENT_CHANGED"):
            self.kernel.refresh(self.directory)
        self.assertEqual(self.ledger_bytes(), b"")

    def test_first_identical_snapshot_is_recorded(self):
        self.kernel.refresh(ROOT / "slots")
        self.assertEqual(len(journal(self.store.ledger)), 1)

    def test_repeat_refresh_does_not_grow_ledger(self):
        values = self.kernel.refresh(ROOT / "slots")
        before = self.ledger_bytes()
        for _ in range(5):
            self.assertEqual(self.kernel.refresh(ROOT / "slots"), values)
        self.assertEqual(self.ledger_bytes(), before)

    def test_generation_advance_survives_restart_and_rollback_is_atomic(self):
        values = self.kernel.slots()
        values[0].update(generation=2, label="second")
        self.stage(values)
        self.kernel.refresh(self.directory)
        before = self.ledger_bytes()
        restarted = Kernel(Store(self.store.root))
        self.assertEqual(restarted.slots(), values)
        with self.assertRaisesRegex(Refusal, "GENERATION_ROLLBACK"):
            restarted.refresh(ROOT / "slots")
        self.assertEqual(self.ledger_bytes(), before)

    def test_one_invalid_file_preserves_whole_snapshot(self):
        self.kernel.refresh(ROOT / "slots")
        before = self.ledger_bytes()
        values = self.kernel.slots()
        values[0].update(generation=2, label="valid change")
        values[3]["label"] = "invalid same-generation change"
        self.stage(values)
        with self.assertRaises(Refusal):
            self.kernel.refresh(self.directory)
        self.assertEqual(self.ledger_bytes(), before)
        self.assertEqual(self.kernel.slots()[0]["generation"], 1)

    def test_hash_valid_generation_rewrite_fails_replay(self):
        values = self.kernel.refresh(ROOT / "slots")
        values[0]["label"] = "changed"
        append(self.store.ledger, {"type": "slots_refreshed", "slots": values})
        with self.assertRaisesRegex(StateError, "INVALID_LEDGER_EVENT"):
            self.kernel.slots()

    def test_hash_valid_generation_rollback_fails_replay(self):
        values = self.kernel.slots()
        values[0]["generation"] = 3
        append(self.store.ledger, {"type": "slot_seen", "slot": values[0]})
        values[0]["generation"] = 2
        append(self.store.ledger, {"type": "slot_seen", "slot": values[0]})
        with self.assertRaisesRegex(StateError, "INVALID_LEDGER_EVENT"):
            self.kernel.slots()

    def test_effective_snapshot_includes_slot_seen(self):
        value = self.kernel.slots()[0]
        value.update(generation=3, label="durably observed")
        append(self.store.ledger, {"type": "slot_seen", "slot": value})
        self.assertEqual(self.kernel.slots()[0], value)

    def test_legacy_first_snapshot_is_not_rewritten(self):
        # v0.1.1 could accept first-generation content different from the bundle.
        # Preserve its first durable observation, then enforce all later changes.
        values = self.kernel.slots()
        values[0]["label"] = "existing v011 snapshot"
        append(self.store.ledger, {"type": "slots_refreshed", "slots": values})
        before = self.ledger_bytes()
        self.assertEqual(self.kernel.slots(), values)
        self.assertEqual(self.ledger_bytes(), before)
        with self.assertRaises(Refusal):
            self.kernel.refresh(ROOT / "slots")

    def test_duplicate_request_claim_fails_before_execution(self):
        append(self.store.ledger, self.claim())
        append(self.store.ledger, self.claim(job="d" * 32))
        before = self.ledger_bytes()
        with self.assertRaisesRegex(StateError, "DUPLICATE_RESERVATION"):
            self.kernel.execute(canonical(make_request("must-not-start")))
        self.assertEqual(self.store.statuses(), [])
        self.assertEqual(self.ledger_bytes(), before)

    def test_duplicate_job_claim_fails_replay(self):
        append(self.store.ledger, self.claim())
        append(self.store.ledger, self.claim(request_key="d" * 64))
        with self.assertRaisesRegex(StateError, "DUPLICATE_RESERVATION"):
            self.kernel.recover()

    def test_duplicate_once_claim_fails_replay(self):
        append(self.store.ledger, self.claim(once_key="1:1"))
        append(self.store.ledger, self.claim(job="d" * 32, request_key="e" * 64, once_key="1:1"))
        with self.assertRaisesRegex(StateError, "DUPLICATE_RESERVATION"):
            self.kernel.slots()

    def test_distinct_request_claims_without_once_key_remain_valid(self):
        append(self.store.ledger, self.claim())
        append(self.store.ledger, self.claim(job="d" * 32, request_key="e" * 64))
        self.assertEqual(len(self.kernel.slots()), 4)

    def test_once_reservation_survives_new_kernel(self):
        first = self.kernel.run_slot(1)
        self.assertEqual(first["worker_outcome"], "success")
        result = Kernel(Store(self.store.root)).run_slot(1)
        self.assertEqual(result["reason"], "GENERATION_ALREADY_RESERVED")

    def test_unqualified_runner_stays_refused_after_refresh(self):
        values = self.kernel.slots()
        values[0].update(generation=2, runner_type="omp_blind_review_v1")
        self.stage(values)
        self.kernel.refresh(self.directory)
        result = self.kernel.run_slot(1)
        self.assertEqual(result["reason"], "RUNNER_NOT_QUALIFIED")
        self.assertEqual(result["admission"], "rejected_runner")

    def test_busy_refresh_preserves_ledger(self):
        self.kernel.refresh(ROOT / "slots")
        before = self.ledger_bytes()
        with self.store.lock():
            with self.assertRaisesRegex(StateError, "LOCK_BUSY"):
                self.kernel.refresh(ROOT / "slots")
        self.assertEqual(self.ledger_bytes(), before)
