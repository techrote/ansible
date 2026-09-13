from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ansible_kernel import config, state

ROOT = Path(__file__).resolve().parents[1]


class BoundedIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "local.json"

    def test_missing_configuration_keeps_defaults(self):
        self.assertEqual(config.load(self.path)["repositories"], {})

    def test_exact_config_limit_is_accepted(self):
        self.path.write_bytes(b"{}" + b" " * (config.MAX_CONFIG_BYTES - 2))
        self.assertEqual(config.load(self.path)["slots_dir"], "slots")

    def test_config_limit_plus_one_is_refused(self):
        self.path.write_bytes(b"{}" + b" " * (config.MAX_CONFIG_BYTES - 1))
        with self.assertRaisesRegex(config.ConfigError, "CONFIG_TOO_LARGE"):
            config.load(self.path)

    def test_config_does_not_use_whole_file_read(self):
        self.path.write_bytes(b"{}")
        # Schemas may read their small trusted source files; local config may not.
        original = Path.read_bytes
        def guard(path):
            if path == self.path:
                raise AssertionError("unbounded local-config read")
            return original(path)
        with patch.object(Path, "read_bytes", guard):
            self.assertEqual(config.load(self.path)["slots_dir"], "slots")

    def test_reader_is_given_exact_config_bound(self):
        self.path.write_bytes(b"{}")
        calls = []
        real_fdopen = state.os.fdopen

        class Reader:
            def __init__(self, fd, mode):
                self.handle = real_fdopen(fd, mode)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.handle.close()
            def read(self, maximum):
                calls.append(maximum)
                return self.handle.read(maximum)

        with patch.object(state.os, "fdopen", Reader):
            config.load(self.path)
        self.assertEqual(calls, [config.MAX_CONFIG_BYTES + 1])

    def test_config_directory_is_typed_refusal(self):
        self.path.mkdir()
        with self.assertRaisesRegex(config.ConfigError, "NONREGULAR_STATE_FILE"):
            config.load(self.path)

    def test_nonregular_path_refused_before_os_open(self):
        self.path.mkdir()
        with patch.object(state.os, "open") as opened:
            with self.assertRaisesRegex(state.StateError, "NONREGULAR_STATE_FILE"):
                state.opened(self.path, os.O_RDONLY)
        opened.assert_not_called()

    def test_hardlinked_config_refused(self):
        source = self.root / "original.json"
        source.write_bytes(b"{}")
        try:
            os.link(source, self.path)
        except OSError:
            self.skipTest("Host does not permit hardlinks")
        with self.assertRaisesRegex(config.ConfigError, "HARDLINK_REFUSED"):
            config.load(self.path)
        self.assertEqual(source.read_bytes(), b"{}")

    def test_fstat_error_closes_descriptor(self):
        self.path.write_bytes(b"data")
        real_open, real_close = state.os.open, state.os.close
        descriptors = []
        def track_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            descriptors.append(fd)
            return fd
        with patch.object(state.os, "open", side_effect=track_open):
            with patch.object(state.os, "close", wraps=real_close) as closed:
                with patch.object(state.os, "fstat", side_effect=OSError("simulated metadata error")):
                    with self.assertRaises(OSError):
                        state.opened(self.path, os.O_RDONLY)
            if not closed.called:  # clean up even when regression is reproduced
                for fd in descriptors:
                    real_close(fd)
            self.assertEqual(closed.call_count, 1)

    def test_post_open_type_check_is_retained(self):
        self.path.write_bytes(b"data")
        metadata = os.stat_result((stat.S_IFIFO | 0o600, 0, 0, 1, 0, 0, 0, 0, 0, 0))
        with patch.object(state.os, "fstat", return_value=metadata):
            with self.assertRaisesRegex(state.StateError, "NONREGULAR_STATE_FILE"):
                state.opened(self.path, os.O_RDONLY)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NONBLOCK"), "POSIX nonblocking flag")
    def test_open_uses_nonblocking_flag_before_type_validation(self):
        self.path.write_bytes(b"data")
        with patch.object(state.os, "open", wraps=os.open) as opened:
            fd = state.opened(self.path, os.O_RDONLY)
            os.close(fd)
        self.assertTrue(opened.call_args.args[1] & os.O_NONBLOCK)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_fifo_refusal_has_no_blocking_open(self):
        os.mkfifo(self.path)
        script = ("from pathlib import Path; from ansible_kernel.config import load, ConfigError; "
                  "import sys\ntry: load(Path(sys.argv[1]))\n"
                  "except ConfigError as error: print(error); raise SystemExit(0)\n"
                  "raise SystemExit(1)\n")
        try:
            process = subprocess.run([sys.executable, "-B", "-c", script, str(self.path)],
                                     cwd=ROOT, capture_output=True, text=True, timeout=2)
        except subprocess.TimeoutExpired:
            self.fail("Configuration read blocked on a FIFO")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("NONREGULAR_STATE_FILE", process.stdout)

    def test_config_duplicate_and_nonfinite_codes_are_preserved(self):
        for raw, code in ((b'{"x":1,"x":2}', "DUPLICATE_CONFIG_KEY"),
                          (b'{"x":NaN}', "NONFINITE_CONFIG_NUMBER"),
                          (b'{"x":1.5}', "NONFINITE_CONFIG_NUMBER")):
            self.path.write_bytes(raw)
            with self.subTest(code=code), self.assertRaisesRegex(config.ConfigError, code):
                config.load(self.path)

    def test_deep_config_rejected_before_schema_walk(self):
        self.path.write_bytes(b'{"x":' * 22 + b'0' + b'}' * 22)
        with self.assertRaisesRegex(config.ConfigError, "CONFIG_COMPLEXITY"):
            config.load(self.path)

    def test_malformed_unicode_config_rejected(self):
        self.path.write_bytes(b'{"$comment":"\\ud800"}')
        with self.assertRaisesRegex(config.ConfigError, "INVALID_LOCAL_CONFIG"):
            config.load(self.path)

    def test_regular_state_read_write_is_unchanged(self):
        state.write_once(self.path, b"ordinary data")
        self.assertEqual(state.read_bytes(self.path, 13), b"ordinary data")
        with self.assertRaisesRegex(state.StateError, "STATE_SIZE_LIMIT"):
            state.read_bytes(self.path, 2)
        with self.assertRaises(FileExistsError):
            state.write_once(self.path, b"cannot replace")
