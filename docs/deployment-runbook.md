# Server deployment runbook

The current operating mode is CI only: the instance is stopped and GitHub
delivery is disabled, independently of repository visibility. These retained
operator procedures require separate authorization; they do not reactivate
federation or authorize an instance start.

The [isolated recovery harness](recovery-testing.md) exercises failure and rollback
paths with disposable Linux files and command substitutes. It never connects to
the server. Passing those simulations alone does not establish live recovery.
The [testing record](recovery-testing.md) documents completed live outcomes and
the closed Agent-verification limitations. The commands below are operational
procedures and require separate authorization before use.

Controlled deployment and strict configuration idempotency testing are complete.
The corrected scripts preserved content, metadata, packages, services, and backup
inventory during the verified repeat run. Live website restoration and the
simulated alarm-to-email test passed; live Agent recovery did not complete full
verification despite restored monitoring health. Deployment, package transactions,
configuration activation, and rollback require approval before executing them
against the lab server.

## Preconditions

1. Verify the intended lab instance and its custom VPC using the established
   `aws-lab` profile in `us-east-2`; confirm SSM is Online. Never embed its identifier
   or public address in a script, command example, output capture, or repository file.
2. Review the complete bundle and arrange a separately approved transfer through
   the existing SSM workflow. Do not place AWS credentials or Git credentials on
   the server. The EC2 role supplies Agent access.
3. Place the reviewed bundle in a root-controlled directory, for example
   `/opt/aws-portfolio-lab`. Keep `scripts`, `website`, and `config` together.
4. Confirm the current server baseline, sufficient disk space, working AWS network
   access, expected Agent fragment, and existing Terraform-owned log groups.
   Confirm the relocated legacy backup remains outside the public document root
   and that its former URL returns HTTP 404.
5. Shell scripts must have LF endings. Invoke them with Bash; executable Git mode
   is not required. No package upgrade, reboot, EC2 lifecycle operation, or Terraform
   command is part of deployment.
6. Run one deployment at a time. Do not run another provisioning tool against the
   same files during deployment or rollback; these scripts do not provide a
   cross-process deployment lock. The restricted SSM executor supplies that lock;
   separately authorized operator work must acquire the same lock and check the
   persistent failure latch before using these scripts. Check command/child
   status as well as lock availability after interrupted execution.

All following examples run **on the Linux server only after approval**:

```bash
cd /opt/aws-portfolio-lab
sudo bash scripts/bootstrap.sh --check
sudo bash scripts/deploy-website.sh --check
sudo bash scripts/configure-monitoring.sh --check
```

`bootstrap --check` reports missing packages and exits without installing or
enabling anything. The other check modes create private temporary staging files
and validate candidates but do not install live files, reload, or activate services.
They require the relevant packages to be installed. Failed monitoring validation
retains a private staging directory for diagnosis; successful checks clean it up.

## Controlled deployment sequence

1. Run bootstrap's prerequisite check. If packages are missing, review them and
   obtain approval for the required package transaction before continuing.
2. Run `sudo bash scripts/bootstrap.sh`. It installs only missing required packages
   and enables Nginx/Agent at boot. It does not start services without configuration.
3. Run both configuration check modes. Website validation checks HTML, the security
   drop-in in an isolated HTTP context, and the current full Nginx configuration.
   It cannot prove integration until the candidate is installed and re-tested.
4. Run `sudo bash scripts/deploy-website.sh`. It backs up changed managed files,
   atomically installs candidates with root:root/0644, tests the full Nginx config,
   reloads only if the drop-in changed (or starts inactive Nginx), and compares the
   HTTP response with the candidate bytes. Static-only changes do not reload Nginx.
5. Run `sudo bash scripts/configure-monitoring.sh`. It checks the JSON contract,
   translates into private staged TOML, runs the Agent schema test, backs up the
   existing source, and activates only changed configuration or an unhealthy Agent.
   Activation can restart the Agent and briefly interrupt telemetry.
6. Run `sudo bash scripts/verify-server.sh`. Expect exit 0. It requires the updated
   portfolio wording, so it can fail against the old site before deployment.
7. After separate approval, repeat the deployment commands with unchanged inputs.
   Compare checksums, inodes, mtime/ctime, numeric ownership, permissions, package
   versions, service process identities and activation timestamps, and backup
   inventory before and after. Expect no package transaction, file replacement,
   metadata write on compliant targets, new recovery backup, Nginx reload, or Agent
   restart. Verify monitoring against the Agent's active cached configuration:
   fetch-config can consume its temporary input JSON. Distinguish private staging
   files, HTTP access entries, and fresh telemetry from configuration changes.
