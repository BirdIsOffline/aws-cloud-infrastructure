# Architecture diagram

The delivery path is disabled in the current CI-only operating mode. Both CD
workflows are disabled, the role denies federation, and its managed policy denies
session service permissions. The diagram preserves the implemented architecture
and marks this operational suspension; CI remains active.

- [Rendered SVG](architecture.svg): self-contained vector image embedded in the
  root README, with selectable text and an accessible title/description.
- [Editable source](architecture.drawio): uncompressed diagrams.net/draw.io XML,
  containing editable labels, shapes and connectors with embedded AWS icons.

The 1200 by 2230 canvas uses three aligned views to keep the complete architecture
legible without routing control-plane arrows through subnet labels. The second
view repeats the **same** existing EC2 target to explain delivery and instance-role
relationships; it does not represent an additional workload.

## Scope and interpretation

1. **Regional workload and observability.** The `us-east-2` boundary contains the
   custom VPC, two Availability Zones, four subnets, internet gateway, named
   public/private route tables, and regional monitoring/notification services.
   Three subnets are unused. The public table has the internet default route;
   the private table has local routing only. Dashed gray arrows identify explicit
   subnet associations rather than traffic. The automatically created local
   routes and unnamed main table are not separately drawn.
2. **Authenticated delivery and instance management.** Manual dispatch and CI
   evidence feed the exact-commit gate before OIDC/STS authentication. The IAM
   provider, deployment role/boundary and EC2 role are shown outside the regional
   view because IAM is global. The dedicated regional SSM document controls the
   fixed four-script sequence, seven approved input hashes, lock and failure
   latch. SSM Agent opens outbound management connections; logical command arrows
   do not imply an inbound management rule or a private VPC endpoint.
3. **Infrastructure management.** Terraform's private state, full plan review and
   separately approved infrastructure changes are distinct from application
   delivery. The count includes 33 managed resource instances and four separately
   counted data sources; the [inventory](../../terraform/README.md) lists them.

Teal solid arrows denote public HTTP; blue solid arrows denote delivery/control;
amber solid arrows denote telemetry/alerts; purple dashed arrows denote separate
infrastructure management. Thin gray dashed arrows denote route/role associations.
Labels and line styles supplement color, and a legend is embedded in the image.

The encrypted EBS object is the instance's root volume, managed inline with EC2.
The security-group caption describes inbound access: HTTP is allowed and SSH is
absent; outbound IPv4 remains unrestricted. EC2 supplies native CPU/network
metrics; the Agent supplies memory/disk metrics and Nginx logs. Dashboard and
alarm arrows show metric consumption. The Agent's 300-second collection interval
and both log groups' seven-day retention are detailed in the
[server baseline](../server-configuration.md). The SNS email subscription is
external to Terraform and its personal endpoint is omitted.

The diagram makes no claim of multi-instance availability, application failover,
TLS, NAT, load balancing, remote Terraform state or off-instance recovery backups.
It shows implemented recovery controls, not a complete live Agent recovery pass.
The [testing record](../recovery-testing.md) documents that limitation and
distinguishes confirmed email delivery after a simulated alarm transition from
an actual CPU threshold breach. No account value, resource ID, public address,
email endpoint or deployment secret is included.

## Editing and publication

Open `architecture.drawio` with diagrams.net or the draw.io desktop application.
Use local/device storage, preserve editable text and embedded assets, then export
the complete page as `architecture.svg`. Retain a white background, the full-page
viewBox, and the SVG accessibility title/description. Avoid external font/image
references, scripts and HTML/foreignObject labels so the image remains portable
when GitHub renders it as an image. Changes to infrastructure or release security
must be reviewed independently; editing the diagram does not implement them.

Before publication, inspect the SVG at native size and approximately 900 pixels
wide, check README/source links, parse both XML files, rerun source hygiene and
secret scans, and verify that labels still agree with the Terraform definitions
and workflow contracts. Temporary browser profiles, downloaded icon archives and
raster inspection previews stay in ignored local storage, not in this directory.
An editor export may change formatting; review the diff and rendering together.

## Icon provenance

Eight service/resource icon types were taken directly from the official
[AWS Architecture Icons](https://aws.amazon.com/architecture/icons/) package
released July 31, 2026: EC2, EBS, CloudWatch, Systems Manager, IAM, SNS, internet
gateway and CloudWatch alarm. Icons are embedded as vectors without changing
their artwork or service colors. Only layout, connectors, captions and boundaries
are project-authored. AWS owns the icon artwork; its architecture-icon page
permits customers and partners to use the assets in architecture diagrams.
No entire asset library or executable third-party diagram dependency is bundled.
