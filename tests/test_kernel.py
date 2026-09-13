from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ansible_kernel import CONTRACT
from ansible_kernel.contract import (Predicate, Refusal, REGISTRY, canonical, check, decode,
                                     make_request, outcome, request, safe_ref, safe_relative, slot)
from ansible_kernel.kernel import Kernel, ROOT
from ansible_kernel.provider import Capture, WindowsJob, clean_environment
from ansible_kernel.qualification import JOB, INFRA, controlled, qualify, semantic_cases, worker
from ansible_kernel.state import (Lock, StateError, Store, append, journal, read_bytes,
                                 write_once)


class ContractTests(unittest.TestCase):
    def test_provider_retry_axes(self):
        result = outcome(JOB, canonical(worker(error_class="provider", retry_exhausted=True)),
                         INFRA, "complete", Predicate())
        self.assertEqual(result["worker_outcome"], "provider_error")
        self.assertEqual(result["transport"], "retry_exhausted")

    def test_serialized_fixtures_match(self):
        actual = json.loads((ROOT / "tests/fixtures/runtime-v1.json").read_text())
        self.assertEqual(actual["cases"], semantic_cases())

    def test_registry_immutable(self):
        with self.assertRaises(TypeError):
            REGISTRY["evil"] = None

    def test_json_duplicate(self):
        with self.assertRaises(Refusal):
            decode(b'{"x":1,"x":2}')

    def test_json_nonfinite_and_float(self):
        for raw in (b'NaN', b'Infinity', b'-Infinity', b'1e999', b'0.5'):
            with self.subTest(raw=raw), self.assertRaises(Refusal):
                decode(raw)

    def test_json_bounds(self):
        for raw in (b' ' * 65537, b'[' * 1000 + b']' * 1000, b'"\\ud800"', b'\xff', b'9' * 5000):
            with self.subTest(length=len(raw)), self.assertRaises(Refusal):
                decode(raw)

    def test_bool_is_not_integer(self):
        for key in ("timeout_seconds",):
            value = make_request("bool")
            value[key] = True
            with self.assertRaises(Refusal):
                request(canonical(value))
        value = make_request("bool-parameter")
        value["parameters"]["duration_ms"] = False
        with self.assertRaises(Refusal):
            request(canonical(value))

    def test_no_command_fields_anywhere(self):
        for key in ("command", "script_path", "module", "environment", "hooks", "success_predicate", "runner"):
            for section in (None, "parameters", "resources"):
                value = make_request("command-injection")
                (value if section is None else value[section])[key] = "do-not-run"
                with self.subTest(key=key, section=section), self.assertRaises(Refusal):
                    request(canonical(value))

    def test_no_resource_envelope_expansion(self):
        for resource, amount in (("memory_mb", 512), ("cpu_seconds", 5)):
            value = make_request("limits")
            value["resources"][resource] = amount
            with self.assertRaises(Refusal) as context:
                request(canonical(value))
            self.assertEqual(context.exception.admission, "rejected_policy")

    def test_unknown_provider(self):
        value = make_request("provider")
        value["provider_id"] = "LinuxVMProvider"
        with self.assertRaises(Refusal) as context:
            request(canonical(value))
        self.assertEqual(context.exception.code, "PROVIDER_NOT_QUALIFIED")

    def test_duplicate_capabilities(self):
        value = make_request("caps")
        value["capabilities"] = ["network", "network"]
        with self.assertRaises(Refusal):
            request(canonical(value))

    def test_missing_fields(self):
        for key in make_request("missing"):
            value = make_request("missing")
            del value[key]
            with self.subTest(key=key), self.assertRaises(Refusal):
                request(canonical(value))

    def test_schema_types(self):
        for value in (None, [], True, 1, "task"):
            with self.subTest(value=value), self.assertRaises(Refusal):
                request(canonical(value))

    def test_unknown_worker_fields(self):
        value = worker(stopReason="error")
        self.assertEqual(outcome(JOB, canonical(value), INFRA, "complete", Predicate())["worker_outcome"], "invalid_result")

    def test_missing_worker_field(self):
        for key in worker():
            value = worker()
            del value[key]
            result = outcome(JOB, canonical(value), INFRA, "complete", Predicate())
            self.assertNotEqual(result["worker_outcome"], "success")

    def test_worker_boolean_spoofing(self):
        for key in ("retry_exhausted", "implementation_activity", "tool_calls"):
            value = worker(**{key: "false"})
            self.assertEqual(outcome(JOB, canonical(value), INFRA, "complete", Predicate())["worker_outcome"], "invalid_result")

    def test_null_and_malformed_result(self):
        for value in (b'{}', b'not json', b'null', b'[]', b'{"outcome":"success","outcome":"failed"}'):
            self.assertEqual(outcome(JOB, value, INFRA, "complete", Predicate())["worker_outcome"], "invalid_result")
        self.assertEqual(outcome(JOB, None, INFRA, "complete", Predicate())["worker_outcome"], "no_result")

    def test_generated_success_invariant(self):
        rng = random.Random(823)
        for _ in range(400):
            value = worker(outcome=rng.choice(["success", "failed", "provider_error"]),
                           error_class=rng.choice(["none", "provider", "worker"]),
                           retry_exhausted=rng.choice([True, False]),
                           final_output=rng.choice([None, "", "valid"]),
                           transport=rng.choice(["ready", "protocol_failed", "retry_exhausted"]))
            infrastructure = {"state": rng.choice(["completed", "controller_failed"]),
                              "exit_code": rng.choice([0, 1, None]),
                              "controller_completed": rng.choice([True, False])}
            evidence = rng.choice(["complete", "missing", "invalid"])
            result = outcome(JOB, canonical(value), infrastructure, evidence, Predicate())
            if result["worker_outcome"] == "success":
                self.assertEqual(value["outcome"], "success")
                self.assertEqual(value["error_class"], "none")
                self.assertFalse(value["retry_exhausted"])
                self.assertTrue(value["final_output"])
                self.assertEqual(value["transport"], "ready")
                self.assertEqual(infrastructure, INFRA)
                self.assertEqual(evidence, "complete")

    def test_paths(self):
        bad = ["../x", "a/../x", "a//x", "/etc/passwd", "C:/x", "C:x", "\\\\host\\x",
               "tests/a.py::test", "NUL", "con.txt", "a/COM1.txt", "a/./b", "a/b.", "-x", "a\\b", "%TEMP%/x"]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(Refusal):
                safe_relative(value)
        safe_relative("tests/test_ok.py")

    def test_refs(self):
        for value in ("../x", "-bad", "a..b", "x.lock", "a/.b", "a//b", "a/", "a^", "a@{b", "a;cmd", "HEAD~1"):
            with self.subTest(value=value), self.assertRaises(Refusal):
                safe_ref(value)
        safe_ref("refs/heads/feature/test")

    def test_legacy_schema_retained_but_armed_validation_stricter(self):
        value = json.loads((ROOT / "slots/slot1.json").read_text())
        del value["runner_type"]
        check(value, "slot-v1.schema.json")
        with self.assertRaises(Refusal):
            slot(canonical(value))

    def test_slot_noop_rejects_unused_authority(self):
        value = json.loads((ROOT / "slots/slot1.json").read_text())
        value["model"] = "anything"
        with self.assertRaises(Refusal):
            slot(canonical(value))

    def test_slot_ids_and_generation(self):
        for key, change in (("slot", True), ("schema_version", True), ("generation", 2**40), ("label", "\x1b[2J")):
            value = json.loads((ROOT / "slots/slot1.json").read_text())
            value[key] = change
            with self.assertRaises(Refusal):
                slot(canonical(value), 1)
        with self.assertRaises(Refusal):
            slot((ROOT / "slots/slot1.json").read_bytes(), 2)


