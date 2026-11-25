"""Offline regression cases for telemetry freshness, deadlines and log hygiene."""

from datetime import datetime, timezone
import json
import subprocess
import unittest
from unittest import mock

from test_cd_delivery import Clock, delivery, environment

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


def point(offset, **statistics):
    return {"Timestamp": datetime.fromtimestamp(BASE + offset, timezone.utc).isoformat(), **statistics}


class Metrics:
    def __init__(self, gauge=None, ingestion=None):
        self.gauge = [point(240, Average=25)] if gauge is None else gauge
        self.ingestion = [point(240, Sum=3)] if ingestion is None else ingestion
        self.calls = []

    def call(self, service, operation, *arguments, **kwargs):
        options = dict(zip(arguments[::2], arguments[1::2]))
        self.calls.append((service, operation, options, kwargs))
        if operation == "describe-log-groups":
            return {"logGroups": [{"logGroupName": options["--log-group-name-prefix"], "retentionInDays": 7}]}
        if operation == "describe-log-streams":
            # Deliberately stale and malformed metadata: neither field proves freshness.
            return {"logStreams": [{"logStreamName": options["--log-stream-name-prefix"],
                                     "lastEventTimestamp": "stale", "lastIngestionTime": 0}]}
        if operation == "get-metric-statistics":
            points = self.ingestion if options["--namespace"] == "AWS/Logs" else self.gauge
            return {"Datapoints": points}
        raise AssertionError("Unexpected API; regression tests permit reads only")


