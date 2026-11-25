"""Offline security tests. Never call the executor's privileged run entry point."""

import base64
import copy
import gzip
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
import zlib

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


executor = module("reviewed_executor", "scripts/ssm/executor.py")
bundle = module("reviewed_bundle", "scripts/ssm/bundle.py")


def encode(envelope):
    raw = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(gzip.compress(raw, mtime=0)).decode()


class BundleSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded, cls.contract = bundle.create()
        cls.envelope = json.loads(gzip.decompress(base64.b64decode(cls.encoded)))

    def changed(self, mutate, message):
        value = copy.deepcopy(self.envelope)
        mutate(value)
        with self.assertRaisesRegex(executor.Rejected, message):
            executor.decode_bundle(encode(value), self.contract)

    def test_approved_bundle_round_trip(self):
        files = executor.decode_bundle(self.encoded, self.contract)
        self.assertEqual(set(files), set(executor.PATHS))
        for name, data in files.items():
            self.assertEqual(data, (ROOT / name).read_bytes())

    def test_deterministic_bundle(self):
        self.assertEqual(bundle.create()[0], self.encoded)

    def test_each_privileged_input_is_pinned(self):
        for index in range(len(self.envelope["files"])):
            with self.subTest(file=index):
                def mutate(value):
                    value["files"][index]["content"] += "changed\n"
                    value["files"][index]["sha256"] = hashlib.sha256(value["files"][index]["content"].encode()).hexdigest()
                self.changed(mutate, "unapproved declared hash")

    def test_changed_bytes_with_original_digest(self):
        self.changed(lambda value: value["files"][0].update(content="bad\n"), "file size limit")

    def test_extra_and_missing_files(self):
        self.changed(lambda value: value["files"].pop(), "unexpected file count")
        self.changed(lambda value: value["files"].append(copy.deepcopy(value["files"][0])), "unexpected file count")

    def test_duplicate_path(self):
        self.changed(lambda value: value["files"].__setitem__(1, copy.deepcopy(value["files"][0])), "unexpected or duplicate path")

    def test_traversal_and_foreign_paths(self):
        for name in ("../index.html", "/etc/profile", "scripts/../index.html", "scripts\\bootstrap.sh", "unapproved/file"):
            with self.subTest(path=name):
                self.changed(lambda value: value["files"][0].update(path=name), "unexpected or duplicate path")

    def test_link_and_device_declarations(self):
        for kind in ("symlink", "hardlink", "directory", "device"):
            with self.subTest(kind=kind):
                self.changed(lambda value: value["files"][0].update(type=kind), "file type or mode")

    def test_unsafe_permission_declarations(self):
        for mode in ("0777", "4755", "0644", 700):
            with self.subTest(mode=mode):
                self.changed(lambda value: value["files"][0].update(mode=mode), "file type or mode")

    def test_extra_command_and_url_inputs(self):
        self.changed(lambda value: value.update(commands="unapproved"), "unexpected envelope fields")
        self.changed(lambda value: value["files"][0].update(url="unapproved"), "unexpected file fields")

    def test_wrong_commit(self):
        self.changed(lambda value: value.update(commit="main; unapproved"), "invalid immutable commit label")

    def test_commit_label_cannot_authorize_changed_contents(self):
        # The future GitHub gate proves provenance; the server independently pins bytes.
        value = copy.deepcopy(self.envelope)
        value["commit"] = "0" * 40
        self.assertEqual(set(executor.decode_bundle(encode(value), self.contract)), set(executor.PATHS))
        value["files"][0]["content"] = "bad\n"
        with self.assertRaises(executor.Rejected):
            executor.decode_bundle(encode(value), self.contract)

    def test_oversized_encoded_bundle(self):
        with self.assertRaisesRegex(executor.Rejected, "encoded size limit"):
            executor.decode_bundle("A" * (self.contract["limits"]["encoded_bytes"] + 1), self.contract)

    def test_decompression_bomb(self):
        encoded = base64.b64encode(gzip.compress(b"A" * (self.contract["limits"]["decoded_bytes"] + 1))).decode()
        with self.assertRaisesRegex(executor.Rejected, "decoded size limit"):
            executor.decode_bundle(encoded, self.contract)

    def test_duplicate_json_members(self):
        raw = b'{"commit":"x","commit":"y","files":[]}'
        with self.assertRaisesRegex(executor.Rejected, "duplicate JSON member"):
            executor.decode_bundle(base64.b64encode(gzip.compress(raw)).decode(), self.contract)

    def test_multiple_and_incomplete_gzip_streams(self):
        compressed = base64.b64decode(self.encoded)
        for data in (compressed + gzip.compress(b"extra"), compressed[:-4]):
            with self.subTest(length=len(data)):
                with self.assertRaisesRegex(executor.Rejected, "incomplete or multiple gzip streams"):
                    executor.decode_bundle(base64.b64encode(data).decode(), self.contract)

    def test_bad_base64_or_compression(self):
        with self.assertRaises(ValueError):
            executor.decode_bundle("not base64", self.contract)
        with self.assertRaises(zlib.error):
            executor.decode_bundle(base64.b64encode(b"not gzip").decode(), self.contract)

    def test_missing_env_and_invalid_operation(self):
        with self.assertRaisesRegex(executor.Rejected, "ENV_VAR interpolation required"):
            executor.operation_parameters({})
        for operation in ("../x", "x; command", "", "x" * 65):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(executor.Rejected, "invalid operation identifier"):
                    executor.operation_parameters({"SSM_Bundle": self.encoded, "SSM_OperationId": operation})

    def test_supported_agent(self):
        executor.supported_agent("3.3.2746.0")
        executor.supported_agent("3.3.3000.0")
        with self.assertRaisesRegex(executor.Rejected, "ENV_VAR support required"):
            executor.supported_agent("3.3.2000.0")

    def test_filesystem_type_ownership_and_mode_rejections(self):
        original = {"st_mode": stat.S_IFREG | 0o600, "st_nlink": 1, "st_uid": 0, "st_gid": 0}
        path = mock.Mock()
        path.lstat.return_value = SimpleNamespace(**original)
        executor.regular_file(path, 0o600)
        for change in ({"st_mode": stat.S_IFLNK | 0o600}, {"st_nlink": 2}, {"st_uid": 1}, {"st_gid": 1}, {"st_mode": stat.S_IFREG | 0o666}):
            with self.subTest(change=change):
                path.lstat.return_value = SimpleNamespace(**dict(original, **change))
                with self.assertRaises(executor.Rejected):
                    executor.regular_file(path, 0o600)

    def test_ssm_size_and_schema_budget(self):
        result = bundle.check()
        self.assertLess(result["encoded_bundle_bytes"], self.contract["limits"]["encoded_bytes"])
        self.assertLess(result["maximum_combined_budget_bytes"], 60 * 1024)
        document = json.loads(bundle.document())
        self.assertEqual(set(document["parameters"]), {"Bundle", "OperationId"})
        loader = document["mainSteps"][0]["inputs"]["runCommand"][0]
        python = loader.split("<<'REVIEWED_EXECUTOR'\n", 1)[1].rsplit("\nREVIEWED_EXECUTOR", 1)[0]
        compile(python, "ssm-loader", "exec")

    def test_reserved_ssm_document_name_prefixes(self):
        for prefix in ("aws-lab", "AmazonLab", "amzn-lab", "AWSSupportLab", "bad/path"):
            with self.subTest(prefix=prefix):
                contract = dict(self.contract, document_name_prefix=prefix)
                with self.assertRaisesRegex(ValueError, "AWS-reserved custom document prefix"):
                    bundle.document_name("reviewed", contract)

    @unittest.skipUnless(os.name == "posix", "Real Linux ownership/mode/link checks require POSIX")
    def test_posix_stage_metadata_and_links(self):
        parent = ROOT / ".local/tests"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            stage = Path(temporary)
            stage.chmod(0o700)
            for name, data in executor.decode_bundle(self.encoded, self.contract).items():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                for directory in target.parents:
                    if directory == stage.parent:
                        break
                    directory.chmod(0o700)
                target.write_bytes(data)
                target.chmod(int(self.contract["files"][name]["mode"], 8))
            executor.validate_stage(stage, self.contract, uid=os.getuid())
            target = stage / "website/index.html"
            target.chmod(0o666)
            with self.assertRaisesRegex(executor.Rejected, "unexpected file permissions"):
                executor.validate_stage(stage, self.contract, uid=os.getuid())
            target.chmod(0o600)
            link = stage / "linked"
            os.link(target, link)
            with self.assertRaises(executor.Rejected):
                executor.validate_stage(stage, self.contract, uid=os.getuid())
            link.unlink()
            target.unlink()
            target.symlink_to(stage / "scripts/bootstrap.sh")
            with self.assertRaises(executor.Rejected):
                executor.validate_stage(stage, self.contract, uid=os.getuid())

    def test_timeout_budget_fails_before_command(self):
        with mock.patch.object(executor, "DEADLINE", 1), mock.patch.object(executor.time, "monotonic", return_value=2), mock.patch.object(executor.subprocess, "Popen") as run:
            with self.assertRaisesRegex(executor.Rejected, "time budget exhausted"):
                executor.command(["not-executed"])
            run.assert_not_called()

    def test_failed_command_keeps_code_without_output_in_exception(self):
        completed = mock.Mock(returncode=42)
        completed.communicate.return_value = (b"captured-only diagnostic content", None)
        with mock.patch.object(executor, "DEADLINE", None), mock.patch.object(executor.subprocess, "Popen", return_value=completed):
            with self.assertRaises(executor.CommandFailed) as failure:
                executor.command(["not-executed"])
            self.assertEqual(failure.exception.code, 42)
            self.assertNotIn("captured-only diagnostic content", str(failure.exception))

    def test_timeout_terminates_group_and_requires_operator(self):
        process = mock.Mock(pid=123)
        process.communicate.side_effect = [executor.subprocess.TimeoutExpired("not-executed", 1), (b"partial output", None)]
        with mock.patch.object(executor, "DEADLINE", None), mock.patch.object(executor.subprocess, "Popen", return_value=process), mock.patch.object(executor.os, "killpg", create=True) as terminate:
            with self.assertRaises(executor.CommandTimedOut):
                executor.command(["not-executed"])
            terminate.assert_called_once_with(123, executor.signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
