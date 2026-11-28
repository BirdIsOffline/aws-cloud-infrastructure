# Security

## Reporting

Use **Report a vulnerability** on GitHub's Security tab. Do not include
credentials, private identifiers, state, raw logs or exploit details in public
issues. If private reporting is unavailable, request a private contact route
without posting sensitive details. This lab has no response-time commitment.

## Repository controls

The last publication checks verified:

- Pull requests, both CI checks, up-to-date branches and resolved conversations
  on main; administrator enforcement; blocked force pushes and branch deletion.
- Zero required approving reviewers for solo maintenance. This is not independent
  two-person review.
- An exact Checkout-only action allowlist, full-length SHA enforcement, read-only
  tokens, no workflow PR approval, and approval for all external contributors.
- Secret scanning, push protection, dependency graph, Dependabot alerts and private
  vulnerability reporting. Automatic dependency/security updates remain disabled.

Both CD workflows remain disabled. Published Terraform denies deployment-role
federation and all deployment-session service permissions. CI requests no AWS
credentials or OIDC token. See [CI security details](docs/ci-cd.md).

## Remaining limits

The lab uses HTTP without TLS, broad adopted instance permissions/outbound access,
local Terraform state and on-instance backups. The deployment executor runs as
root; its boundary does not sandbox the instance role or trusted system tools.

Known dependency findings and their workflow applicability are documented in the
[dependency review](docs/ci-cd.md#dependency-review-and-open-findings).
Passing tests or having no Dependabot alerts does not establish complete coverage.

The repository's corrected monitoring release remains undeployed. Complete live
Agent recovery verification is still incomplete; see the
[testing record](docs/recovery-testing.md). Publication checks did not authenticate
to AWS: source and stored evidence do not independently prove current live IAM
state, instance health or drift. Re-enabling delivery needs a separate review.
