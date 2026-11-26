# Manual GitHub Actions delivery

## Suspension for CI-only publication

Both delivery workflows are disabled at repository level, and AWS denies new
federation and service permissions for the dedicated deployment role's sessions.
CI remains enabled. Do not dispatch or re-run delivery. The procedures below
document the retained implementation and its historical verification; they are
not a reactivation procedure. A future public-delivery design and any restoration
of permissions require separate approval and regression testing.

## Implementation status

The caller, reusable executor, and local synthetic tests are implemented. The six
OIDC/IAM/SSM security resources were separately provisioned and verified, bringing
Terraform to 33 managed resources and four data sources with a post-provisioning
zero-change plan before the publication suspension.
The corrected controlled live deployment passed exact-commit authorization,
OIDC/STS, one restricted SSM execution, four zero script exits, strict idempotency,
HTTP, fresh telemetry, retention and runtime masking checks. The earlier run's
telemetry-verification failure remains recorded. Hosted CI subsequently passed
114 tests with zero skips, including isolated recovery. See the
[testing record](recovery-testing.md) for live website restoration, confirmed
simulated alarm-to-email delivery and the closed Agent-verification limitations.

## Authorization and execution

`.github/workflows/deploy-server.yml` is named **Deploy lab server**, exactly as
required by the former deployment trust policy. Its only trigger is `workflow_dispatch` and its
only input is a full lowercase 40-character `commit` SHA. Select the `main` branch
and the exact current main revision when dispatching. No branch/tag shorthand is
accepted as the commit input.

The first job has only `contents: read` and `actions: read`. It verifies:

- GitHub-hosted execution on the expected GitHub host and private original repository.
- Immutable repository/owner IDs, the approved actor ID, event sender, caller name
  and workflow path. Re-runs, including re-runs by the original actor, are rejected.
- The input commit equals the dispatch's `github.sha`, event input, local checkout,
  and current remote `main` commit.
- The expected active `CI` workflow's newest applicable run for this exact SHA and
  `main` has completed successfully. Only push/manual CI events qualify. It queries
  all statuses rather than searching for any historical success, then reads the
  newest run's current attempt. Missing, failed, cancelled, queued, in-progress,
  skipped, stale and superseded-attempt results fail closed. More than 100 matching
  runs or incomplete API results require operator review rather than guessing.

Only that job's success permits calling
`.github/workflows/deploy-server-executor.yml`. The local reusable-workflow
reference resolves at the caller's immutable commit; it is not an external action
using a floating version. No environment is attached, preserving the branch-based
OIDC subject. The reusable job repeats the gate and prepares the bundle before
the credential action. It repeats authorization again immediately before sending
the command. GitHub refs and SSM submission cannot be one atomic transaction;
main can advance after the final check. The transferred bytes remain the exact
selected commit and independently pinned release even in that race.

The caller uses the constant concurrency group `lab-server-deployment` with
`cancel-in-progress: false`. Do not add the same group to the called workflow:
that can deadlock or cancel its own caller. GitHub permits one running and one
pending run in this group; a newer dispatch can replace a pending run. This is not
a durable FIFO queue. The root executor also retains its server lock and durable
recovery latch, including when GitHub cancellation releases its concurrency slot.

## Repository configuration

Deployment configuration has been migrated to repository-level **Actions secrets**
under **Settings > Secrets and variables > Actions > Secrets**. All eight secret
names were verified after encrypted upload, and the seven superseded variables
were removed after compatibility checks. Secret values cannot be read back through
the API; upload inputs were cross-checked with approved private/live values first.
Real values remain outside source and documentation. No permanent AWS keys or
variable fallback are used; reusable secrets are passed explicitly, without
`secrets: inherit`.

| Repository secret | Required value |
| --- | --- |
| `CD_GITHUB_OWNER_ID` | Reviewed immutable owner ID from the historical deployment contract |
| `CD_GITHUB_REPOSITORY_ID` | Reviewed immutable repository ID from that contract |
| `CD_ALLOWED_ACTOR_IDS` | JSON array of numeric strings; exactly the approved actor list, one to five entries |
| `CD_ROLE_ARN` | Provisioned `aws-lab-github-deploy-role` ARN |
| `CD_ROLE_UNIQUE_ID` | Existing role's `RoleId`, available as private Terraform `unique_id` or through an approved operator GetRole query |
| `CD_INSTANCE_ID` | Existing lab web instance ID |
| `CD_VPC_ID` | Existing custom lab VPC ID |
| `CD_SSM_DOCUMENT_SHA256` | Operator-verified AWS `DescribeDocument` SHA-256 for the approved version 1 |

