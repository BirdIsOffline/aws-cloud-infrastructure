"""Synthetic CD authorization, failure handling and orchestration tests; no remote calls."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("restricted_delivery", ROOT / "scripts/cd/delivery.py")
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)
SHA = "a" * 40
COMMAND = "-".join("a" * count for count in (8, 4, 4, 4, 12))


def environment():
    return {
        "CD_COMMIT": SHA, "CD_GITHUB_OWNER_ID": "101", "CD_GITHUB_REPOSITORY_ID": "202",
        "CD_ALLOWED_ACTOR_IDS": '["303"]',
        "CD_ROLE_ARN": "arn:aws:iam::" + "1" * 12 + ":role/aws-lab-github-deploy-role",
        "CD_ROLE_UNIQUE_ID": "AROA" + "A" * 17,
        "CD_INSTANCE_ID": "i-" + "a" * 17, "CD_VPC_ID": "vpc-" + "b" * 17,
        "CD_SSM_DOCUMENT_SHA256": "c" * 64,
        "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW": delivery.WORKFLOW,
        "GITHUB_WORKFLOW_REF": delivery.REPOSITORY + "/" + delivery.CALLER + "@refs/heads/main",
        "GITHUB_REPOSITORY": delivery.REPOSITORY, "GITHUB_REPOSITORY_ID": "202",
        "GITHUB_REPOSITORY_OWNER_ID": "101", "GITHUB_SHA": SHA,
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_ACTOR_ID": "303", "GITHUB_ACTOR": "operator",
        "GITHUB_TRIGGERING_ACTOR": "operator", "GITHUB_RUN_ID": "404"
    }


def repository():
    return {"full_name": delivery.REPOSITORY, "id": 202, "owner": {"id": 101}, "private": True, "fork": False}


def event():
    return {"ref": "refs/heads/main", "inputs": {"commit": SHA}, "sender": {"id": 303, "login": "operator"}, "repository": repository()}


def ci_run(number=1, **changes):
    value = {"id": number, "run_number": number, "run_attempt": 1, "head_sha": SHA,
             "head_branch": "main", "event": "push", "workflow_id": 505, "path": delivery.CI,
             "head_repository": {"id": 202}, "status": "completed", "conclusion": "success"}
    value.update(changes)
    return value


class GitHubResponses:
    def __init__(self, runs=None):
        self.runs = [ci_run()] if runs is None else runs
        self.current = None
        self.main = SHA
        self.total = len(self.runs)

    def get(self, endpoint):
        if endpoint.endswith("/git/ref/heads/main"):
            return {"ref": "refs/heads/main", "object": {"type": "commit", "sha": self.main}}
        if endpoint.endswith("/actions/workflows/ci.yml"):
            return {"id": 505, "path": delivery.CI, "name": "CI", "state": "active"}
        if "/actions/workflows/ci.yml/runs?" in endpoint:
            return {"total_count": self.total, "workflow_runs": copy.deepcopy(self.runs)}
        if "/actions/runs/" in endpoint:
            return copy.deepcopy(self.current or next(run for run in self.runs if str(run["id"]) == endpoint.rsplit("/", 1)[1]))
        return repository()


class Gates(unittest.TestCase):
    def authorize(self, env=None, payload=None, api=None, head=SHA):
        return delivery.authorize(env or environment(), payload or event(), api or GitHubResponses(), head=lambda: head)

    def test_exact_authorized_dispatch(self):
        self.assertEqual(self.authorize()["COMMIT"], SHA)

    def test_ref_event_workflow_host_and_rerun_rejection(self):
        bad = {"GITHUB_REF": "refs/heads/other", "GITHUB_EVENT_NAME": "push", "GITHUB_WORKFLOW": "Other workflow",
               "GITHUB_WORKFLOW_REF": "other", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_TRIGGERING_ACTOR": "different",
               "GITHUB_SERVER_URL": "https://invalid.example", "RUNNER_ENVIRONMENT": "self-hosted"}
        for key, value in bad.items():
            with self.subTest(key=key), self.assertRaises(delivery.Rejected):
                self.authorize(dict(environment(), **{key: value}))

    def test_commit_inputs_dispatch_checkout_and_current_main_must_agree(self):
        for kind in ("input", "dispatch", "checkout", "main"):
            env, payload, api, head = environment(), event(), GitHubResponses(), SHA
            if kind == "input":
                payload["inputs"]["commit"] = "b" * 40
            elif kind == "dispatch":
                env["GITHUB_SHA"] = "b" * 40
            elif kind == "checkout":
                head = "b" * 40
            else:
                api.main = "b" * 40
            with self.subTest(kind=kind), self.assertRaises(delivery.Rejected):
                self.authorize(env, payload, api, head)

    def test_actor_and_immutable_identity_rejection(self):
        for key in ("GITHUB_ACTOR_ID", "GITHUB_REPOSITORY_ID", "GITHUB_REPOSITORY_OWNER_ID"):
            with self.subTest(key=key), self.assertRaises(delivery.Rejected):
                self.authorize(dict(environment(), **{key: "999"}))
        payload = event()
        payload["repository"]["fork"] = True
        with self.assertRaises(delivery.Rejected):
            self.authorize(payload=payload)

    def test_configuration_rejects_arbitrary_role_ids_hashes_and_actor_lists(self):
        invalid = {"CD_COMMIT": "main; command", "CD_ROLE_ARN": "unapproved-role", "CD_INSTANCE_ID": "other",
                   "CD_VPC_ID": "other", "CD_ALLOWED_ACTOR_IDS": '["303", "303"]', "CD_SSM_DOCUMENT_SHA256": "bad"}
        for key, value in invalid.items():
            with self.subTest(key=key), self.assertRaises(delivery.Rejected):
                delivery.config(dict(environment(), **{key: value}))

    def test_missing_failed_cancelled_pending_skipped_ci_rejected(self):
        cases = [[], [ci_run(status="queued", conclusion=None)], [ci_run(status="in_progress", conclusion=None)]]
        cases += [[ci_run(conclusion=value)] for value in ("failure", "cancelled", "timed_out", "neutral", "skipped", "stale")]
        for runs in cases:
            with self.subTest(runs=runs), self.assertRaises(delivery.Rejected):
                self.authorize(api=GitHubResponses(runs))

    def test_newer_unsuccessful_run_overrides_older_success(self):
        api = GitHubResponses([ci_run(2, status="queued", conclusion=None), ci_run(1)])
        with self.assertRaisesRegex(delivery.Rejected, "Newest applicable"):
            self.authorize(api=api)

    def test_wrong_commit_branch_workflow_event_or_repository_does_not_qualify(self):
        for change in ({"head_sha": "b" * 40}, {"head_branch": "other"}, {"workflow_id": 999},
                       {"event": "pull_request"}, {"path": delivery.CALLER}, {"head_repository": {"id": 999}}):
            with self.subTest(change=change), self.assertRaises(delivery.Rejected):
                self.authorize(api=GitHubResponses([ci_run(**change)]))

    def test_latest_ci_attempt_and_truncated_history_rejected(self):
        api = GitHubResponses()
        api.current = ci_run(run_attempt=2)
        with self.assertRaisesRegex(delivery.Rejected, "attempt changed"):
            self.authorize(api=api)
        api = GitHubResponses()
        api.total = 101
        with self.assertRaisesRegex(delivery.Rejected, "truncated"):
            self.authorize(api=api)

    def test_api_does_not_follow_redirects_or_accept_foreign_routes(self):
        self.assertIsNone(delivery.NoRedirect().redirect_request(None, None, 302, "", {}, "https://invalid.example"))
        with self.assertRaises(delivery.Rejected):
            delivery.GitHub("synthetic").get("/other/route")


class Clock:
    def __init__(self):
        self.now = 0

    def read(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def success(cfg, data):
    return {"Status": "Success", "CommandId": COMMAND, "InstanceId": cfg["INSTANCE_ID"],
            "DocumentName": data["document_name"], "DocumentVersion": "1", "PluginName": "RestrictedDeployment",
            "ResponseCode": 0, "StandardOutputContent": json.dumps({"status": "verified", "script_exit_codes": {name: 0 for name in delivery.SCRIPTS}, "local_http": 200, "legacy_backup_http": 404})}


class Polling(unittest.TestCase):
    def setUp(self):
        self.cfg = delivery.config(environment())
        self.data = {"document_name": "reviewed-document"}
        self.clock = Clock()

    def poll(self, aws):
        return delivery.poll(aws, COMMAND, self.cfg, self.data, self.clock.read, self.clock.sleep)

    def test_eventual_consistency_then_success_uses_only_polling_reads(self):
        aws = mock.Mock()
        aws.call.side_effect = [delivery.InvocationMissing(), {"Status": "Pending"}, success(self.cfg, self.data)]
        self.poll(aws)
        self.assertEqual(aws.call.call_count, 3)
        self.assertTrue(all(call.args[:2] == ("ssm", "get-command-invocation") for call in aws.call.call_args_list))

    def test_terminal_failure_and_cancellation_never_retry_execution(self):
        for status in ("Failed", "Cancelled", "TimedOut", "Cancelling"):
            aws = mock.Mock()
            aws.call.return_value = {"Status": status}
            with self.subTest(status=status), self.assertRaises(delivery.Ambiguous):
                self.poll(aws)
            aws.call.assert_called_once()

    def test_poll_deadline_and_missing_invocation_are_bounded(self):
        aws = mock.Mock()
        aws.call.return_value = {"Status": "Delayed"}
        with mock.patch.object(delivery, "POLL_SECONDS", 12), self.assertRaises(delivery.Ambiguous):
            self.poll(aws)
        self.assertEqual(aws.call.call_count, 3)
        aws = mock.Mock()
        aws.call.side_effect = delivery.InvocationMissing()
        self.clock = Clock()
        with self.assertRaises(delivery.Ambiguous):
            self.poll(aws)
        self.assertLessEqual(aws.call.call_count, 7)

    def test_unknown_status_and_invalid_success_report_fail_closed(self):
        for change in ({"Status": "Unknown"}, {"ResponseCode": 1}, {"InstanceId": "different"},
                       {"StandardOutputContent": "not-json"}, {"DocumentVersion": "2"}):
            aws = mock.Mock()
            aws.call.return_value = dict(success(self.cfg, self.data), **change)
            with self.subTest(change=change), self.assertRaises(delivery.Rejected):
                self.poll(aws)

    def test_non_idempotent_send_timeout_is_not_retried(self):
        aws = delivery.AWS()
        with mock.patch.object(delivery.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic", 30)) as run:
            with self.assertRaises(delivery.Ambiguous):
                aws.call("ssm", "send-command")
            with self.assertRaises(delivery.Rejected):
                aws.call("ssm", "send-command")
            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs["env"]["AWS_MAX_ATTEMPTS"], "1")

    def test_raw_aws_errors_are_not_exposed(self):
        aws = delivery.AWS()
        response = mock.Mock(returncode=1, stderr=b"private response body marker")
        with mock.patch.object(delivery.subprocess, "run", return_value=response):
            with self.assertRaises(delivery.Rejected) as caught:
                aws.call("sts", "get-caller-identity")
        self.assertNotIn("private response body marker", str(caught.exception))


class DocumentsAndMonitoring(unittest.TestCase):
    def test_target_identity_running_ssm_and_agent_version(self):
        cfg = delivery.config(environment())
        session = "cd-404-1"
        vpc = {"VpcId": cfg["VPC_ID"], "IsDefault": False, "CidrBlock": "10.20.0.0/16", "Tags": [{"Key": "Name", "Value": "aws-cloud-lab-vpc"}]}
        instance = {"InstanceId": cfg["INSTANCE_ID"], "VpcId": cfg["VPC_ID"], "State": {"Name": "running"},
                    "Tags": [{"Key": "Name", "Value": "aws-lab-web-01"}], "PublicIpAddress": "synthetic-address"}
        info = {"InstanceId": cfg["INSTANCE_ID"], "PingStatus": "Online", "AgentVersion": "3.3.2746.0"}
        def response(service, operation, *args, **kwargs):
            if operation == "get-caller-identity":
                return {"Account": cfg["account"], "Arn": "arn:aws:sts::" + cfg["account"] + ":assumed-role/aws-lab-github-deploy-role/" + session, "UserId": cfg["ROLE_UNIQUE_ID"] + ":" + session}
            if operation == "describe-vpcs":
                return {"Vpcs": [vpc]}
            if operation == "describe-instances":
                return {"Reservations": [{"Instances": [instance]}]}
            return {"InstanceInformationList": [info]}
        aws = mock.Mock()
        aws.call.side_effect = response
        with mock.patch.object(delivery.ipaddress, "ip_address", return_value=SimpleNamespace(version=4, is_global=True)):
            delivery.target(aws, cfg, session)
            instance["State"]["Name"] = "stopped"
            with self.assertRaises(delivery.Rejected):
                delivery.target(aws, cfg, session)
            instance["State"]["Name"] = "running"
            info["PingStatus"] = "ConnectionLost"
            with self.assertRaises(delivery.Rejected):
                delivery.target(aws, cfg, session)
            info["PingStatus"] = "Online"
            info["AgentVersion"] = "3.3.2000.0"
            with self.assertRaises(ValueError):
                delivery.target(aws, cfg, session)
        self.assertTrue(all(call.args[1] != "send-command" for call in aws.call.call_args_list))

    def test_document_identity_version_status_and_hash_are_required(self):
        cfg = delivery.config(environment())
        data = {"document_name": "reviewed-document"}
        description = {"Name": data["document_name"], "Owner": cfg["account"], "Status": "Active", "DocumentVersion": "1",
                       "DefaultVersion": "1", "LatestVersion": "1", "HashType": "Sha256", "Hash": cfg["SSM_DOCUMENT_SHA256"],
                       "DocumentType": "Command", "SchemaVersion": "2.2", "TargetType": "/AWS::EC2::Instance"}
        aws = mock.Mock()
        aws.call.return_value = {"Document": description}
        delivery.document(aws, cfg, data)
        for key, value in (("Hash", "bad"), ("Owner", "other"), ("LatestVersion", "2"), ("Status", "Updating"), ("HashType", "Sha1")):
            aws.call.return_value = {"Document": dict(description, **{key: value})}
            with self.subTest(key=key), self.assertRaises(delivery.Rejected):
                delivery.document(aws, cfg, data)

    def test_historical_metrics_and_logs_do_not_count_as_fresh(self):
        cfg = delivery.config(environment())
        clock = Clock()
        def response(service, operation, *args, **kwargs):
            if operation == "describe-log-groups":
                return {"logGroups": [{"logGroupName": args[-1], "retentionInDays": 7}]}
            if operation == "get-metric-statistics":
                return {"Datapoints": [{"Timestamp": "2000-01-01T00:00:00Z", "Average": 1}]}
            return {"logStreams": [{"logStreamName": cfg["INSTANCE_ID"], "lastIngestionTime": 1, "lastEventTimestamp": 1}]}
        aws = mock.Mock()
        aws.call.side_effect = response
        with mock.patch.object(delivery, "MONITOR_SECONDS", 20), self.assertRaisesRegex(delivery.Rejected, "not observed"):
            delivery.monitoring(aws, cfg, 1_000_000_000, clock.read, clock.sleep)
        self.assertLess(clock.now, 40)

    def test_fresh_metrics_ingestion_and_retention_pass(self):
        cfg = delivery.config(environment())
        def response(service, operation, *args, **kwargs):
            if operation == "describe-log-groups":
                return {"logGroups": [{"logGroupName": args[-1], "retentionInDays": 7}]}
            if operation == "get-metric-statistics":
                return {"Datapoints": [{"Timestamp": "2001-09-09T02:00:00Z", "Average": 1, "Sum": 1}]}
            return {"logStreams": [{"logStreamName": cfg["INSTANCE_ID"], "lastIngestionTime": 1_000_000_100_000, "lastEventTimestamp": 1_000_000_100_000}]}
        aws = mock.Mock()
        aws.call.side_effect = response
        delivery.monitoring(aws, cfg, 1_000_000_000)
        operations = {call.args[1] for call in aws.call.call_args_list}
        self.assertNotIn("get-log-events", operations)

    def test_changed_retention_fails_without_modifying_it(self):
        aws = mock.Mock()
        aws.call.return_value = {"logGroups": [{"logGroupName": "/aws/portfolio-lab/nginx/access", "retentionInDays": 30}]}
        with self.assertRaisesRegex(delivery.Rejected, "seven-day"):
            delivery.monitoring(aws, delivery.config(environment()), 1_000_000_000)
        aws.call.assert_called_once()


class PrivateRelease(unittest.TestCase):
    def test_approved_seven_file_bundle_and_document_are_reused(self):
        data = delivery.release()
        self.assertTrue(data["document_name"].startswith("portfolio-lab-deploy-server-"))
        self.assertLess(len(data["bundle"]), 16 * 1024)

    def test_mismatched_operator_document_hash_rejected_before_staging(self):
        with mock.patch.object(delivery, "release", return_value={"document_content": "synthetic"}), self.assertRaisesRegex(delivery.Rejected, "approved document hash"):
            delivery.prepare(delivery.config(environment()), environment())

    def deployment_case(self, verification_error=None):
        parent = ROOT / ".local/tests"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            root = Path(temporary)
            env = environment()
            env["GITHUB_ENV"] = str(root / "runner.env")
            env["GITHUB_STEP_SUMMARY"] = str(root / "summary.md")
            env["GITHUB_EVENT_PATH"] = str(root / "event.json")
            Path(env["GITHUB_EVENT_PATH"]).write_text(json.dumps(event()))
            (root / "website").mkdir()
            (root / "website/index.html").write_text("synthetic homepage\n")
            data = {"bundle": "synthetic-bundle", "document_name": "synthetic-document", "document_content": "synthetic"}
            import hashlib
            cfg = delivery.config(env)
            cfg["SSM_DOCUMENT_SHA256"] = hashlib.sha256(data["document_content"].encode()).hexdigest()
            with mock.patch.object(delivery, "ROOT", root), mock.patch.object(delivery, "release", return_value=data), mock.patch.object(delivery, "target", return_value="synthetic-address"), mock.patch.object(delivery, "document"), mock.patch.object(delivery, "http"), mock.patch.object(delivery, "authorize"), mock.patch.object(delivery, "poll"), mock.patch.object(delivery, "monitoring") as monitoring, mock.patch("builtins.print"):
                delivery.prepare(cfg, env)
                env.update(dict(line.split("=", 1) for line in Path(env["GITHUB_ENV"]).read_text().splitlines()))
                aws = mock.Mock()
                aws.call.return_value = {"Command": {"CommandId": COMMAND, "DocumentName": data["document_name"], "DocumentVersion": "1", "InstanceIds": [cfg["INSTANCE_ID"]]}}
                monitoring.side_effect = verification_error
                if verification_error is None:
                    delivery.deploy(cfg, env, mock.Mock(), aws)
                else:
                    with self.assertRaises(type(verification_error)):
                        delivery.deploy(cfg, env, mock.Mock(), aws)
                    self.assertTrue((Path(env["CD_STAGE"]) / "accepted.json").exists())
                payload = json.loads((Path(env["CD_STAGE"]) / "command.json").read_text())
                self.assertEqual(payload["DocumentVersion"], "1")
                self.assertEqual(payload["DocumentHash"], cfg["SSM_DOCUMENT_SHA256"])
                self.assertEqual(payload["InstanceIds"], [cfg["INSTANCE_ID"]])
                self.assertEqual(set(payload["Parameters"]), {"Bundle", "OperationId"})
                with self.assertRaises(FileExistsError):
                    delivery.deploy(cfg, env, mock.Mock(), aws)
                aws.call.assert_called_once()

    def test_orchestrator_submits_once_with_exact_version_hash_and_files(self):
        self.deployment_case()

    def test_no_redeployment_after_telemetry_verification_failure(self):
        self.deployment_case(delivery.Rejected("Fresh telemetry not observed"))

    def test_no_redeployment_after_verification_credential_expiration(self):
        self.deployment_case(delivery.CredentialsExpired("Temporary credentials expired"))


if __name__ == "__main__":
    unittest.main()
