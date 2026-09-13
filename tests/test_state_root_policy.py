from __future__ import annotations

from contextlib import ExitStack, chdir, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ansible_kernel import cli, config
from ansible_kernel.state import Store


class StateRootPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.home = self.parent / "operator-home"
        self.home.mkdir()
        (self.home / ".git").mkdir()
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}))
        if os.name == "nt":
            self.context.enter_context(patch.dict(os.environ, {"LOCALAPPDATA": str(self.home)}))
            self.default = self.home / "techrote-ansible"
        else:
            self.context.enter_context(patch.object(Path, "home", return_value=self.home))
            self.default = self.home / ".local" / "state" / "techrote-ansible"
        self.value = {"repositories": {"intrallm": str(self.home)}, "slots_dir": "slots",
                      "approved_models": ["none"], "local_state_dir": None}

    def invoke(self, *args, value=None):
        with patch.object(cli, "load_config", return_value=self.value if value is None else value):
            with redirect_stdout(io.StringIO()) as output:
                code = cli.main(list(args))
        return code, json.loads(output.getvalue())

    def test_configuration_reports_concrete_default_without_creation(self):
        self.assertEqual(config.state_root(self.value), self.default.resolve())
        self.assertFalse(self.default.exists())

    def test_default_policy_matches_store(self):
        selected = config.state_root(self.value)
        self.assertEqual(Store().root, selected)

    def test_cli_default_inside_known_repository_is_refused_before_creation(self):
        code, value = self.invoke("status")
        self.assertEqual(code, 3)
        self.assertEqual(value["error"], "STATE_ROOT_INSIDE_GIT_CHECKOUT")
        self.assertFalse(self.default.exists())

    def test_read_only_queries_apply_default_repository_boundary(self):
        for command in ("inspect", "events"):
            with self.subTest(command=command):
                code, value = self.invoke(command, "a" * 32)
                self.assertEqual(code, 3)
                self.assertEqual(value["error"], "STATE_ROOT_INSIDE_GIT_CHECKOUT")
                self.assertFalse(self.default.exists())

    def test_other_operator_commands_apply_default_repository_boundary(self):
        for command in ("slots", "panel", "recover"):
            with self.subTest(command=command):
                code, value = self.invoke(command)
                self.assertEqual(code, 3)
                self.assertEqual(value["error"], "STATE_ROOT_INSIDE_GIT_CHECKOUT")
                self.assertFalse(self.default.exists())

    def test_safe_explicit_override_takes_precedence_over_unsafe_default(self):
        target = self.parent / "external-state"
        code, value = self.invoke("--state-root", str(target), "status")
        self.assertEqual(code, 0)
        self.assertEqual(value, [])
        self.assertTrue(target.is_dir())
        self.assertFalse(self.default.exists())

    def test_configured_and_explicit_unsafe_roots_are_refused(self):
        target = self.home / "inside-repo"
        configured = {**self.value, "local_state_dir": str(target)}
        code, value = self.invoke("status", value=configured)
        self.assertEqual((code, value["error"]), (3, "STATE_ROOT_INSIDE_GIT_CHECKOUT"))
        code, value = self.invoke("--state-root", str(target), "status")
        self.assertEqual((code, value["error"]), (3, "STATE_ROOT_INSIDE_GIT_CHECKOUT"))
        self.assertFalse(target.exists())

    def test_config_command_displays_concrete_default_without_mutation(self):
        code, value = self.invoke("config")
        self.assertEqual(code, 0)
        self.assertEqual(value["local_state_dir"], str(self.default.resolve()))
        self.assertFalse(self.default.exists())

    def test_safe_default_query_still_does_not_create_state(self):
        safe = {**self.value, "repositories": {}}
        code, value = self.invoke("inspect", "a" * 32, value=safe)
        self.assertEqual((code, value["error"]), (3, "STATE_ROOT_NOT_FOUND"))
        self.assertFalse(self.default.exists())

    def test_safe_configured_root_takes_precedence_over_default(self):
        target = self.parent / "configured-state"
        value = {**self.value, "local_state_dir": str(target)}
        self.assertEqual(config.state_root(value), target.resolve())
        code, output = self.invoke("status", value=value)
        self.assertEqual((code, output), (0, []))
        self.assertTrue(target.is_dir())
        self.assertFalse(self.default.exists())

    def test_checked_canonical_path_is_the_path_used_by_store(self):
        project = self.parent / "another-repository"
        project.mkdir()
        (project / ".git").mkdir()
        value = {**self.value, "repositories": {"intrallm": str(project)}}
        with chdir(project):
            code, output = self.invoke("--state-root", "~/quoted-state", "status", value=value)
        self.assertEqual((code, output), (0, []))
        self.assertTrue((self.home / "quoted-state" / "runs").is_dir())
        self.assertFalse((project / "~").exists())

    def test_isolation_check_returns_the_canonical_checked_path(self):
        selected = config.assert_state_root_isolated(Path("~/checked-state"), {**self.value, "repositories": {}})
        self.assertEqual(selected, (self.home / "checked-state").resolve())
        self.assertFalse(selected.exists())