The document name is derived from the complete pinned executor content. Its
version is fixed at `1`; neither arbitrary document names nor commands are workflow
inputs. The configured AWS hash must also equal the locally rendered document hash.

The verified deployment setup used repository Actions with the pinned official
`actions/checkout` and `aws-actions/configure-aws-credentials` actions. During
CI-only publication, leave both delivery workflows disabled. Keep default workflow token
permissions read-only; explicit job permissions grant only the needed reads and
OIDC permission. No write token, PAT, GitHub environment, AWS key, SSH key, OIDC
subject customization, or paid environment reviewer feature is required.

Restrict repository write/admin access, secret changes, and manual dispatch
authority. Use protected branches/rulesets and independent reviews where the
repository plan supports them; do not assume those protections exist for a Free
private repository. A dispatch by an allowed actor is manual deployment
authorization, **not independent reviewer approval**. An actor allowlist and CI
cannot compensate for a malicious trusted main writer or repository administrator.

## Trust and least privilege

Before suspension, the workflow matched these eight approved `StringEquals`
conditions. The current live trust is deny-only:

| Claim | Workflow behavior |
| --- | --- |
| `aud` | Credential action requests `sts.amazonaws.com` explicitly |
| `sub` | Immutable owner/repository subject, branch `refs/heads/main`, no environment |
| `repository_owner_id` | Actual immutable owner; checked against operator configuration |
| `repository_id` | Actual immutable repository; checked against operator configuration |
| `actor_id` | Exact approved initiating actor; re-runs rejected |
| `ref` | Dispatch and current revision restricted to `refs/heads/main` |
| `workflow` | Caller name `Deploy lab server` |
| `job_workflow_ref` | `BirdIsOffline/aws-cloud-infrastructure/.github/workflows/deploy-server-executor.yml@refs/heads/main` |

The reusable workflow inherits caller context for ordinary claims; its own path
supplies `job_workflow_ref`. Only the reusable caller job and actual executor job
have `id-token: write`; the authorization job and CI do not. Credentials last
1,800 seconds, are restricted to the expected account, and are checked with
`GetCallerIdentity` against the exact role/session without logging the response.
Credential action output credentials are disabled, account masking is enabled,
and no AWS profile is written. Automatic STS retries and CLI request retries are
disabled; no SendCommand retry is allowed.

The existing role cannot read the document body, instance logs, credentials or
Terraform state, edit IAM/documents, start/stop EC2, or invoke AWS-RunShellScript.
The helper uses the existing DescribeDocument permission for identity, ownership,
type, version, status and AWS hash checks. Root execution remains limited by the
separate pinned server-side executor; the boundary does not sandbox root or the
existing EC2 instance role.

## Bundle, execution and verification

`scripts/cd/delivery.py` reuses `scripts/ssm/bundle.py` and the existing bounded
decoder rather than inventing a second release format. Only the four approved
scripts, Nginx hardening, Agent JSON, and homepage are bundled. All seven contents
must match the selected Git commit and operator-approved sizes/hashes/modes.
The existing 16 KiB encoded bundle and conservative 60 KiB combined budget remain
enforced. The executor/contract/document and server scripts are unchanged.

Preparation uses a fresh private runner directory under ignored `.local/cd/`:
0700 directories, 0600 regular input files, exclusive creation, link/path checks,
and no uploaded workflow artifacts. The deployment step rebuilds and compares the
bundle before use. No GitHub token, AWS credentials, inventory, URL or arbitrary
shell command is transferred to EC2.

Before submitting, the helper verifies the assumed identity, custom VPC identity,
running named instance, existing public IPv4 association, SSM Online status, and
Agent version at least 3.3.2746.0. DescribeDocument must show the derived name,
correct owner/type, Active status, and original/default/latest version 1 with the
approved SHA-256. An ordinary public HTTP availability check must pass.

