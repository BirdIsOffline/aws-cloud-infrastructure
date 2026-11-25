# Restricted authenticated delivery infrastructure

## Status and trust model

Six Terraform security resources were separately provisioned from the approved
saved plan and verified live. State now retains 33 managed resources and four data
sources, with a refreshed zero-change plan. The first published manual run proved
OIDC, restricted SSM execution and server idempotency, but its telemetry gate failed.
Freshness and secret-masking corrections are implemented and the eight repository
secrets are configured; a separately approved controlled live retest remains pending.
The [manual delivery runbook](manual-deployment.md) covers workflow
authorization, required variables and remaining live tests. Terraform 1.17.2 and
the locked AWS provider 6.74.0 remain unchanged.

| Resource address | Purpose |
| --- | --- |
| `aws_iam_openid_connect_provider.github` | GitHub issuer and STS audience |
| `aws_iam_role.github_deploy` | Dedicated federated deployment identity |
| `aws_iam_policy.github_deploy` | Instance/document-scoped delivery permission |
| `aws_iam_role_policy_attachment.github_deploy` | Attach the delivery policy |
| `aws_iam_policy.github_deploy_boundary` | Explicit API action and target ceiling |
| `aws_ssm_document.deploy_server` | Content-addressed, pinned deployment executor |

Read-only discovery found no pre-existing IAM OIDC provider; the approved apply
created the dedicated issuer. Do not create a duplicate or silently take ownership
of a provider used elsewhere. The existing EC2 role, instance, networking,
monitoring, and their protections are unchanged.

## External identity configuration

Supply the required `github_deployment_identity` object through private operator
configuration: `TF_VAR_github_deployment_identity` or an ignored variable file.
The object contains numeric-string `owner_id`, `repository_id`, and a nonempty
set of one to five explicitly approved `actor_ids`. There are no real IDs or
permissive defaults in source. The variable is sensitive to redact Terraform UI
output; resulting trust-policy values will still exist in private Terraform state.

The trust policy uses `StringEquals` for all of:

- Audience `sts.amazonaws.com`.
- The exact immutable-ID subject for this repository's `main` branch.
- Immutable `repository_owner_id`, `repository_id`, and allowed `actor_id` values.
- `ref` equal to `refs/heads/main`.
- Caller workflow name `Deploy lab server`.
- `job_workflow_ref` equal to the future reusable executor workflow path
  `BirdIsOffline/aws-cloud-infrastructure/.github/workflows/deploy-server-executor.yml@refs/heads/main`.

Subject IDs are assembled from the external inputs. No wildcard subject,
`StringEqualsIfExists`, or legacy subject fallback is accepted. Missing claims
fail closed. AWS now officially supports the extra GitHub keys above. Its
documented GitHub key mapping does not list standalone `workflow_ref`; the
implementation uses the supported `job_workflow_ref` instead. That claim requires
a reusable workflow: a standalone CD job will intentionally fail this trust policy.
The workflow-name claim adds a check but is mutable and is not a substitute for
immutable IDs or the executor workflow reference.

No environment claim is required. The design works without private environment
reviewer gates or a paid plan upgrade. Main access and dispatch authorization
remain security-critical: private branch protections cannot be assumed on Free,
and a manual dispatch is not independent two-person approval. Actor restrictions
also require careful treatment of re-runs: the future workflow must check the
initiating/re-running actor instead of assuming a re-run represents fresh approval.

The role maximum session is one hour; the future authentication step should request
a 30-minute session and use full-SHA action pins. Only the deployment job should
receive `id-token: write`. Validate the actual required claims during an approved
authentication test without logging JWTs. This step did not request any token.

## Permissions and boundary review

`SendCommand` requires permission for both the dedicated document ARN and existing
instance ARN. Separate statements apply the existing instance Name-tag condition
only to the instance. IAM permissions reference existing Terraform resources;
account-specific ARN values are not embedded in source.

The role can inspect the document, target identity/readiness, command invocation,
metrics, retention, and stream metadata in `us-east-2`. It cannot list command
history or retrieve visitor log events. Necessary describe/poll/metric APIs have
wildcard resources because not all support resource-level restrictions; their
regional action list is explicit. `DescribeLogStreams` is scoped to the two lab
log groups. The instance must be verified running and SSM-online by future CD;
this role cannot start it.

The boundary independently denies actions outside the fixed API ceiling, sending
commands to other instances/documents, and regional operations outside the lab
region. Its allows retain exact resources and conditions. It grants no extra
permissions. There is no permission to modify IAM, pass/assume roles, edit or
share documents, access state/secrets, publish SNS messages, start sessions, or
change EC2/network resources. No `AWS-RunShellScript` permission is granted.

