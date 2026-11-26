# Terraform infrastructure reference

Terraform manages **33 resource instances** in `us-east-2`, with **four data
sources** counted separately. The original 27 networking, compute, identity,
monitoring, and notification resources were imported without recreating them.
Six delivery security resources were subsequently provisioned from a reviewed
saved plan. Refreshed plans verified zero infrastructure changes after adoption
and after provisioning. These are recorded verification results, not a continuous
drift guarantee.

## CI-only publication suspension

The dedicated GitHub deployment role now has a deny-only federation trust, and
its existing managed policy contains an unconditional deny for all actions and
resources. This also removes service permissions from already-issued role
sessions after IAM propagation; credential bytes are not erased and retain their
original expiry. The role, policy attachment, permissions boundary, issuer and
pinned SSM document retain their identities. EC2's service role is unaffected.
Both CD workflows are disabled in GitHub; CI remains active.

The former trust, policy version and source are retained only in protected,
ignored operator evidence. They are not automatic restoration inputs. There is
no enable variable or private-input override that restores deployment access.
Re-enabling deployment requires a separately reviewed source change and approved
infrastructure procedure. Never apply historical saved plans as a restoration
shortcut. The approved, single-attribute public-IP lifecycle exception below
resolves the stopped-instance planning artifact without changing launch intent.
The deny-only trust retains its existing sensitive classification; its policy
bytes are unchanged. A complete, normally refreshed plan with EC2 stopped returned
exit code 0: no resource actions, output changes, or pending data-source reads.
All 33 managed resources and four data sources were preserved without an apply.
This revision includes the suspension configuration and its offline CI assertions.
Do not use older revisions or saved plans to restore access. Check the Actions
results for hosted validation of the exact source revision.

## Resource inventory

Each row counts Terraform-managed instances, including `for_each` instances and
policy attachments. It does not count automatically created service objects,
inline root storage, data sources, or externally managed subscriptions as
additional resources.

### Networking: 16

| Resource address | Count | Responsibility |
| --- | ---: | --- |
| `aws_vpc.lab` | 1 | Custom IPv4 VPC |
| `aws_internet_gateway.lab` | 1 | Public internet attachment |
| `aws_subnet.public["public_1"]`, `aws_subnet.public["public_2"]` | 2 | Public subnets |
| `aws_subnet.private["private_1"]`, `aws_subnet.private["private_2"]` | 2 | Private subnets |
| `aws_route_table.public`, `aws_route_table.private` | 2 | Named public/private route tables |
| `aws_route.public_internet` | 1 | Public default route through the gateway |
| `aws_route_table_association.public["public_1"]`, `aws_route_table_association.public["public_2"]` | 2 | Explicit public associations |
| `aws_route_table_association.private["private_1"]`, `aws_route_table_association.private["private_2"]` | 2 | Explicit private associations |
| `aws_security_group.web` | 1 | Web server security group |
| `aws_vpc_security_group_ingress_rule.web_http` | 1 | Public TCP 80 |
| `aws_vpc_security_group_egress_rule.web_all_ipv4` | 1 | Outbound IPv4 |

### Compute and instance identity: 5

| Resource address | Count | Responsibility |
| --- | ---: | --- |
| `aws_instance.web` | 1 | Existing server, including root EBS settings |
| `aws_iam_role.ec2_ssm` | 1 | EC2 service trust |
| `aws_iam_role_policy_attachment.ssm_core` | 1 | AmazonSSMManagedInstanceCore |
| `aws_iam_role_policy_attachment.cloudwatch_agent` | 1 | CloudWatchAgentServerPolicy |
| `aws_iam_instance_profile.ec2_ssm` | 1 | Instance/role association |

### Monitoring and notifications: 6

| Resource address | Count | Responsibility |
| --- | ---: | --- |
| `aws_cloudwatch_log_group.nginx["access"]`, `aws_cloudwatch_log_group.nginx["error"]` | 2 | Nginx logs and retention |
| `aws_cloudwatch_metric_alarm.high_cpu` | 1 | CPU threshold and SNS ALARM action |
| `aws_cloudwatch_dashboard.infrastructure` | 1 | Four preserved widgets |
| `aws_sns_topic.alerts` | 1 | Standard notification topic |
| `aws_sns_topic_policy.alerts` | 1 | Separate topic policy ownership |

### Deployment security: 6

| Resource address | Count | Responsibility |
| --- | ---: | --- |
| `aws_iam_openid_connect_provider.github` | 1 | GitHub issuer and STS audience |
| `aws_iam_role.github_deploy` | 1 | Deny-only federation during CI-only publication |
| `aws_iam_policy.github_deploy` | 1 | Dedicated delivery policy with unconditional permissions deny |
| `aws_iam_role_policy_attachment.github_deploy` | 1 | Attach delivery permissions |
| `aws_iam_policy.github_deploy_boundary` | 1 | Independent permission ceiling |
| `aws_ssm_document.deploy_server` | 1 | Content-addressed restricted executor |

### Data sources: 4