Exactly one SendCommand targets the existing instance and dedicated document with
version `1`, `DocumentHashType: Sha256`, its approved hash, delivery timeout 120
seconds, concurrency one, and zero tolerated errors. OperationId includes the
GitHub run/attempt; the SSM comment also records the immutable commit. No other
deployment document is permitted. Private local receipts record submission and
acceptance; they are never published as artifacts.

Polling is read-only, with a 1,050-second budget including request timeouts.
InvocationDoesNotExist is tolerated for the first 30 seconds only.
Failure, cancellation, unknown status, unavailable polling, or a deadline stops
the job without resubmitting or trying an independent rollback. The fixed plugin
timeout remains 900 seconds. A valid success must identify the exact command,
instance, document/version/plugin and report all four scripts at exit 0, local
HTTP 200 and former-backup HTTP 404.

After server success, round the freshness cutoff **up** to the next whole minute
(preserve an already exact minute). Wait for that boundary, then make one health
probe for the exact approved public homepage (HTTP 200) and former backup URL
(HTTP 404). This produces access traffic in the eligible window. Alignment waiting,
HTTP, retention/stream reads, metric queries and polling share a 480-second budget.

Memory/disk queries use `Average` and 60-second periods; the Agent still collects
every 300 seconds. StartTime is the safe cutoff and EndTime is rounded down to a
completed minute. Only finite statistics in `[cutoff, EndTime)` qualify. Historical,
overlapping, incomplete and future buckets are rejected. This avoids comparing
five-minute bucket starts against a completion timestamp within that bucket.

Fresh access-log **group ingestion** requires positive `Sum` datapoints from
`AWS/Logs` / `IncomingLogEvents`, dimension `LogGroupName` equal to the access group,
in the same safe window. Zero, missing, negative and historical points do not pass.
This proves uploads into the group, which can include multiple streams or buffered
older events; it does not prove individual-stream freshness or event creation time.
Both expected instance streams must separately exist and both groups retain seven
days. Neither `lastEventTimestamp` nor `lastIngestionTime` is used for freshness:
these metadata fields are eventually consistent. Existing disk dimensions are
preserved. An idle error stream is valid. No raw visitor logs, synthetic errors,
alarm-state changes or notifications are used.

## Failure handling and operator recovery

Job timeout remains 35 minutes; the credential session remains 30 minutes. A
conservative deadline starts during preparation, before authentication, with a
90-second safety margin. Before sending, require 1,050 seconds for SSM polling,
480 for monitoring and 60 reserve (1,590 total); otherwise nothing is submitted.
Every AWS subprocess is bounded by its phase and credential deadlines, at most
30 seconds per call. Expiry stops verification without reauthentication, alternate
credentials or replay. SDK retries remain disabled. A monitoring/HTTP failure after a
successful command is not permission to redeploy. Inspect the successful command
and repeat only separately authorized read-only verification.

SSM SendCommand has no client idempotency token. A lost submission response can
mean the command was accepted. The helper marks submission before making the
request, never retries it, and never automatically cancels. An operator can use
the GitHub run/attempt and SSM comment to inspect commands with separate operator
permissions if the runner/receipt is unavailable. Do not enable debug tracing or
upload private receipts, payloads, SSM output or recovery files.

GitHub cancellation or credential expiry does not prove that a command stopped.
The root executor coordinates ordinary failure recovery and keeps its persistent
failure latch. A timeout or hard termination requires operator checks for active
children, server lock, operation record, backups and baseline service health.
Only a separately authorized operator may clear the latch after verified recovery.
Do not re-run the job or create a fresh dispatch as a workaround for a failed run.
Isolated Linux tests cover failure, timeout, latch and recovery branches. Their
success does not establish live interruption/cancellation recovery. Live website
restoration passed; complete Agent restoration verification did not. Future
operator recovery requires separate approval and the safeguards above.

## Release revision procedure

1. Review changes to any of the seven deployment inputs. A successful new CI run
   does not authorize new executable/configuration bytes by itself.
2. Obtain separate operator approval of exact hashes, sizes, modes and any allowed
   predecessor homepage hash in `config/ssm/approved-release.json`.
