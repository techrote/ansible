"""Real loopback TLS tests using a public test-only certificate/key, no network service."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import threading
import unittest
from unittest.mock import patch

from ansible_kernel import slot_transport as t
from test_slot_transport import TOKEN, fixture

FIXTURES = Path(__file__).parent / "fixtures"


class TLSTransportTests(unittest.TestCase):
    def setUp(self):
        self.responses = fixture()
        self.requests = []
        self.status = 200
        self.extra_headers = {}
        test = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def do_GET(self):
                test.requests.append((self.path, self.headers.get("Authorization")))
                body = test.responses.get(self.path, b"{}")
                self.send_response(test.status)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                for key, value in test.extra_headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (OSError, ssl.SSLError):
                    pass

        self.server = ThreadingHTTPServer(("localhost", 0), Handler)
        self.server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(FIXTURES / "localhost-test-cert.pem", FIXTURES / "localhost-test-key.pem")
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        native = t.http.client.HTTPSConnection
        def redirect_for_test(timeout, context):
            return native("localhost", self.server.server_address[1], timeout=timeout, context=context)
        self.redirect = patch.object(t, "_connection", side_effect=redirect_for_test)

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def reader(self):
        reader = t.GitHubReader(TOKEN)
        reader._context = ssl.create_default_context(cafile=str(FIXTURES / "localhost-test-cert.pem"))
        return reader

    def test_eight_read_snapshot_over_real_tls(self):
        with self.redirect:
            snapshot = t.collect_snapshot(self.reader())
        self.assertEqual(snapshot["provenance"]["commit_sha"], "a" * 40)
        self.assertEqual(len(self.requests), 8)
        self.assertTrue(all(auth == "Bearer " + TOKEN for _, auth in self.requests))

    def test_untrusted_certificate_is_not_accepted(self):
        with self.redirect, self.assertRaisesRegex(t.TransportError, "TRANSPORT_IO_FAILED"):
            t.GitHubReader(TOKEN)(t.REF_PATH)
        self.assertEqual(self.requests, [])

    def test_redirect_never_forwards_the_credential(self):
        self.status = 302
        self.extra_headers["Location"] = "https://example.invalid/never-follow"
        with self.redirect, self.assertRaisesRegex(t.TransportError, "TRANSPORT_REDIRECT_REFUSED"):
            self.reader()(t.REF_PATH)
        self.assertEqual(len(self.requests), 1)

    def test_oversized_body_is_refused_over_real_tls(self):
        self.responses[t.REF_PATH] = b"x" * 65537
        with self.redirect, self.assertRaisesRegex(t.TransportError, "TRANSPORT_RESPONSE_LIMIT"):
            self.reader()(t.REF_PATH)
