# AWS Cloud Infrastructure, Security & Automation

An AWS engineering project covering infrastructure adoption, Linux configuration
automation, restricted application delivery, and operational verification. An
existing EC2 web server and its supporting infrastructure were brought under
Terraform without recreating resources. A verified GitHub Actions pipeline used
short-lived OIDC credentials and a restricted Systems Manager executor to deliver
an explicitly approved release.

**Current operating mode: CI only.** Both delivery workflows are disabled at the
repository level. The dedicated role denies federation and its managed policy
denies service permissions for issued sessions. The delivery implementation and
its verified historical results are retained; re-enabling it requires a separate
security review and approved configuration change. This operating mode does not
depend on repository visibility. The lab instance is stopped; availability and
telemetry results below describe completed live tests.

The project manages **33 Terraform resources**. Latest verified hosted CI passed
**121 Python tests plus one mocked Terraform test**, with zero skips. Live
deployment, strict configuration idempotency, website restoration, and
CloudWatch-to-SNS email notification delivery were also verified. Live CloudWatch
Agent restoration recovered monitoring, but did **not** pass complete recovery
verification. The [testing and recovery record](docs/recovery-testing.md) separates
these outcomes from isolated simulations and private offline checks.

## Architecture

![AWS architecture: one EC2 workload across a four-subnet VPC, restricted OIDC and SSM delivery, CloudWatch monitoring and separate Terraform management](docs/diagrams/architecture.svg)

[Open full-size SVG](docs/diagrams/architecture.svg) ·
[Editable draw.io source](docs/diagrams/architecture.drawio) ·
[Diagram scope and editing notes](docs/diagrams/README.md)

The diagram's delivery path describes the implemented architecture, disabled in
the current CI-only operating mode; it does not authorize deployment.

The lab uses `us-east-2` and a custom `10.20.0.0/16` VPC. Two public and two
private subnets span `us-east-2a` and `us-east-2b`. The public route table reaches
the internet through an internet gateway; the private route table has only local
VPC routing. There is no NAT gateway.

One Amazon Linux 2023 `t3.micro` instance in the first public subnet serves a
responsive static Nginx website when running. Its launch configuration explicitly
enables public IPv4 assignment; subnet-level automatic assignment is disabled on
all four subnets. A stopped instance has no current public association. The
second public subnet and both private subnets have no application workloads.
This is a single-instance architecture, with no load balancer or failover tier.

Systems Manager provides administration and command execution without inbound SSH
or a key pair. The CloudWatch Agent sends memory/disk metrics and Nginx logs to
CloudWatch. A four-widget dashboard shows CPU, memory, disk, and network activity.
A CPU alarm sends ALARM notifications through SNS to an externally managed,
confirmed email subscription.

Infrastructure changes and application delivery follow separate paths. Terraform
owns AWS resources; four Bash scripts own the website and selected operating
system configuration. No Terraform provisioners, user-data deployment, or
automatic infrastructure apply is part of the delivery workflow.

## Terraform implementation

The first **27 resources were discovered, defined, and imported** in dependency
order. Refreshed plans verified configuration parity without infrastructure
changes. Six OIDC, IAM, and SSM delivery resources were subsequently provisioned
from a separately reviewed saved plan. A refreshed zero-change plan verified all
33 resources after provisioning.

| Category | Managed instances | Scope |
| --- | ---: | --- |
| Networking | 16 | VPC, four subnets, gateway, two route tables, default route, four associations, security group, two rules |
| Compute and instance identity | 5 | EC2 with inline root EBS settings, role, two policy attachments, instance profile |
| Monitoring and notifications | 6 | Dashboard, CPU alarm, two log groups, SNS topic and separate topic policy |
| Deployment security | 6 | OIDC provider, role, permission policy, attachment, permissions boundary, SSM document |
| **Total** | **33** | Four read-only data sources are counted separately |