| Data address | Purpose |
| --- | --- |
| `data.aws_ami.web` | Exact Amazon-owned AL2023 image name, x86_64/HVM/EBS filters; no latest selection |
| `data.aws_kms_key.ebs` | Existing `alias/aws/ebs` key |
| `data.aws_partition.current` | Partition for AWS-managed policy references |
| `data.aws_caller_identity.current` | Runtime account condition in the adopted SNS policy |

## Configuration layout

| File | Contents |
| --- | --- |
| `versions.tf`, `providers.tf`, `variables.tf` | Terraform/provider constraints, external authentication, region and exact AMI name |
| `.terraform.lock.hcl` | AWS provider 6.74.0 and verified Windows/Linux package checksums |
| `vpc.tf`, `subnets.tf`, `routing.tf`, `security-groups.tf` | Network and standalone routes/rules/associations |
| `compute.tf`, `iam.tf` | Server, inline root volume, instance role and profile |
| `cloudwatch.tf`, `sns.tf` | Dashboard, alarm, log groups, topic and separate policy |
| `cd_iam.tf`, `cd_ssm.tf`, `cd_variables.tf` | Federated delivery security, pinned document and private identity inputs |
| `tests/deployment_suspension.tftest.hcl` | Fully mocked, offline assertions for federation/session denial and preserved EC2 role access |
| `outputs.tf` | Resource references for operator use; values can contain private identifiers |

The configuration accepts Terraform `>= 1.17.2, < 2.0.0` and AWS provider `~> 6.0`;
CI uses **Terraform 1.17.2** and the committed lock selects **AWS 6.74.0**. Use
read-only lock initialization to prevent unreviewed provider changes. Terraform
authentication uses the external credential chain, never credentials in source.

## Preserved network and compute settings

The VPC has default tenancy, DNS resolution enabled, DNS hostnames disabled, and
no IPv6 allocation. Stable local maps provide subnet and association keys.

| Subnet key | CIDR | Availability Zone |
| --- | --- | --- |
| `public_1` | `10.20.1.0/24` | `us-east-2a` |
| `public_2` | `10.20.2.0/24` | `us-east-2b` |
| `private_1` | `10.20.11.0/24` | `us-east-2a` |
| `private_2` | `10.20.12.0/24` | `us-east-2b` |

All subnets disable automatic public IPv4 assignment, IPv6 assignment, DNS64 and
resource-name DNS records. The instance explicitly overrides the subnet setting
with `associate_public_ip_address = true`. The private table has no internet
default route or NAT. The unnamed main route table and automatic local routes
remain unmanaged. Existing Name tags and deliberate untagged resources are
preserved; no provider default tags are injected.

The web security group allows inbound TCP 80 from all IPv4 addresses, with all
outbound IPv4 traffic allowed. No SSH, HTTPS, or IPv6 rule is defined. Separate
rule and route resources avoid conflicting inline definitions.

The on-demand `t3.micro` occupies `public_1`, uses the exact AMI name configured
in `variables.tf`, and has no key pair or user data. It preserves default tenancy,
EBS optimization, source/destination checking, termination protection, disabled
stop protection, shutdown behavior `stop`, basic monitoring, disabled hibernation,
one core/two threads, and standard CPU credits. IMDSv2 is required with hop limit
2; the metadata HTTP endpoint is enabled, its IPv6 endpoint and metadata tags are
disabled.

The root block device is 8 GiB gp3, 3,000 IOPS, 125 MiB/s, encrypted with the
existing AWS-managed EBS key, and deleted on termination. It is managed only
inside `aws_instance.web`; no separate volume/attachment is imported. The EC2 role
preserves its description, EC2-only service trust, two AWS-managed attachments,
and instance profile. It has no permissions boundary or inline policy; the
separate GitHub deployment role does have a boundary.

### Public IPv4 lifecycle exception

The original launch enabled public IPv4 assignment, verified again while running.
Two refreshed plans before/after explicitly managing it proposed no infrastructure
changes. Their exit code 2 reflected a public-address output update, not an AWS
change. Subsequent parity verification completed after provisioning.

Provider 6.74.0 treats the setting as optional/computed and replacement-sensitive,
and reads current interface association rather than original launch intent. AWS
releases an automatically assigned public address when the instance stops. The
stage-1 normal plan therefore proposed replacement for the observed `false`
versus configured `true`; `prevent_destroy` correctly blocked it.

The approved exception in `aws_instance.web` is exactly:

```hcl
lifecycle {
  prevent_destroy = true
  ignore_changes  = [associate_public_ip_address]
}
```

`associate_public_ip_address = true` remains explicit outside the lifecycle
block. Terraform uses it when creating an instance; for an existing instance,
only this attribute is excluded from update reconciliation. Refresh still runs,
and public-address outputs still reflect AWS observations. State is not edited
to pretend that a stopped instance has an address. AMI, subnet, security groups,
metadata options, root encryption/KMS settings, IAM profile and every other
attribute remain subject to ordinary drift detection and destruction safeguards.

