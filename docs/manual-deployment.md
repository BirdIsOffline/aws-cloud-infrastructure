# Manual GitHub Actions delivery

These instructions describe the implemented workflow, which is currently disabled.
The instance is stopped and deployment access is denied. They are not instructions
to re-enable it. Review the [delivery design](authenticated-delivery.md) and
[testing limits](recovery-testing.md) before any future operating decision.

## Authorization and setup

The caller is `.github/workflows/deploy-server.yml` (**Deploy lab server**); the
reusable workflow is `deploy-server-executor.yml`. Dispatch accepts an exact
40-character commit SHA. It must equal the dispatch revision and current main.
The latest applicable CI attempt for that exact commit must have succeeded;
missing, outdated, cancelled, failed or pending results reject deployment. Re-runs
are rejected. Authorization completes before the OIDC-enabled job.

The public repository currently fails the retained private-repository check.
Reactivation would need reviewed trust, policy, document, allowlist and workflow
changes, not just enabling the workflow. Main protection and zero-reviewer solo
maintenance do not provide independent deployment approval.

The existing configuration uses these repository Actions secrets, passed explicitly
between workflows without `secrets: inherit`:

| Secret | Purpose |
| --- | --- |
| `CD_GITHUB_OWNER_ID` | Expected immutable owner |
| `CD_GITHUB_REPOSITORY_ID` | Expected immutable repository |
| `CD_ALLOWED_ACTOR_IDS` | JSON array of one to five allowed numeric-string actor IDs |
| `CD_ROLE_ARN` | Dedicated deployment role |
| `CD_ROLE_UNIQUE_ID` | RoleId for identity checking and early masking |
| `CD_INSTANCE_ID` | Existing workload |
| `CD_VPC_ID` | Existing custom VPC |
| `CD_SSM_DOCUMENT_SHA256` | Verified AWS document hash for version 1 |

Cross-check inputs privately against the intended resources before upload. Secret
values cannot be read back through the API. No permanent AWS key or variable fallback
is used. Masking must precede runner output: late script masking cannot hide step
headers. Account IDs, role unique IDs and other derived values are masked too.
Never log tokens, API responses or command payloads.

## Submission and polling

Preparation builds only the seven pinned inputs from the selected commit in private
0700 runner directories with 0600 input files. It compares the local document hash
with the configured AWS hash. No payload is uploaded as a workflow artifact.

Before submission, verify the assumed role/unique identity, custom VPC, named running
instance, public IPv4, SSM Online status and supported Agent. DescribeDocument must
show the expected owner/type, Active state, and original/default/latest version 1.
HTTP availability must pass. Authorization and available time are checked again.

Exactly one SendCommand specifies the existing instance, dedicated document,
version 1, SHA-256, unique run-based operation ID, concurrency one, zero tolerated
errors and a 120-second delivery timeout. Receipts record submission before the
request and acceptance afterward. The helper never automatically resubmits.

SSM polling is bounded to 1,050 seconds; a missing invocation is tolerated only
for the first 30 seconds. Success must match the exact command, instance, document
and plugin, with four script exits of zero and expected local HTTP results.
Unknown, failed, cancelled or timed-out execution requires inspection.

## HTTP and telemetry verification

After command success, round completion up to a whole minute and make HTTP probes
in that window: homepage 200 with exact approved content, former backup URL 404.
The following checks share an eight-minute observation budget:

- Memory/disk use Average and 60-second query periods. The Agent still collects
  every 300 seconds. Only finite datapoints in completed buckets after the cutoff
  qualify; historical, overlapping, incomplete and future buckets do not.
- Access-group ingestion needs positive Sum from `AWS/Logs` `IncomingLogEvents`,
  with the exact `LogGroupName` dimension, in the same window.
- Both instance log streams must exist and both groups retain seven days.

Group ingestion can contain buffered older events or multiple streams. It does
not establish individual-stream freshness or event creation time. Eventually
consistent stream timestamps are not freshness evidence. An idle error stream is
valid; no visitor logs or synthetic errors are retrieved/generated.

## Failure handling

The workflow timeout is 35 minutes and credentials last 30 minutes. Deadlines begin
before authentication, reserve a 90-second margin and require 1,590 seconds before
submission for polling, telemetry and reserve. Each AWS call is also bounded.
Expiration stops verification without alternate credentials or a replay.

GitHub concurrency uses `cancel-in-progress: false`; it is not a durable FIFO queue.
The server lock and latch remain necessary. Cancellation or a lost response does
not prove the remote command stopped. Inspect receipts, SSM status, child processes,
lock, latch and backups using separately authorized operator access. A monitoring
failure after a successful deployment calls for read-only investigation, not a new
deployment. Clear the latch only after verified recovery. The
[server runbook](deployment-runbook.md) describes the rollback interfaces.
