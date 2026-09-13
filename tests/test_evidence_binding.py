from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ansible_kernel.contract import canonical, make_request
from ansible_kernel.kernel import Kernel
from ansible_kernel.queries import events_page, inspect_job
from ansible_kernel.state import StateError, Store, append, journal


class EvidenceBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state')
        self.kernel = Kernel(self.store)
        self.count = 0

    def success(self):
        self.count += 1
        result = self.kernel.execute(canonical(make_request('binding-' + str(self.count))))
        self.assertEqual(result['worker_outcome'], 'success')
        return result['job_id']

    def files(self, job):
        return {p.name: p.read_bytes() for p in self.store.job(job).iterdir() if p.is_file()}

    def rewrite_events(self, job, change):
        # Test-only reconstruction of valid hash chains to exercise semantic checks.
        path = self.store.job(job) / 'status.jsonl'
        rows = journal(path)
        change(rows)
        path.unlink()
        for row in rows:
            append(path, row)

    def legacy(self, job):
        path = self.store.job(job)
        manifest = {n: hashlib.sha256((path / n).read_bytes()).hexdigest()
                    for n in ('worker.json', 'provider.json')}
        (path / 'manifest.json').write_bytes(canonical(manifest) + b'\n')
        def convert(rows):
            rows[-1].pop('manifest_sha256', None)
            rows[-1]['result']['implementation_version'] = '0.2.0'
        self.rewrite_events(job, convert)

    def rehash_file(self, job, name, value):
        path = self.store.job(job)
        raw = canonical(value) + b'\n'
        (path / name).write_bytes(raw)
        manifest = json.loads((path / 'manifest.json').read_bytes())
        hashes = manifest.get('files', manifest)
        hashes[name] = hashlib.sha256(raw).hexdigest()
        (path / 'manifest.json').write_bytes(canonical(manifest) + b'\n')

    def assert_invalid(self, job):
        result = self.store.result(job)
        self.assertEqual(result['worker_outcome'], 'invalid_result', result)
        return result

    def test_swapped_complete_bundles_cannot_satisfy_other_job(self):
        first, second = self.success(), self.success()
        for name in ('worker.json', 'provider.json', 'manifest.json'):
            (self.store.job(second) / name).write_bytes((self.store.job(first) / name).read_bytes())
        self.assert_invalid(second)

    def test_manifest_is_job_bound_and_anchored_in_terminal_event(self):
        job = self.success()
        raw = (self.store.job(job) / 'manifest.json').read_bytes()
        manifest = json.loads(raw)
        self.assertEqual(manifest.get('manifest_version'), 'ansible.evidence-manifest.v2')
        self.assertEqual(manifest['job_id'], job)
        self.assertEqual(manifest['runner_id'], 'noop_v1')
        self.assertEqual(manifest['runner_contract'], 'ansible.runner.noop.v1')
        self.assertEqual(set(manifest['files']), {'metadata.json', 'provider.json', 'worker.json'})
        self.assertEqual(self.store.events(job)[-1]['manifest_sha256'], hashlib.sha256(raw).hexdigest())

    def test_rehashed_changed_output_does_not_reestablish_success(self):
        job = self.success()
        value = json.loads((self.store.job(job) / 'worker.json').read_bytes())
        value['final_output'] = 'different output'
        self.rehash_file(job, 'worker.json', value)
        self.assert_invalid(job)

    def test_rehashed_metadata_cannot_change_slot_identity(self):
        job = self.success()
        value = json.loads((self.store.job(job) / 'metadata.json').read_bytes())
        value['slot_context'] = {'slot': 4, 'generation': 100}
        self.rehash_file(job, 'metadata.json', value)
        self.assert_invalid(job)

    def test_missing_metadata_invalidates_current_success(self):
        job = self.success()
        (self.store.job(job) / 'metadata.json').unlink()
        self.assertEqual(self.assert_invalid(job)['evidence'], 'missing')

    def test_new_success_requires_manifest_anchor(self):
        job = self.success()
        self.rewrite_events(job, lambda rows: rows[-1].pop('manifest_sha256', None))
        self.assert_invalid(job)

    def test_bad_anchor_is_a_typed_lifecycle_refusal(self):
        job = self.success()
        self.rewrite_events(job, lambda rows: rows[-1].update(manifest_sha256='../wrong'))
        with self.assertRaisesRegex(StateError, 'INVALID_MANIFEST_ANCHOR'):
            self.store.result(job)

    def test_anchor_not_permitted_on_nonterminal_event(self):
        job = self.success()
        self.rewrite_events(job, lambda rows: rows[0].update(manifest_sha256='a' * 64))
        with self.assertRaisesRegex(StateError, 'PREMATURE_MANIFEST_ANCHOR'):
            self.store.result(job)

    def test_legacy_valid_result_remains_readable_without_mutation(self):
        job = self.success(); self.legacy(job)
        before = self.files(job)
        self.assertEqual(self.store.result(job)['worker_outcome'], 'success')
        self.assertEqual(before, self.files(job))

    def test_legacy_swapped_worker_is_refused_even_with_matching_hashes(self):
        first, second = self.success(), self.success()
        self.legacy(second)
        worker = json.loads((self.store.job(first) / 'worker.json').read_bytes())
        self.rehash_file(second, 'worker.json', worker)
        self.assert_invalid(second)

    def test_legacy_rehashed_wrong_predicate_is_not_success(self):
        job = self.success(); self.legacy(job)
        worker = json.loads((self.store.job(job) / 'worker.json').read_bytes())
        worker['final_output'] = 'not the registered noop output'
        self.rehash_file(job, 'worker.json', worker)
        self.assert_invalid(job)

    def test_legacy_retry_provider_error_overrides_stale_success(self):
        job = self.success(); self.legacy(job)
        worker = json.loads((self.store.job(job) / 'worker.json').read_bytes())
        worker.update(retry_exhausted=True, error_class='provider')
        self.rehash_file(job, 'worker.json', worker)
        self.assert_invalid(job)

    def test_legacy_invalid_worker_shape_does_not_pass_hash_only_check(self):
        job = self.success(); self.legacy(job)
        self.rehash_file(job, 'worker.json', {'job_id': job, 'outcome': 'success'})
        self.assert_invalid(job)

    def test_legacy_provider_must_have_host_enforcement_evidence(self):
        job = self.success(); self.legacy(job)
        provider = json.loads((self.store.job(job) / 'provider.json').read_bytes())
        provider['limits_applied'] = False
        self.rehash_file(job, 'provider.json', provider)
        self.assert_invalid(job)

    def test_old_manifest_cannot_silently_downgrade_new_result(self):
        job = self.success()
        version = self.store.result(job)['implementation_version']
        self.legacy(job)
        self.rewrite_events(job, lambda rows: rows[-1]['result'].update(implementation_version=version))
        self.assert_invalid(job)

    def test_contradictory_success_axes_are_refused(self):
        cases = [ {'admission': 'rejected_policy'}, {'transport': 'retry_exhausted'},
                  {'evidence': 'partial'}, {'infrastructure': {'state': 'completed', 'exit_code': 9, 'controller_completed': True}} ]
        for changes in cases:
            job = self.success()
            self.rewrite_events(job, lambda rows: rows[-1]['result'].update(changes))
            with self.subTest(changes=changes):
                self.assert_invalid(job)

    def test_wrong_terminal_phase_cannot_claim_success(self):
        job = self.success()
        self.rewrite_events(job, lambda rows: rows[-1].update(state='failed'))
        self.assert_invalid(job)

    def test_every_query_surface_uses_revalidated_result(self):
        a, b = self.success(), self.success()
        for name in ('worker.json', 'provider.json', 'manifest.json'):
            (self.store.job(b) / name).write_bytes((self.store.job(a) / name).read_bytes())
        self.assertEqual(inspect_job(self.store,b)['verified_result']['worker_outcome'], 'invalid_result')
        self.assertEqual(events_page(self.store,b)['verified_result']['worker_outcome'], 'invalid_result')
        status = next(v for v in self.store.statuses() if v['job_id']==b)
        self.assertEqual(status['result']['worker_outcome'], 'invalid_result')

    def test_revalidation_does_not_mutate_or_read_lifecycle_twice(self):
        job = self.success()
        before = self.files(job)
        with patch.object(self.store, 'events', wraps=self.store.events) as events:
            self.assertEqual(inspect_job(self.store,job)['verified_result']['worker_outcome'], 'success')
        self.assertEqual(events.call_count, 1)
        self.assertEqual(before, self.files(job))

    def test_fixed_manifest_whitelist_rejects_extra_paths(self):
        job = self.success()
        manifest = json.loads((self.store.job(job) / 'manifest.json').read_bytes())
        manifest.get('files', manifest)['../secret'] = 'a' * 64
        (self.store.job(job) / 'manifest.json').write_bytes(canonical(manifest))
        self.assert_invalid(job)

    def test_non_success_and_rejected_results_remain_observable(self):
        idle = self.kernel.run_slot(2)
        self.assertEqual(self.store.result(idle['job_id']), idle)
        with patch('ansible_kernel.kernel.provider.run', side_effect=RuntimeError('not logged')):
            result = self.kernel.execute(canonical(make_request('provider-fail')))
        self.assertEqual(self.store.result(result['job_id']), result)

    def test_direct_evidence_verification_checks_job_binding(self):
        a, b = self.success(), self.success()
        for n in ('worker.json','provider.json','manifest.json'):
            (self.store.job(b)/n).write_bytes((self.store.job(a)/n).read_bytes())
        self.assertEqual(self.store.verify_evidence(b), 'invalid')