Only the separate infrastructure operator may change trust, policies, boundary,
or executor. The boundary does not sandbox root or restrict the existing EC2
instance role: trusted OS binaries, package repositories, system services, and
root-controlled host configuration remain part of the trusted computing base.
The account's SCPs, IAM effective evaluation, service validation, and real token
exchange have not been tested by local Terraform validation.

## Bundle authorization and provenance

`config/ssm/approved-release.json` pins the size, SHA-256, and staging mode of all
seven approved files: four scripts, Nginx hardening, Agent JSON, and homepage.
The three non-executable inputs are pinned too: they cannot redirect privileged
configuration processing or log collection through caller-selected content.

The local packer verifies each source against both those hashes and the local
immutable Git HEAD blob. It rejects symlinks/hardlinks and emits a deterministic
JSON envelope compressed once with gzip/base64. No archive extraction, download
URL, shell-command, or caller-selected path is supported. Output is permitted only
under ignored `.local` storage and is created exclusively.

The envelope records its immutable source commit. On the server that value is
an audit label with strict syntax, not proof of CI success. All actual bytes are
authorized by the independent pinned hashes; changing a commit label cannot
authorize different bytes. `approved_from_commit` records the revision used to
review the initial pins, not a self-referential requirement that a manifest contain
its own Git commit hash. Future CD must independently verify successful CI for
the exact source commit, its main-branch provenance, and matching executor pins
before acquiring credentials. No GitHub token is transferred to EC2.

```bash
python3 -B scripts/ssm/bundle.py
python3 -B -m unittest discover -s tests -p 'test_ssm_executor.py'
```

The packer checks, rather than silently accepting, a source/contract mismatch.
To generate parameter data later, an operator may use its `--output` argument
with a fresh file under `.local`. OperationId must be supplied separately from the
future workflow run/attempt identifier. Do not print the payload in Actions logs.

## Document and execution limits

The schema-2.2 document accepts only `Bundle` and `OperationId` using `ENV_VAR`.
There is no unsafe direct parameter substitution in shell code. Absence of the
interpolated variables, an SSM Agent below 3.3.2746.0, unsupported OS, or unexpected
inputs aborts before deployment. There is no fallback to legacy substitution.

Limits are fixed in the immutable contract:

- Encoded bundle: at most 16 KiB; uncompressed envelope: at most 48 KiB.
- Each source file: at most 16 KiB, with its exact reviewed size and digest.
- One gzip stream; truncated streams, concatenated streams, trailing bytes,
  decompression bombs, duplicate JSON keys/paths, extra fields and link/device
  declarations are rejected.
- The rendered document plus the maximum encoded parameter and 1 KiB overhead
  must fit a conservative 60 KiB budget, below the 64 KiB document quota. This
  check runs locally and is a Terraform precondition. It is not a claim that
  AWS has accepted a live SendCommand request; that remains a rollout check.
- The SSM plugin timeout is 900 seconds. Subprocesses share a 600-second initial
  budget; recovery gets up to 180 seconds, leaving headroom. OS hangs or hard
  termination can still require manual recovery.

Future CD must set a short SendCommand delivery timeout (120 seconds), target one
explicit instance, and refuse stopped/offline targets. That delivery timeout is
separate from plugin execution time. Already accepted commands can outlive their
submitting job/session; revoking trust or cancelling GitHub does not by itself
prove a queued/running command has stopped. Pending-command cancellation and
emergency recovery stay with the separately authorized infrastructure operator.

## Preflight, deployment, and recovery

The executor requires root and creates a fresh private stage. It verifies
root ownership, exact 0700 directories/scripts and 0600 inputs, regular file types,
single links, checksums and Bash syntax. A root-owned server-side flock prevents
two cooperating executors running together. Every OperationId gets an exclusive
durable record: failed/completed IDs are never silently replayed.
Before live execution, a durable recovery-required latch is created. Only verified
success removes it. A failed or abruptly interrupted deployment blocks subsequent
operations until an independently authorized operator has reviewed recovery and
explicitly cleared the latch; a new OperationId cannot bypass that protection.

Preflight requires installed prerequisites, active/enabled services, working HTTP,
valid Nginx and Agent configuration, and an approved baseline. CD does not install
missing packages: the pinned bootstrap's `--check` must pass first. Existing
hardening and active cached telemetry must match the reviewed contract; unexpected
drift requires operator review. Only explicitly approved homepage predecessor
hashes may be replaced. The canonical Agent input may be absent because the
Agent consumes it; active cached JSON is authoritative.