3. Review/validate the rendered executor. A contract, template or executor change
   creates a new content-addressed document name. The existing prevent_destroy
   guard requires the separately reviewed parallel-document/policy cutover
   procedure in [the security model](authenticated-delivery.md); do not bypass it.
4. Separately plan, approve and provision infrastructure changes, then verify live
   document/policies and update the approved repository document hash if needed.
   No CD job runs Terraform or provisions infrastructure.
5. Publish the reviewed release/workflow changes only after separate approval;
   require CI success for the resulting exact current main commit. Select that SHA
   in a new authorized manual dispatch. Documentation/workflow-only changes can
   keep the same seven-file release pins if the deployed contents are unchanged.

This workflow has no authentication-only/dry-run dispatch mode: dispatch proceeds
to SendCommand after all gates pass. An authentication-only live test therefore
requires a separately reviewed non-deploying path before any dispatch. Do not use
an intentional failure or revoked permission as a substitute for that path.

## Local checks and live verification boundaries

Run `bash scripts/ci/validate.sh` and `actionlint` from the project root. The CI
entry point discovers both executor and delivery test suites. Synthetic tests cover
authorization/CI denials, input/document validation, stale telemetry, private
staging, single submission, eventual consistency, terminal failures and polling
deadlines. Existing bundle tests exercise altered files, traversal, links, malformed
compression and size limits. No test assumes a role or executes an SSM command.

The corrected live run verified OIDC/STS, restricted SSM, all four scripts, server
idempotency, HTTP, aligned telemetry checks and secret-based masking. The current
hosted suite passed all 114 tests without skips. The 225 private operator-wrapper
checks are separate offline evidence. Live cancellation, timeout and failed
automatic-recovery scenarios were not deliberately exercised; they remain
limitations, not implied passing results. No additional live test is authorized
by this runbook.

## Logging migration and previous exposure

Runner step headers can print environment values before a script starts, so Python
`add-mask` calls cannot retroactively protect repository-variable values. All eight
inputs now use Actions secrets, registered for masking before runner logging, and
are scoped to the steps that need them. Checkout receives no deployment secrets.
The helper also masks derived account IDs and scalar actor IDs before exporting
derived environment values, and validates STS UserId against `CD_ROLE_UNIQUE_ID`.

The pinned AWS action logs the assumed-role unique ID. `mask-aws-account-id` alone
does not cover it; supplying the existing RoleId as an Actions secret masks that
substring before the action logs it. No IAM GetRole permission is added to CD:
the separately authorized operator supplies the value. These identifiers are not
authentication credentials; secrets are used here for log privacy. Trusted code
and privileged repository administrators can still access the inputs. Never enable
token dumps or log raw API responses, payloads or credentials.

The eight secrets were created from verified private/live values; their names were
confirmed before removing the obsolete variables. Future input changes require
separate operator approval. Require successful CI for the exact current main commit
and separate deployment approval before dispatch. An incomplete configuration fails
closed before OIDC, without falling back to variables.

Keep the repository private while reviewing the old deployment run logs, downloaded
copies and artifacts. Preserve needed audit evidence privately with redactions;
separately authorize deletion of affected GitHub run logs/artifacts before public
publication. New secret masks do not redact old logs. Exposed resource identifiers
alone do not warrant infrastructure replacement or access-key rotation. The first
run's AWS credential fields were masked. No historical runs, logs or artifacts were
deleted during the approved secret migration and publication.

References for the correction: [CloudWatch query periods and rounding](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricStatistics.html),
[IncomingLogEvents](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CloudWatch-Logs-Monitoring-CloudWatch-Metrics.html),
[GitHub secrets and masking](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets),
[pinned action's role ID logging](https://github.com/aws-actions/configure-aws-credentials/blob/e1253824e5c10ff9df46874f81ed3ec929e19cfd/src/index.ts#L261).

Action pins were checked against official public release refs: checkout v6.1.0
and configure-aws-credentials v6.3.0. Review future action revisions separately.

References: [reusable workflow OIDC claims](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows),
[GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc),
[workflow-run API](https://docs.github.com/en/rest/actions/workflow-runs),
[credential action inputs](https://github.com/aws-actions/configure-aws-credentials/blob/e1253824e5c10ff9df46874f81ed3ec929e19cfd/action.yml).
