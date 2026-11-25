"""Pinned SSM executor. Importing this module never executes server commands."""

import base64
import hashlib
import http.client as http_client
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import tempfile
import time
import zlib

SEQUENCE = ("bootstrap.sh", "deploy-website.sh", "configure-monitoring.sh", "verify-server.sh")
PATHS = tuple("scripts/" + name for name in SEQUENCE) + (
    "config/nginx/security.conf", "config/cloudwatch/amazon-cloudwatch-agent.json", "website/index.html"
)
AGENT = Path("/opt/aws/amazon-cloudwatch-agent")
CACHED = AGENT / "etc/amazon-cloudwatch-agent.d/file_amazon-cloudwatch-agent.json"
SOURCE = AGENT / "etc/amazon-cloudwatch-agent.json"
HOMEPAGE = Path("/usr/share/nginx/html/index.html")
SECURITY = Path("/etc/nginx/conf.d/security.conf")
ENVIRONMENT = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C", "LANG": "C", "HOME": "/root"}
DEADLINE = None


class Rejected(ValueError):
    """Messages are fixed categories; never include caller-controlled values."""


class CommandFailed(Rejected):
    def __init__(self, code):
        super().__init__("server command failed; private diagnostic retained")
        self.code = code


class CommandTimedOut(Rejected):
    pass


def require(condition, message):
    if not condition:
        raise Rejected(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON member")
        result[key] = value
    return result


def read_json(data):
    return json.loads(data, object_pairs_hook=unique_object)


def decode_bundle(encoded, contract, with_commit=False):
    """Pure bounded decoder shared by the local packer, tests, and SSM runtime."""
    limits = contract["limits"]
    require(isinstance(encoded, str) and 0 < len(encoded) <= limits["encoded_bytes"], "encoded size limit")
    compressed = base64.b64decode(encoded, validate=True)
    require(base64.b64encode(compressed).decode() == encoded, "noncanonical base64")
    decoder = zlib.decompressobj(31)
    raw = decoder.decompress(compressed, limits["decoded_bytes"] + 1)
    require(len(raw) <= limits["decoded_bytes"], "decoded size limit")
    require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail, "incomplete or multiple gzip streams")
    envelope = read_json(raw.decode("utf-8"))
    require(isinstance(envelope, dict) and set(envelope) == {"commit", "files"}, "unexpected envelope fields")
    require(isinstance(envelope["commit"], str) and re.fullmatch(r"[0-9a-f]{40}", envelope["commit"]) is not None, "invalid immutable commit label")
    entries = envelope["files"]
    require(isinstance(entries, list) and len(entries) == len(PATHS), "unexpected file count")
    require(set(contract["files"]) == set(PATHS), "executor contract file set")
    result = {}
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == {"path", "type", "mode", "sha256", "content"}, "unexpected file fields")
        name = entry["path"]
        require(isinstance(name, str) and name in PATHS and name not in result, "unexpected or duplicate path")
        require(not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts and "\\" not in name, "unsafe path")
        spec = contract["files"][name]
        require(entry["type"] == "file" and entry["mode"] == spec["mode"], "file type or mode")
        require(entry["sha256"] == spec["sha256"], "unapproved declared hash")
        content = entry["content"]
        require(isinstance(content, str) and len(content) <= limits["file_bytes"], "file encoding limit")
        data = content.encode("utf-8")
        require(len(data) == spec["bytes"] and len(data) <= limits["file_bytes"], "file size limit")
        require(sha(data) == spec["sha256"], "unapproved file contents")
        data.decode("utf-8")
        require(not data.startswith(b"\xef\xbb\xbf") and b"\r" not in data and data.endswith(b"\n"), "UTF-8/LF contract")
        result[name] = data
    require(set(result) == set(PATHS), "missing approved file")
    return (result, envelope["commit"]) if with_commit else result


def operation_parameters(environment):
    require("SSM_Bundle" in environment and "SSM_OperationId" in environment, "ENV_VAR interpolation required")
    operation = environment["SSM_OperationId"]
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", operation) is not None, "invalid operation identifier")
    return environment["SSM_Bundle"], operation


