#!/usr/bin/env python3
"""Manual CD gates and bounded SSM orchestration. Tests inject all remote responses."""

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import tempfile
import time
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "BirdIsOffline/aws-cloud-infrastructure"
CALLER = ".github/workflows/deploy-server.yml"
EXECUTOR = ".github/workflows/deploy-server-executor.yml"
CI = ".github/workflows/ci.yml"
WORKFLOW = "Deploy lab server"
REGION = "us-east-2"
SCRIPTS = ("bootstrap.sh", "deploy-website.sh", "configure-monitoring.sh", "verify-server.sh")
POLL_SECONDS = 1050
MONITOR_SECONDS = 480


class Rejected(RuntimeError):
    """A checked invariant failed; messages contain no remote response bodies."""


class Ambiguous(Rejected):
    """Remote execution may continue. Never resubmit or automatically roll back."""


class InvocationMissing(RuntimeError):
    """The safe polling API has not yet observed the accepted command."""


def require(condition, message):
    if not condition:
        raise Rejected(message)


def fullmatch(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def config(environment):
    cfg = {key: environment.get("CD_" + key, "") for key in (
        "COMMIT", "GITHUB_OWNER_ID", "GITHUB_REPOSITORY_ID", "ALLOWED_ACTOR_IDS",
        "ROLE_ARN", "INSTANCE_ID", "VPC_ID", "SSM_DOCUMENT_SHA256"
    )}
    require(fullmatch(r"[0-9a-f]{40}", cfg["COMMIT"]), "Select a full lowercase commit SHA")
    for key in ("GITHUB_OWNER_ID", "GITHUB_REPOSITORY_ID"):
        require(fullmatch(r"[1-9][0-9]{0,19}", cfg[key]), "Missing or invalid immutable GitHub configuration")
    try:
        actors = json.loads(cfg["ALLOWED_ACTOR_IDS"])
    except (ValueError, TypeError):
        raise Rejected("Actor configuration must be a JSON array of numeric strings") from None
    require(isinstance(actors, list) and 1 <= len(actors) <= 5, "Invalid approved actor count")
    require(all(fullmatch(r"[1-9][0-9]{0,19}", actor) for actor in actors), "Invalid approved actor identifier")
    require(len(set(actors)) == len(actors), "Duplicate approved actors")
    cfg["actors"] = set(actors)
    require(fullmatch(r"arn:aws:iam::[0-9]{12}:role/aws-lab-github-deploy-role", cfg["ROLE_ARN"]), "Unexpected deployment role configuration")
    cfg["account"] = cfg["ROLE_ARN"].split(":")[4]
    require(fullmatch(r"i-[0-9a-f]{17}", cfg["INSTANCE_ID"]), "Invalid target instance configuration")
    require(fullmatch(r"vpc-[0-9a-f]{17}", cfg["VPC_ID"]), "Invalid lab VPC configuration")
    require(fullmatch(r"[0-9a-f]{64}", cfg["SSM_DOCUMENT_SHA256"]), "Missing approved AWS document SHA-256")
    return cfg


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token):
        require(bool(token), "Missing read-only GitHub token")
        self.token = token

    def get(self, endpoint):
        require(endpoint.startswith("/repos/" + REPOSITORY + "/") or endpoint == "/repos/" + REPOSITORY, "Unexpected GitHub API route")
        req = request.Request("https://api.github.com" + endpoint, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "portfolio-lab-delivery"
        })
        try:
            with request.build_opener(NoRedirect).open(req, timeout=15) as response:
                body = response.read(4 * 1024 * 1024 + 1)
                require(len(body) <= 4 * 1024 * 1024, "GitHub API response exceeds limit")
                return json.loads(body)
        except (OSError, ValueError):
            raise Rejected("GitHub read-only check failed; no credentials or response body logged") from None


def git_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def applicable_run(run, commit, workflow_id, repository_id):
    return (
        run.get("head_sha") == commit and run.get("head_branch") == "main"
        and run.get("event") in {"push", "workflow_dispatch"}
        and run.get("workflow_id") == workflow_id
        and run.get("path", "").split("@", 1)[0] == CI
        and str(run.get("head_repository", {}).get("id")) == repository_id
    )


