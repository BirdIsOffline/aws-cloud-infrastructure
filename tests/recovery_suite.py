"""Linux-only simulated recovery. Refuse execution outside the disposable root."""

import base64
import contextlib
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import unittest
from unittest import mock


def isolation_guard():
    if sys.platform != "linux" or not Path("/.recovery-fixture.json").is_file() or not Path("/.recovery-runtime.json").is_file():
        raise RuntimeError("Recovery fixtures MUST NOT run on the host filesystem")
    identity = json.loads(Path("/.recovery-runtime.json").read_text())
    if identity != {"device": Path("/").stat().st_dev, "inode": Path("/").stat().st_ino}:
        raise RuntimeError("Disposable root identity mismatch")
    if not os.environ.get("RECOVERY_ISOLATED") or os.geteuid() != 0:
        raise RuntimeError("Isolated root context missing")


def diagnostic_summary(text, record=None):
    """Allowlisted categories only: never forward raw output, inputs, paths or IDs."""
    record = record if isinstance(record, dict) else {}
    text = str(text)[-32768:].lower()
    categories = {
        "missing_temporary_directory": ("mktemp:", "no such file or directory"),
        "temporary_file_failure": ("mktemp:",),
        "permission_denied": ("permission denied",),
        "candidate_validation_failure": ("validation failed",),
        "activation_failure": ("activation failed",),
        "rollback_failure": ("rollback failed",),
        "http_failure": ("http", "failed"),
        "python_exception": ("traceback (most recent call last)",),
    }
    scripts = ("bootstrap.sh", "deploy-website.sh", "configure-monitoring.sh", "verify-server.sh")
    codes = record.get("scripts", {})
    codes = codes if isinstance(codes, dict) else {}
    statuses = {"preflight", "deploying", "verified", "failed"}
    recovery = {"not required", "baseline health and configuration verified",
                "operator recovery required; never retry blindly",
                "operator must verify stopped subprocesses before recovery"}
    return {
        "status": record.get("status") if record.get("status") in statuses else "unavailable",
        "failed_script": record.get("failed_script") if record.get("failed_script") in scripts else None,
        "script_exit_codes": {name: codes[name] for name in scripts if name in codes and type(codes[name]) is int and -255 <= codes[name] <= 255},
        "recovery": record.get("recovery") if record.get("recovery") in recovery else "unavailable",
        "categories": [name for name, needles in categories.items() if all(value in text for value in needles)],
    }


def temporary_directory_metadata():
    for name in ("/tmp", "/var/tmp"):
        value = Path(name).lstat()
        if not stat.S_ISDIR(value.st_mode) or (value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode)) != (0, 0, 0o1777):
            raise RuntimeError("Fixture temporary directory metadata is unsafe")


def reset_temporary_directories():
    isolation_guard()
    for name in ("/tmp", "/var/tmp"):
        target = Path(name)
        if target.is_symlink() or target.exists() and not target.is_dir():
            raise RuntimeError("Unsafe fixture temporary directory")
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(mode=0o1777)
        os.chown(target, 0, 0)
        target.chmod(0o1777)
    temporary_directory_metadata()


def bare_mktemp():
    isolation_guard()
    # No TMPDIR override: exercise the unchanged verification script's default.
    return subprocess.run(["/usr/bin/mktemp"], env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C", "HOME": "/nonexistent"},
                          capture_output=True, text=True, timeout=5)


def temporary_directory_readiness():
    isolation_guard()
    temporary_directory_metadata()
    result = bare_mktemp()
    if result.returncode:
        raise RuntimeError("Bare mktemp readiness failed: " + json.dumps(diagnostic_summary(result.stderr)))
    target = Path(result.stdout.strip())
    if target.parent != Path("/tmp") or not target.name.startswith("tmp."):
        raise RuntimeError("Bare mktemp returned an unexpected fixture path")
    value = target.lstat()
    if not stat.S_ISREG(value.st_mode) or (value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode), value.st_nlink) != (0, 0, 0o600, 1):
        raise RuntimeError("Bare mktemp produced unsafe file metadata")
    target.unlink()


