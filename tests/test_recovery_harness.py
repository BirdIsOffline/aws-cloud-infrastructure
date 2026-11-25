"""Portable isolation guards. Privileged fixtures are never executed here."""

import ast
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("isolated_recovery_runner", ROOT / "tests/recovery_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class IsolationGuards(unittest.TestCase):
    def fixture(self):
        parent = ROOT / ".local/tests"
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="recovery-", dir=parent)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        nonce = "a" * 32
        (root / runner.MARKER).write_text(json.dumps({"nonce": nonce, "format": 1}))
        return root, nonce

    def test_child_environment_does_not_inherit_credentials_or_hooks(self):
        with mock.patch.object(runner.os, "environ", {"AWS_PROFILE": "synthetic", "AWS_SESSION_TOKEN": "synthetic", "GH_TOKEN": "synthetic", "PYTHONPATH": "synthetic", "BASH_ENV": "synthetic", "HTTPS_PROXY": "synthetic"}):
            env = runner.clean_environment()
        self.assertEqual(set(env), {"PATH", "HOME", "LANG", "LC_ALL"})
        self.assertEqual(env["HOME"], "/nonexistent")

    def test_workspace_fixture_identity_is_required(self):
        root, nonce = self.fixture()
        self.assertEqual(runner.checked_root(root, nonce), root)

    def test_incorrect_nonce_rejected_before_cleanup(self):
        root, nonce = self.fixture()
        with self.assertRaises(ValueError):
            runner.checked_root(root, "b" * len(nonce))
        self.assertTrue(root.exists())

    def test_outside_path_rejected_before_marker_access(self):
        with self.assertRaises(ValueError):
            runner.checked_root(ROOT, "a" * 32)

    def test_invalid_nonce_rejected(self):
        root, _ = self.fixture()
        with self.assertRaises(ValueError):
            runner.checked_root(root, "../unsafe")

    def test_symlinked_root_rejected(self):
        root, nonce = self.fixture()
        with mock.patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
            runner.checked_root(root, nonce)

    def test_namespace_isolation_fails_closed(self):
        host = {"net": "host-net", "pid": "host-pid", "mnt": "host-mnt"}
        child = {key: "child-" + key for key in host}
        runner.namespace_guard(host, child)
        for key in host:
            with self.subTest(namespace=key), self.assertRaises(RuntimeError):
                runner.namespace_guard(host, {**child, key: host[key]})

    def test_unknown_runner_arguments_rejected_without_subprocess(self):
        with mock.patch.object(runner.sys, "argv", ["runner", "--unsafe"]), \
                mock.patch.object(runner.subprocess, "run") as process, self.assertRaises(ValueError):
            runner.main()
        process.assert_not_called()

    def test_non_linux_never_attempts_privileged_execution(self):
        with mock.patch.object(runner.sys, "platform", "win32"), \
                mock.patch.object(runner.sys, "argv", ["runner"]), \
                mock.patch.object(runner.subprocess, "run") as process, mock.patch("builtins.print"):
            self.assertEqual(runner.main(), 0)
        process.assert_not_called()

    def test_fixture_source_allowlist_excludes_private_infrastructure(self):
        contract = json.loads((ROOT / "config/ssm/approved-release.json").read_text())
        self.assertEqual(set(runner.INPUTS), set(contract["files"]) | {"scripts/ssm/executor.py", "config/ssm/approved-release.json"})

    def test_linux_suite_contains_no_skipped_cases(self):
        tree = ast.parse((ROOT / "tests/recovery_suite.py").read_text())
        cases = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
        self.assertGreaterEqual(len(cases), 25)
        self.assertTrue(all(not node.decorator_list for node in cases))


if __name__ == "__main__":
    unittest.main()