def latest_ci(api, commit, repository_id):
    base = "/repos/" + REPOSITORY
    workflow = api.get(base + "/actions/workflows/ci.yml")
    require(workflow.get("path") == CI and workflow.get("name") == "CI" and workflow.get("state") == "active", "Expected CI workflow is not active")
    workflow_id = workflow["id"]
    query = parse.urlencode({"head_sha": commit, "branch": "main", "per_page": 100})
    response = api.get(base + "/actions/workflows/ci.yml/runs?" + query)
    require(isinstance(response.get("total_count"), int) and response["total_count"] <= 100, "CI history is truncated or invalid; operator review required")
    runs = response.get("workflow_runs", [])
    require(len(runs) == response["total_count"], "Incomplete CI history")
    applicable = [run for run in runs if applicable_run(run, commit, workflow_id, repository_id)]
    require(applicable, "No applicable CI run for this exact main revision")
    require(all(isinstance(run.get("run_number"), int) and isinstance(run.get("id"), int) for run in applicable), "Invalid CI run metadata")
    latest = max(applicable, key=lambda run: (run["run_number"], run["id"]))
    # Fetch the latest attempt's live status. Never filter the list to successes.
    current = api.get(base + "/actions/runs/" + str(latest["id"]))
    require(applicable_run(current, commit, workflow_id, repository_id) and current.get("id") == latest["id"], "CI run identity changed")
    require(current.get("run_attempt") == latest.get("run_attempt") and isinstance(current.get("run_attempt"), int), "CI attempt changed; use a fresh dispatch")
    require(current.get("status") == "completed" and current.get("conclusion") == "success", "Newest applicable CI attempt has not succeeded")
    return current["id"]


def authorize(environment, event, api, head=git_head):
    cfg = config(environment)
    require(environment.get("GITHUB_ACTIONS") == "true" and environment.get("RUNNER_ENVIRONMENT") == "github-hosted", "GitHub-hosted execution is required")
    require(environment.get("GITHUB_SERVER_URL") == "https://github.com" and environment.get("GITHUB_API_URL") == "https://api.github.com", "Unexpected GitHub host")
    require(environment.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "Only a manual dispatch is authorized")
    require(environment.get("GITHUB_REF") == "refs/heads/main" and event.get("ref") in {"main", "refs/heads/main"}, "Dispatch must use main")
    require(environment.get("GITHUB_WORKFLOW") == WORKFLOW, "Unexpected caller workflow name")
    require(environment.get("GITHUB_WORKFLOW_REF") == REPOSITORY + "/" + CALLER + "@refs/heads/main", "Unexpected caller workflow reference")
    require(environment.get("GITHUB_REPOSITORY") == REPOSITORY, "Unexpected repository")
    require(environment.get("GITHUB_REPOSITORY_ID") == cfg["GITHUB_REPOSITORY_ID"] and environment.get("GITHUB_REPOSITORY_OWNER_ID") == cfg["GITHUB_OWNER_ID"], "Immutable context identity differs")
    require(environment.get("GITHUB_SHA") == cfg["COMMIT"] == event.get("inputs", {}).get("commit") == head(), "Selected commit, dispatch revision and checkout must match")
    require(environment.get("GITHUB_RUN_ATTEMPT") == "1", "Re-runs are rejected; review recovery before a fresh dispatch")
    actor = environment.get("GITHUB_ACTOR_ID")
    require(actor in cfg["actors"] and str(event.get("sender", {}).get("id")) == actor, "Dispatch actor is not approved")
    require(environment.get("GITHUB_ACTOR") == environment.get("GITHUB_TRIGGERING_ACTOR") == event.get("sender", {}).get("login"), "Re-running or substituted actor rejected")
    require(fullmatch(r"[1-9][0-9]{0,19}", environment.get("GITHUB_RUN_ID")), "Invalid dispatch run identifier")
    repository = api.get("/repos/" + REPOSITORY)
    for record in (repository, event.get("repository", {})):
        require(record.get("full_name") == REPOSITORY and str(record.get("id")) == cfg["GITHUB_REPOSITORY_ID"] and str(record.get("owner", {}).get("id")) == cfg["GITHUB_OWNER_ID"], "Repository identity differs")
        require(record.get("private") is True and record.get("fork") is False, "Expected private original repository")
    main = api.get("/repos/" + REPOSITORY + "/git/ref/heads/main")
    require(main.get("ref") == "refs/heads/main" and main.get("object", {}).get("type") == "commit" and main["object"]["sha"] == cfg["COMMIT"], "Selected revision is no longer current main")
    latest_ci(api, cfg["COMMIT"], cfg["GITHUB_REPOSITORY_ID"])
    return cfg