def emit_fixture_diagnostics():
    try:
        isolation_guard()
        record = {}
        path = Path("/var/lib/aws-portfolio-deploy/fixture-operation.json")
        if path.is_file() and not path.is_symlink() and path.stat().st_size < 32768:
            record = json.loads(path.read_text())
        text = ""
        stage = Path(record.get("stage", "/unavailable"))
        if stage.parent == Path("/var/tmp") and stage.name.startswith("aws-portfolio-cd.") and stage.resolve() == stage:
            value = stage.lstat()
            if stat.S_ISDIR(value.st_mode) and value.st_uid == value.st_gid == 0 and stat.S_IMODE(value.st_mode) == 0o700:
                log = stage / "execution.log"
                value = log.lstat()
                if stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and value.st_uid == value.st_gid == 0:
                    with log.open("rb") as stream:
                        stream.seek(max(0, value.st_size - 32768))
                        text = stream.read(32768).decode("utf-8", errors="replace")
        print("FIXTURE_DIAGNOSTIC " + json.dumps(diagnostic_summary(text, record), sort_keys=True), file=sys.stderr)
    except (OSError, ValueError, TypeError, RuntimeError):
        print('FIXTURE_DIAGNOSTIC {"collection":"unavailable"}', file=sys.stderr)


class FixtureResult(unittest.TextTestResult):
    def addFailure(self, test, err):
        super().addFailure(test, err)
        emit_fixture_diagnostics()

    def addError(self, test, err):
        super().addError(test, err)
        emit_fixture_diagnostics()


class FixtureRunner(unittest.TextTestRunner):
    resultclass = FixtureResult


class FixtureReadiness(unittest.TestCase):
    def setUp(self):
        reset_temporary_directories()

    def test_bare_mktemp_missing_tmp_reproduces_original_failure(self):
        moved = Path("/fixture/temporarily-missing-tmp")
        self.assertFalse(moved.exists() or moved.is_symlink())
        Path("/tmp").rename(moved)
        try:
            result = bare_mktemp()
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing_temporary_directory", diagnostic_summary(result.stderr)["categories"])
        finally:
            moved.rename("/tmp")
        temporary_directory_readiness()

    def test_initialized_temporary_directories_support_bare_mktemp(self):
        temporary_directory_readiness()


