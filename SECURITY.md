# Security

## Scope and reporting

This repository is an AWS lab with a public CI-only operating mode. Historical
live delivery is retained as engineering evidence, not an enabled service.
No availability, lossless telemetry or disaster-recovery guarantee is provided.

Do not put credentials, account/resource identifiers, Terraform state, raw logs
or exploit details in public issues. Use GitHub's **Report a vulnerability** action
on the repository Security tab. If private reporting is unavailable, open only a
nonsensitive issue requesting a private contact route. No response-time commitment
is made.

## Verified repository controls

The audited baseline on November 28, 2026 covered commit
`a68db8ed88bdfc2a2cf8261f437afdc0eecebc66` and GitHub settings:

- Main requires pull requests, both CI jobs, up-to-date branches and resolved
  conversations. Protections apply to administrators; force pushes and deletion
  are blocked. Zero independent reviewers are required for solo maintenance.
- Actions accept only the two exact CI pins in the [CI guide](docs/ci-cd.md#repository-hygiene-and-action-pins),
  with full-length SHA enforcement. Default tokens are read-only, workflow PR
  creation/approval is disabled, and all external contributors require workflow approval.
- Secret scanning and push protection are enabled. They supplement, rather than
  replace, local source/history and retained-log privacy checks.
- Both CD workflows are disabled. The published Terraform role trust denies
  federation; its attached policy explicitly denies deployment-session permissions.
  CI requests no AWS authentication or OIDC token and does not deploy infrastructure.

These GitHub controls were read live. AWS was not queried: published Terraform,
local state or previous reports cannot establish current live IAM, sessions,
instance health or drift. Re-enabling delivery requires separate review.

## Open security work

The audit found dependency graph, Dependabot alerts and private reporting disabled.
The hardening rollout enables these free features while keeping automatic updates
disabled. Alert coverage does not replace bundle-aware reviews: SHA-pinned actions,
bundled npm code and Terraform Go modules may not produce Dependabot alerts.

This hardening replaces Setup Terraform with an installer that requires the
pinned HashiCorp signing-key fingerprint, a valid signed manifest and the exact
Terraform 1.17.2 Linux archive hash before extraction. No verification fallback is
allowed. Checkout 7.0.1 and AWS Credentials 6.3.1 use reviewed immutable pins; the
rollout narrows CI to a Checkout-only allowlist. Checkout retains response-handling DoS
advisories, and Terraform includes two medium OpenTelemetry findings whose paths
CI does not enable. The obsolete OpenPGP warning does not match Terraform's
reviewed implementation. See the [dependency review](docs/ci-cd.md#dependency-review-and-open-findings)
for applicability, validation requirements and the Checkout-only allowlist.
Pins and passing tests do not establish vulnerability-free operation.

The lab retains HTTP without TLS, broad adopted instance permissions and outbound
access, local Terraform state and on-instance backups. The executor runs as root.
Live Agent recovery verification remains incomplete; isolated tests do not close
that gap. See the [security boundary](docs/authenticated-delivery.md) and
[recovery record](docs/recovery-testing.md).