for case in semantic_cases():
    def test(self, case=case):
        result = outcome(JOB, canonical(case["worker"]), case.get("infra", INFRA),
                         case.get("evidence", "complete"),
                         Predicate(implementation=case.get("implementation", False),
                                   min_tool_calls=int(case.get("implementation", False))),
                         case.get("stop"))
        self.assertEqual(result["worker_outcome"], case["expected"])
    setattr(ContractTests, "test_semantics_" + case["name"], test)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.kernel = Kernel(self.store)

    def test_append_and_hash_corruption(self):
        path = self.store.root / "test.jsonl"
        append(path, {"a": 1})
        append(path, {"b": 2})
        self.assertEqual(journal(path), [{"a": 1}, {"b": 2}])
        path.write_bytes(path.read_bytes().replace(b'"a":1', b'"a":9'))
        with self.assertRaises(StateError):
            journal(path)

    def test_torn_tail_refuses_append(self):
        append(self.store.ledger, {"type": "reserved"})
        with self.store.ledger.open("ab") as handle:
            handle.write(b'{"partial":')
        original = self.store.ledger.read_bytes()
        with self.assertRaises(StateError):
            append(self.store.ledger, {"not": "allowed"})
        self.assertEqual(self.store.ledger.read_bytes(), original)

    def test_lock_exclusive_and_releases(self):
        with self.store.lock():
            with self.assertRaises(StateError):
                with self.store.lock():
                    pass
        with self.store.lock():
            pass

    def test_job_traversal(self):
        for value in ("../x", "", "a" * 31, "A" * 32, "a" * 32 + "/x"):
            with self.assertRaises(StateError):
                self.store.job(value)

    def test_state_transition_and_terminal_immutability(self):
        job_id = self.store.new_job({})
        with self.assertRaises(StateError):
            self.store.transition(job_id, "completed")
        self.store.transition(job_id, "failed", result={})
        with self.assertRaises(StateError):
            self.store.transition(job_id, "running")

    def test_write_once(self):
        path = self.store.root / "one.json"
        write_once(path, b"one")
        with self.assertRaises(FileExistsError):
            write_once(path, b"two")
        self.assertEqual(path.read_bytes(), b"one")

    def test_symlink(self):
        target = self.store.root / "target"
        target.write_text("unchanged")
        link = self.store.root / "link"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Host does not permit symlink creation")
        with self.assertRaises(StateError):
            read_bytes(link)
        with self.assertRaises(StateError):
            append(link, {"x": 1})
        self.assertEqual(target.read_text(), "unchanged")

    def test_hardlink(self):
        target = self.store.root / "target"
        target.write_text("unchanged")
        linked = self.store.root / "linked"
        try:
            os.link(target, linked)
        except OSError:
            self.skipTest("Host does not permit hard links")
        with self.assertRaises(StateError):
            read_bytes(linked)

    def test_checkout_cannot_store_state(self):
        with self.assertRaises(StateError):
            Store(ROOT / "forbidden-state")

    def test_control_priority_and_terminal_refusal(self):
        job_id = self.store.new_job({})
        self.store.control(job_id, "cancel")
        self.store.control(job_id, "contain")
        self.assertEqual(self.store.stop_reason(job_id), "contained")
        self.store.transition(job_id, "failed", result={})
        with self.assertRaises(StateError):
            self.store.control(job_id, "cancel")

    def test_data_refresh_does_not_change_code(self):
        before = {p: p.read_bytes() for p in (ROOT / "ansible_kernel").glob("*.py")}
        self.kernel.refresh(ROOT / "slots")
        self.assertEqual(len(self.kernel.slots()), 4)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_generation_rollback_and_rewrite(self):
        self.kernel.refresh(ROOT / "slots")
        value = self.kernel.slots()[0]
        value["label"] = "changed in same generation"
        with self.assertRaises(Refusal):
            self.kernel._generation(value)
        value["generation"] = 0
        with self.assertRaises(Refusal):
            self.kernel._generation(value)

    def test_recovery_never_reads_result_json_as_success(self):
        job_id = self.store.new_job({})
        self.store.transition(job_id, "validated")
        self.store.transition(job_id, "admitted")
        self.store.transition(job_id, "starting")
        self.store.transition(job_id, "running")
        write_once(self.store.job(job_id) / "result.json", b'{"worker_outcome":"success"}')
        self.kernel.recover()
        self.assertEqual(self.store.result(job_id)["worker_outcome"], "unknown")
        self.assertEqual(self.store.result(job_id)["reason"], "OWNER_LOST_REQUIRES_REVIEW")

    def test_recovery_before_first_event(self):
        path = self.store.job("b" * 32)
        path.mkdir()
        self.kernel.recover()
        self.assertEqual(self.store.result(path.name)["worker_outcome"], "unknown")


