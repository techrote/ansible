from __future__ import annotations

from contextlib import redirect_stdout
import copy
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ansible_kernel import cli, config, slot_transport as t
from ansible_kernel.contract import Refusal, canonical, digest
from ansible_kernel.kernel import Kernel, ROOT
from ansible_kernel.state import StateError, Store, append

TOKEN = "ghp_" + "test_not_a_real_token_" * 2


def tree_response(entries):
    # Fixture construction is checked against native Git in a separate test.
    entries = sorted(entries, key=lambda e: (e["path"] + ("/" if e["mode"] == "040000" else "")).encode())
    raw = b"".join(e["mode"].lstrip("0").encode() + b" " + e["path"].encode()
                    + b"\0" + bytes.fromhex(e["sha"]) for e in entries)
    sha = t.git_oid("tree", raw)
    return sha, canonical({"sha": sha, "tree": entries, "truncated": False}), raw


def fixture(values=None, modes=None, root_mode="040000"):
    values = values or [json.loads((ROOT / "slots" / f"slot{n}.json").read_text()) for n in range(1, 5)]
    values = copy.deepcopy(values)
    raw_slots = [canonical(v) + b"\n" for v in values]
    entries = [{"path": f"slot{n}.json", "mode": (modes or {}).get(n, "100644"),
                "type": "commit" if (modes or {}).get(n) == "160000" else "blob",
                "sha": t.git_oid("blob", raw), "size": len(raw)}
               for n, raw in enumerate(raw_slots, 1)]
    slots_sha, slots_tree, _ = tree_response(entries)
    root_sha, root_tree, _ = tree_response([
        {"path": "slots", "mode": root_mode, "type": "tree" if root_mode == "040000" else "blob", "sha": slots_sha},
        {"path": "README.md", "mode": "100644", "type": "blob", "sha": "f" * 40},
    ])
    commit_sha = "a" * 40
    responses = {
        t.REF_PATH: canonical({"ref": t.SOURCE_REF, "object": {"type": "commit", "sha": commit_sha}}),
        t.PREFIX + "commits/" + commit_sha: canonical({"sha": commit_sha, "tree": {"sha": root_sha}}),
        t.PREFIX + "trees/" + root_sha: root_tree,
        t.PREFIX + "trees/" + slots_sha: slots_tree,
    }
    responses.update({t.PREFIX + "blobs/" + e["sha"]: raw for e, raw in zip(entries, raw_slots)})
    return responses


class Reader:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def __call__(self, path, *, raw=False):
        self.calls.append((path, raw))
        return self.responses[path]


class Response:
    def __init__(self, data=b"{}", status=200, headers=None):
        self.data, self.status = io.BytesIO(data), status
        self.headers = headers or []
        self.reads = []

    def getheaders(self):
        return self.headers

    def getheader(self, name, default=None):
        return next((v for k, v in self.headers if k.lower() == name.lower()), default)

    def read1(self, size):
        self.reads.append(size)
        return self.data.read(size)