def supported_agent(version):
    require(re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", version) is not None, "unrecognized SSM Agent version")
    numbers = tuple(int(part) for part in version.split("."))
    require(numbers + (0,) * (4 - len(numbers)) >= (3, 3, 2746, 0), "SSM Agent ENV_VAR support required")


def regular_file(path, mode=None, uid=0):
    value = path.lstat()
    require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1, "non-regular or linked file")
    require(value.st_uid == uid and value.st_gid == uid, "unexpected file ownership")
    if mode is not None:
        require(stat.S_IMODE(value.st_mode) == mode, "unexpected file permissions")
    return value


def secure_parents(path):
    for parent in reversed(path.parents):
        value = parent.lstat()
        require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and value.st_gid == 0, "unsafe parent directory")
        require(not stat.S_IMODE(value.st_mode) & 0o022, "writable parent directory")


def private_directory(path):
    secure_parents(path)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    value = path.lstat()
    require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and value.st_gid == 0 and stat.S_IMODE(value.st_mode) == 0o700, "unsafe private directory")
    sync_directory(path.parent)
    return path


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def materialize(files, stage, contract):
    # Stage is a fresh root-owned mkdtemp; never reuse a caller-provided directory.
    for relative, data in files.items():
        target = stage / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, int(contract["files"][relative]["mode"], 8))
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    validate_stage(stage, contract)


def validate_stage(stage, contract, uid=0):
    require(stage.resolve() == stage, "stage path resolution")
    expected = set(PATHS)
    directories = {"."} | {str(parent) for name in PATHS for parent in PurePosixPath(name).parents if str(parent) != "."}
    for path in [stage] + list(stage.rglob("*")):
        name = path.relative_to(stage).as_posix()
        value = path.lstat()
        if name in directories:
            require(stat.S_ISDIR(value.st_mode) and value.st_uid == uid and value.st_gid == uid and stat.S_IMODE(value.st_mode) == 0o700, "stage directory metadata")
        else:
            require(name in expected, "unexpected staged file")
            regular_file(path, int(contract["files"][name]["mode"], 8), uid=uid)
            require(sha(path.read_bytes()) == contract["files"][name]["sha256"], "staged content hash")
            expected.remove(name)
    require(not expected, "missing staged file")


def command(arguments, log=None, timeout=120):
    if DEADLINE is not None:
        timeout = min(timeout, DEADLINE - time.monotonic())
        require(timeout > 0, "executor time budget exhausted")
    process = subprocess.Popen(arguments, env=ENVIRONMENT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, getattr(signal, "SIGKILL", 9))
            except ProcessLookupError:
                pass
            try:
                output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                output = b""
    if log is not None:
        with log.open("ab") as stream:
            stream.write(output)
    if timed_out:
        raise CommandTimedOut("subprocess timeout; verify process quiescence before recovery")
    if process.returncode != 0:
        raise CommandFailed(process.returncode)
    return output.decode("utf-8").strip()


def services():
    for service in ("nginx", "amazon-cloudwatch-agent"):
        require(command(["systemctl", "is-active", service]) == "active", "service inactive")
        require(command(["systemctl", "is-enabled", service]) == "enabled", "service not enabled")


def http_check(expected):
    connection = http_client.HTTPConnection("127.0.0.1", 80, timeout=10)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read(64 * 1024)
        require(response.status == 200 and body == expected, "local HTTP/content mismatch")
        connection.request("HEAD", "/index.html.backup")
        response = connection.getresponse()
        response.read()
        require(response.status == 404, "former backup URL accessible")
    finally:
        connection.close()


def check_agent():
    status = read_json(command([str(AGENT / "bin/amazon-cloudwatch-agent-ctl"), "-a", "status"]))
    require(status.get("status") == "running" and status.get("configstatus") == "configured", "Agent not configured")