def release():
    packer = runpy.run_path(str(ROOT / "scripts/ssm/bundle.py"))
    packer["check"]()
    encoded, contract = packer["create"]()
    rendered = packer["document"]()
    return {"bundle": encoded, "document_name": packer["document_name"](rendered, contract), "document_content": rendered}


def private_directory(path):
    require(path.parent == ROOT or path.parent.exists(), "Missing private staging parent")
    if not path.exists():
        path.mkdir(mode=0o700)
    require(not path.is_symlink() and path.is_dir(), "Unsafe private stage directory")
    if os.name == "posix":
        require(stat.S_IMODE(path.stat().st_mode) == 0o700 and path.stat().st_uid == os.getuid(), "Private stage permissions or owner differ")
    return path


def write_private(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def prepare(cfg, environment):
    data = release()
    require(hashlib.sha256(data["document_content"].encode()).hexdigest() == cfg["SSM_DOCUMENT_SHA256"], "Source executor differs from the approved document hash")
    parent = private_directory(private_directory(ROOT / ".local") / "cd")
    stage = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    write_private(stage / "release.json", {"commit": cfg["COMMIT"], **data})
    session = "cd-" + environment["GITHUB_RUN_ID"] + "-1"
    with open(environment["GITHUB_ENV"], "a", encoding="utf-8") as output:
        for key, value in {"CD_STAGE": str(stage), "CD_ACCOUNT_ID": cfg["account"], "CD_SESSION_NAME": session}.items():
            output.write(key + "=" + value + "\n")
    for value in (cfg["account"], cfg["ROLE_ARN"], cfg["INSTANCE_ID"], cfg["VPC_ID"]):
        print("::add-mask::" + value)


class AWS:
    def __init__(self):
        self.submitted = False

    def call(self, service, operation, *arguments):
        sending = (service, operation) == ("ssm", "send-command")
        if sending:
            require(not self.submitted, "A second submission is forbidden")
            self.submitted = True  # Set before starting the non-idempotent request.
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("AWS_ENDPOINT_URL") or key in {"AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"}:
                env.pop(key, None)
        env.update(AWS_MAX_ATTEMPTS="1", AWS_RETRY_MODE="standard", AWS_EC2_METADATA_DISABLED="true", AWS_PAGER="")
        try:
            result = subprocess.run([
                "aws", service, operation, *arguments, "--region", REGION, "--output", "json",
                "--no-cli-pager", "--cli-connect-timeout", "5", "--cli-read-timeout", "20"
            ], env=env, capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            if sending:
                raise Ambiguous("SSM submission outcome is unknown; operator inspection required, never resubmit") from None
            raise Rejected("AWS read timed out or could not execute; response details withheld") from None
        if result.returncode:
            if sending:
                raise Ambiguous("SSM submission failed or outcome is unknown; operator inspection required, never resubmit")
            if (service, operation) == ("ssm", "get-command-invocation") and b"(InvocationDoesNotExist)" in result.stderr:
                raise InvocationMissing()
            raise Rejected("AWS read-only verification failed; response details withheld")
        try:
            return json.loads(result.stdout)
        except ValueError:
            if sending:
                raise Ambiguous("SSM submission response is invalid; operator inspection required, never resubmit") from None
            raise Rejected("Invalid AWS read response") from None


def target(aws, cfg, session):
    identity = aws.call("sts", "get-caller-identity")
    require(identity.get("Account") == cfg["account"] and identity.get("Arn") == "arn:aws:sts::" + cfg["account"] + ":assumed-role/aws-lab-github-deploy-role/" + session, "Unexpected assumed role identity")
    vpcs = aws.call("ec2", "describe-vpcs", "--vpc-ids", cfg["VPC_ID"])["Vpcs"]
    require(len(vpcs) == 1 and vpcs[0]["VpcId"] == cfg["VPC_ID"] and not vpcs[0]["IsDefault"] and vpcs[0]["CidrBlock"] == "10.20.0.0/16", "Lab VPC verification failed")
    require({tag["Key"]: tag["Value"] for tag in vpcs[0].get("Tags", [])}.get("Name") == "aws-cloud-lab-vpc", "Unexpected VPC name")
    instances = [instance for reservation in aws.call("ec2", "describe-instances", "--instance-ids", cfg["INSTANCE_ID"])["Reservations"] for instance in reservation["Instances"]]
    require(len(instances) == 1, "Unexpected instance count")
    instance = instances[0]
    require(instance["InstanceId"] == cfg["INSTANCE_ID"] and instance["VpcId"] == cfg["VPC_ID"] and instance["State"]["Name"] == "running", "Target must be the running lab instance")
    require({tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}.get("Name") == "aws-lab-web-01", "Unexpected instance name")
    address = ipaddress.ip_address(instance.get("PublicIpAddress", ""))
    require(address.version == 4 and address.is_global, "Target needs its existing public IPv4 association")
    info = aws.call("ssm", "describe-instance-information", "--filters", json.dumps([{"Key": "InstanceIds", "Values": [cfg["INSTANCE_ID"]]}]))["InstanceInformationList"]
    require(len(info) == 1 and info[0]["InstanceId"] == cfg["INSTANCE_ID"] and info[0]["PingStatus"] == "Online", "Target must be SSM Online")
    checker = runpy.run_path(str(ROOT / "scripts/ssm/executor.py"))
    checker["supported_agent"](info[0]["AgentVersion"])
    return str(address)


def document(aws, cfg, data):
    # DescribeDocument is deliberately scoped; the deployment role cannot GetDocument or edit it.
    description = aws.call("ssm", "describe-document", "--name", data["document_name"], "--document-version", "1")["Document"]
    require(description.get("Name") == data["document_name"] and description.get("Owner") == cfg["account"], "Unexpected dedicated document identity")
    require(description.get("Status") == "Active" and description.get("DocumentVersion") == description.get("DefaultVersion") == description.get("LatestVersion") == "1", "Only active original/default/latest document version one is authorized")
    require(description.get("HashType") == "Sha256" and description.get("Hash") == cfg["SSM_DOCUMENT_SHA256"], "AWS-reported document hash differs from operator approval")
    require(description.get("DocumentType") == "Command" and description.get("SchemaVersion") == "2.2" and description.get("TargetType") == "/AWS::EC2::Instance", "Document execution contract differs")


def invocation_success(result, command_id, cfg, data):
    require(result.get("CommandId") == command_id and result.get("InstanceId") == cfg["INSTANCE_ID"], "Invocation identity differs")
    require(result.get("DocumentName") == data["document_name"] and result.get("DocumentVersion") == "1" and result.get("PluginName") == "RestrictedDeployment", "Invocation executor differs")
    require(result.get("ResponseCode") == 0, "Executor returned a nonzero response code")
    try:
        report = json.loads(result.get("StandardOutputContent", ""))
    except ValueError:
        raise Rejected("Executor did not return its verified success report") from None
    require(report.get("status") == "verified" and report.get("script_exit_codes") == {name: 0 for name in SCRIPTS}, "Executor did not verify all four scripts")
    require(report.get("local_http") == 200 and report.get("legacy_backup_http") == 404, "Executor local HTTP checks failed")


def poll(aws, command_id, cfg, data, clock=time.monotonic, sleep=time.sleep):
    started = clock()
    while clock() - started < POLL_SECONDS:
        try:
            result = aws.call("ssm", "get-command-invocation", "--command-id", command_id, "--instance-id", cfg["INSTANCE_ID"], "--plugin-name", "RestrictedDeployment")
        except InvocationMissing:
            if clock() - started >= 30:
                raise Ambiguous("Accepted command remains unobservable; operator inspection required") from None
            sleep(5)
            continue
        status = result.get("Status")
        if status == "Success":
            invocation_success(result, command_id, cfg, data)
            return
        if status in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
            raise Ambiguous("SSM execution failed, was cancelled, or timed out; inspect recovery latch and command before any new dispatch")
        require(status in {"Pending", "InProgress", "Delayed"}, "Unknown SSM execution status; operator inspection required")
        sleep(5)
    raise Ambiguous("SSM polling deadline reached; command may still run, never automatically resubmit or roll back")


def http(address, path, status, expected=None):
    require(path in {"/", "/index.html.backup"}, "Unexpected HTTP verification path")
    try:
        with request.build_opener(NoRedirect).open("http://" + address + path, timeout=10) as response:
            actual_status, body = response.status, response.read(65537)
    except error.HTTPError as response:
        actual_status, body = response.code, b""
    except OSError:
        raise Rejected("Public HTTP verification failed; address withheld") from None
    require(actual_status == status and (expected is None or body == expected), "Public HTTP status or approved homepage content differs")


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def monitoring(aws, cfg, since, clock=time.monotonic, sleep=time.sleep):
    groups = ("/aws/portfolio-lab/nginx/access", "/aws/portfolio-lab/nginx/error")
    for name in groups:
        matched = [group for group in aws.call("logs", "describe-log-groups", "--log-group-name-prefix", name)["logGroups"] if group["logGroupName"] == name]
        require(len(matched) == 1 and matched[0].get("retentionInDays") == 7, "Both log groups must retain seven-day retention")
    start = clock()
    while clock() - start < MONITOR_SECONDS:
        fresh_metrics = []
        for name, extra in (("mem_used_percent", []), ("disk_used_percent", [{"Name": "path", "Value": "/"}, {"Name": "fstype", "Value": "xfs"}])):
            dimensions = [{"Name": "InstanceId", "Value": cfg["INSTANCE_ID"]}, *extra]
            points = aws.call("cloudwatch", "get-metric-statistics", "--namespace", "AWSPortfolioLab", "--metric-name", name, "--dimensions", json.dumps(dimensions), "--start-time", datetime.fromtimestamp(since, timezone.utc).isoformat(), "--end-time", datetime.now(timezone.utc).isoformat(), "--period", "300", "--statistics", "Average")["Datapoints"]
            fresh_metrics.append(any(timestamp(point["Timestamp"]) >= since for point in points))
        fresh_access = False
        for name in groups:
            streams = [stream for stream in aws.call("logs", "describe-log-streams", "--log-group-name", name, "--log-stream-name-prefix", cfg["INSTANCE_ID"])["logStreams"] if stream["logStreamName"] == cfg["INSTANCE_ID"]]
            require(len(streams) == 1, "Expected existing instance log stream missing")
            if name == groups[0]:
                fresh_access = streams[0].get("lastIngestionTime", 0) / 1000 >= since and streams[0].get("lastEventTimestamp", 0) / 1000 >= since
        if all(fresh_metrics) and fresh_access:
            return
        sleep(15)
    raise Rejected("Fresh post-deployment metrics or access-log ingestion not observed; do not redeploy to retry verification")


def deploy(cfg, environment, api, aws):
    parent = ROOT / ".local/cd"
    stage = Path(environment.get("CD_STAGE", ""))
    require(stage.is_absolute() and stage.parent == parent and stage.name.startswith("run-"), "Unexpected private stage path")
    private_directory(private_directory(ROOT / ".local") / "cd")
    private_directory(stage)
    prepared = stage / "release.json"
    metadata = prepared.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and prepared.stat().st_size < 64 * 1024, "Unsafe prepared release file")
    if os.name == "posix":
        require(stat.S_IMODE(metadata.st_mode) == 0o600 and metadata.st_uid == os.getuid(), "Private release ownership or permissions differ")
    data = json.loads(prepared.read_text())
    require(data == {"commit": cfg["COMMIT"], **release()}, "Prepared release bytes or source commit changed")
    require(hashlib.sha256(data["document_content"].encode()).hexdigest() == cfg["SSM_DOCUMENT_SHA256"], "Approved document hash mismatch")
    session = "cd-" + environment["GITHUB_RUN_ID"] + "-1"
    address = target(aws, cfg, session)
    document(aws, cfg, data)
    http(address, "/", 200)  # Check availability before submitting a command.
    authorize(environment, json.loads(Path(environment["GITHUB_EVENT_PATH"]).read_text()), api)
    operation = session
    payload = {
        "InstanceIds": [cfg["INSTANCE_ID"]], "DocumentName": data["document_name"],
        "DocumentVersion": "1", "DocumentHash": cfg["SSM_DOCUMENT_SHA256"], "DocumentHashType": "Sha256",
        "Parameters": {"Bundle": [data["bundle"]], "OperationId": [operation]},
        "TimeoutSeconds": 120, "MaxConcurrency": "1", "MaxErrors": "0",
        "Comment": operation + " " + cfg["COMMIT"]
    }
    payload_path = stage / "command.json"
    write_private(payload_path, payload)
    # A local exclusive receipt also prevents a second submission from this stage.
    write_private(stage / "submission-started.json", {"operation": operation, "commit": cfg["COMMIT"]})
    response = aws.call("ssm", "send-command", "--cli-input-json", "file://" + str(payload_path))
    command = response.get("Command", {})
    command_id = command.get("CommandId", "")
    if not fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", command_id):
        raise Ambiguous("Accepted command identity missing; operator inspection required")
    write_private(stage / "accepted.json", {"operation": operation, "command_id": command_id})
    require(command.get("DocumentName") == data["document_name"] and command.get("DocumentVersion") == "1" and command.get("InstanceIds") == [cfg["INSTANCE_ID"]], "Accepted command target or executor differs; operator inspection required")
    poll(aws, command_id, cfg, data)
    since = time.time()  # Strictly newer observations; historical datapoints do not qualify.
    http(address, "/", 200, (ROOT / "website/index.html").read_bytes())
    http(address, "/index.html.backup", 404)
    monitoring(aws, cfg, since)
    with open(environment["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
        output.write("Deployment verified for commit `" + cfg["COMMIT"] + "`. All four scripts succeeded; local/public HTTP, backup protection, fresh telemetry and seven-day retention passed.\n")
    print("PASS: approved deployment, HTTP health and fresh monitoring verified; identifiers withheld.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("gate", "prepare", "deploy"))
    phase = parser.parse_args().phase
    environment = os.environ
    api = GitHub(environment.get("GH_TOKEN"))
    event = json.loads(Path(environment["GITHUB_EVENT_PATH"]).read_text())
    cfg = authorize(environment, event, api)
    if phase == "gate":
        with open(environment["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("commit=" + cfg["COMMIT"] + "\n")
        print("PASS: manual actor, immutable identity, main revision and newest applicable CI authorized.")
    elif phase == "prepare":
        prepare(cfg, environment)
        print("PASS: repeated authorization and seven-file private release preparation; no AWS authentication yet.")
    else:
        deploy(cfg, environment, api, AWS())


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, Rejected) else "CD verification failed (" + type(error).__name__ + "); sensitive details withheld"
        print("FAIL: " + message)
        print("No automatic retry, cancellation, or operator recovery. Inspect any accepted command and persistent recovery latch before a new dispatch.")
        raise SystemExit(1) from None