class SnapshotTests(unittest.TestCase):
    def test_pins_once_and_uses_only_oid_paths_after_ref(self):
        reader = Reader(fixture())
        snapshot = t.collect_snapshot(reader)
        self.assertEqual(len(reader.calls), 8)
        self.assertEqual(sum(p == t.REF_PATH for p, _ in reader.calls), 1)
        self.assertTrue(all(t.SOURCE_REF not in p for p, _ in reader.calls[1:]))
        self.assertEqual(snapshot["provenance"]["commit_sha"], "a" * 40)
        for n, record in enumerate(snapshot["provenance"]["files"], 1):
            raw = reader.responses[t.PREFIX + "blobs/" + record["blob_sha"]]
            self.assertEqual(record["content_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(record["value_sha256"], digest(snapshot["slots"][n-1]))
            self.assertEqual(record["path"], f"slots/slot{n}.json")

    def test_wrong_ref_or_object_type_is_refused(self):
        for ref, kind in (("refs/heads/other", "commit"), (t.SOURCE_REF, "tag")):
            data = fixture()
            data[t.REF_PATH] = canonical({"ref": ref, "object": {"type": kind, "sha": "a" * 40}})
            with self.subTest(ref=ref, kind=kind), self.assertRaisesRegex(t.TransportError, "TRANSPORT_REF_MISMATCH"):
                t.collect_snapshot(Reader(data))

    def test_commit_identity_mismatch_is_refused(self):
        data = fixture()
        key = t.PREFIX + "commits/" + "a" * 40
        response = json.loads(data[key]); response["sha"] = "b" * 40
        data[key] = canonical(response)
        with self.assertRaisesRegex(t.TransportError, "TRANSPORT_COMMIT_MISMATCH"):
            t.collect_snapshot(Reader(data))

    def test_returned_urls_are_never_followed(self):
        data = fixture()
        for key, raw in list(data.items()):
            if "/blobs/" not in key:
                value = json.loads(raw); value["url"] = "https://evil.invalid/token"
                data[key] = canonical(value)
        reader = Reader(data)
        t.collect_snapshot(reader)
        self.assertTrue(all(path.startswith(t.PREFIX) for path, _ in reader.calls))

    def test_blob_swap_size_and_bytes_mismatch_refused(self):
        for mutate in (lambda raw: b"x" * len(raw), lambda raw: raw + b" "):
            data = fixture(); key = next(k for k in data if "/blobs/" in k)
            data[key] = mutate(data[key])
            with self.assertRaisesRegex(t.TransportError, "TRANSPORT_BLOB_MISMATCH"):
                t.collect_snapshot(Reader(data))

    def test_symlink_submodule_and_executable_slots_are_refused(self):
        for mode in ("120000", "160000", "100755"):
            with self.subTest(mode=mode), self.assertRaisesRegex(t.TransportError, "TRANSPORT_FILE_MODE_REFUSED"):
                t.collect_snapshot(Reader(fixture(modes={2: mode})))

    def test_symlink_directory_is_refused(self):
        with self.assertRaisesRegex(t.TransportError, "TRANSPORT_FILE_MODE_REFUSED"):
            t.collect_snapshot(Reader(fixture(root_mode="120000")))

    def test_missing_slot_refused(self):
        with self.assertRaisesRegex(t.TransportError, "TRANSPORT_PATH_MISSING"):
            t.entry_at({}, "slot1.json", "100644")

    def test_tree_duplicate_ambiguous_names_and_modes_refused(self):
        valid = {"path": "name", "mode": "100644", "type": "blob", "sha": "a" * 40}
        cases = [[valid, valid], [{**valid, "path": "../slots"}], [{**valid, "path": "a/b"}],
                 [{**valid, "path": "."}], [{**valid, "path": "a\0b"}],
                 [{**valid, "mode": "bad"}], [{**valid, "type": "tree"}],
                 [{**valid, "sha": "../../x"}]]
        for entries in cases:
            raw = canonical({"sha": "b" * 40, "truncated": False, "tree": entries})
            with self.subTest(entries=entries), self.assertRaises(t.TransportError):
                t.verified_tree(raw, "b" * 40)

    def test_tree_hash_truncation_and_capacity_refused(self):
        sha, raw, _ = tree_response([])
        with self.assertRaisesRegex(t.TransportError, "TRANSPORT_TREE_HASH_MISMATCH"):
            t.verified_tree(canonical({"sha": "a" * 40, "tree": [], "truncated": False}), "a" * 40)
        for replacement in ({"truncated": True}, {"sha": "a" * 40}, {"tree": [0] * 129}):
            with self.subTest(replacement=replacement), self.assertRaises(t.TransportError):
                t.verified_tree(canonical({**json.loads(raw), **replacement}), sha)

    def test_git_tree_and_blob_hashes_match_native_git(self):
        for kind, data in (("blob", b"literal\x00bytes\xff\n"),
                           ("tree", tree_response([
                               {"path": "a", "mode": "040000", "type": "tree", "sha": "b" * 40},
                               {"path": "a.txt", "mode": "100644", "type": "blob", "sha": "c" * 40},
                               {"path": "z", "mode": "120000", "type": "blob", "sha": "d" * 40}])[2])):
            native = subprocess.run(["git", "hash-object", "-t", kind, "--stdin"],
                                    input=data, capture_output=True, check=True).stdout.decode().strip()
            self.assertEqual(t.git_oid(kind, data), native)

    def test_invalid_schema_or_legacy_slots_not_translated(self):
        values = [json.loads((ROOT / "slots" / f"slot{n}.json").read_text()) for n in range(1, 5)]
        values[0]["title"] = values[0].pop("label")
        reader = Reader(fixture(values))
        with self.assertRaisesRegex(t.TransportError, "REMOTE_SLOT_SCHEMA_INVALID"):
            t.collect_snapshot(reader)
        self.assertEqual(len(reader.calls), 8)

    def test_wrong_slot_position_refused(self):
        values = [json.loads((ROOT / "slots" / f"slot{n}.json").read_text()) for n in range(1, 5)]
        values[0]["slot"] = 2
        with self.assertRaisesRegex(t.TransportError, "REMOTE_SLOT_SCHEMA_INVALID"):
            t.collect_snapshot(Reader(fixture(values)))

    def test_bad_json_deep_input_duplicate_and_unicode_refused(self):
        for raw in (b'{"ref":1,"ref":2}', b'[' * 30 + b'0' + b']' * 30,
                    b'{"x":"\\ud800"}', b'NaN', b'{}' + b' ' * 65536):
            with self.subTest(raw=raw[:50]), self.assertRaises(t.TransportError):
                t.json_object(raw)

    def test_receipt_detaches_mutable_caller(self):
        value = t.collect_snapshot(Reader(fixture()))
        validated = t.validate_snapshot(value)
        value["slots"][0]["label"] = "later mutation"
        self.assertNotEqual(value["slots"], validated["slots"])

    def test_receipt_wrong_digest_path_extra_field_or_repository_refused(self):
        base = t.collect_snapshot(Reader(fixture()))
        for mutate in (lambda p: p.update(slots_digest="0" * 64),
                       lambda p: p.update(repository="other/repo"),
                       lambda p: p.update(token=TOKEN),
                       lambda p: p["files"][0].update(path="slots/slot2.json"),
                       lambda p: p["files"][0].update(value_sha256="0" * 64)):
            value = copy.deepcopy(base); mutate(value["provenance"])
            with self.assertRaisesRegex(t.TransportError, "TRANSPORT_SNAPSHOT_INVALID"):
                t.validate_snapshot(value)


class HTTPTests(unittest.TestCase):
    def exchange(self, response, path=t.REF_PATH, raw=False):
        with patch.object(t.http.client, "HTTPSConnection") as constructor:
            connection = constructor.return_value
            connection.getresponse.return_value = response
            value = t.GitHubReader(TOKEN)(path, raw=raw)
        self.assertTrue(connection.close.called)
        return value, constructor, connection

    def test_fixed_tls_origin_headers_and_explicit_auth(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "https://evil.invalid", "GH_TOKEN": "other",
                                     "NETRC": "/not-used"}):
            value, constructor, connection = self.exchange(Response(b'{"ok":true}'))
        self.assertEqual(value, b'{"ok":true}')
        self.assertEqual(constructor.call_args.args, ("api.github.com", 443))
        context = constructor.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, t.ssl.CERT_REQUIRED)
        headers = connection.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertEqual(connection.request.call_args.args, ("GET", t.REF_PATH))
        self.assertFalse(connection.set_tunnel.called)

    def test_raw_media_type_only_for_blob(self):
        _, _, connection = self.exchange(Response(b"{}"), t.PREFIX + "blobs/" + "a" * 40, raw=True)
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Accept"], "application/vnd.github.raw+json")

    def test_redirect_auth_missing_rate_and_error_body_are_redacted(self):
        for status, expected in ((301, "TRANSPORT_REDIRECT_REFUSED"), (307, "TRANSPORT_REDIRECT_REFUSED"),
                                 (401, "TRANSPORT_AUTH_FAILED"), (403, "TRANSPORT_AUTH_FAILED"),
                                 (404, "TRANSPORT_NOT_FOUND"), (429, "TRANSPORT_RATE_LIMITED"),
                                 (500, "TRANSPORT_HTTP_FAILED")):
            response = Response(TOKEN.encode(), status, [("Location", "https://evil.invalid/" + TOKEN)])
            with patch.object(t.http.client, "HTTPSConnection") as constructor:
                connection = constructor.return_value; connection.getresponse.return_value = response
                with self.subTest(status=status), self.assertRaisesRegex(t.TransportError, expected) as exc:
                    t.GitHubReader(TOKEN)(t.REF_PATH)
                self.assertNotIn(TOKEN, str(exc.exception))
                self.assertEqual(connection.request.call_count, 1)
                self.assertTrue(connection.close.called)
                self.assertEqual(response.reads, [])

    def test_response_size_bounded_with_and_without_content_length(self):
        for response in (Response(b"x" * 65537), Response(b"", headers=[("Content-Length", "65537")])):
            with self.assertRaisesRegex(t.TransportError, "TRANSPORT_RESPONSE_LIMIT"):
                self.exchange(response)
            self.assertLessEqual(sum(response.reads), 65537)

    def test_exact_response_size_allowed(self):
        self.assertEqual(len(self.exchange(Response(b"x" * 65536))[0]), 65536)

    def test_bad_encoding_length_and_short_body_refused(self):
        for response in (Response(headers=[("Content-Encoding", "gzip")]),
                         Response(headers=[("Content-Length", "2"), ("Content-Length", "2")]),
                         Response(headers=[("Content-Length", "garbage")]),
                         Response(b"x", headers=[("Content-Length", "3")])):
            with self.assertRaises(t.TransportError):
                self.exchange(response)

    def test_timeout_and_io_errors_do_not_echo_private_details(self):
        for failure, expected in ((TimeoutError(TOKEN), "TRANSPORT_TIMEOUT"),
                                  (OSError(TOKEN), "TRANSPORT_IO_FAILED"),
                                  (http.client.BadStatusLine(TOKEN), "TRANSPORT_IO_FAILED")):
            with patch.object(t.http.client, "HTTPSConnection") as constructor:
                constructor.return_value.getresponse.side_effect = failure
                with self.assertRaisesRegex(t.TransportError, expected) as exc:
                    t.GitHubReader(TOKEN)(t.REF_PATH)
                self.assertNotIn(TOKEN, str(exc.exception))
                self.assertTrue(constructor.return_value.close.called)

    def test_request_budget_and_deadline(self):
        reader = t.GitHubReader(TOKEN)
        reader._requests = 8
        with self.assertRaisesRegex(t.TransportError, "TRANSPORT_REQUEST_LIMIT"):
            reader(t.REF_PATH)
        reader = t.GitHubReader(TOKEN); reader._deadline = time.monotonic() - 1
        with self.assertRaisesRegex(t.TransportError, "TRANSPORT_TIMEOUT"):
            reader(t.REF_PATH)

    def test_slow_drip_cannot_reset_total_deadline(self):
        reader = t.GitHubReader(TOKEN)
        response = Response(b"x" * 50)
        def drip(_):
            reader._deadline = time.monotonic() - 1
            return b"x"
        response.read1 = drip
        with patch.object(t.http.client, "HTTPSConnection") as constructor:
            constructor.return_value.getresponse.return_value = response
            with self.assertRaisesRegex(t.TransportError, "TRANSPORT_TIMEOUT"):
                reader(t.REF_PATH)

    def test_arbitrary_paths_or_wrong_media_type_never_connect(self):
        reader = t.GitHubReader(TOKEN)
        with patch.object(t.http.client, "HTTPSConnection") as connection:
            for path, raw in (("https://evil.invalid", False), (t.PREFIX + "trees/../../x", False),
                              (t.PREFIX + "commits/" + "a" * 40, True),
                              (t.PREFIX + "blobs/" + "a" * 40, False),
                              (t.REF_PATH + "?other=1", False)):
                with self.subTest(path=path), self.assertRaisesRegex(t.TransportError, "TRANSPORT_PATH_REFUSED"):
                    reader(path, raw=raw)
        connection.assert_not_called()

    def test_invalid_credentials_fail_before_connect_and_are_not_repr(self):
        for value in ("", TOKEN + "\r\nAuthorization:x", "x" * 256, "a b" * 20, None):
            with self.assertRaisesRegex(t.TransportError, "TRANSPORT_CREDENTIAL_INVALID"):
                t.GitHubReader(value)
        self.assertNotIn(TOKEN, repr(t.GitHubReader(TOKEN)))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "state")
        self.kernel = Kernel(self.store)
        self.snapshot = t.collect_snapshot(Reader(fixture()))

    def test_atomic_publication_provenance_restart_and_idempotence(self):
        result = self.kernel.refresh_remote(self.snapshot)
        self.assertTrue(result["changed"])
        before = self.store.ledger.read_bytes()
        restart = Kernel(Store(self.store.root))
        self.assertEqual(restart.slots(), self.snapshot["slots"])
        self.assertEqual(restart.slot_source(), self.snapshot["provenance"])
        self.assertFalse(restart.refresh_remote(self.snapshot)["changed"])
        self.assertEqual(self.store.ledger.read_bytes(), before)

    def test_new_commit_same_slots_records_new_provenance_once(self):
        self.kernel.refresh_remote(self.snapshot)
        other = copy.deepcopy(self.snapshot); other["provenance"]["commit_sha"] = "b" * 40
        self.assertTrue(self.kernel.refresh_remote(other)["changed"])
        before = self.store.ledger.read_bytes()
        self.assertFalse(self.kernel.refresh_remote(other)["changed"])
        self.assertEqual(self.store.ledger.read_bytes(), before)

    def test_bad_quartet_does_not_change_previous_ledger(self):
        self.kernel.refresh_remote(self.snapshot)
        before = self.store.ledger.read_bytes()
        for changes in ({"generation": 1, "label": "same-gen rewrite"}, {"generation": 0}):
            values = copy.deepcopy(self.snapshot["slots"]); values[0]["generation"] = 2; values[3].update(changes)
            with self.assertRaises((Refusal, t.TransportError)):
                self.kernel.refresh_remote(t.collect_snapshot(Reader(fixture(values))))
            self.assertEqual(self.store.ledger.read_bytes(), before)

    def test_remote_rollback_is_refused_after_advancement(self):
        values = copy.deepcopy(self.snapshot["slots"]); values[0]["generation"] = 2
        self.kernel.refresh_remote(t.collect_snapshot(Reader(fixture(values))))
        before = self.store.ledger.read_bytes()
        with self.assertRaisesRegex(Refusal, "GENERATION_ROLLBACK"):
            self.kernel.refresh_remote(self.snapshot)
        self.assertEqual(self.store.ledger.read_bytes(), before)

    def test_local_publication_clears_remote_source_without_changing_once_claims(self):
        self.kernel.refresh_remote(self.snapshot)
        self.assertEqual(self.kernel.run_slot(1)["worker_outcome"], "success")
        incoming = Path(self.temp.name) / "incoming"; incoming.mkdir()
        values = copy.deepcopy(self.snapshot["slots"]); values[1].update(generation=2, label="local new data")
        for n, value in enumerate(values, 1):
            (incoming / f"slot{n}.json").write_bytes(canonical(value))
        self.kernel.refresh(incoming)
        self.assertIsNone(self.kernel.slot_source())
        self.assertEqual(self.kernel.run_slot(1)["reason"], "GENERATION_ALREADY_RESERVED")

    def test_bad_provenance_replay_fails_closed_before_execution(self):
        invalid = copy.deepcopy(self.snapshot); invalid["provenance"]["slots_digest"] = "0" * 64
        append(self.store.ledger, {"type": "slots_remote_refreshed", **invalid})
        before = self.store.ledger.read_bytes()
        with self.assertRaisesRegex(StateError, "INVALID_LEDGER_EVENT"):
            self.kernel.run_slot(1)
        self.assertEqual(self.store.statuses(), [])
        self.assertEqual(self.store.ledger.read_bytes(), before)

    def test_later_observation_cannot_keep_stale_remote_provenance(self):
        self.kernel.refresh_remote(self.snapshot)
        changed = copy.deepcopy(self.snapshot["slots"][0]); changed["generation"] = 2
        append(self.store.ledger, {"type": "slot_seen", "slot": changed})
        self.assertIsNone(self.kernel.slot_source())

    def test_busy_publication_leaves_ledger_unchanged(self):
        self.kernel.refresh_remote(self.snapshot); before = self.store.ledger.read_bytes()
        with self.store.lock(), self.assertRaisesRegex(StateError, "LOCK_BUSY"):
            self.kernel.refresh_remote(self.snapshot)
        self.assertEqual(self.store.ledger.read_bytes(), before)

    def test_remote_assignment_does_not_enable_omp(self):
        values = copy.deepcopy(self.snapshot["slots"])
        values[0].update(generation=2, runner_type="omp_blind_review_v1")
        self.kernel.refresh_remote(t.collect_snapshot(Reader(fixture(values))))
        self.assertEqual(self.kernel.run_slot(1)["reason"], "RUNNER_NOT_QUALIFIED")

    def test_snapshot_cannot_spoof_same_generation_values_via_provenance(self):
        invalid = copy.deepcopy(self.snapshot); invalid["slots"][0]["label"] = "spoof"
        with self.assertRaisesRegex(t.TransportError, "TRANSPORT_SNAPSHOT_INVALID"):
            self.kernel.refresh_remote(invalid)
        self.assertFalse(self.store.ledger.exists())


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "state"
        self.config = {"repositories": {}, "local_state_dir": None, "slots_dir": "slots",
                       "approved_models": ["none"], "remote_slots_enabled": True}

    def invoke(self, *args, token=TOKEN):
        stdin = io.TextIOWrapper(io.BytesIO((token + "\n").encode()), encoding="ascii")
        with patch.object(cli, "load_config", return_value=self.config), patch.object(cli.sys, "stdin", stdin):
            with redirect_stdout(io.StringIO()) as output:
                code = cli.main(["--state-root", str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_remote_disabled_by_default_and_no_child_or_state(self):
        self.config.pop("remote_slots_enabled")
        with patch.object(cli, "fetch_remote_snapshot") as fetch:
            code, result = self.invoke("refresh-remote", "--token-stdin")
        self.assertEqual((code, result["error"]), (3, "REMOTE_SLOTS_DISABLED"))
        fetch.assert_not_called(); self.assertFalse(self.root.exists())

    def test_no_ambient_credential_fallback(self):
        with patch.dict(os.environ, {"GH_TOKEN": TOKEN, "GITHUB_TOKEN": TOKEN}):
            with patch.object(cli, "fetch_remote_snapshot") as fetch:
                code, result = self.invoke("refresh-remote")
        self.assertEqual((code, result["error"]), (3, "TRANSPORT_CREDENTIAL_REQUIRED"))
        fetch.assert_not_called(); self.assertFalse(self.root.exists())

    def test_failure_no_state_creation_and_no_secret_in_output(self):
        with patch.object(cli, "fetch_remote_snapshot", side_effect=t.TransportError("TRANSPORT_AUTH_FAILED")):
            code, value = self.invoke("refresh-remote", "--token-stdin")
        self.assertEqual((code, value["error"]), (3, "TRANSPORT_AUTH_FAILED"))
        self.assertNotIn(TOKEN, json.dumps(value)); self.assertFalse(self.root.exists())

    def test_success_publishes_then_readonly_source_reports_provenance(self):
        snapshot = t.collect_snapshot(Reader(fixture()))
        with patch.object(cli, "fetch_remote_snapshot", return_value=snapshot) as fetch:
            code, value = self.invoke("refresh-remote", "--token-stdin")
        self.assertEqual(code, 0); self.assertTrue(value["changed"])
        fetch.assert_called_once_with(TOKEN)
        code, value = self.invoke("slot-source")
        self.assertEqual(value["provenance"], snapshot["provenance"])
        self.assertNotIn(TOKEN, json.dumps(value))

    def test_slot_source_missing_root_does_not_create_it(self):
        code, value = self.invoke("slot-source")
        self.assertEqual((code, value["error"]), (3, "STATE_ROOT_NOT_FOUND"))
        self.assertFalse(self.root.exists())

    def test_config_opt_in_is_strict_boolean(self):
        path = Path(self.temp.name) / "config.json"
        for v in (1, "true", {}, None):
            path.write_bytes(canonical({"remote_slots_enabled": v}))
            with self.subTest(v=v), self.assertRaises(config.ConfigError):
                config.load(path)
        for v in (True, False):
            path.write_bytes(canonical({"remote_slots_enabled": v}))
            self.assertIs(config.load(path)["remote_slots_enabled"], v)


class SupervisorTests(unittest.TestCase):
    def supervise_probe(self, code):
        # Redirect only the test's Popen to trusted deterministic local probes;
        # production never accepts an alternate executable/script from data.
        native = subprocess.Popen
        calls = []
        def start(command, **kwargs):
            calls.append((command, kwargs.copy()))
            return native([sys.executable, "-I", "-S", "-B", "-c", code], **kwargs)
        return patch.object(t.subprocess, "Popen", side_effect=start), calls

    def test_hung_helper_is_killed_and_credentials_not_in_command_or_env(self):
        patched, calls = self.supervise_probe("import sys,time; sys.stdin.buffer.read(); time.sleep(30)")
        with patched, patch.object(t, "HELPER_SECONDS", 0.2):
            with self.assertRaisesRegex(t.TransportError, "TRANSPORT_TIMEOUT"):
                t.fetch_remote_snapshot(TOKEN)
        command, kwargs = calls[0]
        self.assertNotIn(TOKEN, str(command)); self.assertNotIn(TOKEN, str(kwargs["env"]))
        self.assertFalse(kwargs["shell"]); self.assertTrue(kwargs["close_fds"])
        self.assertNotIn("GH_TOKEN", kwargs["env"]); self.assertNotIn("HTTPS_PROXY", kwargs["env"])

    def test_output_flood_is_bounded_and_not_success(self):
        patched, _ = self.supervise_probe("import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x'*1048576); sys.stdout.flush()")
        with patched, self.assertRaisesRegex(t.TransportError, "TRANSPORT_OUTPUT_LIMIT"):
            t.fetch_remote_snapshot(TOKEN)

    def test_raw_stderr_is_never_echoed(self):
        patched, _ = self.supervise_probe("import sys; s=sys.stdin.buffer.read(); sys.stderr.buffer.write(s); print('{}')")
        with patched, self.assertRaisesRegex(t.TransportError, "TRANSPORT_HELPER_FAILED") as exc:
            t.fetch_remote_snapshot(TOKEN)
        self.assertNotIn(TOKEN, str(exc.exception))

    def test_validated_helper_receipt_only(self):
        snapshot = t.collect_snapshot(Reader(fixture()))
        code = "import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(" + repr(canonical(snapshot)) + ")"
        patched, _ = self.supervise_probe(code)
        with patched:
            self.assertEqual(t.fetch_remote_snapshot(TOKEN), snapshot)

    def test_nonzero_exit_never_returns_valid_snapshot_as_success(self):
        snapshot = t.collect_snapshot(Reader(fixture()))
        code = "import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(" + repr(canonical(snapshot)) + "); sys.exit(3)"
        patched, _ = self.supervise_probe(code)
        with patched, self.assertRaisesRegex(t.TransportError, "TRANSPORT_HELPER_FAILED"):
            t.fetch_remote_snapshot(TOKEN)

    def test_error_receipt_code_is_allowlisted(self):
        for code_value in ("TRANSPORT_NOT_FOUND", TOKEN):
            code = "import sys; sys.stdin.buffer.read(); print(" + repr(json.dumps({"error": code_value})) + "); sys.exit(3)"
            patched, _ = self.supervise_probe(code)
            with patched, self.assertRaises(t.TransportError) as exc:
                t.fetch_remote_snapshot(TOKEN)
            self.assertNotIn(TOKEN, str(exc.exception))

    def test_real_helper_refuses_bad_token_without_connecting(self):
        completed = subprocess.run([sys.executable, "-I", "-S", "-B", str(ROOT / "run_slot_transport.py"), str(os.getpid())],
                                   input=b"bad-token\n", capture_output=True, timeout=5)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout), {"error": "TRANSPORT_CREDENTIAL_INVALID"})
        self.assertEqual(completed.stderr, b"")

    def test_helper_requires_isolated_bootstrap(self):
        completed = subprocess.run([sys.executable, "-B", str(ROOT / "run_slot_transport.py")],
                                   input=b"", capture_output=True, timeout=5)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"-I -S -B", completed.stderr)


if __name__ == "__main__":
    unittest.main()