def copy_private(source, target):
    with target.open("xb") as stream:
        stream.write(source.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    regular_file(target, 0o600)
    require(sha(source.read_bytes()) == sha(target.read_bytes()), "durable backup verification")
    sync_directory(target.parent)


def save_record(path, record):
    # The record already exists exclusively under the server lock.
    regular_file(path, 0o600)
    temporary = path.with_suffix(".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def _run(contract):
    global DEADLINE
    import fcntl  # Linux only; pure validators and tests remain portable.

    DEADLINE = time.monotonic() + 600
    require(os.geteuid() == 0 and os.getegid() == 0, "root ownership required")
    os.umask(0o077)
    encoded, operation = operation_parameters(os.environ)
    supported_agent(command(["rpm", "-q", "--qf", "%{VERSION}", "amazon-ssm-agent"]))
    files, release_commit = decode_bundle(encoded, contract, with_commit=True)
    operating_system = Path("/etc/os-release").read_text()
    require(re.search(r'^ID="?amzn"?$', operating_system, re.M) and re.search(r'^VERSION_ID="?2023"?$', operating_system, re.M), "Amazon Linux 2023 required")
    control = private_directory(Path("/var/lib/aws-portfolio-deploy"))
    descriptor = os.open(control / "deployment.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        regular_file(control / "deployment.lock", 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Rejected("another deployment owns the server lock") from error
        marker = control / "recovery-required"
        require(not marker.exists() and not marker.is_symlink(), "operator must review previous incomplete deployment")
        record_path = control / (operation + ".json")
        with record_path.open("x", encoding="utf-8") as stream:
            stream.write("{}\n")
            stream.flush()
            os.fsync(stream.fileno())
        stage = Path(tempfile.mkdtemp(prefix="aws-portfolio-cd.", dir="/var/tmp"))
        record = {"status": "preflight", "commit": release_commit, "stage": str(stage), "scripts": {}, "recovery": "not required"}
        website_backup = monitoring_backup = None
        started = False
        try:
            materialize(files, stage, contract)
            diagnostic = stage / "execution.log"
            diagnostic.touch(mode=0o600, exist_ok=False)
            for name in SEQUENCE:
                command(["bash", "-n", str(stage / "scripts" / name)], diagnostic)
            # Prove all packages already exist: this CD executor cannot recover package transactions.
            command(["bash", str(stage / "scripts/bootstrap.sh"), "--check"], diagnostic)
            services()
            check_agent()
            require(not Path("/usr/share/nginx/html/index.html.backup").exists() and not Path("/usr/share/nginx/html/index.html.backup").is_symlink(), "legacy backup returned")
            for path in (HOMEPAGE, SECURITY):
                secure_parents(path)
                regular_file(path, 0o644)
            for path in (CACHED, SOURCE):
                secure_parents(path)
                if path.exists() or path.is_symlink():
                    regular_file(path)
            regular_file(CACHED, 0o600)
            if SOURCE.exists():
                regular_file(SOURCE, 0o644)
            before_page = HOMEPAGE.read_bytes()
            before_security = SECURITY.read_bytes()
            before_cached = CACHED.read_bytes()
            before_source = SOURCE.read_bytes() if SOURCE.exists() else None
            require("retention_in_days" not in before_cached.decode(), "legacy Agent retention requires operator review")
            original_main = Path("/etc/nginx/nginx.conf").read_bytes()
            secure_parents(Path("/etc/nginx/nginx.conf"))
            regular_file(Path("/etc/nginx/nginx.conf"), 0o644)
            http_check(before_page)
            for name in ("deploy-website.sh", "configure-monitoring.sh"):
                command(["bash", str(stage / "scripts" / name), "--check"], diagnostic)
            # Refuse unexpected Agent fragments and broken integration before backups or live writes.
            desired_cached = read_json(files["config/cloudwatch/amazon-cloudwatch-agent.json"])
            require(sha(before_page) in contract["baseline_homepage_sha256"], "unreviewed website baseline")
            require(before_security == files["config/nginx/security.conf"], "unreviewed Nginx baseline")
            require(read_json(before_cached) == desired_cached, "monitoring drift requires operator review")
            require(before_source is None or read_json(before_source) == desired_cached, "unreviewed Agent input baseline")
            website_changes = before_page != files["website/index.html"] or before_security != files["config/nginx/security.conf"]
            monitoring_changes = read_json(before_cached) != desired_cached or before_source != files["config/cloudwatch/amazon-cloudwatch-agent.json"]
            if website_changes or monitoring_changes:
                private_directory(Path("/var/backups/aws-portfolio-lab"))
            if website_changes:
                parent = private_directory(Path("/var/backups/aws-portfolio-lab/website"))
                website_backup = private_directory(parent / ("cd-" + operation))
                require(not list(website_backup.iterdir()), "recovery directory already used")
                copy_private(HOMEPAGE, website_backup / "index.html")
                copy_private(SECURITY, website_backup / "security.conf")
            if monitoring_changes:
                parent = private_directory(Path("/var/backups/aws-portfolio-lab/monitoring"))
                monitoring_backup = private_directory(parent / ("cd-" + operation))
                require(not list(monitoring_backup.iterdir()), "recovery directory already used")
                copy_private(CACHED, monitoring_backup / "amazon-cloudwatch-agent.json")
                if SOURCE.exists():
                    copy_private(SOURCE, monitoring_backup / "source.json")
            record["baseline_hashes"] = {"homepage": sha(before_page), "security": sha(before_security), "cached_agent": sha(before_cached)}
            record["recovery_directories"] = [str(path) for path in (website_backup, monitoring_backup) if path is not None]
            record["status"] = "deploying"
            save_record(record_path, record)
            # A hard-killed process may release flock while its children still run.
            # Only verified success clears this durable latch; failures require an operator.
            with marker.open("x", encoding="utf-8") as stream:
                stream.write(record_path.name + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            sync_directory(control)
            started = True
            for name in SEQUENCE:
                try:
                    command(["bash", str(stage / "scripts" / name)], diagnostic, timeout=150)
                except CommandFailed as error:
                    record["scripts"][name] = error.code
                    record["failed_script"] = name
                    raise
                record["scripts"][name] = 0
                save_record(record_path, record)
            services()
            check_agent()
            http_check(files["website/index.html"])
            require(read_json(CACHED.read_bytes()) == desired_cached, "active Agent source mismatch")
            require(Path("/etc/nginx/nginx.conf").read_bytes() == original_main, "unmanaged Nginx configuration changed")
            for path in (HOMEPAGE, SECURITY):
                regular_file(path, 0o644)
            record["status"] = "verified"
            save_record(record_path, record)
            started = False  # Verified commit point: a reporting failure must not roll back success.
            regular_file(marker, 0o600)
            marker.unlink()
            sync_directory(control)
            print(json.dumps({"status": "verified", "script_exit_codes": record["scripts"], "local_http": 200, "legacy_backup_http": 404}))
        except Exception as error:
            record["status"] = "failed"
            record["failure_category"] = str(error) if isinstance(error, Rejected) else type(error).__name__
            if started and not isinstance(error, CommandTimedOut):
                DEADLINE = time.monotonic() + 180
                try:
                    if monitoring_backup is not None:
                        command(["bash", str(stage / "scripts/configure-monitoring.sh"), "--rollback", str(monitoring_backup)], diagnostic, timeout=120)
                        # fetch-config can consume its input: restore the original source's presence separately.
                        if before_source is None:
                            if SOURCE.exists():
                                regular_file(SOURCE)
                                SOURCE.unlink()
                        else:
                            temporary = SOURCE.parent / (".cd-recovery-" + operation)
                            with temporary.open("xb") as stream:
                                stream.write(before_source)
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.chmod(temporary, 0o644)
                            os.replace(temporary, SOURCE)
                    if website_backup is not None:
                        command(["bash", str(stage / "scripts/deploy-website.sh"), "--rollback", str(website_backup)], diagnostic, timeout=120)
                    services()
                    check_agent()
                    command(["nginx", "-t"], diagnostic)
                    http_check(before_page)
                    require(SECURITY.read_bytes() == before_security and read_json(CACHED.read_bytes()) == read_json(before_cached), "recovery configuration mismatch")
                    require(Path("/etc/nginx/nginx.conf").read_bytes() == original_main, "unmanaged configuration needs operator recovery")
                    record["recovery"] = "baseline health and configuration verified"
                except Exception:
                    record["recovery"] = "operator recovery required; never retry blindly"
            elif started:
                record["recovery"] = "operator must verify stopped subprocesses before recovery"
            save_record(record_path, record)
            raise
        # Keep the private stage, diagnostics, and operation record for operator review.


def run(contract):
    try:
        _run(contract)
    except Exception:
        # No raw subprocess output, parameters, paths, or caller-controlled exceptions in SSM output.
        print(json.dumps({"status": "failed", "message": "Deployment rejected or failed; review private operation records and diagnostics before retrying."}))
        raise SystemExit(1)
