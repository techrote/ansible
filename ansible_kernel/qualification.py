"""Executable, local qualification: reports actual checks, not advertised intent."""
from __future__ import annotations

import platform
from pathlib import Path
import tempfile
import threading
import time

from . import CONTRACT, WORKER_CONTRACT, VERSION
from .contract import (Predicate, Refusal, canonical, make_request, outcome, request,
                       safe_relative)
from .kernel import Kernel, fingerprint
from .state import Store


JOB = "a" * 32
INFRA = {"state": "completed", "exit_code": 0, "controller_completed": True}


def worker(**changes) -> dict:
    value = {"contract_version": WORKER_CONTRACT, "job_id": JOB, "outcome": "success",
             "transport": "ready", "final_output": "A valid analytical result.",
             "error_class": "none", "retry_exhausted": False, "tool_calls": 0,
             "implementation_activity": False}
    value.update(changes)
    return value


def semantic_cases() -> list[dict]:
    return [
        {"name": "genuine_success", "worker": worker(), "expected": "success"},
        {"name": "provider_429_after_clean_controller", "worker": worker(outcome="provider_error", error_class="provider", retry_exhausted=True, final_output=None), "expected": "provider_error"},
        {"name": "retry_exhaustion", "worker": worker(retry_exhausted=True), "expected": "provider_error"},
        {"name": "zero_output_exit_zero", "worker": worker(final_output=None), "expected": "no_result"},
        {"name": "whitespace_output", "worker": worker(final_output="  "), "expected": "no_result"},
        {"name": "zero_tool_analytical_success", "worker": worker(), "expected": "success"},
        {"name": "empty_implementation_activity", "worker": worker(), "implementation": True, "expected": "invalid_result"},
        {"name": "implementation_with_activity", "worker": worker(implementation_activity=True, tool_calls=1), "implementation": True, "expected": "success"},
        {"name": "worker_cannot_assert_containment", "worker": worker(outcome="contained"), "expected": "invalid_result"},
        {"name": "worker_failure", "worker": worker(outcome="failed"), "expected": "failed"},
        {"name": "error_overrides_success_claim", "worker": worker(error_class="worker"), "expected": "worker_error"},
        {"name": "protocol_failure", "worker": worker(transport="protocol_failed"), "expected": "invalid_result"},
        {"name": "missing_evidence", "worker": worker(), "evidence": "missing", "expected": "invalid_result"},
        {"name": "wrong_job", "worker": worker(job_id="b" * 32), "expected": "invalid_result"},
        {"name": "wrong_worker_contract", "worker": worker(contract_version="ansible.worker.v99"), "expected": "invalid_result"},
        {"name": "controller_failure", "worker": worker(), "infra": {"state": "controller_failed", "exit_code": 1, "controller_completed": False}, "expected": "unknown"},
        {"name": "nonzero_exit_cannot_succeed", "worker": worker(), "infra": {**INFRA, "exit_code": 1}, "expected": "unknown"},
        {"name": "cancel_overrides_success", "worker": worker(), "stop": "cancelled", "expected": "cancelled"},
        {"name": "contain_overrides_success", "worker": worker(), "stop": "contained", "expected": "contained"},
        {"name": "timeout_overrides_success", "worker": worker(), "stop": "timeout", "expected": "timeout"},
    ]


def assert_true(condition: bool, label: str = "ASSERTION_FAILED") -> None:
    if not condition:
        raise AssertionError(label)


def controlled(kernel: Kernel, action: str, request_id: str) -> dict:
    results, errors = [], []

    def target():
        try:
            results.append(kernel.execute(canonical(make_request(request_id, 4000))))
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=target)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            running = [item for item in kernel.store.statuses() if item["state"] == "running"]
            if running:
                kernel.store.control(running[0]["job_id"], action)
                break
            if not thread.is_alive():
                raise AssertionError("WORKER_DID_NOT_RUN")
            time.sleep(0.01)
        else:
            raise AssertionError("CONTROL_DEADLINE")
    finally:
        thread.join(8)
    assert_true(not thread.is_alive() and not errors and bool(results))
    return results[0]


