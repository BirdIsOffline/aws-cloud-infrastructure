# Server configuration

This is the tested running baseline. The instance is now stopped; package and
health observations below are historical. Terraform owns AWS resources, while
server scripts manage the files listed here.

## Baseline and files

| Component | Tested configuration |
| --- | --- |
| System | Amazon Linux 2023.12.20261120, x86_64 |
| Nginx | 1.30.7, active and enabled; root master and nginx workers |
| CloudWatch Agent | 1.300073.2, running/configured and enabled; root |
| Document root | `/usr/share/nginx/html`, root:root 0755 |
| Homepage | `website/index.html` → document-root `index.html`, root:root 0644 |
| Hardening | `config/nginx/security.conf` → `/etc/nginx/conf.d/security.conf`, root:root 0644 |
| Agent source | `config/cloudwatch/amazon-cloudwatch-agent.json` → `/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json`, root:root 0644 |
| Logs | `/var/log/nginx/access.log` and `/var/log/nginx/error.log` |

The package-owned Nginx configuration listens on port 80, uses server name `_`,
and includes `conf.d/*.conf`. The managed drop-in sets `server_tokens off;`.
Scripts leave the main configuration, default assets, log ownership and rotation
alone. TLS and additional response headers are not configured.

The homepage is static HTML with inline responsive CSS and no external assets or
build tools. Its earlier “CI/CD integration is planned” text is retained because
the website is a hash-pinned release snapshot. Current project status belongs in
the README; changing website content requires new release pins.

## Monitoring contract

The Agent uses region `us-east-2`, namespace `AWSPortfolioLab` and a 300-second
collection interval, globally and for both metric collectors:

- Memory: `mem_used_percent`.
- Disk: `used_percent`, resource `/`, with `drop_device: true`.
- Appended dimension: `InstanceId` from `${aws:InstanceId}`.
- Access/error logs: `/aws/portfolio-lab/nginx/access` and
  `/aws/portfolio-lab/nginx/error`, with stream name `{instance_id}`.

Terraform controls seven-day retention. Agent JSON omits `retention_in_days`.
Rollback saves the original configuration privately but removes legacy retention
fields from the activation candidate. It does not call retention APIs.

Native `fetch-config` can consume its source JSON. Active cached JSON is therefore
the reference for verification; generated TOML/YAML and other Agent files are not
repository inputs. Activation may regenerate files or change timestamps without
changing configuration meaning. That differs from a healthy no-op deployment,
which should not activate the Agent at all. Unexpected additional fragments are
rejected because fetch-config can replace the configuration set.

## Dependencies and ownership

Scripts require root, Bash, systemd, Python 3, Nginx, curl, GNU coreutils,
`cmp`/diffutils and the Agent. Bootstrap installs only missing required packages
from configured AL2023 repositories; it does not upgrade everything or replace a
working curl. Fresh installations are not exact package-version reproductions.
Package repositories and AWS endpoints must be reachable when needed.

Managed targets must be regular files rather than symlinks. Ownership/mode writes
occur only when needed. Recovery directories under
`/var/backups/aws-portfolio-lab/{website,monitoring}` are root-owned 0700. Backups,
validation logs and raw access logs stay private; access logs include visitor
addresses and request information.

The former public `index.html.backup` was relocated intact to private storage.
Its old URL returned 404. Scripts create no new backups beneath the document root.

Use the [deployment runbook](deployment-runbook.md) for commands and rollback.
The [testing record](recovery-testing.md) distinguishes tested idempotency and
website restoration from incomplete live Agent recovery verification. The newer
rollback correction is tested in CI but remains undeployed.