class IntegrationTests(unittest.TestCase):
    setUp = StateTests.setUp
    def test_real_output_flood_is_contained(self):
        real_popen = subprocess.Popen

        def trusted_test_process(command, **kwargs):
            command = list(command)
            command[4] = str(ROOT / "tests/flood_probe.py")
            return real_popen(command, **kwargs)
        with patch("ansible_kernel.provider.subprocess.Popen", side_effect=trusted_test_process):
            value = self.kernel.execute(canonical(make_request("output-limit")))
        self.assertEqual(value["worker_outcome"], "contained")
        metadata = decode(read_bytes(self.store.job(value["job_id"]) / "provider.json"))
        self.assertEqual(metadata["error"], "OUTPUT_LIMIT")

    def test_capture_memory_bounded(self):
        import io
        overflow = threading.Event()
        capture = Capture(io.BytesIO(b"X" * 1000000), overflow)
        self.assertEqual(len(capture.finish()), 32768)
        self.assertTrue(overflow.is_set())

    def test_lifecycle_replay_rejects_invalid_transition(self):
        job_id = self.store.new_job({})
        append(self.store.job(job_id) / "status.jsonl", {"state": "completed", "time_ns": time.time_ns()})
        with self.assertRaises(StateError):
            self.store.events(job_id)
        self.assertEqual(self.store.statuses()[0]["state"], "unreadable")

    def test_malformed_reservation_refuses_execution(self):
        append(self.store.ledger, {"type": "reserved", "job_id": "../outside"})
        with self.assertRaises(StateError):
            self.kernel.execute(canonical(make_request("after-corruption")))
        self.assertEqual(self.store.statuses(), [])

    def test_real_noop(self):
        value = self.kernel.execute(canonical(make_request("noop")))
        self.assertEqual(value["worker_outcome"], "success")
        self.assertEqual(value["infrastructure"], INFRA)
        metadata = decode(read_bytes(self.store.job(value["job_id"]) / "provider.json"))
        self.assertTrue(metadata["limits_applied"])

    def test_once_slot(self):
        self.assertEqual(self.kernel.run_slot(1)["worker_outcome"], "success")
        self.assertEqual(self.kernel.run_slot(1)["reason"], "GENERATION_ALREADY_RESERVED")
        self.assertEqual(self.kernel.run_slot(2)["reason"], "SLOT_IDLE")

    def test_request_replay(self):
        self.kernel.execute(canonical(make_request("duplicate")))
        value = self.kernel.execute(canonical(make_request("duplicate", 1)))
        self.assertEqual(value["reason"], "REQUEST_ALREADY_RESERVED")

    def test_evidence_mutation_invalidates_success(self):
        value = self.kernel.execute(canonical(make_request("tamper")))
        path = self.store.job(value["job_id"]) / "worker.json"
        path.write_text("changed")
        self.assertEqual(self.store.result(value["job_id"])["worker_outcome"], "invalid_result")

    def test_evidence_removal_invalidates_success(self):
        value = self.kernel.execute(canonical(make_request("removed")))
        (self.store.job(value["job_id"]) / "manifest.json").unlink()
        self.assertEqual(self.store.result(value["job_id"])["evidence"], "missing")

    def test_cancel(self):
        value = controlled(self.kernel, "cancel", "cancellation")
        self.assertEqual(value["worker_outcome"], "cancelled")

    def test_contain(self):
        value = controlled(self.kernel, "contain", "containment")
        self.assertEqual(value["worker_outcome"], "contained")

    def test_timeout(self):
        value = make_request("timeout", 4000)
        value["timeout_seconds"] = 1
        self.assertEqual(self.kernel.execute(canonical(value))["worker_outcome"], "timeout")

    def test_controller_exception(self):
        with patch("ansible_kernel.kernel.provider.run", side_effect=RuntimeError("never expose this")):
            value = self.kernel.execute(canonical(make_request("controller-failed")))
        self.assertEqual(value["infrastructure"]["state"], "controller_failed")
        self.assertNotEqual(value["worker_outcome"], "success")
        self.assertNotIn(b"never expose this", canonical(value))

    def test_environment_not_inherited(self):
        with patch.dict(os.environ, {"GH_TOKEN": "sentinel-secret", "PYTHONPATH": "bad", "SSH_AUTH_SOCK": "bad"}):
            value = clean_environment(self.store.root)
        for key in ("GH_TOKEN", "PYTHONPATH", "SSH_AUTH_SOCK", "PATH"):
            self.assertNotIn(key, value)

    def test_qualification(self):
        report = qualify()
        self.assertTrue(report["profile_qualified"], report)
        self.assertFalse(report["real_agent_qualified"])

    def test_cli_requires_isolated_startup(self):
        proc = subprocess.run([sys.executable, "-S", "-B", str(ROOT / "run_kernel.py"), "contract"],
                              capture_output=True, timeout=5)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(b"Use python -I -S -B", proc.stderr)

    def test_cli_exit_codes(self):
        command = [sys.executable, "-I", "-S", "-B", str(ROOT / "run_kernel.py"), "--state-root", str(self.store.root)]
        for mode, expected in ((["run-slot", "1"], 0), (["run-slot", "1"], 2), (["--expect-contract", "v99", "contract"], 2)):
            proc = subprocess.run(command + mode, capture_output=True, timeout=10)
            self.assertEqual(proc.returncode, expected, proc.stdout)
            json.loads(proc.stdout)


