from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from ansible_kernel.config import (ConfigError, assert_state_root_isolated,
                                   load as load_config, resolve_repository,
                                   state_root as configured_state_root)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "ansible"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.config_path = self.root / "config" / "local.json"
        self.config_path.parent.mkdir()

    def write(self, text: str) -> None:
        self.config_path.write_text(text, encoding="utf-8")

    def test_missing_config_uses_safe_defaults(self):
        value = load_config(self.parent / "missing.json")
        self.assertEqual(value["repositories"], {})
        self.assertEqual(value["slots_dir"], "slots")
        self.assertEqual(value["approved_models"], ["none"])
        self.assertIsNone(value["local_state_dir"])

    def test_unknown_and_duplicate_config_keys_fail_closed(self):
        for text in ('{"command":"pwsh"}',
                     '{"slots_dir":"slots","slots_dir":"other"}'):
            self.write(text)
            with self.subTest(text=text), self.assertRaises(ConfigError):
                load_config(self.config_path)

    def test_schema_types_and_unsafe_slots_fail_closed(self):
        for text in ('{"$comment":7}', '{"repositories":[]}',
                     '{"slots_dir":"../elsewhere"}',
                     '{"approved_models":["ok","ok"]}',
                     '{"approved_models":["bad model"]}'):
            self.write(text)
            with self.subTest(text=text), self.assertRaises(ConfigError):
                load_config(self.config_path)

    def test_explicit_repository_path_must_be_absolute_checkout(self):
        self.write('{"repositories":{"intrallm":"relative/path"}}')
        with self.assertRaises(ConfigError):
            load_config(self.config_path)
        not_repo = self.parent / "notrepo"
        not_repo.mkdir()
        self.write(json.dumps({"repositories": {"intrallm": str(not_repo)}}))
        with self.assertRaises(ConfigError):
            load_config(self.config_path)

    def test_fixed_sibling_repository_discovery(self):
        repo = self.parent / "intrallm"
        repo.mkdir()
        (repo / ".git").mkdir()
        value = load_config(self.parent / "missing.json")
        self.assertEqual(resolve_repository("intrallm", value, root=self.root), repo.resolve())
        self.assertIsNone(resolve_repository("dashminimix", value, root=self.root))
        with self.assertRaises(ConfigError):
            resolve_repository("arbitrary-repo", value, root=self.root)

    def test_explicit_repository_overrides_sibling(self):
        sibling = self.parent / "intrallm"
        sibling.mkdir()
        (sibling / ".git").mkdir()
        explicit = self.parent / "elsewhere" / "intrallm"
        explicit.mkdir(parents=True)
        (explicit / ".git").mkdir()
        self.write(json.dumps({"repositories": {"intrallm": str(explicit)}}))
        value = load_config(self.config_path)
        self.assertEqual(resolve_repository("intrallm", value, root=self.root), explicit.resolve())

    def test_state_root_must_not_be_inside_trusted_or_known_repo(self):
        repo = self.parent / "intrallm"
        repo.mkdir()
        (repo / ".git").mkdir()
        value = {"repositories": {"intrallm": str(repo.resolve())},
                 "slots_dir": "slots", "approved_models": ["none"],
                 "local_state_dir": None}
        for path in (self.root / "runtime", repo / "runtime"):
            with self.subTest(path=path), self.assertRaises(ConfigError):
                assert_state_root_isolated(path, value, root=self.root)
        assert_state_root_isolated(self.parent / "state", value, root=self.root)

    def test_local_state_dir_is_operator_absolute_path(self):
        self.write('{"local_state_dir":"relative"}')
        with self.assertRaises(ConfigError):
            load_config(self.config_path)
        external = self.parent / "state"
        self.write(json.dumps({"local_state_dir": str(external)}))
        value = load_config(self.config_path)
        self.assertEqual(configured_state_root(value), external.resolve())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support required")
    def test_config_symlink_is_refused(self):
        real = self.parent / "real.json"
        real.write_text('{}', encoding="utf-8")
        link = self.parent / "linked.json"
        try:
            link.symlink_to(real)
        except OSError:
            self.skipTest("Host does not permit symlink creation")
        with self.assertRaises(ConfigError):
            load_config(link)


if __name__ == "__main__":
    unittest.main()
