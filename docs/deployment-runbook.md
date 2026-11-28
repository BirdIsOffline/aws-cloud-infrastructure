# Server deployment and recovery

Use this runbook only for separately authorized work on the existing Linux server.
Current operation is CI only: EC2 is stopped and CD is disabled. The repository's
new monitoring rollback correction has passed CI but is not deployed; identify
which release is on the server before choosing recovery tools.

## Before running scripts

1. Verify the instance and custom VPC with scoped queries using external profile
   `aws-lab` in `us-east-2`. Confirm EC2 health, SSM Online and the expected release.
2. Confirm no active deployment command or recovery latch. Acquire the existing
   `/var/lib/aws-portfolio-deploy/deployment.lock` for the entire operation. Operator
   work must use the same lock as CD; the standalone scripts do not lock themselves.
   Lock availability alone does not prove interrupted child processes stopped.
3. Verify service health, disk space, managed-file fingerprints and metadata,
   package/service identities, backup inventory and current Agent cache. Preserve
   that baseline privately before making changes.
4. Transfer only reviewed files into a root-controlled directory such as
   `/opt/aws-portfolio-lab`, keeping `scripts`, `config` and `website` together.
   Check hashes, LF endings, regular file types and permissions. Do not transfer
   AWS/Git credentials; the instance role supplies Agent permissions.
5. Verify private recovery copies outside the document root and the expected
   Terraform-owned log groups. Confirm the former backup URL is inaccessible.

Do not use these scripts to change IAM, networking, instance lifecycle or Terraform
state. Missing packages, unrelated configuration drift or unknown Agent fragments
need investigation before deployment.

## Validate and deploy

On the server, under the checks and lock above:

```bash
cd /opt/aws-portfolio-lab
sudo bash scripts/bootstrap.sh --check
sudo bash scripts/deploy-website.sh --check
sudo bash scripts/configure-monitoring.sh --check
```

Bootstrap check mode reports missing dependencies without installation or service
enablement. The other checks use private staging and test candidates without
installing live files. Failed Agent validation retains private diagnostics.

For an authorized deployment, run in order:

```bash
sudo bash scripts/bootstrap.sh
sudo bash scripts/deploy-website.sh
sudo bash scripts/configure-monitoring.sh
sudo bash scripts/verify-server.sh
```

Bootstrap installs only missing packages and enables services; it does not run a
blanket upgrade. Website deployment stages HTML and the hardening drop-in, checks
Nginx, backs up changed files and atomically installs root:root 0644 targets.
Static-only changes need no reload; a changed drop-in reloads active Nginx, and
an inactive service is started. The HTTP response must match the candidate bytes.

Monitoring validates JSON, staged translation and Agent schema before activation.
It synchronizes a consumed source without restarting a healthy matching cache.
A changed configuration or unhealthy Agent may require activation and a short
telemetry gap. Retention remains Terraform-owned. Verification checks both
services, Nginx syntax, HTTP and expected homepage content.

Afterward verify public HTTP 200 with approved content, backup URL 404, active and
enabled services, and AWS delivery using the [telemetry criteria](manual-deployment.md#http-and-telemetry-verification).
A running service alone does not prove ingestion.

## Rollback

Use only a verified root-owned 0700 backup directory printed by the deployment:

```bash
sudo bash scripts/deploy-website.sh --rollback "$WEBSITE_BACKUP_DIRECTORY"
sudo bash scripts/configure-monitoring.sh --rollback "$MONITORING_BACKUP_DIRECTORY"
```

Website rollback stages/validates the saved files, backs up current files, restores
content or the recorded absent hardening drop-in, tests Nginx and checks served
bytes. A missing predecessor homepage cannot be reconstructed. An older homepage
may legitimately fail the new-content wording check in `verify-server.sh`.

Monitoring backups retain the original JSON and a retention-free rollback
candidate. Agent source consumption is legitimate; validate the active cache.
The corrected repository script requires matching restored semantics and the prior
service state. With no predecessor, both new source/cache paths must be absent.
Failed removal, incomplete restoration, mismatched configuration or incorrect
service state returns 41. Only verified automatic rollback returns 40. Those new
checks are not a completed live recovery result.

## Failures and repeat-run checks

| Exit | Meaning |
| --- | --- |
| 0 | Requested operation/check succeeded |
| 1 | Unexpected command failure; inspect diagnostics |
| 2 / 3 / 5 | Invalid arguments / unsafe prerequisite or path / missing dependency |
| 10 / 11 / 12 | Verification: Nginx inactive / Agent inactive / service not enabled |
| 20 / 21 | Candidate or Nginx validation failed / Agent not running and configured |
| 30 / 31 | HTTP failure / unexpected content |
| 40 / 41 | Activation failed, rollback completed / rollback failed, operator recovery needed |

Preserve diagnostics and backups on failure; do not retry blindly or clear the
latch to bypass it. For a separately authorized no-op repeat, compare content,
inodes, mtime/ctime, ownership/modes, packages, service processes/activation times
and backups. Expect no unnecessary persistent writes, restart, reload or backup.
Temporary staging, request logs and metric activity are normal. Recovery copies
need a retention policy and cannot replace an off-instance backup.
