"""Disabled, pinned Ohmy normalized-summary conformance seam.

This module validates a deliberately small, sanitized summary exported by a trusted
future host adapter. It does not launch OMP, import Ohmy, parse raw provider frames,
select commands, or qualify a real runner. The exact upstream draft pin is part of
the accepted data contract so drift fails closed.
"""
from __future__ import annotations

from . import WORKER_CONTRACT
from .contract import Refusal, canonical, check, decode

ADAPTER_CONTRACT = "ansible.ohmy-summary.v1"
OHMY_REVISION = "ff36977f67fc9f8f089e1db8e7aee3a7dee84ffb"
OHMY_NORMALIZED_CONTRACT = 1
OMP_REVISION = "00085d4e7dfdcfbf302c122fa2682b410a0f43d1"
LIVE_ADAPTER_QUALIFIED = False

_PROVIDER_FAILURES = {
    "AUTHENTICATION",
    "QUOTA_EXHAUSTED",
    "RATE_LIMITED",
    "PROVIDER_UNAVAILABLE",
    "MODEL_UNAVAILABLE",
    "CONTEXT_LIMIT",
    "NETWORK",
    "RETRY_EXHAUSTED",
}
_PROTOCOL_FAILURES = {"PROTOCOL", "SESSION_BUSY", "STALE_CURSOR"}


def parse_summary(raw: bytes, expected_job_id: str) -> dict:
    """Validate one bounded sanitized summary against the exact reviewed pins."""
    value = decode(raw)
    if not isinstance(value, dict):
        raise Refusal("INVALID_OHMY_SUMMARY")
    if value.get("contract_version") != ADAPTER_CONTRACT:
        raise Refusal("INCOMPATIBLE_OHMY_ADAPTER_CONTRACT")
    check(value, "ohmy-adapter-v1.schema.json")
    if value["job_id"] != expected_job_id:
        raise Refusal("WRONG_JOB_RESULT")
    if value["ohmy_revision"] != OHMY_REVISION:
        raise Refusal("UNQUALIFIED_OHMY_REVISION")
    if value["normalized_contract_version"] != OHMY_NORMALIZED_CONTRACT:
        raise Refusal("INCOMPATIBLE_OHMY_NORMALIZED_CONTRACT")
    if value["omp_revision"] != OMP_REVISION:
        raise Refusal("UNQUALIFIED_OMP_REVISION")

    source = value["failure_source"]
    code = value["failure_code"]
    status = value["http_status"]
    if (source == "NONE") != (code == "NONE"):
        raise Refusal("CONTRADICTORY_OHMY_FAILURE")
    if source == "NONE" and status is not None:
        raise Refusal("CONTRADICTORY_OHMY_FAILURE")
    if value["retry_exhausted"] and source == "NONE":
        raise Refusal("CONTRADICTORY_OHMY_FAILURE")
    if code == "RETRY_EXHAUSTED" and not value["retry_exhausted"]:
        raise Refusal("CONTRADICTORY_OHMY_FAILURE")
    return value


def project(raw: bytes, expected_job_id: str) -> dict:
    """Project a valid summary into the existing generic worker contract.

    The returned projection is intentionally not a qualification token. Even LIVE
    provenance remains unqualified until #13/#14 host/profile/live acceptance is
    separately satisfied.
    """
    value = parse_summary(raw, expected_job_id)
    transport = value["transport"]
    worker_outcome = "success"
    error_class = "none"

    if value["lifecycle"] == "command_failed":
        worker_outcome = "failed"
    elif value["lifecycle"] in ("local_only", "indeterminate"):
        # A local-only acknowledgement/output is not evidence that the requested
        # model review ran, and indeterminate lifecycle cannot establish success.
        worker_outcome = "no_result"

    code = value["failure_code"]
    source = value["failure_source"]
    if value["retry_exhausted"] or code == "RETRY_EXHAUSTED":
        worker_outcome, error_class, transport = "provider_error", "provider", "retry_exhausted"
    elif code in _PROVIDER_FAILURES:
        worker_outcome, error_class = "provider_error", "provider"
    elif code in _PROTOCOL_FAILURES or source == "TRANSPORT":
        worker_outcome, error_class = "invalid_result", "none"
        if transport == "ready":
            transport = "protocol_failed"
    elif source != "NONE":
        # Includes normalized CANCELLED: worker/provider data cannot assert the
        # host-owned cancellation/timeout/containment axes.
        worker_outcome, error_class = "worker_error", "worker"

    if transport not in ("ready", "retry_exhausted") and worker_outcome == "success":
        worker_outcome, error_class = "invalid_result", "none"

    worker = {
        "contract_version": WORKER_CONTRACT,
        "job_id": expected_job_id,
        "outcome": worker_outcome,
        "transport": transport,
        "final_output": value["final_output"],
        "error_class": error_class,
        "retry_exhausted": value["retry_exhausted"],
        "tool_calls": value["tool_calls"],
        "implementation_activity": value["implementation_activity"],
    }
    check(worker, "worker-v1.schema.json")
    return {
        "worker": worker,
        "worker_bytes": canonical(worker),
        "evidence": "complete" if value["evidence_complete"] else "partial",
        "origin": value["origin"],
        "run_id": value["run_id"],
        "session_id": value["session_id"],
        "qualification_eligible": LIVE_ADAPTER_QUALIFIED,
    }