Unrelated system directories are inspected, not chmodded. Owned private directory
hierarchies are created with missing parents handled explicitly and unsafe existing
ownership/modes/links rejected. Standard system parents such as `/var/backups`
must already exist and be secure; the executor does not create or repair unrelated
system directories. When configuration changes are necessary, fsynced
private coordinator backups are verified before any deployment script executes.
No coordinator recovery backups are created for a compliant no-op run. Private
staging/operation records are normal runtime activity and have a separate purpose.

The fixed order is bootstrap, website deployment, monitoring configuration, server
verification. Postchecks require active/enabled services, healthy Agent, exact local
HTTP content, HTTP 404 for the former backup URL, matching cached configuration,
correct managed-file metadata, and an unchanged package-owned main Nginx config.
Public HTTP, fresh AWS telemetry and seven-day retention remain mandatory checks
for the future orchestrator using the read-only permissions provided here.

On failure after deployment starts, the coordinator attempts monitoring then website
recovery through the pinned rollback interfaces, restores the original presence of
the consumed Agent input, and verifies baseline HTTP/configuration/service health.
The scripts retain their own recovery behavior. A failed recovery is recorded for
the operator; no automatic second deployment is attempted. No package transaction
or EC2 lifecycle action is part of recovery. Private records contain stage and
backup locations; public SSM output contains only a sanitized success/failure summary.
Timed-out subprocess groups are terminated, but their quiescence must be reviewed
by an operator before rollback; automatic recovery is deliberately skipped in that
ambiguous case. Ordinary completed-command failures retain coordinated recovery.

A global SSM timeout or abrupt process termination may interrupt recovery. GitHub
job cancellation does not prove the remote command stopped. Never blindly re-run:
inspect command status and the private operation record first. Root operators and
other tools must respect the server lock. Staging/backup retention needs a separate
review; this executor does not recursively delete diagnostic or recovery data.

## Executor revision and rollout procedure

The SSM document name includes a hash of its complete rendered content: code,
template, limits and all approved inputs. Any change produces a different name
and ARN. Only that ARN is permitted by the identity policy and boundary. Use
the `portfolio-lab-deploy-server` prefix; custom document names cannot begin with
AWS-reserved prefixes such as `aws`, `amazon`, or `amzn`. The logical Terraform
resource address is unchanged. Use
document version 1 and the exact document hash when sending commands. IAM cannot
enforce a SendCommand document version through an Automation-only condition key;
do not create unreviewed versions under an authorized document name.

1. Review any new source/configuration and predecessor baseline. Recompute hashes
   from reviewed bytes; never copy arbitrary caller-supplied digests into the contract.
2. Run local validation/tests and review the complete content-addressed document.
3. Separately approve an infrastructure plan. Initial intended changes are exactly
   six additions with no changes to the existing 27 resources. The stopped-instance
   public-IP observation can still trigger the previously documented EC2 parity
   caveat: report it, preserve prevent_destroy, and do not start/replace the instance
   or edit state to force a clean plan.
4. Before first apply, supply private identity inputs, confirm issuer ownership,
   and review all IAM and SSM changes. No apply is authorized by this document.
5. For a later executor replacement, prevent_destroy intentionally blocks replacing
   the resource at the same address. Use a separately reviewed parallel versioned
   resource/address and policy cutover, then separately authorize retirement of the
   old version. Do not weaken guards to bypass the review.
6. The exact manual caller/reusable pair is now implemented locally. Publish and
   test it only with separate approval. The required job_workflow_ref claim cannot
   be tested from a standalone job. This caller deploys after its gates; a separate
   reviewed non-deploying path is required for an authentication-only live test.
   Separately approve formal recovery tests and instance readiness before command
   execution. Keep the constant GitHub concurrency group with cancel-in-progress
   disabled, in addition to the server lock.

Local tests prove decoder/input behavior, not live IAM enforcement, SSM service
acceptance, Linux service activation, delivery, or rollback. POSIX ownership/link
tests cannot execute on native Windows and are reported as skipped there. Existing
infrastructure definitions and state remain unchanged during workflow implementation.

References: [AWS GitHub condition keys](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_iam-condition-keys.html),
[GitHub immutable subjects](https://docs.github.com/en/actions/reference/security/oidc),
[SSM parameter interpolation](https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-troubleshooting.html),
[SSM document quota](https://docs.aws.amazon.com/general/latest/gr/ssm.html),
[SSM permissions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ssm.html).
