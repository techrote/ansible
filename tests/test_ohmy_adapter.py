from __future__ import annotations

import unittest

from ansible_kernel.contract import Predicate, Refusal, canonical, outcome
from ansible_kernel.ohmy_adapter import (
    ADAPTER_CONTRACT,
    OHMY_NORMALIZED_CONTRACT,
    OHMY_REVISION,
    OMP_REVISION,
    parse_summary,
    project,
)

JOB = "c" * 32
INFRA = {"state": "completed", "exit_code": 0, "controller_completed": True}


def summary(**changes):
    value = {
        "contract_version": ADAPTER_CONTRACT,
        "job_id": JOB,
        "ohmy_revision": OHMY_REVISION,
        "normalized_contract_version": OHMY_NORMALIZED_CONTRACT,
        "omp_revision": OMP_REVISION,
        "origin": "SYNTHETIC",
        "run_id": "run-1",
        "session_id": "session-1",
        "lifecycle": "agent_settled",
        "evidence_complete": True,
        "transport": "ready",
        "failure_source": "NONE",
        "failure_code": "NONE",
        "http_status": None,
        "retry_exhausted": False,
        "final_output": "A bounded analytical review.",
        "tool_calls": 0,
        "implementation_activity": False,
    }
    value.update(changes)
    return value


def result(value, predicate=None, infra=None, stop=None):
    projection = project(canonical(value), JOB)
    return outcome(JOB, projection["worker_bytes"], infra or INFRA,
                   projection["evidence"], predicate or Predicate(), stop)


class OhmyAdapterTests(unittest.TestCase):
    def test_zero_tool_analytical_projection_can_succeed(self):
        projected = project(canonical(summary()), JOB)
        self.assertEqual(projected["worker"]["tool_calls"], 0)
        self.assertFalse(projected["qualification_eligible"])
        self.assertEqual(result(summary())["worker_outcome"], "success")

    def test_provider_429_overrides_terminal_success(self):
        value = summary(failure_source="ASSISTANT", failure_code="RATE_LIMITED",
                        http_status=429, final_output="stale prose")
        self.assertEqual(result(value)["worker_outcome"], "provider_error")

    def test_retry_exhaustion_is_provider_failure(self):
        value = summary(failure_source="RETRY", failure_code="RETRY_EXHAUSTED",
                        retry_exhausted=True, final_output=None)
        actual = result(value)
        self.assertEqual(actual["worker_outcome"], "provider_error")
        self.assertEqual(actual["transport"], "retry_exhausted")

    def test_missing_and_whitespace_output_are_no_result(self):
        for output in (None, "", " \t"):
            with self.subTest(output=output):
                self.assertEqual(result(summary(final_output=output))["worker_outcome"], "no_result")

    def test_local_only_and_indeterminate_cannot_establish_model_review(self):
        for lifecycle in ("local_only", "indeterminate"):
            with self.subTest(lifecycle=lifecycle):
                self.assertEqual(result(summary(lifecycle=lifecycle))["worker_outcome"], "no_result")

    def test_incomplete_evidence_invalidates_apparent_success(self):
        self.assertEqual(result(summary(evidence_complete=False))["worker_outcome"], "invalid_result")

    def test_transport_failure_invalidates_apparent_success(self):
        actual = result(summary(transport="connection_failed"))
        self.assertEqual(actual["worker_outcome"], "invalid_result")
        self.assertEqual(actual["transport"], "connection_failed")

    def test_protocol_failure_is_not_success(self):
        actual = result(summary(failure_source="TRANSPORT", failure_code="PROTOCOL"))
        self.assertEqual(actual["worker_outcome"], "invalid_result")
        self.assertEqual(actual["transport"], "protocol_failed")

    def test_normalized_cancel_does_not_masquerade_as_host_cancel(self):
        actual = result(summary(failure_source="ASSISTANT", failure_code="CANCELLED"))
        self.assertEqual(actual["worker_outcome"], "worker_error")
        self.assertNotEqual(actual["reason"], "HOST_CANCELLED")

    def test_host_cancel_timeout_and_containment_remain_authoritative(self):
        for stop in ("cancelled", "timeout", "contained"):
            with self.subTest(stop=stop):
                self.assertEqual(result(summary(), stop=stop)["worker_outcome"], stop)

    def test_controller_failure_cannot_preserve_success(self):
        infra = {"state": "controller_failed", "exit_code": 1, "controller_completed": False}
        self.assertEqual(result(summary(), infra=infra)["worker_outcome"], "unknown")

    def test_provider_failure_survives_controller_failure(self):
        infra = {"state": "controller_failed", "exit_code": 1, "controller_completed": False}
        value = summary(failure_source="ASSISTANT", failure_code="PROVIDER_UNAVAILABLE")
        self.assertEqual(result(value, infra=infra)["worker_outcome"], "provider_error")

    def test_implementation_predicate_uses_activity_not_tool_count_alone(self):
        predicate = Predicate(implementation=True, min_tool_calls=0)
        self.assertEqual(result(summary(), predicate)["worker_outcome"], "invalid_result")
        active = summary(implementation_activity=True, tool_calls=0)
        self.assertEqual(result(active, predicate)["worker_outcome"], "success")

    def test_wrong_job_and_pin_drift_fail_closed(self):
        cases = [
            (summary(job_id="d" * 32), "WRONG_JOB_RESULT"),
            (summary(ohmy_revision="0" * 40), "UNQUALIFIED_OHMY_REVISION"),
            (summary(omp_revision="1" * 40), "UNQUALIFIED_OMP_REVISION"),
        ]
        for value, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(Refusal) as caught:
                    project(canonical(value), JOB)
                self.assertEqual(caught.exception.code, code)

    def test_contract_and_normalized_version_drift_fail_closed(self):
        value = summary(contract_version="ansible.ohmy-summary.v99")
        with self.assertRaises(Refusal) as caught:
            project(canonical(value), JOB)
        self.assertEqual(caught.exception.code, "INCOMPATIBLE_OHMY_ADAPTER_CONTRACT")
        value = summary(normalized_contract_version=2)
        with self.assertRaises(Refusal):
            project(canonical(value), JOB)

    def test_unknown_fields_and_oversized_output_are_rejected(self):
        value = summary()
        value["raw_frame"] = {"secret": "must not persist"}
        with self.assertRaises(Refusal):
            project(canonical(value), JOB)
        with self.assertRaises(Refusal):
            project(canonical(summary(final_output="x" * 8193)), JOB)

    def test_failure_cross_fields_are_consistent(self):
        contradictory = [
            summary(failure_source="NONE", failure_code="RATE_LIMITED"),
            summary(failure_source="RETRY", failure_code="NONE"),
            summary(failure_source="NONE", failure_code="NONE", http_status=429),
            summary(retry_exhausted=True),
            summary(failure_source="RETRY", failure_code="RETRY_EXHAUSTED", retry_exhausted=False),
        ]
        for value in contradictory:
            with self.subTest(value=value):
                with self.assertRaises(Refusal) as caught:
                    parse_summary(canonical(value), JOB)
                self.assertEqual(caught.exception.code, "CONTRADICTORY_OHMY_FAILURE")

    def test_source_identity_and_summary_are_sanitized_bounded_fields_only(self):
        projected = project(canonical(summary(origin="LIVE")), JOB)
        self.assertEqual(projected["origin"], "LIVE")
        self.assertFalse(projected["qualification_eligible"])
        self.assertEqual(set(projected), {"worker", "worker_bytes", "evidence", "origin",
                                          "run_id", "session_id", "qualification_eligible"})


if __name__ == "__main__":
    unittest.main()