class Freshness(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cfg = delivery.config(environment())

    def verify(self, api, since=26, current=360, probe=None):
        return delivery.monitoring(api, self.cfg, BASE + since, self.clock.read, self.clock.sleep,
                                   wall=lambda: BASE + current + self.clock.now, probe=probe)

    def test_fresh_sample_uses_minute_bucket_not_older_five_minute_bucket(self):
        # Completion at :00:26; a :04 sample must not be returned in a :00 bucket.
        api = Metrics()
        self.verify(api)
        for service, operation, options, kwargs in api.calls:
            if operation == "get-metric-statistics":
                self.assertEqual(options["--period"], "60")
                self.assertEqual(delivery.timestamp(options["--start-time"]), BASE + 60)
                self.assertEqual(delivery.timestamp(options["--end-time"]), BASE + 360)
                self.assertLessEqual(kwargs["deadline"], delivery.MONITOR_SECONDS)
                if options["--namespace"] == "AWS/Logs":
                    self.assertEqual(options["--metric-name"], "IncomingLogEvents")
                    self.assertEqual(options["--statistics"], "Sum")
                    self.assertEqual(json.loads(options["--dimensions"]),
                                     [{"Name": "LogGroupName", "Value": "/aws/portfolio-lab/nginx/access"}])

    def test_old_and_overlapping_buckets_cannot_satisfy_cutoff(self):
        api = Metrics(gauge=[point(-60, Average=10), point(0, Average=20)])
        with mock.patch.object(delivery, "MONITOR_SECONDS", 31), self.assertRaises(delivery.Rejected):
            self.verify(api)
        self.assertEqual(self.clock.now, 31)

    def test_positive_zero_negative_and_missing_ingestion(self):
        for data in ([], [point(240, Sum=0)], [point(240, Sum=-1)], [point(240)], [point(0, Sum=100)]):
            self.clock = Clock()
            with self.subTest(data=data), mock.patch.object(delivery, "MONITOR_SECONDS", 31), self.assertRaises(delivery.Rejected):
                self.verify(Metrics(ingestion=data))
        self.verify(Metrics(ingestion=[point(240, Sum=1)]))

    def test_stale_stream_metadata_does_not_block_fresh_group_ingestion(self):
        self.verify(Metrics())

    def test_fresh_stream_metadata_cannot_replace_group_ingestion(self):
        api = Metrics(ingestion=[])
        original = api.call
        def read(service, operation, *args, **kwargs):
            value = original(service, operation, *args, **kwargs)
            for stream in value.get("logStreams", []):
                stream.update(lastEventTimestamp=int((BASE + 300) * 1000), lastIngestionTime=int((BASE + 300) * 1000))
            return value
        with mock.patch.object(api, "call", side_effect=read), mock.patch.object(delivery, "MONITOR_SECONDS", 20), self.assertRaises(delivery.Rejected):
            self.verify(api)

    def test_future_open_minute_missing_and_nonfinite_statistics_rejected(self):
        for sample in (point(360, Average=1), point(420, Average=1), point(240),
                       point(240, Average=float("nan")), point(240, Average=float("inf")), point(240, Average=True)):
            with self.subTest(sample=sample):
                self.assertFalse(delivery.fresh_points([sample], BASE + 60, BASE + 360, "Average"))
        self.assertTrue(delivery.fresh_points([point(60, Average=0)], BASE + 60, BASE + 360, "Average"))

    def test_exact_minute_cutoff_accepts_that_complete_minute(self):
        self.verify(Metrics(gauge=[point(60, Average=1)], ingestion=[point(60, Sum=1)]), since=60)

    def test_health_probe_waits_until_safe_cutoff_and_runs_once(self):
        api = Metrics(gauge=[point(60, Average=1)], ingestion=[point(60, Sum=1)])
        observed = []
        self.verify(api, current=26, probe=lambda: observed.append(BASE + 26 + self.clock.now))
        self.assertEqual(observed, [BASE + 60])
        self.assertTrue(all(operation != "send-command" for _, operation, _, _ in api.calls))

    def test_missing_stream_and_changed_retention_fail_closed(self):
        for operation in ("describe-log-streams", "describe-log-groups"):
            api = Metrics()
            original = api.call
            def read(service, name, *args, **kwargs):
                value = original(service, name, *args, **kwargs)
                if name == operation:
                    if operation == "describe-log-streams":
                        value["logStreams"] = []
                    else:
                        value["logGroups"][0]["retentionInDays"] = 30
                return value
            with self.subTest(operation=operation), mock.patch.object(api, "call", side_effect=read), self.assertRaises(delivery.Rejected):
                self.verify(api)

    def test_monitoring_expired_credentials_stop_without_retry_or_submission(self):
        api = Metrics()
        original = api.call
        def read(service, operation, *args, **kwargs):
            if operation == "get-metric-statistics":
                raise delivery.CredentialsExpired("Temporary credentials expired")
            return original(service, operation, *args, **kwargs)
        with mock.patch.object(api, "call", side_effect=read) as calls, self.assertRaises(delivery.CredentialsExpired):
            self.verify(api)
        self.assertEqual(sum(c.args[1] == "get-metric-statistics" for c in calls.call_args_list), 1)
        self.assertTrue(all(c.args[1] != "send-command" for c in calls.call_args_list))


class CredentialBudgets(unittest.TestCase):
    def test_no_aws_request_after_global_expiry(self):
        aws = delivery.AWS(deadline=10, clock=lambda: 10)
        with mock.patch.object(delivery.subprocess, "run") as run, self.assertRaises(delivery.CredentialsExpired):
            aws.call("logs", "describe-log-groups")
        run.assert_not_called()

    def test_expired_token_response_is_not_retried_or_exposed(self):
        aws = delivery.AWS()
        response = mock.Mock(returncode=1, stderr=b"(ExpiredToken) sensitive diagnostic content")
        with mock.patch.object(delivery.subprocess, "run", return_value=response) as run:
            with self.assertRaises(delivery.CredentialsExpired) as caught:
                aws.call("cloudwatch", "get-metric-statistics")
            run.assert_called_once()
        self.assertNotIn("sensitive diagnostic content", str(caught.exception))
        self.assertFalse(aws.submitted)

    def test_call_timeout_is_capped_by_phase_and_credential_deadlines(self):
        aws = delivery.AWS(deadline=12, clock=lambda: 10)
        response = mock.Mock(returncode=0, stdout=b"{}")
        with mock.patch.object(delivery.subprocess, "run", return_value=response) as run:
            aws.call("cloudwatch", "get-metric-statistics", deadline=11)
        self.assertEqual(run.call_args.kwargs["timeout"], 1)
        self.assertEqual(run.call_args.kwargs["env"]["AWS_MAX_ATTEMPTS"], "1")

    def test_insufficient_full_deployment_budget_rejected_before_send(self):
        required = delivery.POLL_SECONDS + delivery.MONITOR_SECONDS + delivery.DEPLOYMENT_RESERVE
        aws = delivery.AWS(deadline=required - 1, clock=lambda: 0)
        with self.assertRaises(delivery.Rejected):
            aws.require_deployment_budget()
        self.assertFalse(aws.submitted)
        self.assertLess(required, delivery.SESSION_SECONDS - delivery.SESSION_MARGIN)

    def test_read_timeout_does_not_reauthenticate(self):
        with mock.patch.object(delivery.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic", 1)) as run:
            with self.assertRaises(delivery.Rejected):
                delivery.AWS().call("logs", "describe-log-groups")
            run.assert_called_once()


class Logging(unittest.TestCase):
    def test_derived_account_and_actor_values_registered_for_masking(self):
        cfg = delivery.config(environment())
        with mock.patch("builtins.print") as output:
            delivery.mask_configuration(cfg)
        masked = {call.args[0] for call in output.call_args_list}
        self.assertIn("::add-mask::" + cfg["account"], masked)
        self.assertIn("::add-mask::" + cfg["ROLE_UNIQUE_ID"], masked)
        self.assertIn("::add-mask::303", masked)
        self.assertNotIn("::add-mask::" + cfg["COMMIT"], masked)


if __name__ == "__main__":
    unittest.main()