The [Terraform reference](terraform/README.md) lists every resource address and
the four data sources. Resource references replace hardcoded infrastructure IDs;
the exact Amazon-owned AMI is resolved by name rather than selecting the latest
image. Stable map keys preserve import addresses. Routes, security-group rules,
and the SNS policy use separate resources without conflicting inline ownership.

Private local state is deliberately excluded from Git. A checkout is not a safe
starting point for applying against the adopted environment without its matching
state and private identity inputs. Provider 6.74.0 also observes the instance's
current public IPv4 association: stopping the instance previously produced a
replacement proposal despite unchanged launch intent. A reviewed lifecycle
exception ignores **only** `associate_public_ip_address` for existing-instance
updates, preserving the explicit `true` launch setting and `prevent_destroy`.
All other attributes remain checked normally. Public-IP drift must be verified
separately; a zero-change plan alone does not prove this setting. See the
[exception and verification procedure](terraform/README.md#public-ipv4-lifecycle-exception).

## Security controls and boundaries

- The instance requires IMDSv2, uses encrypted 8 GiB gp3 root storage with the
  AWS-managed EBS KMS key, and has termination protection. Terraform
  `prevent_destroy` protects the VPC, instance, and selected delivery resources
  while their definitions remain present.
- The web security group permits public HTTP only and unrestricted outbound IPv4.
  There is no inbound SSH, HTTPS, or IPv6 rule. Nginx suppresses its version token;
  TLS and additional response-header hardening remain outside the current design.
- The previously verified OIDC trust used eight exact `StringEquals` conditions for the STS audience,
  immutable repository/owner subject, owner/repository/actor IDs, main branch,
  caller workflow name, and reusable executor reference. No wildcard subject or
  permanent AWS access key was used. Publication suspension now replaces that
  allow with an unconditional federation deny and adds a deny-all statement to
  the existing dedicated deployment policy. The permissions boundary is retained.
- Before suspension, the delivery role and its boundary restricted `SendCommand` to one
  instance and one dedicated document. They permitted required verification reads,
  but no arbitrary shell document, IAM editing, EC2 lifecycle changes, Terraform
  state access, or SNS publishing. Some describe/metric reads require wildcard
  resources; the explicit action list and regional restrictions bound that access.
  The current deny-all overrides those retained grants.
- The executor pins all seven release inputs, including non-executable
  configuration. It rejects altered hashes, unsafe paths, links, extra files, and
  oversized bundles. Private staging, server-side locking, durable recovery
  records, and a persistent failure latch constrain execution and recovery.
- Eight Actions secrets supply deployment identifiers and register log masks
  before runner output. Credentials, state, plans, raw logs, recovery copies, and
  personal endpoints stay outside source. The email subscription is not managed
  in Terraform, so its endpoint is absent from state as well as the repository.

The executor runs as root; trusted OS tools, package sources, the instance role,
and repository administrators remain part of the trust boundary. Manual dispatch
is operator authorization, not independent reviewer approval. The design does
not depend on paid private-repository environment approval features. See the
[delivery security model](docs/authenticated-delivery.md) for the full boundary.

## Server automation and delivery

| Script | Responsibility |
| --- | --- |
| `bootstrap.sh` | Check Amazon Linux 2023 prerequisites, install only missing packages, enable required services |
| `deploy-website.sh` | Validate/stage HTML and Nginx hardening, atomically install changes, preserve private backups, support rollback |
| `configure-monitoring.sh` | Validate the Agent contract and generated configuration, activate only when needed, support recovery |
| `verify-server.sh` | Check service health, Nginx syntax, local HTTP, and approved website content |

Live repeat execution preserved content, inodes, mtime/ctime, ownership,
permissions, package versions, service processes/activation timestamps, and
recovery-backup inventory. No unnecessary package transactions, file replacements,
metadata writes, Nginx reloads, or Agent restarts occurred. Temporary staging,
operation records, request logs, and telemetry are expected runtime activity.

CI runs on pushes to `main`, pull requests targeting `main`, and manual dispatch,
using Ubuntu runners and read-only repository permissions. It validates source
hygiene, Bash syntax/ShellCheck, JSON and monitoring contracts, HTML structure,
release integrity, security/recovery tests, and locked Terraform initialization,
formatting, and validation. External actions use full commit SHA pins. CI has no
AWS authentication and performs no infrastructure plan or deployment.

The retained delivery implementation is **manual dispatch only**, and both
workflows are currently disabled. Before OIDC access, its workflow requires
the selected full commit to match the dispatch revision and current main, and
the newest applicable CI attempt for that exact commit to have succeeded. The
reusable executor requests a 30-minute role session, verifies target readiness
and document version/hash, submits one restricted command, and polls within
bounded deadlines. GitHub concurrency and the server lock prevent overlapping
execution. An ambiguous submission or failed verification never triggers an
automatic redeployment.

## Monitoring and verified results

The Agent publishes `mem_used_percent` and root-filesystem `disk_used_percent`
under `AWSPortfolioLab` every 300 seconds. Nginx access/error log groups retain
data for seven days, with retention owned by Terraform. The CPU alarm evaluates
average `AWS/EC2` CPU utilization at `>= 80%` for two consecutive five-minute
periods and treats missing data as missing.

Post-deployment verification uses completed, cutoff-aligned 60-second query
buckets for fresh memory/disk samples. Positive `AWS/Logs:IncomingLogEvents`
with the access group's `LogGroupName` dimension proves fresh group ingestion;
expected streams are checked separately. This does not establish individual
event creation time or per-stream freshness.

| Verification | Result and boundary |
| --- | --- |
| Latest hosted Ubuntu CI | **121 Python tests passed, zero skips:** 88 ordinary tests, 31 isolated recovery cases, two Linux fixture-readiness guards |
| Mocked Terraform test | **One run passed:** seven assertions covering federation/session denial, trust sensitivity, role/boundary preservation, and public-IP launch intent; no AWS apply |
| Historical hosted recovery baseline | **114 passed, zero skips:** 81 ordinary tests, 31 isolated recovery cases, two Linux fixture-readiness guards |
| Private operator-wrapper review | **225 separate offline checks passed:** 170 server, 31 controller, 24 observer checks; not hosted tests or a live recovery pass |
| Authenticated delivery | Complete live OIDC/STS, restricted SSM execution, four zero script exits, HTTP checks, fresh metrics/log ingestion, retention, and identifier masking verified |
| Strict configuration idempotency | Verified on the live server, including unchanged compliant-file ctime and service identities |
| Live website restoration | Controlled HTML comment added, then existing rollback interface restored exact original content and security metadata; expected inode/timestamp changes recorded; no unnecessary service reload/restart |
| Live Agent restoration | Monitoring recovered and subsequent health/telemetry checks passed; complete restoration verification remained incomplete and is closed with limitations |
| Alarm-to-email notification | One labelled simulated `SetAlarmState` transition recorded a successful SNS action; operator confirmed the matching email; alarm returned naturally to evaluated OK |

The [latest verified CI run](https://github.com/BirdIsOffline/aws-cloud-infrastructure/actions/runs/45759551505)
records these 121 Python tests and the mocked Terraform test for commit
`f6a5976faaabb401aa06f056b9c06d74b2d3b156`. Historical test counts remain separate.

Isolated recovery cases exercise unchanged production code with disposable Linux
files, command substitutes, and chroot/network/PID/mount isolation. They cover
failure handling, automatic rollback, latch enforcement, real POSIX contention,
interruptions, timeouts, and duplicate-submission prevention. These simulations
do not replace live service testing. The alarm test used no CPU load or direct
SNS publish; a genuine CPU threshold breach was **not** tested.

## Technology stack and repository

| Layer | Technology |
| --- | --- |
| Infrastructure | Terraform 1.17.2, HashiCorp AWS provider 6.74.0, AWS CLI v2 |
| AWS services | VPC, EC2/EBS, IAM/OIDC, Systems Manager, CloudWatch, SNS |
| Server | Amazon Linux 2023 x86_64, Nginx, systemd, CloudWatch Agent |
| Automation | Bash, Python 3 standard library, Git |
| Delivery and checks | GitHub Actions Ubuntu runners, ShellCheck, actionlint, Gitleaks |
| Website | Static HTML with inline responsive CSS; no application build dependencies |

| Path | Contents |
| --- | --- |
| `terraform/` | Infrastructure definitions, provider lock, resource inventory and adoption notes |
| `.github/workflows/` | CI, manual delivery caller, reusable deployment executor |
| `scripts/` | Four server automation scripts |
| `scripts/ci/`, `scripts/cd/`, `scripts/ssm/` | Shared validation, delivery orchestration, bundle validation and pinned executor |
| `config/nginx/`, `config/cloudwatch/`, `config/ssm/` | Server configuration, approved release contract and document template |
| `tests/` | Security, delivery, telemetry, and isolated Linux recovery tests |
| `website/` | Hash-pinned homepage |
| `docs/` | Server baseline, operational runbooks, security model and testing record |

Read the [server baseline](docs/server-configuration.md) for file destinations,
permissions and monitoring contracts; the [CI guide](docs/ci-cd.md) for validation
and action pins; and the [testing record](docs/recovery-testing.md) for evidence
and recovery limitations. The deployment runbooks describe procedures, not
authorization to execute them.

## Validation and deployment prerequisites

With Bash, Python 3, Git, ShellCheck, and Terraform 1.17.2 available:

```bash
bash scripts/ci/validate.sh
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=terraform validate
```

The complete recovery suite requires Linux namespace/chroot support and the
privileges described in the [recovery guide](docs/recovery-testing.md). Windows
checks cannot substitute for those Linux cases. Provider initialization downloads
public packages but requires no AWS credentials. Static validation does not prove
live parity, permissions, or service health.

Live deployment additionally requires the provisioned trust/policy/document,
eight verified Actions secrets, an allowed operator, a running SSM-online instance
with ENV_VAR-capable SSM Agent, a healthy approved server baseline, and successful
CI for the exact current main commit. New release bytes require separate approval
of their pinned hashes and executor revision. See the
[manual delivery runbook](docs/manual-deployment.md); the
[server runbook](docs/deployment-runbook.md) covers separately authorized operator
deployment and rollback.

## Cost and operational limitations

Compute runtime, retained EBS storage, public IPv4 usage, CloudWatch logs/metrics,
dashboard/alarm usage, and notifications are cost drivers. No NAT gateway, load
balancer, or artifact-storage service is added. Seven-day log retention limits log
growth; private on-instance backups need their own retention review. No claim of
zero cost or Free Tier coverage is made. Stopping compute does not remove retained
storage costs and requires separate lifecycle approval.

This lab has no TLS endpoint, multi-instance availability, off-instance recovery
backup, remote Terraform backend, or demonstrated disaster recovery from total
instance loss. Root-volume delete-on-termination remains enabled. Existing broad
instance managed policies, outbound access, and the adopted SNS policy were
preserved; further least-privilege, transport, and encryption changes need review.
Deployment cancellation/interruption and failed automatic recovery were simulated
in isolation rather than exercised on the instance. Agent recovery verification is
closed without a complete live pass; no RTO/RPO guarantee follows from these tests.

The hash-pinned homepage retains wording from its earlier approved release,
including the then-planned CI/CD status; these documents describe current verified
capabilities. Updating that deployed content requires the release-review process.
Historical Actions logs were privacy-reviewed; exposed logs were removed while
their run records, clean logs, and successful results were preserved. Recheck newly
generated logs before any repository visibility change. Private reports and recovery
evidence are intentionally not published.
