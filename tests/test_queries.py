from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from ansible_kernel.cli import main
from ansible_kernel.contract import canonical, make_request
from ansible_kernel.kernel import Kernel, ROOT
from ansible_kernel.queries import MAX_PAGE_SIZE, events_page, inspect_job
from ansible_kernel.state import StateError, Store


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "state"
        self.store = Store(self.root)
        self.kernel = Kernel(self.store)

    def successful_job(self, slot=False):
        result = self.kernel.run_slot(1) if slot else self.kernel.execute(canonical(make_request("query-test")))
        self.assertEqual(result["worker_outcome"], "success")
        return result["job_id"]

    def tree_hashes(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob("*") if path.is_file()}

    def cli(self, *args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["--state-root", str(self.root), *args])
        return code, json.loads(stdout.getvalue())

    def test_inspection_reports_verified_result_and_slot_binding(self):
        job = self.successful_job(slot=True)
        result = inspect_job(self.store, job)
        self.assertEqual(result["contract_version"], "ansible.job-status.v1")
        self.assertEqual(result["slot_context"], {"slot": 1, "generation": 1})
        self.assertTrue(result["terminal"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["verified_result"]["worker_outcome"], "success")
        self.assertIsNone(result["control_requested"])

    def test_idle_refusal_is_bound_without_launch(self):
        result = self.kernel.run_slot(2)
        self.assertEqual(result["reason"], "SLOT_IDLE")
        summary = inspect_job(self.store, result["job_id"])
        self.assertEqual(summary["slot_context"], {"slot": 2, "generation": 1})
        self.assertEqual(summary["state"], "rejected")

    def test_repeat_once_refusal_keeps_slot_binding(self):
        self.successful_job(slot=True)
        result = self.kernel.run_slot(1)
        self.assertEqual(result["reason"], "GENERATION_ALREADY_RESERVED")
        self.assertEqual(inspect_job(self.store, result["job_id"])["slot_context"], {"slot": 1, "generation": 1})

    def test_direct_job_has_no_invented_slot(self):
        job = self.successful_job()
        self.assertIsNone(inspect_job(self.store, job)["slot_context"])

    def test_legacy_metadata_has_no_invented_slot(self):
        job = self.store.new_job({"contract_version": "ansible.execution.v1"})
        self.assertIsNone(inspect_job(self.store, job)["slot_context"])

    def test_binding_remains_original_after_slot_refresh(self):
        job = self.successful_job(slot=True)
        values = self.kernel.slots()
        values[0].update(generation=2, label="later assignment")
        incoming = Path(self.temp.name) / "incoming"
        incoming.mkdir()
        for value in values:
            (incoming / f'slot{value["slot"]}.json').write_bytes(canonical(value))
        self.kernel.refresh(incoming)
        self.assertEqual(inspect_job(self.store, job)["slot_context"]["generation"], 1)

    def test_pages_have_stable_cursors_across_store_restart(self):
        job = self.successful_job()
        cursor, seen = 0, []
        while True:
            page = events_page(Store(self.root, create=False), job, after=cursor, limit=2)
            self.assertLessEqual(len(page["events"]), 2)
            seen.extend(page["events"])
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        self.assertEqual([event["sequence"] for event in seen], list(range(1, len(seen) + 1)))
        self.assertEqual(len(seen), len(self.store.events(job)))
        self.assertEqual(seen[-1]["state"], "completed")
        self.assertEqual(events_page(self.store, job, after=cursor)["events"], [])

    def test_empty_known_job_has_no_false_result(self):
        job = self.store.new_job({})
        (self.store.job(job) / "status.jsonl").unlink()
        page = events_page(self.store, job)
        self.assertEqual(page["total_events"], 0)
        self.assertFalse(page["terminal"])
        self.assertIsNone(page["verified_result"])
        summary = inspect_job(self.store, job)
        self.assertEqual(summary["state"], "unknown")
        self.assertEqual(summary["elapsed_ms"], 0)

    def test_invalid_cursors_fail_closed(self):
        job = self.store.new_job({})
        for cursor in (-1, True, "0", 0.0, 2147483648):
            with self.subTest(cursor=cursor), self.assertRaisesRegex(StateError, "INVALID_EVENT_CURSOR"):
                events_page(self.store, job, after=cursor)
        with self.assertRaisesRegex(StateError, "EVENT_CURSOR_AHEAD"):
            events_page(self.store, job, after=2)

    def test_invalid_page_sizes_fail_closed(self):
        job = self.store.new_job({})
        for limit in (0, -1, True, "1", 1.0, MAX_PAGE_SIZE + 1):
            with self.subTest(limit=limit), self.assertRaisesRegex(StateError, "INVALID_EVENT_PAGE_SIZE"):
                events_page(self.store, job, limit=limit)

    def test_no_raw_success_leaks_from_corrupted_evidence(self):
        job = self.successful_job()
        (self.store.job(job) / "worker.json").write_bytes(b"tampered")
        for response in (inspect_job(self.store, job), events_page(self.store, job)):
            self.assertEqual(response["verified_result"]["worker_outcome"], "invalid_result")
        page = events_page(self.store, job)
        self.assertTrue(all(set(event) == {"sequence", "state", "time_ns"} for event in page["events"]))
        self.assertNotIn('"worker_outcome": "success"', json.dumps(page))

    def test_queries_do_not_mutate_existing_files_or_take_execution_lock(self):
        job = self.successful_job(slot=True)
        before = self.tree_hashes()
        with self.store.lock():
            inspect_job(self.store, job)
            events_page(self.store, job)
        self.assertEqual(before, self.tree_hashes())

    def test_unknown_job_does_not_create_directory(self):
        before = self.tree_hashes()
        for query in (inspect_job, events_page):
            with self.assertRaisesRegex(StateError, "UNKNOWN_JOB"):
                query(self.store, "a" * 32)
        self.assertEqual(before, self.tree_hashes())
        self.assertFalse((self.store.runs / ("a" * 32)).exists())

    def test_invalid_job_ids_never_become_paths(self):
        for job in ("../outside", "a" * 31, "A" * 32, None):
            for query in (inspect_job, events_page):
                with self.subTest(job=job), self.assertRaisesRegex(StateError, "INVALID_JOB_ID"):
                    query(self.store, job)

    def test_missing_read_only_root_is_not_created(self):
        missing = Path(self.temp.name) / "not-created"
        with self.assertRaisesRegex(StateError, "STATE_ROOT_NOT_FOUND"):
            Store(missing, create=False)
        self.assertFalse(missing.exists())

    def test_missing_read_only_runs_directory_is_not_created(self):
        root = Path(self.temp.name) / "root-without-runs"
        root.mkdir(mode=0o700)
        with self.assertRaisesRegex(StateError, "RUNS_DIRECTORY_NOT_FOUND"):
            Store(root, create=False)
        self.assertFalse((root / "runs").exists())

    def test_malformed_binding_is_refused(self):
        for binding in ({"slot": True, "generation": 1}, {"slot": 1, "generation": 0},
                        {"slot": 1, "generation": 1, "command": "no"}, []):
            job = self.store.new_job({"slot_context": binding})
            with self.assertRaisesRegex(StateError, "INVALID_SLOT_CONTEXT"):
                inspect_job(self.store, job)

    def test_torn_journal_is_never_silently_repaired(self):
        job = self.store.new_job({})
        path = self.store.job(job) / "status.jsonl"
        path.write_bytes(path.read_bytes()[:-1])
        before = self.tree_hashes()
        for query in (inspect_job, events_page):
            with self.assertRaisesRegex(StateError, "TORN_JOURNAL"):
                query(self.store, job)
        self.assertEqual(before, self.tree_hashes())

    def test_active_elapsed_is_nonnegative_and_terminal_elapsed_freezes(self):
        job = self.store.new_job({})
        start = self.store.events(job)[0]["time_ns"]
        self.assertEqual(inspect_job(self.store, job, now_ns=start + 12_000_000)["elapsed_ms"], 12)
        self.assertEqual(inspect_job(self.store, job, now_ns=start - 1)["elapsed_ms"], 0)
        completed = self.successful_job()
        a = inspect_job(self.store, completed, now_ns=start)
        b = inspect_job(self.store, completed, now_ns=start + 900_000_000_000)
        self.assertEqual(a["elapsed_ms"], b["elapsed_ms"])

    def test_control_marker_is_not_claimed_as_termination(self):
        job = self.store.new_job({})
        self.store.control(job, "cancel")
        summary = inspect_job(self.store, job)
        self.assertEqual(summary["control_requested"], "cancel")
        self.assertFalse(summary["terminal"])
        self.assertIsNone(summary["verified_result"])
        self.store.control(job, "contain")
        self.assertEqual(inspect_job(self.store, job)["control_requested"], "contain")

    def test_queries_and_statuses_read_lifecycle_only_once(self):
        job = self.successful_job()
        for query in (lambda: inspect_job(self.store, job), lambda: events_page(self.store, job), self.store.statuses):
            with patch.object(self.store, "events", wraps=self.store.events) as events:
                query()
            self.assertEqual(events.call_count, 1)

    def test_cli_queries_and_contract_advertisement(self):
        job = self.successful_job()
        code, summary = self.cli("inspect", job)
        self.assertEqual(code, 0)
        self.assertEqual(summary["job_id"], job)
        code, page = self.cli("events", job, "--limit", "1")
        self.assertEqual(code, 0)
        self.assertEqual(len(page["events"]), 1)
        code, contract = self.cli("contract")
        self.assertEqual(contract["query_contracts"]["events"], "ansible.events.v1")
        self.assertEqual(contract["max_event_page_size"], MAX_PAGE_SIZE)
        self.assertFalse(contract["real_agent_qualified"])

    def test_cli_bad_cursor_returns_typed_error(self):
        job = self.store.new_job({})
        code, error = self.cli("events", job, "--after", "-1")
        self.assertEqual(code, 3)
        self.assertEqual(error["error"], "INVALID_EVENT_CURSOR")

    def test_cli_does_not_create_missing_root(self):
        missing = Path(self.temp.name) / "cli-missing"
        for command in ("inspect", "events"):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = main(["--state-root", str(missing), command, "a" * 32])
            self.assertEqual(code, 3)
            self.assertEqual(json.loads(output.getvalue())["error"], "STATE_ROOT_NOT_FOUND")
            self.assertFalse(missing.exists())

    def test_real_controller_can_be_observed_without_recovery_or_interruption(self):
        request = Path(self.temp.name) / "request.json"
        request.write_bytes(canonical(make_request("live-query", duration_ms=1000)))
        process = subprocess.Popen([sys.executable, "-I", "-S", "-B", str(ROOT / "run_kernel.py"),
                                    "--state-root", str(self.root), "run", str(request)],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            observed = False
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and process.poll() is None:
                for candidate in self.store.runs.iterdir():
                    try:
                        summary = inspect_job(self.store, candidate.name)
                    except (StateError, OSError):
                        continue  # publication may currently be between fsyncs
                    if summary["state"] == "running":
                        self.assertFalse(summary["terminal"])
                        self.assertIsNone(summary["verified_result"])
                        observed = True
                        break
                if observed:
                    break
                time.sleep(0.01)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["worker_outcome"], "success")
            self.assertTrue(observed, "Did not observe live running state")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def test_malformed_metadata_is_typed_refusal(self):
        job = self.store.new_job({})
        (self.store.job(job) / "metadata.json").write_bytes(b'{"slot_context":')
        with self.assertRaisesRegex(StateError, "INVALID_JOB_METADATA"):
            inspect_job(self.store, job)

    def test_invalid_terminal_record_is_not_a_query_success(self):
        job = self.store.new_job({})
        self.store.transition(job, "failed", result={"worker_outcome": "success"})
        for query in (inspect_job, events_page):
            with self.assertRaisesRegex(StateError, "INVALID_TERMINAL_RECORD"):
                query(self.store, job)

    def test_redirected_job_directory_is_refused(self):
        target = Path(self.temp.name) / "elsewhere"
        target.mkdir()
        link = self.store.runs / ("b" * 32)
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Host does not permit symlink creation")
        for query in (inspect_job, events_page):
            with self.assertRaisesRegex(StateError, "PATH_REDIRECTION_REFUSED"):
                query(self.store, "b" * 32)
