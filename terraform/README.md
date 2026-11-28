# Terraform infrastructure reference

Terraform manages **33 resources and four data sources** in `us-east-2`: 27
imported without recreation and six delivery-security resources added later.
Refreshed plans verified parity, not continuous drift monitoring.

## Ownership and operation

Terraform owns AWS resources; Bash handles server configuration without
provisioners or user data. The unnamed
main route table, automatic local routes, email subscription, log streams/events,
metric datapoints and on-instance recovery copies are outside Terraform ownership.
No email endpoint is stored in Terraform configuration or state.

CI uses Terraform 1.17.2 and locked AWS provider 6.74.0; configuration constraints
allow Terraform `>= 1.17.2, < 2.0.0` and provider `~> 6.0`. Authentication remains
external. No provider default tags override the adopted tags.

## Resource inventory


Counts include `for_each` instances and policy attachments; inline root storage
and service-created objects are not additional resources.

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
| `aws_iam_role.github_deploy` | 1 | Deny-only federation in CI-only mode |
| `aws_iam_policy.github_deploy` | 1 | Dedicated delivery policy with unconditional permissions deny |
| `aws_iam_role_policy_attachment.github_deploy` | 1 | Attach delivery permissions |
| `aws_iam_policy.github_deploy_boundary` | 1 | Deployment permission limit |
| `aws_ssm_document.deploy_server` | 1 | Content-addressed restricted executor |

### Data sources: 4

| Data address | Purpose |
| --- | --- |
| `data.aws_ami.web` | Exact Amazon-owned AL2023 image name, x86_64/HVM/EBS filters; no latest selection |
| `data.aws_kms_key.ebs` | Existing `alias/aws/ebs` key |
| `data.aws_partition.current` | Partition for AWS-managed policy references |
| `data.aws_caller_identity.current` | Runtime account condition in the adopted SNS policy |

## Adopted configuration

| Setting | Value |
| --- | --- |
| VPC | `10.20.0.0/16`, default tenancy, DNS resolution enabled, hostnames disabled, no IPv6 |
| `public_1` / `public_2` | `10.20.1.0/24` in `us-east-2a` / `10.20.2.0/24` in `us-east-2b` |
| `private_1` / `private_2` | `10.20.11.0/24` in `us-east-2a` / `10.20.12.0/24` in `us-east-2b` |
| Routing | Public default route through internet gateway; private local-only; four explicit associations |
| Subnet address assignment | Automatic public IPv4 and IPv6 assignment disabled |
| Security group | Public TCP 80; no SSH/HTTPS/IPv6 ingress; unrestricted outbound IPv4 |
| EC2 | One on-demand `t3.micro` in `public_1`, exact Amazon-owned AL2023 AMI lookup, no key pair or user data |
| Instance controls | Required IMDSv2, hop limit 2, basic monitoring, standard CPU credits, termination protection, shutdown behavior stop |
| Root volume | 8 GiB gp3, 3,000 IOPS, 125 MiB/s, AWS-managed EBS key, delete on termination |
| EC2 role | EC2 service trust, AmazonSSMManagedInstanceCore and CloudWatchAgentServerPolicy |

Standalone routes/rules and static subnet keys preserve import addresses.
Root storage is managed inline with EC2.

### Public IPv4 lifecycle exception

The instance explicitly launches with `associate_public_ip_address = true`;
running tests confirmed assignment. Provider 6.74.0 reads current association,
so stopped EC2 previously caused a replacement proposal.

The narrow exception is:

```hcl
lifecycle {
  prevent_destroy = true
  ignore_changes  = [associate_public_ip_address]
}
```

The explicit true creation setting remains. Refresh and public-address outputs
still work; all other EC2 settings remain subject to drift detection. The tradeoff
is that a clean plan cannot establish public-IP assignment intent for an existing
instance. Do not start EC2 merely to hide this discrepancy or broaden the exception.

For an authorized running-instance check, verify instance/VPC/subnet identity,
primary interface/public association, security group and gateway route, then EC2,
SSM and approved HTTP content. Keep the address private and do not assume it stays
constant. An absent address while stopped does not prove future assignment.
Reassess the exception after a deliberate provider or network change. Python
contract tests and the mocked Terraform test preserve its narrow scope and launch
intent. See [provider implementation](https://github.com/hashicorp/terraform-provider-aws/blob/v6.74.0/internal/service/ec2/ec2_instance.go)
and [lifecycle semantics](https://developer.hashicorp.com/terraform/language/meta-arguments/lifecycle).

## Monitoring and delivery controls

The dashboard has CPU, memory, disk and network widgets, each 6×6 at horizontal
positions 0/6/12/18. CPU/memory use Average at 300 seconds; network uses Sum.
The disk widget preserves its omitted statistic/period and root/xfs dimensions.
The CPU alarm uses Average, `>= 80`, two 300-second evaluation periods and two
breaching datapoints; missing data is `missing`. Only ALARM invokes SNS.

Log groups are STANDARD, seven-day retention, without customer-managed KMS or
deletion protection. The standard SNS topic preserves its defaults and separate
SourceOwner-conditioned policy. These are adopted settings, not maximum hardening.

In CI-only mode, deployment trust denies federation and the attached policy denies
all actions/resources, removing service permissions from existing sessions after
IAM propagation. Credential bytes still expire normally; denial is not command
cancellation. EC2's role is separate. Historical trust and policies are private
records, not automatic restoration inputs.

The VPC, EC2, issuer, deployment role, boundary and SSM document have
`prevent_destroy`. Guards do not protect deleted definitions or out-of-band AWS
deletions. The revised monitoring contract derives a new document name even with
unchanged Terraform code; replacing the deployed document at the same address is
blocked. A future rollout needs the [parallel-document cutover](../docs/authenticated-delivery.md#executor-revision-and-rollout-procedure).

## State and validation

Local state, backups, private inputs, credentials and plans stay ignored.
Sensitive variables redact output, not stored state/plans. Outputs may contain
private identifiers.

From this directory, these static checks need no AWS authentication:

```bash
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
terraform test
```

The tests use a fully mocked provider and disposable test state. They do not
operate on AWS or the adopted state. A checkout alone cannot safely manage this
environment. Any future infrastructure work needs matching private state, external
temporary credentials, identity inputs and review of a complete refreshed plan.
Do not repeat completed imports, apply an empty-state checkout or restore access
using an old saved plan. The repository's newer rollback release remains undeployed.
