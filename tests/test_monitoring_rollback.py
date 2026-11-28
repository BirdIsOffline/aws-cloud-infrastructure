"""Exercise the rollback JSON verifier without running privileged Bash commands."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class MonitoringRollbackConfiguration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "scripts/configure-monitoring.sh").read_text(encoding="utf-8")
        helper = source.split("verify_restored_configuration() {\n", 1)[1]
        cls.code = compile(helper.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0],
                           "configure-monitoring.sh:verify_restored_configuration", "exec")

    def setUp(self):
        parent = ROOT / ".local/tests"
        parent.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(prefix="rollback-json-", dir=parent)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.expected = self.root / "expected.json"
        self.cached = self.root / "cached.json"
        self.source = self.root / "source.json"
        self.configuration = json.loads((ROOT / "config/cloudwatch/amazon-cloudwatch-agent.json").read_text())
        for path in (self.expected, self.cached, self.source):
            path.write_text(json.dumps(self.configuration), encoding="utf-8")

    def verify(self):
        with mock.patch.object(sys, "argv", ["verifier", str(self.expected), str(self.cached), str(self.source)]):
            exec(self.code, {"__name__": "__main__"})

    def test_semantically_identical_cache_and_source_are_accepted(self):
        self.cached.write_text(json.dumps(self.configuration, sort_keys=True, indent=4), encoding="utf-8")
        self.verify()

    def test_consumed_source_is_accepted(self):
        self.source.unlink()
        self.verify()

    def test_missing_or_non_regular_cache_is_rejected(self):
        self.cached.unlink()
        with self.assertRaises(SystemExit):
            self.verify()
        self.cached.mkdir()
        with self.assertRaises(SystemExit):
            self.verify()

    def test_changed_cache_is_rejected(self):
        self.cached.write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.verify()

    def test_changed_surviving_source_is_rejected(self):
        self.source.write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.verify()

    def test_malformed_cache_or_source_is_rejected(self):
        for path in (self.cached, self.source):
            with self.subTest(file=path.name):
                original = path.read_bytes()
                path.write_text("{", encoding="utf-8")
                with self.assertRaises(json.JSONDecodeError):
                    self.verify()
                path.write_bytes(original)

    def test_cache_or_source_symlinks_are_rejected(self):
        for path in (self.cached, self.source):
            with self.subTest(file=path.name), mock.patch.object(Path, "is_symlink", lambda target: target == path):
                with self.assertRaises(SystemExit):
                    self.verify()

    def test_non_regular_surviving_source_is_rejected(self):
        self.source.unlink()
        self.source.mkdir()
        with self.assertRaises(SystemExit):
            self.verify()

    def test_unexpected_agent_owned_retention_is_rejected(self):
        self.configuration["logs"]["logs_collected"]["files"]["collect_list"][0]["retention_in_days"] = 7
        self.cached.write_text(json.dumps(self.configuration), encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.verify()


if __name__ == "__main__":
    unittest.main()