8. Separately approve read-only AWS checks for expected metric dimensions, intervals,
   and log delivery. Active service checks alone do not prove successful AWS ingestion.
   Do not generate load, force alarm transitions, or publish test notifications.
9. Test website rollback and monitoring rollback in an approved maintenance window,
   verify the previous state, and re-deploy the reviewed desired files. Review the
   resulting diff and any telemetry gap. Do not treat syntax checks as a rollback test.

## Website rollback

On a changed deployment, the script prints its root-owned, mode-0700 backup
directory beneath `/var/backups/aws-portfolio-lab/website`. It records existing
homepage/security files and absence markers for a previously absent drop-in.

```bash
sudo bash scripts/deploy-website.sh --rollback "$WEBSITE_BACKUP_DIRECTORY"
```

Set that variable to the directory printed by the approved deployment, not an
untrusted path. The script accepts only root-controlled backups under its own
backup root, stages/validates them, and saves the current files before rollback.
It verifies that HTTP serves the restored homepage. The older homepage may have
older wording; the updated-content verification script can correctly fail afterward.
Rollback cannot reconstruct a previous missing homepage and refuses that case.

If a normal deployment fails after changes begin, it automatically restores saved
managed files, rechecks Nginx, and restores the prior active/inactive service state.
If rollback itself fails, exit 41 requires manual review of the private backup;
do not delete the backup or retry blindly. Legacy default pages/assets are untouched.

## Monitoring rollback

```bash
sudo bash scripts/configure-monitoring.sh --rollback "$MONITORING_BACKUP_DIRECTORY"
```

Use the root-owned backup directory printed by the approved activation. The backup
contains the original source privately and a rollback candidate without Agent-owned
retention. The rollback follows the same validation/activation path and preserves
the current source in a new backup. Unknown additional Agent fragments cause a
preflight refusal; never bypass it without reviewing multi-config replacement.

Activation failures automatically attempt to restore the previous telemetry source.
Legacy retention fields are intentionally not reactivated. If there was no previous
configuration, recovery stops the Agent and removes only this script's new source
and cached fragment. Previously inactive Agent service state is restored. Private
activation/rollback logs remain in the backup directory, never in the repository.

The proposed corrected release verifies that both source/cache paths are absent
after no-predecessor cleanup; failed removal or leftover paths return exit 41.
For a predecessor configuration it requires semantic equality of the restored
cache and any surviving source with the retention-free backup. Agent consumption
of the source is allowed. A previously active Agent must be active and report
running/configured; a previously inactive Agent must return to inactive. Only
verified rollback returns exit 40. This correction is local and has not been
deployed or live-tested; see the [release revision](authenticated-delivery.md#proposed-monitoring-rollback-release).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Requested operation or check succeeded |
| 1 | Unexpected command failure; read the diagnostic before retrying |
| 2 | Invalid arguments |
| 3 | Root/platform/path/configuration ownership prerequisite failed |
| 5 | Required dependency missing; includes bootstrap check mode |
| 10 / 11 | Verification: Nginx / Agent inactive |
| 12 | Verification: required service not enabled at boot |
| 20 | Explicit candidate/schema validation failure; Nginx verification syntax failure |
| 21 | Verification: Agent not running/configured |
| 30 / 31 | Verification: HTTP failure / unexpected portfolio content |
| 40 | Activation failed and automatic rollback completed |
| 41 | Automatic rollback failed; manual recovery needed |

Some external validation commands can return their own nonzero status before a
transaction begins. No script performs a blanket upgrade or destructive cleanup.
Backups need a separately reviewed retention policy and may consume disk over time.

## Local versus Linux validation

Local validation covers Bash parsing, help-only execution, JSON parsing and the
monitoring contract, homepage structure/content, source hygiene, LF endings, and
Terraform file integrity. Git Bash on Windows is not Amazon Linux: it cannot
validate systemd, Nginx or Agent binaries, RPM/DNF behavior, AWS ingestion, Linux
ownership/atomic filesystem operations, or real rollback. Controlled Linux tests
verified deployment and strict idempotency. Recovery outcomes are maintained in
the [testing record](recovery-testing.md), rather than inferred from these checks.
ShellCheck is mandatory in the CI entry point; it is a development dependency,
not a required package on the deployment target.