def load_executor():
    spec = importlib.util.spec_from_file_location("unchanged_executor", "/project/scripts/ssm/executor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state(**changes):
    path = Path("/fixture/state.json")
    value = json.loads(path.read_text())
    value.update(changes)
    path.write_text(json.dumps(value))
    return value


class OfflineHTTP:
    """Preserve production HTTP-check logic without opening a network socket."""

    def __init__(self, *args, **kwargs):
        self.path = ""

    def request(self, method, path):
        self.path = path

    def getresponse(self):
        path = Path("/usr/share/nginx/html") / self.path.lstrip("/") if self.path != "/" else Path("/usr/share/nginx/html/index.html")
        body = path.read_bytes() if path.is_file() else b""
        response = mock.Mock(status=200 if path.is_file() else 404)
        response.read.side_effect = lambda *args: body
        return response

    def close(self):
        pass


def encoded(contract):
    files = []
    for relative, spec in contract["files"].items():
        files.append({"path": relative, "type": "file", "mode": spec["mode"], "sha256": spec["sha256"],
                      "content": (Path("/project") / relative).read_text()})
    raw = json.dumps({"commit": "a" * 40, "files": files}).encode()
    return base64.b64encode(gzip.compress(raw, mtime=0)).decode()


def run_executor(contract, operation="fixture-operation"):
    executor = load_executor()
    with mock.patch.dict(os.environ, {"SSM_Bundle": encoded(contract), "SSM_OperationId": operation}), \
            mock.patch.object(executor.http_client, "HTTPConnection", OfflineHTTP):
        with contextlib.redirect_stdout(io.StringIO()):
            executor.run(contract)


class Recovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        isolation_guard()
        cls.contract = json.loads(Path("/project/config/ssm/approved-release.json").read_text())
        cls.approved = {name: (Path("/project") / name).read_bytes() for name in cls.contract["files"]}
        cls.original_executor = Path("/project/scripts/ssm/executor.py").read_bytes()
        cls.original_contract = Path("/project/config/ssm/approved-release.json").read_bytes()

    def setUp(self):
        isolation_guard()
        for relative, data in self.approved.items():
            target = Path("/project") / relative
            target.write_bytes(data)
            target.chmod(int(self.contract["files"][relative]["mode"], 8))
        for name in ("/fixture", "/etc/nginx", "/usr/share/nginx", "/opt/aws/amazon-cloudwatch-agent", "/var/lib/aws-portfolio-deploy", "/var/backups/aws-portfolio-lab"):
            target = Path(name)
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True)
        reset_temporary_directories()
        temporary_directory_readiness()
        self.page = Path("/usr/share/nginx/html/index.html")
        self.page.parent.mkdir(parents=True)
        self.page.write_bytes(self.approved["website/index.html"] + b"<!-- isolated predecessor -->\n")
        self.page.chmod(0o644)
        self.before_page = self.page.read_bytes()
        security = Path("/etc/nginx/conf.d/security.conf")
        security.parent.mkdir()
        security.write_bytes(self.approved["config/nginx/security.conf"])
        security.chmod(0o644)
        Path("/etc/nginx/nginx.conf").write_text("# isolated fixture only\n")
        Path("/etc/nginx/nginx.conf").chmod(0o644)
        self.agent = Path("/opt/aws/amazon-cloudwatch-agent")
        (self.agent / "bin").mkdir()
        (self.agent / "etc/amazon-cloudwatch-agent.d").mkdir(parents=True)
        self.cached = self.agent / "etc/amazon-cloudwatch-agent.d/file_amazon-cloudwatch-agent.json"
        self.cached.write_bytes(self.approved["config/cloudwatch/amazon-cloudwatch-agent.json"])
        self.cached.chmod(0o600)
        self.source = self.agent / "etc/amazon-cloudwatch-agent.json"
        (self.agent / "etc/common-config.toml").write_text("# isolated\n")
        Path("/etc/os-release").write_text('ID="amzn"\nVERSION_ID="2023"\n')
        stub = Path("/suite/recovery_stub.py")
        for name in ("rpm", "dnf", "systemctl", "nginx", "curl"):
            shutil.copyfile(stub, Path("/usr/bin") / name)
            (Path("/usr/bin") / name).chmod(0o755)
        for name in ("amazon-cloudwatch-agent-ctl", "config-translator", "amazon-cloudwatch-agent"):
            shutil.copyfile(stub, self.agent / "bin" / name)
            (self.agent / "bin" / name).chmod(0o755)
        Path("/fixture/state.json").write_text(json.dumps({"active": {"nginx": True, "amazon-cloudwatch-agent": True}}))
        self.control = Path("/var/lib/aws-portfolio-deploy")
        self.control.chmod(0o700)
        Path("/var/backups/aws-portfolio-lab").chmod(0o700)
        self.marker = self.control / "recovery-required"

    def tearDown(self):
        for name in ("bootstrap.sh", "deploy-website.sh", "configure-monitoring.sh", "verify-server.sh"):
            self.assertEqual((Path("/project/scripts") / name).read_bytes(), self.approved["scripts/" + name])
        self.assertEqual(Path("/project/scripts/ssm/executor.py").read_bytes(), self.original_executor)
        self.assertEqual(Path("/project/config/ssm/approved-release.json").read_bytes(), self.original_contract)
        self.assertFalse(any(name.startswith(("AWS_", "GH_", "GITHUB_")) for name in os.environ))

    def script(self, name, *args):
        environment = os.environ.copy()
        if Path("/fixture/bin").is_dir():
            environment["PATH"] = "/fixture/bin:" + environment["PATH"]
        process = subprocess.Popen(["/usr/bin/bash", "/project/scripts/" + name, *args], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            output, errors = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
            self.fail("Fixture script timed out; its process group was terminated")
        return subprocess.CompletedProcess(process.args, process.returncode, output, errors)

    def assert_code(self, result, code):
        self.assertEqual(result.returncode, code, json.dumps(diagnostic_summary(result.stdout + result.stderr)))

    def assert_verification_fault_once(self):
        self.assertTrue(state().get("verification_failure_injected"))
        self.assertEqual(state().get("injected_faults", []).count("verification_http"), 1)

    def assert_regular(self, path, mode):
        value = path.lstat()
        self.assertTrue(stat.S_ISREG(value.st_mode))
        self.assertEqual((value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode), value.st_nlink), (0, 0, mode, 1))

    def coordinator_contract(self):
        # Only a synthetic in-memory predecessor allowance; never write or deploy it.
        value = copy.deepcopy(self.contract)
        value["baseline_homepage_sha256"] = [hashlib.sha256(self.before_page).hexdigest()]
        return value

    def record(self):
        path = self.control / "fixture-operation.json"
        self.assert_regular(path, 0o600)
        return json.loads(path.read_text())

    def assert_backups_private(self):
        for path in Path("/var/backups/aws-portfolio-lab").rglob("*"):
            if path.is_dir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            else:
                mode = stat.S_IMODE(path.stat().st_mode)
                self.assertIn(mode, (0o600, 0o644))
                self.assert_regular(path, 0o600 if path.parent.name.startswith("cd-") else mode)
        self.assertFalse(Path("/usr/share/nginx/html/index.html.backup").exists())

    def test_bootstrap_missing_prerequisite_exits_5_without_installation(self):
        state(missing_package=True)
        self.assert_code(self.script("bootstrap.sh", "--check"), 5)
        self.assertFalse(any(x[0] == "dnf" for x in state()["commands"]))

    def test_bootstrap_existing_packages_no_installation(self):
        self.assert_code(self.script("bootstrap.sh"), 0)
        self.assertFalse(any(x[0] == "dnf" for x in state()["commands"]))

    def test_website_candidate_failure_before_live_write(self):
        Path("/project/website/index.html").write_text("not HTML\n")
        self.assert_code(self.script("deploy-website.sh"), 20)
        self.assertEqual(self.page.read_bytes(), self.before_page)
        self.assertFalse(list(Path("/var/backups/aws-portfolio-lab").iterdir()))

    def test_website_post_replacement_failure_restores_baseline_exit_40(self):
        state(website_http_failure=True)
        self.assert_code(self.script("deploy-website.sh"), 40)
        self.assertEqual(self.page.read_bytes(), self.before_page)
        self.assert_regular(self.page, 0o644)
        self.assert_backups_private()

    def test_website_nginx_validation_failure_before_live_write(self):
        state(nginx_invalid=True)
        self.assert_code(self.script("deploy-website.sh"), 20)
        self.assertEqual(self.page.read_bytes(), self.before_page)
        self.assertFalse(list(Path("/var/backups/aws-portfolio-lab").iterdir()))

    def test_website_unsuccessful_automatic_rollback_exit_41(self):
        state(website_http_failure=True, rollback_nginx_failure=True)
        self.assert_code(self.script("deploy-website.sh"), 41)
        self.assertEqual(self.page.read_bytes(), self.before_page)
        self.assertTrue(list(Path("/var/backups/aws-portfolio-lab/website").iterdir()))
        self.assert_backups_private()

    def test_website_explicit_rollback_restores_verified_backup(self):
        self.assert_code(self.script("deploy-website.sh"), 0)
        backup = next(Path("/var/backups/aws-portfolio-lab/website").iterdir())
        self.assert_code(self.script("deploy-website.sh", "--rollback", str(backup)), 0)
        self.assertEqual(self.page.read_bytes(), self.before_page)
        self.assert_regular(self.page, 0o644)

    def test_monitoring_invalid_candidate_exits_20_without_activation(self):
        before = self.cached.read_bytes()
        Path("/project/config/cloudwatch/amazon-cloudwatch-agent.json").write_text("{}\n")
        self.assert_code(self.script("configure-monitoring.sh"), 20)
        self.assertEqual(self.cached.read_bytes(), before)
        self.assertEqual(state().get("activations", 0), 0)

    def test_monitoring_translation_failure_leaves_live_config_untouched(self):
        state(translation_failure=True)
        before = self.cached.read_bytes()
        self.assert_code(self.script("configure-monitoring.sh"), 20)
        self.assertEqual(self.cached.read_bytes(), before)
        self.assertFalse(self.source.exists())

    def test_monitoring_schema_failure_leaves_live_config_untouched(self):
        state(schema_failure=True)
        self.assert_code(self.script("configure-monitoring.sh"), 20)
        self.assertEqual(state().get("activations", 0), 0)

    def monitoring_predecessor(self):
        before = json.loads(self.cached.read_text())
        before["agent"]["debug"] = True
        self.cached.write_text(json.dumps(before) + "\n")
        return before

    def test_monitoring_activation_failure_restores_configuration_exit_40(self):
        before = self.monitoring_predecessor()
        state(activation_failures=1)
        self.assert_code(self.script("configure-monitoring.sh"), 40)
        self.assertEqual(json.loads(self.cached.read_text()), before)
        self.assertTrue(state()["active"]["amazon-cloudwatch-agent"])
        self.assertEqual(state()["activations"], 2)
        self.assert_regular(self.cached, 0o600)

    def test_monitoring_failed_recovery_exits_41_preserves_backup(self):
        before = self.monitoring_predecessor()
        state(activation_failures=2)
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        backup = next(Path("/var/backups/aws-portfolio-lab/monitoring").iterdir())
        self.assertEqual(json.loads((backup / "amazon-cloudwatch-agent.json").read_text()), before)
        self.assertFalse(state()["active"]["amazon-cloudwatch-agent"])
        self.assert_backups_private()

    def no_monitoring_predecessor(self, **faults):
        self.cached.unlink()
        self.assertFalse(self.source.exists())
        state(active={"nginx": True, "amazon-cloudwatch-agent": False}, activation_failures=1, **faults)

    def substitute_removal(self):
        directory = Path("/fixture/bin")
        directory.mkdir()
        shutil.copyfile("/suite/recovery_stub.py", directory / "rm")
        (directory / "rm").chmod(0o755)

    def test_monitoring_no_predecessor_cleanup_restores_absence_exit_40(self):
        self.no_monitoring_predecessor()
        self.assert_code(self.script("configure-monitoring.sh"), 40)
        self.assertFalse(self.source.exists() or self.source.is_symlink())
        self.assertFalse(self.cached.exists() or self.cached.is_symlink())
        self.assertFalse(state()["active"]["amazon-cloudwatch-agent"])
        self.assert_backups_private()

    def test_monitoring_cleanup_removal_failure_exits_41(self):
        self.no_monitoring_predecessor(removal_failure=True)
        self.substitute_removal()
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        self.assertTrue(self.source.is_file() and self.cached.is_file())
        self.assertFalse(state()["active"]["amazon-cloudwatch-agent"])
        self.assert_backups_private()

    def test_monitoring_cleanup_incomplete_removal_exits_41(self):
        self.no_monitoring_predecessor(incomplete_removal=True)
        self.substitute_removal()
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        self.assertTrue(self.source.is_file() and self.cached.is_file())
        self.assert_backups_private()

    def test_monitoring_cleanup_wrong_service_state_exits_41(self):
        self.no_monitoring_predecessor()
        state(active={"nginx": True, "amazon-cloudwatch-agent": True}, ignore_agent_stop=True)
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        self.assertFalse(self.source.exists() or self.cached.exists())

    def test_monitoring_rollback_cache_mismatch_exits_41(self):
        self.monitoring_predecessor()
        state(activation_failures=1, rollback_cache_mismatch=True)
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        self.assert_backups_private()

    def test_monitoring_rollback_missing_cache_exits_41(self):
        self.monitoring_predecessor()
        state(activation_failures=1, rollback_cache_missing=True)
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        self.assertFalse(self.cached.exists())
        self.assert_backups_private()

    def test_monitoring_rollback_source_mismatch_exits_41(self):
        self.monitoring_predecessor()
        state(activation_failures=1, rollback_source_mismatch=True)
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        self.assert_backups_private()

    def test_monitoring_rollback_unconfigured_agent_exits_41(self):
        self.monitoring_predecessor()
        state(activation_failures=1, rollback_unconfigured=True)
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        self.assertTrue(state()["active"]["amazon-cloudwatch-agent"])

    def test_monitoring_rollback_inactive_agent_exits_41(self):
        self.monitoring_predecessor()
        state(activation_failures=1, rollback_inactive=True)
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        self.assertFalse(state()["active"]["amazon-cloudwatch-agent"])

    def test_monitoring_rollback_restores_prior_inactive_state_exit_40(self):
        before = self.monitoring_predecessor()
        state(active={"nginx": True, "amazon-cloudwatch-agent": False}, activation_failures=1)
        self.assert_code(self.script("configure-monitoring.sh"), 40)
        self.assertEqual(json.loads(self.cached.read_text()), before)
        self.assertFalse(state()["active"]["amazon-cloudwatch-agent"])
        self.assert_regular(self.cached, 0o600)

    def test_monitoring_rollback_ignored_stop_exits_41(self):
        self.monitoring_predecessor()
        state(active={"nginx": True, "amazon-cloudwatch-agent": False}, activation_failures=1, ignore_agent_stop=True)
        self.assert_code(self.script("configure-monitoring.sh"), 41)
        self.assertTrue(state()["active"]["amazon-cloudwatch-agent"])

    def test_monitoring_rollback_consumed_source_exit_40(self):
        before = self.monitoring_predecessor()
        state(activation_failures=1, consume_source=True)
        self.assert_code(self.script("configure-monitoring.sh"), 40)
        self.assertFalse(self.source.exists())
        self.assertEqual(json.loads(self.cached.read_text()), before)
        self.assertTrue(state()["active"]["amazon-cloudwatch-agent"])
        self.assert_regular(self.cached, 0o600)

    def test_monitoring_rollback_does_not_reclaim_log_retention(self):
        before = self.monitoring_predecessor()
        with_retention = copy.deepcopy(before)
        for entry in with_retention["logs"]["logs_collected"]["files"]["collect_list"]:
            entry["retention_in_days"] = 7
        self.cached.write_text(json.dumps(with_retention))
        state(activation_failures=1)
        self.assert_code(self.script("configure-monitoring.sh"), 40)
        self.assertEqual(json.loads(self.cached.read_text()), before)
        backup = next(Path("/var/backups/aws-portfolio-lab/monitoring").iterdir())
        self.assertEqual(json.loads((backup / "original.json").read_text()), with_retention)
        self.assert_backups_private()

    def test_monitoring_healthy_cached_config_does_not_restart(self):
        self.assert_code(self.script("configure-monitoring.sh"), 0)
        self.assertEqual(state().get("activations", 0), 0)
        self.assert_regular(self.source, 0o644)

    def test_monitoring_activation_can_consume_input(self):
        self.monitoring_predecessor()
        state(consume_source=True)
        self.assert_code(self.script("configure-monitoring.sh"), 0)
        self.assertFalse(self.source.exists())
        self.assertEqual(json.loads(self.cached.read_text()), json.loads(self.approved["config/cloudwatch/amazon-cloudwatch-agent.json"]))

    def test_coordinator_success_clears_latch_and_records_four_zero_exits(self):
        run_executor(self.coordinator_contract())
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.record()["status"], "verified")
        self.assertEqual(set(self.record()["scripts"].values()), {0})
        self.assertEqual(len(self.record()["scripts"]), 4)
        self.assertEqual(self.page.read_bytes(), self.approved["website/index.html"])
        self.assert_backups_private()

    def test_coordinator_prerequisite_failure_does_not_create_latch(self):
        state(missing_package=True)
        with self.assertRaises(SystemExit) as result:
            run_executor(self.coordinator_contract())
        self.assertEqual(result.exception.code, 1)
        self.assertEqual(self.record()["status"], "failed")
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.page.read_bytes(), self.before_page)

    def test_coordinator_modified_bundle_rejected_before_staging(self):
        executor = load_executor()
        envelope = json.loads(gzip.decompress(base64.b64decode(encoded(self.contract))))
        envelope["files"][0]["content"] += "unapproved\n"
        bad = base64.b64encode(gzip.compress(json.dumps(envelope).encode(), mtime=0)).decode()
        with mock.patch.dict(os.environ, {"SSM_Bundle": bad, "SSM_OperationId": "fixture-operation"}), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            executor.run(self.contract)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.control / "fixture-operation.json").exists())
        self.assertEqual(self.page.read_bytes(), self.before_page)

    def test_production_baseline_restriction_remains_enforced(self):
        with self.assertRaises(SystemExit):
            run_executor(copy.deepcopy(self.contract))
        self.assertEqual(self.record()["failure_category"], "unreviewed website baseline")
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.page.read_bytes(), self.before_page)

    def test_coordinator_candidate_validation_failure_before_backups(self):
        state(translation_failure=True)
        with self.assertRaises(SystemExit):
            run_executor(self.coordinator_contract())
        self.assertFalse(self.marker.exists())
        self.assertFalse(list(Path("/var/backups/aws-portfolio-lab").iterdir()))
        self.assertEqual(self.page.read_bytes(), self.before_page)

    def test_coordinator_recovers_website_monitoring_and_absent_source(self):
        state(verification_http_failure=True)
        with self.assertRaises(SystemExit):
            run_executor(self.coordinator_contract())
        record = self.record()
        self.assertEqual(record["scripts"]["verify-server.sh"], 30)
        self.assert_verification_fault_once()
        self.assertEqual(record["recovery"], "baseline health and configuration verified")
        self.assertEqual(self.page.read_bytes(), self.before_page)
        self.assertFalse(self.source.exists())
        self.assert_regular(self.page, 0o644)
        self.assert_regular(self.cached, 0o600)
        self.assert_regular(self.marker, 0o600)
        self.assert_backups_private()

    def test_coordinator_recovers_original_source_bytes_and_presence(self):
        self.source.write_bytes(json.dumps(json.loads(self.cached.read_text())).encode() + b"\n")
        self.source.chmod(0o644)
        before = self.source.read_bytes()
        state(verification_http_failure=True)
        with self.assertRaises(SystemExit):
            run_executor(self.coordinator_contract())
        self.assertEqual(self.source.read_bytes(), before)
        self.assert_regular(self.source, 0o644)
        self.assertEqual(self.record()["recovery"], "baseline health and configuration verified")
        self.assert_verification_fault_once()

    def test_latch_blocks_a_different_operation_without_new_record(self):
        state(verification_http_failure=True)
        with self.assertRaises(SystemExit):
            run_executor(self.coordinator_contract())
        with self.assertRaises(SystemExit):
            run_executor(self.coordinator_contract(), "another-operation")
        self.assertTrue(self.marker.exists())
        self.assertFalse((self.control / "another-operation.json").exists())
        self.assert_verification_fault_once()

    def test_completed_operation_cannot_be_replayed(self):
        run_executor(self.coordinator_contract())
        before = (self.control / "fixture-operation.json").read_bytes()
        with self.assertRaises(SystemExit):
            run_executor(copy.deepcopy(self.contract))
        self.assertEqual((self.control / "fixture-operation.json").read_bytes(), before)

    def test_fixture_operator_clears_latch_only_after_verified_recovery(self):
        state(verification_http_failure=True)
        with self.assertRaises(SystemExit):
            run_executor(self.coordinator_contract())
        self.assertEqual(self.record()["recovery"], "baseline health and configuration verified")
        self.assert_verification_fault_once()
        self.assertEqual(self.page.read_bytes(), self.before_page)
        import fcntl
        with (self.control / "deployment.lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_regular(self.marker, 0o600)
            self.marker.unlink()  # Test-only operator action, inside disposable root.
            load_executor().sync_directory(self.control)
        state(verification_http_failure=False)
        run_executor(self.coordinator_contract(), "recovered-operation")
        self.assertFalse(self.marker.exists())
        record = json.loads((self.control / "recovered-operation.json").read_text())
        self.assertEqual(record["status"], "verified")

    def test_coordinator_failed_recovery_preserves_latch_and_record(self):
        executor = load_executor()
        original = executor.command
        def command(args, *rest, **kwargs):
            if "--rollback" in args:
                raise executor.CommandFailed(41)
            return original(args, *rest, **kwargs)
        state(verification_http_failure=True)
        with mock.patch.object(executor, "command", side_effect=command), \
                mock.patch.object(executor.http_client, "HTTPConnection", OfflineHTTP), \
                mock.patch.dict(os.environ, {"SSM_Bundle": encoded(self.coordinator_contract()), "SSM_OperationId": "fixture-operation"}), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            executor.run(self.coordinator_contract())
        self.assertEqual(self.record()["recovery"], "operator recovery required; never retry blindly")
        self.assert_verification_fault_once()
        self.assertTrue(self.marker.exists())

    def test_coordinator_timeout_skips_unsafe_automatic_recovery(self):
        executor = load_executor()
        original = executor.command
        def command(args, *rest, **kwargs):
            if len(args) == 2 and args[0] == "bash" and args[1].endswith("bootstrap.sh"):
                raise executor.CommandTimedOut("subprocess timeout")
            return original(args, *rest, **kwargs)
        with mock.patch.object(executor, "command", side_effect=command), \
                mock.patch.object(executor.http_client, "HTTPConnection", OfflineHTTP), \
                mock.patch.dict(os.environ, {"SSM_Bundle": encoded(self.coordinator_contract()), "SSM_OperationId": "fixture-operation"}), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            executor.run(self.coordinator_contract())
        self.assertEqual(self.record()["recovery"], "operator must verify stopped subprocesses before recovery")
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.page.read_bytes(), self.before_page)

    def test_real_posix_lock_contention_rejects_second_executor(self):
        code = "import fcntl,time;f=open('/var/lib/aws-portfolio-deploy/deployment.lock','w');fcntl.flock(f,fcntl.LOCK_EX);print('locked',flush=True);time.sleep(30)"
        self.control.chmod(0o700)
        process = subprocess.Popen(["/usr/bin/python3", "-I", "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            (self.control / "deployment.lock").chmod(0o600)
            with self.assertRaises(SystemExit):
                run_executor(self.coordinator_contract())
            self.assertFalse((self.control / "fixture-operation.json").exists())
        finally:
            process.kill()
            process.wait(timeout=5)
            process.stdout.close()

    def test_real_subprocess_timeout_terminates_child_group(self):
        executor = load_executor()
        with self.assertRaises(executor.CommandTimedOut):
            executor.command(["/usr/bin/python3", "-I", "-c", "import time;time.sleep(30)"], timeout=0.2)

    def test_timeout_escalates_to_kill_for_term_ignoring_child(self):
        executor = load_executor()
        with self.assertRaises(executor.CommandTimedOut):
            executor.command(["/usr/bin/python3", "-I", "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"], timeout=0.5)

    def test_interruption_leaves_durable_latch_even_when_lock_releases(self):
        state(block_bootstrap=True)
        contract = self.coordinator_contract()
        Path("/fixture/contract.json").write_text(json.dumps(contract))
        process = subprocess.Popen(["/usr/bin/python3", "-I", "-B", "/suite/recovery_suite.py", "--worker"], start_new_session=True)
        group = None
        try:
            until = time.monotonic() + 10
            while not Path("/fixture/blocked.json").exists() and time.monotonic() < until:
                time.sleep(0.02)
            self.assertTrue(Path("/fixture/blocked.json").exists())
            group = json.loads(Path("/fixture/blocked.json").read_text())["group"]
            self.assertGreater(group, 1)
            process.kill()
            process.wait(timeout=5)
            import fcntl
            with (self.control / "deployment.lock").open("r+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertTrue(self.marker.exists())
            self.assertEqual(self.record()["status"], "deploying")
            self.assertEqual(self.page.read_bytes(), self.before_page)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            if group is not None:
                try:
                    os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            # PID 1 reaps orphaned fixture children; namespace exit is the final fence.
            until = time.monotonic() + 2
            while time.monotonic() < until:
                try:
                    child, _ = os.waitpid(-1, os.WNOHANG)
                    if child == 0:
                        time.sleep(0.02)
                except ChildProcessError:
                    break

    def test_network_and_host_escape_are_unavailable(self):
        self.assertFalse(Path("/proc").exists())
        with self.assertRaises(PermissionError):
            os.chroot("/")
        # Parent directories cannot escape the disposable root.
        self.assertEqual(Path("/../../").resolve(), Path("/"))
        self.assertFalse(Path("/project/terraform").exists())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", 9), timeout=0.1)


if __name__ == "__main__":
    isolation_guard()
    if sys.argv[1:] == ["--worker"]:
        run_executor(json.loads(Path("/fixture/contract.json").read_text()))
    else:
        unittest.main(verbosity=2, testRunner=FixtureRunner)