class ResourceTests(unittest.TestCase):
    def probe(self, mode):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        command = [sys.executable, "-I", "-S", "-B", str(ROOT / "tests/limit_probe.py"), mode, str(os.getpid())]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=temp.name, env=clean_environment(Path(temp.name)))
        job = None
        try:
            if os.name == "nt":
                job = WindowsJob(128, 1)
                job.assign(process)
            stdout, stderr = process.communicate(b"G", timeout=8)
            return process.returncode, stdout, stderr
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if job is not None:
                job.close()

    def test_memory_limit_is_enforced(self):
        code, stdout, stderr = self.probe("memory")
        self.assertEqual(code, 42, (stdout, stderr))

    def test_cpu_limit_is_enforced(self):
        code, stdout, stderr = self.probe("cpu")
        self.assertNotEqual(code, 0, (stdout, stderr))
        self.assertNotEqual(code, 70, (stdout, stderr))
        self.assertIn(b"cpu_probe_ready", stdout)
        self.assertEqual(stderr, b"")
        if sys.platform.startswith("linux"):
            self.assertIn(code, (-9, -24))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux parent-death guard required")
    def test_linux_parent_death_kills_worker(self):
        import selectors
        program = (
            "import os,subprocess,sys; "
            "p=subprocess.Popen([sys.executable,'-I','-S','-B',sys.argv[1],'sleep',str(os.getpid())],"
            "stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE); "
            "p.stdin.write(b'G');p.stdin.flush(); "
            "assert p.stdout.readline()==b'ready\\n'; "
            "print(p.pid,flush=True);sys.stdin.buffer.read(1)"
        )
        parent = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", program,
                                   str(ROOT / "tests/limit_probe.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        child_pid = None
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(parent.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=5), "parent bootstrap timed out")
                child_pid = int(parent.stdout.readline().strip())
            parent.kill()
            parent.communicate(timeout=3)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                proc = Path(f"/proc/{child_pid}/stat")
                try:
                    state = proc.read_text().rsplit(")", 1)[1].split()[0]
                except FileNotFoundError:
                    return
                if state == "Z":
                    return  # Exited; reaping belongs to the adopting host process.
                time.sleep(0.01)
            self.fail("worker survived owner termination")
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.communicate(timeout=3)
            if child_pid is not None:
                try:
                    os.kill(child_pid, 9)
                except ProcessLookupError:
                    pass

    @unittest.skipUnless(os.name == "nt", "Windows Job Object host required")
    def test_windows_job_close_terminates(self):
        command = [sys.executable, "-I", "-S", "-B", str(ROOT / "tests/limit_probe.py"), "sleep", str(os.getpid())]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        job, reader, banner = None, None, []
        try:
            job = WindowsJob(128, 1)
            job.assign(process)
            process.stdin.write(b"G")
            process.stdin.flush()
            reader = threading.Thread(target=lambda: banner.append(process.stdout.readline()), daemon=True)
            reader.start()
            reader.join(5)
            self.assertFalse(reader.is_alive(), "worker readiness timed out")
            self.assertEqual([line.strip() for line in banner], [b"ready"])
            self.assertIsNone(process.poll(), "worker ended before the containment check")
            # Windows kill-on-close can report exit 0. Verify that a known-live
            # 30-second task stops within 3 seconds without reaching completion.
            job.close()
            process.wait(timeout=3)
            stdout, stderr = process.communicate(timeout=3)
            self.assertNotIn(b"completed", stdout)
            self.assertEqual(stderr, b"")
        finally:
            if job is not None:
                job.close()
            if process.poll() is None:
                process.kill()
            if reader is not None:
                reader.join(3)
            process.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
