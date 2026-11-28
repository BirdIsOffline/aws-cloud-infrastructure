# Architecture diagram

- [SVG](architecture.svg): self-contained image used in the root README.
- [Editable source](architecture.drawio): uncompressed draw.io/diagrams.net XML
  with editable labels, connectors and embedded icons.

The diagram shows one EC2 workload, not a highly available application. Its
second view repeats the same instance to explain delivery and IAM relationships.
Three subnets are unused. Public subnets use the internet gateway; private subnets
have local routing only. SSM connects outbound, not through an inbound SSH rule.
IAM is global; the workload and monitoring are in `us-east-2`.

Teal arrows show HTTP, blue delivery/control, amber monitoring, purple dashed
Terraform management, and gray dashed associations. The delivery path is implemented but currently disabled.
The diagram does not imply TLS, NAT, a load balancer, failover or off-instance
recovery. The [testing record](../recovery-testing.md) describes recovery limits.

## Editing

Open the draw.io file using local/device storage. Preserve editable text and
embedded assets, then export the full page as `architecture.svg` with a white
background, viewBox and accessible title/description. Avoid external images,
fonts, scripts and foreignObject labels. Check both native-size rendering and a
roughly 900-pixel-wide preview, XML parsing, README links and agreement with the
[Terraform inventory](../../terraform/README.md).

## AWS icon attribution

Eight icon types—EC2, EBS, CloudWatch, Systems Manager, IAM, SNS, internet gateway
and alarm—came from the official [AWS Architecture Icons](https://aws.amazon.com/architecture/icons/)
package released July 31, 2026. Their artwork and service colors are unchanged;
AWS owns the icons and permits their use in architecture diagrams. Layout,
connectors and captions are project-authored. No full icon library or executable
third-party diagram dependency is included.