This is a tradeoff: a zero-change plan no longer proves that an existing
instance's public-IP assignment matches intent. Genuine changes to this one
setting, including intentional configuration edits, are not automatically
reconciled. There is no state-dependent conditional ignore rule. Starting EC2
merely to obtain a clean plan, removing the explicit launch setting, falsifying
it to `false`, using `ignore_changes = all`, targeting a plan or disabling refresh
would not preserve the current requirements. An Elastic IP or provider upgrade
is a separate architecture/version decision, not part of this exception.

#### Separate public-IP verification

For a separately authorized running-instance check, verify the named instance,
custom VPC, expected public subnet, primary network interface and current public
association through scoped read-only EC2 queries. Inspect the interface's current
auto-assignment setting where available, security group, public route-table
association and internet-gateway default route; subnet auto-assignment must stay
disabled because the instance has its own launch override. Verify EC2/SSM health
and approved HTTP content using the address only in memory/private evidence.
Do not hardcode an expected public address: it can change after stop/start.

While stopped, absence of a current address is expected and cannot re-prove
future assignment. Preserve the previously verified launch/running evidence and
review available interface attributes or retained launch-event evidence; do not
infer enabled assignment solely from an empty address. A missing or unexpected
association when running is a failed check requiring investigation, not permission
to allocate an address, replace the instance, start/stop it, or apply changes.
The suspended CD helper also checks a running instance's public association and
HTTP before deployment, but is disabled and is not a continuous drift monitor.

Reassess this exception when the provider is deliberately upgraded or the network
design changes. Remove it only after separate review and regression checks show
that both stopped/running observations can be handled safely. Local contract
tests reject an expanded ignore list, lost destruction guard and false launch
intent; the mocked Terraform test confirms the `true` creation value. The normal
refreshed plan remains the live parity check for all managed infrastructure.

References: [pinned provider schema/read/create implementation](https://github.com/hashicorp/terraform-provider-aws/blob/v6.74.0/internal/service/ec2/ec2_instance.go),
[Terraform lifecycle semantics](https://developer.hashicorp.com/terraform/language/meta-arguments/lifecycle),
[EC2 interface address lifecycle](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-eni.html).

## Monitoring and external ownership

The four dashboard widgets retain their discovered layout: CPU, memory, disk,
and network at x positions 0/6/12/18, y 0, each 6 by 6, time-series/unstacked.
CPU/memory use Average over 300 seconds; network uses Sum over 300 seconds. The
disk widget deliberately omits statistic/period and preserves root path/xfs
dimensions. Instance dimensions reference the managed server.

The CPU alarm uses Average over 300 seconds, threshold `>= 80`, two evaluation
periods and two datapoints to alarm, missing-data treatment `missing`, and enabled
actions. Only its ALARM list references SNS; OK/insufficient-data lists are empty.
Alarm state is runtime data. The controlled notification test is documented in
the [testing record](../docs/recovery-testing.md), separate from infrastructure
configuration.

Both untagged Nginx log groups use STANDARD class, seven-day retention, no
customer-managed KMS association, and no deletion protection. The standard SNS
topic preserves its adopted defaults and lack of configured KMS encryption. Its
separate policy preserves the original action list, wildcard principal and
owning-account SourceOwner condition; runtime references resolve private values.
These preserved settings are not a claim of maximum hardening.

Outside Terraform ownership:

- The confirmed email subscription and personal endpoint; no subscription data
  source, variable, output or resource stores it in state.
- The unnamed main route table, automatic local routes and service-created
  default objects.
- Nginx, website files, Agent installation/configuration and on-instance recovery
  copies, managed separately by reviewed server automation.
- Log streams/events, metric datapoints, alarm runtime state and SNS delivery data.

Future SNS publisher scoping, TLS enforcement, topic/log encryption, log deletion
protection, and tighter instance permissions require separate design and review.
The [delivery security model](../docs/authenticated-delivery.md) owns the OIDC,
permissions-boundary and executor-revision details.

## State, validation and operations

State and backups are private local files; no remote backend is configured. Keep
the matching state, private immutable GitHub identity inputs, credentials and saved
plans out of version control. A sensitive Terraform variable redacts presentation
but does not encrypt values in state or plans. Protect and back up those files
separately. The committed provider lock remains eligible for version control.

From this directory, static checks require no AWS authentication:

```bash
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
terraform test
```

Formatting/validation do not read live AWS or prove configuration parity. CI does
not run plans, imports, applies or destroys. Existing-environment operations need
the private state, external temporary credentials, private identity inputs, and
a separately reviewed full refreshed plan. Adoption is complete: do not repeat
imports or apply a fresh checkout to the adopted account.

VPC, instance, OIDC provider, deployment role, boundary and SSM document have
`prevent_destroy` guards. These do not protect resources after definitions are
removed or prevent deletion outside Terraform. The content-addressed document
requires a separately reviewed parallel-resource/policy cutover for revision;
application delivery cannot alter its executor or permission ceiling.