def qualify() -> dict:
    checks = []

    def run_check(name, fn):
        try:
            fn()
            checks.append({"name": name, "passed": True})
        except Exception as exc:
            checks.append({"name": name, "passed": False, "error_type": type(exc).__name__,
                           "code": getattr(exc, "code", "CHECK_FAILED")})

    for case in semantic_cases():
        def verify(case=case):
            predicate = Predicate(implementation=case.get("implementation", False),
                                  min_tool_calls=1 if case.get("implementation") else 0)
            result = outcome(JOB, canonical(case["worker"]), case.get("infra", INFRA),
                             case.get("evidence", "complete"), predicate, case.get("stop"))
            assert_true(result["worker_outcome"] == case["expected"])
        run_check(case["name"], verify)
    with tempfile.TemporaryDirectory(prefix="ansible-qualify-") as directory:
        kernel = Kernel(Store(Path(directory)))
        run_check("accepted_schema", lambda: request(canonical(make_request("accepted"))))

        def rejected(change, expected):
            value = make_request("rejection")
            value.update(change)
            result = kernel.execute(canonical(value))
            assert_true(result["admission"] == expected)
            assert_true(result["worker_outcome"] != "success")
        run_check("unknown_field", lambda: rejected({"command": "must not execute"}, "rejected_schema"))
        run_check("unknown_runner", lambda: rejected({"runner_id": "not_registered"}, "rejected_runner"))
        run_check("omp_refused", lambda: rejected({"runner_id": "omp_blind_review_v1"}, "rejected_runner"))
        run_check("capability_refused", lambda: rejected({"capabilities": ["network"]}, "rejected_capability"))
        run_check("incompatible_contract", lambda: rejected({"contract_version": "ansible.execution.v99"}, "rejected_policy"))
        run_check("resource_envelope", lambda: rejected({"resources": {"memory_mb": 512, "cpu_seconds": 2}}, "rejected_policy"))

        def path_refused():
            try:
                safe_relative("../outside.py")
            except Refusal:
                return
            raise AssertionError("TRAVERSAL_ACCEPTED")
        run_check("path_restriction", path_refused)

        def noop():
            result = kernel.execute(canonical(make_request("real-noop")))
            assert_true(result["worker_outcome"] == "success")
            assert_true(kernel.store.verify_evidence(result["job_id"]) == "complete")
            assert_true(kernel.store.result(result["job_id"]) == result)
        run_check("real_noop_and_evidence", noop)
        run_check("request_replay_refused", lambda: assert_true(kernel.execute(canonical(make_request("real-noop")))["admission"] == "rejected_policy"))
        run_check("real_cancellation", lambda: assert_true(controlled(kernel, "cancel", "cancel-check")["worker_outcome"] == "cancelled"))
        run_check("real_containment", lambda: assert_true(controlled(kernel, "contain", "contain-check")["worker_outcome"] == "contained"))

        def timeout():
            value = make_request("timeout-check", 4000)
            value["timeout_seconds"] = 1
            assert_true(kernel.execute(canonical(value))["worker_outcome"] == "timeout")
        run_check("real_timeout", timeout)

        def once():
            assert_true(kernel.run_slot(1)["worker_outcome"] == "success")
            assert_true(kernel.run_slot(1)["reason"] == "GENERATION_ALREADY_RESERVED")
        run_check("slot_once", once)

        def recovery():
            with kernel.store.lock():
                job_id = kernel.store.new_job({"qualification": "interrupted"})
                kernel.store.transition(job_id, "validated")
                kernel.store.transition(job_id, "admitted")
            assert_true(job_id in kernel.recover())
            assert_true(kernel.store.result(job_id)["worker_outcome"] == "unknown")
        run_check("restart_never_infers_success", recovery)
    passed = all(check["passed"] for check in checks)
    return {"contract_version": CONTRACT, "implementation_version": VERSION,
            "source_fingerprint": fingerprint(), "platform": platform.system(),
            "python": platform.python_version(), "profile": "trusted-noop-only",
            "profile_qualified": passed, "real_agent_qualified": False,
            "runners": {"noop_v1": "ansible.runner.noop.v1", "omp_blind_review_v1": "disabled"},
            "unsupported": ["untrusted_code_isolation", "network_denial", "cpu_rate_limit",
                            "live_ohmy_adapter", "vm_providers", "worker_network_authority"],
            "operator_slot_transport": "opt_in_separately_tested_not_qualified_by_noop",
            "checks": checks}
