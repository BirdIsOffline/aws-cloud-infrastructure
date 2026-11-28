# Authenticated delivery design

The project demonstrated manual GitHub Actions delivery using OIDC and a restricted
SSM document. It is now CI only: both CD workflows are disabled and published IAM
configuration denies federation and deployment-session permissions. The retained
helper also requires a private original repository, so making the repository public
did not silently enable deployment. [Manual delivery](manual-deployment.md) covers
inputs and execution; this document explains the security boundaries.

## Identity and permissions

The original trust used eight exact `StringEquals` conditions: STS audience,
immutable repository/owner subject, `repository_owner_id`, `repository_id`, allowed
`actor_id`, main `ref`, caller `workflow` name and reusable `job_workflow_ref`.
There were no wildcard subjects or missing-claim fallbacks.

Private Terraform configuration supplies numeric-string `owner_id`, `repository_id`
and one to five allowed `actor_ids` through `github_deployment_identity`. Sensitive
classification hides presentation, not contents of state or saved plans.

Historically, the deployment role and independent permissions boundary limited
SendCommand to the existing instance and one document. Describe/poll/metric APIs
had an explicit regional action list; stream reads were scoped to two log groups.
There was no arbitrary AWS-RunShellScript, IAM editing, state access, SNS publishing,
EC2 lifecycle or visitor-log read permission. A boundary limits IAM permissions;
it does not sandbox root or the existing EC2 role.

The reusable executor requested 30-minute credentials, checked role identity and
received OIDC permission only where needed. Exact-commit and actor checks ran
before authentication and again before submission.

## Pinned inputs and executor

`config/ssm/approved-release.json` authorizes seven files: four Bash scripts,
Nginx hardening, Agent JSON and homepage. Every file has an exact hash, size and
staging mode. Configuration is pinned because it can influence privileged behavior.

The packer compares those bytes with immutable Git HEAD blobs and creates one
consistently formatted gzip/base64 JSON envelope. The server independently checks contents;
its commit label records the source revision, not proof of CI. `approved_from_commit`
records review ancestry, not the manifest's own future commit.

```bash
python3 -B scripts/ssm/bundle.py
python3 -B -m unittest discover -s tests -p 'test_ssm_executor.py'
```

Only `Bundle` and `OperationId` are document parameters. Schema 2.2 uses safe
`ENV_VAR` interpolation and requires SSM Agent 3.3.2746.0 or newer. Missing support
fails closed. Paths, links/devices, duplicate JSON members, extra files, malformed
or concatenated gzip streams and hash/mode mismatches are rejected.

Limits are 16 KiB encoded, 48 KiB decoded and 16 KiB per file. The rendered
document plus maximum parameter data and overhead must fit 60 KiB. The plugin
allows 900 seconds; scripts share an initial 600-second budget, with up to 180
seconds for coordinated recovery.

## Locking and recovery

Fresh root-owned staging uses 0700 directories/scripts and 0600 input files.
Checks cover ownership, regular single-link files, syntax, approved baseline,
installed prerequisites, active/enabled services and HTTP. CD refuses missing
packages rather than installing them. Unexpected Agent fragments or monitoring
drift require operator review. Cached Agent JSON is authoritative when its source
has been consumed.

A server `flock` prevents cooperating deployments from overlapping. Exclusive
operation records prevent replay. A durable recovery-required latch is written
before changes; only verified success clears it. New operation IDs cannot bypass
an existing latch. Changed files receive verified private backups before scripts
run; a compliant no-op run needs no recovery backup.

The fixed order is bootstrap, website, monitoring and server verification. Ordinary
completed-command failures trigger coordinated monitoring/website recovery and
baseline checks. Timeouts terminate the child process group but skip automatic
rollback because child processes may still be running. Interrupted execution retains
records and requires operator inspection. Root operators must respect the same
lock and latch. Trusted system binaries, package repositories and administrators
remain outside the executor's protection boundary.

## Monitoring rollback release

The corrected repository script checks removal results, expected absence, restored
JSON semantics and prior active/inactive service state before returning rollback
success. It allows legitimate source consumption and removes legacy retention
from the recovery candidate. Six other release pins and executor code were unchanged.

This correction passed hosted tests but remains **undeployed**. Historical live
idempotency and delivery results apply to the earlier AWS release. JSON checks do
not establish full generated TOML/YAML or metadata recovery; the
[live Agent limitation](recovery-testing.md#live-agent-restoration) remains open.

## Executor revision and rollout procedure

The document name hashes its full rendered code, template and contract. Changing
any pinned input therefore changes the document name and referenced ARN.

1. Review source, predecessor allowance, hashes, sizes and modes; run tests and the
   production packer against committed bytes.
2. Review a complete refreshed infrastructure plan with the matching private state
   and inputs. Do not recreate the existing six security resources.
3. Use a separately reviewed parallel-document/policy cutover. `prevent_destroy`
   intentionally blocks replacing the current document at the same resource address.
4. Verify the new version-1 document and AWS hash before any separately authorized
   deployment. Retire the old document only after a reviewed transition.

Do not enable CD, restore trust or apply historical plans as a shortcut. IAM cannot
use an Automation-only condition key to enforce Command document versions; the
caller must pin version and hash, and the role must remain unable to edit documents.
The current source revision is not a zero-change infrastructure proposal.
