# Continuous integration and manual delivery

The current operating mode is **CI only**: CI is active, both delivery workflows
are disabled in GitHub, and the dedicated AWS role has federation and session
permission denies. The authenticated delivery sections describe the retained,
previously verified implementation. No deployment is authorized by this guide.

## Isolated recovery validation

The source job also runs the offline Linux recovery harness through the existing
validation entry point. Its 31 recovery cases and two readiness guards use unchanged
production code inside an ephemeral chroot with isolated network/PID/mount namespaces and no credentials or
host mounts. Missing Linux isolation support fails CI. Thirteen additional portable
guard tests run with the existing regression suite. See
[the recovery test guide](recovery-testing.md) for prerequisites, safety boundaries,
expected exit codes, and the distinction between simulated and live recovery.
The published recovery baseline passed all 114 tests with zero skips: 81 ordinary tests,
31 recovery cases and two Linux readiness guards. See the recovery guide for
recorded results and limits; the separate 225 private offline checks are not
part of this CI count.

Latest verified hosted CI passed **121 Python tests and one mocked Terraform
test**, with zero skips: 88 ordinary Python tests, 31 recovery cases, two Linux
readiness guards, and a separate mocked Terraform run with seven assertions.
[CI run 45759551505](https://github.com/BirdIsOffline/aws-cloud-infrastructure/actions/runs/45759551505)
records that result for commit `f6a5976faaabb401aa06f056b9c06d74b2d3b156`.

## Current scope

`.github/workflows/ci.yml` validates public source only. It runs on pushes to
`main`, pull requests targeting `main`, and manual workflow dispatch. Both jobs
use GitHub-hosted `ubuntu-24.04` runners. The workflow grants only `contents: read`,
does not persist checkout credentials, and references no AWS credentials, OIDC
permission, deployment secrets, live deployment commands, or infrastructure
deployment step. The recovery harness executes production scripts only against
its isolated substitutes and disposable filesystem.

Concurrent runs for the same ref cancel superseded CI work. Source validation has
a ten-minute timeout; Terraform validation has twenty minutes. Every failed check
fails its job. Terraform runs only after the source checks pass. There are no path
filters that could skip checks while reporting a successful required workflow.

Hosted CI passed after the reviewed Windows/Linux provider checksum correction
and again with the complete isolated recovery suite.
Server automation previously passed strict live configuration idempotency;
these CI checks do not execute it against any server or repeat that live test.

## Checks and local usage

Run from the project root on Linux with Bash, Python 3, Git, and ShellCheck:

```bash
bash scripts/ci/validate.sh
```

The reusable entry point runs:

- `scripts/ci/validate.py`: validates publishable source, UTF-8, forbidden paths,
  whitespace/conflict markers, JSON, and LF endings for shell/Python scripts,
  workflows, and deployment JSON/HTML/CSS. Documentation and Terraform can use
  platform checkout line endings; executable/deployed input files must use LF.
- The existing pure Python input-validator heredocs in `deploy-website.sh`,
  `configure-monitoring.sh`, and `verify-server.sh`, with local source arguments.
  This preserves a single monitoring/content contract without executing Bash
  deployment entry points. Extraction fails if the expected validator block is
  missing or ambiguous. Review the CI adapter when changing that interface.
- Additional explicit HTML tag nesting, duplicate-attribute, doctype, root-language,
  and required document-element checks. This is a project-specific structural
  validator, not full W3C conformance, browser rendering, or CSS validation.
- `bash -n` and ShellCheck at all default severities for all four server scripts
  and the CI shell entry point. Missing tools fail rather than silently skip.
- The restricted executor bundle/size checks and local positive/negative unit
  tests, including protections for all seven pinned files. They do not perform
  privileged deployment on the host; the recovery runner separately executes
  production code inside isolation. Native Windows skips real POSIX metadata
  tests; those executed successfully on the hosted Linux runner.

Ubuntu runner images provide Bash, Python 3, Git, and ShellCheck. Their installed
versions can change with image updates; no package installation or upgrade is part
of this workflow. Bootstrap's `source=/dev/null` ShellCheck annotation describes
the platform-owned `/etc/os-release` input: it is not repository source. It does
not disable ShellCheck diagnostics or change runtime platform verification.

On Windows, `python scripts/ci/validate.py` runs the portable source checks.
Use Git Bash for Bash parsing and an existing ShellCheck executable for linting.
The complete shell entry point requires `python3` on PATH, as on the Ubuntu runner.

Terraform CI uses exactly **1.17.2**, matching the installed project CLI, and the
existing `.terraform.lock.hcl`, which selects **hashicorp/aws 6.74.0**:

```bash
cd terraform
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
terraform test
```

Initialization needs public Terraform registry/release network access. It installs
providers without initializing a backend or updating the lock file. Validation
checks configuration/schema consistency; it does not evaluate live AMI, account,
or KMS lookups. It cannot establish live parity, cost, least privilege, server
health, or drift. No state, saved plan, or Terraform directory is uploaded as an
artifact or cached by this workflow.

The Terraform test uses a fully mocked AWS provider and disposable in-memory
test state. It checks deny-only federation, the existing-session permissions deny,
the retained boundary and EC2 service role, trust-policy sensitivity, and the
explicit public-IP creation setting. It does not apply against AWS or use the
adopted state. Seven additional Python contract tests restrict the lifecycle
exception to that one attribute and preserve destruction protection. These
checks extend the historical 114-test baseline and passed in the latest verified
hosted run above. Review Actions results for any later source revision.

The existing lock includes release archive checksums for multiple platforms. Local
compatibility verification uses an isolated configuration copy, clean initialization,
and Terraform's Linux AMD64 provider mirror download, comparing the archive against
the unchanged lock and HashiCorp's release checksum manifest. Hosted Ubuntu CI
subsequently passed initialization and validation. Any future workflow/helper
change still requires a successful hosted run after reviewed publication.

## Repository hygiene and action pins

The source scanner enumerates Git-tracked files plus untracked, non-ignored files.
This includes initial local work before its first commit and catches force-added
ignored files. It excludes ignored local state/cache files without reading their
contents. It rejects state, plans, tfvars, private keys, credential/environment
files, local Terraform overrides, backups, symlinks, and raw AWS inventory shapes.
It checks all included files for common credential/token patterns, account/resource
identifiers, email addresses, personal Windows paths, and public IPv4 addresses.
Findings report locations and categories without printing matched values. Local
development instructions, runtime logs, archives, and inventory directories are
excluded and rejected if force-added. No account-identifier allowlist is needed:
the AMI lookup uses the provider's `amazon` owner alias.

Keep `.terraform.lock.hcl` in version control. State, backups, `.terraform`, and
real credentials must remain ignored and untracked. The pattern scanner is a
guardrail, not comprehensive secret detection or a history scanner. Review Git's
staged diff before publication. Enable GitHub secret scanning, push protection and
branch rules where available under the repository plan; retain mandatory local
scans and operator review without assuming paid private-repository protections.
Never commit runtime SSM output, email subscription details or recovery archives.

External actions are pinned to full commit SHAs verified against official
repository tag refs when this workflow was implemented:

| Action | Release | Commit |
| --- | --- | --- |
| `actions/checkout` | v6.1.0 | `d23441a48e516b6c34aea4fa41551a30e30af803` |
| `hashicorp/setup-terraform` | v4.0.1 | `dfe3c3f87815947d99a8997f908cb6525fc44e9e` |
| `aws-actions/configure-aws-credentials` (CD only) | v6.3.0 | `e1253824e5c10ff9df46874f81ed3ec929e19cfd` |

Update pins through reviewed changes after verifying the new commit belongs to the
official repository and reviewing release notes. Local workflow validation uses
actionlint where available; no unpinned lint action is introduced.

## Repository protections and solo maintenance

CI-only operation is independent of repository visibility. Both CD workflows
remain disabled and both AWS deployment denial controls remain in force. The
retained CD implementation still requires a private original repository; changing
visibility does not adapt that gate or authorize delivery.

Repository policy requires full-length action SHAs. The two approved CI actions
are `actions/checkout` and `hashicorp/setup-terraform` at the exact pins above.
Where GitHub supports an action allowlist, allow only those two pins, with broad
GitHub-owned and verified-creator allowances disabled. The retained CD credential
action is not part of the CI allowlist. Keep default workflow tokens read-only,
workflow PR creation/approval disabled, and fork secrets/write tokens unavailable.
Require maintainer approval for all external-contributor workflows where supported.

The intended `main` protection requires pull requests, both named CI jobs from
the GitHub Actions app, up-to-date branches, resolved conversations, and no force
pushes or branch deletion. Apply protections to administrators without routine
bypass. This is a solo project: require **zero approving reviewers**, no code-owner
approval, and no independent approval of the latest push. Pull requests and CI
remain required; they do not constitute independent two-person review.

GitHub feature availability depends on visibility and plan. Free private
repositories cannot enforce every protection above; do not describe unavailable
settings as active. Verify branch protection, the exact action allowlist, external
workflow approvals, secret scanning and push protection during an independently
approved public cutover before re-enabling public CI. This guide does not authorize
a visibility change, subscription purchase, or restoration of deployment access.

## Authenticated manual delivery

The six restricted IAM/OIDC/SSM resources were separately provisioned and verified.
A post-provisioning plan verified parity across 33 managed resources and four
data sources before the publication cutoff.
The first published caller/reusable run passed authorization, OIDC, SSM execution
and all four scripts but failed its telemetry gate. After correcting aligned-minute
queries and IncomingLogEvents checks and migrating inputs to pre-registered Actions
secrets, the controlled live deployment passed every end-to-end verification.
The eight secrets are configured and superseded variables removed. See the
[testing record](recovery-testing.md) for the distinction between this success,
live recovery outcomes and offline simulations.
See the
[authenticated delivery security model](authenticated-delivery.md) for resource
addresses, external identity inputs, supported trust claims, permission boundary,
content-addressed executor, pinned inputs, limits, recovery, and revision procedure.

The implementation uses manual dispatch from main and a dedicated reusable
executor workflow, with successful CI for the exact source commit required before
credentials. It does not depend on paid private-environment reviewer gates. Exact
immutable owner/repository/actor IDs, branch, workflow name, and reusable workflow
reference are required by IAM. Main-writer and operator trust remains explicit;
manual dispatch is not independent two-person approval.

Deployment remains separate from Terraform infrastructure changes. It uses
short-lived OIDC credentials, private integrity-checked SSM transfer, one lab
instance/document, server-side locking, and no SSH, permanent AWS keys, new
artifact-storage service, or automatic Terraform deployment. A constant concurrency
group prevents automatic cancellation of running deployments. The helper verifies
public HTTP, fresh telemetry, and seven-day log retention after server success.
Future publication, authentication or execution requires separate approval.
The CI entry point now runs all `test_*.py` suites, including synthetic CD gating,
input, private staging and polling tests. No test makes live deployment calls.

See the [manual delivery runbook](manual-deployment.md) for the eight repository
secrets, including the role unique ID masking input, all eight trust conditions,
telemetry evidence limits, pinned release procedure, failure handling and live-test
boundaries. Repository privacy and
read-only default token permissions were preserved during the approved migration.

References: [GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use),
[repository Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository),
[protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
[secret scanning availability](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/detect-secret-leaks/enable-secret-scanning),
[GitHub OIDC with AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws),
[SSM Run Command setup](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command-setting-up.html),
[Terraform init](https://developer.hashicorp.com/terraform/cli/commands/init),
[Terraform dependency lock file](https://developer.hashicorp.com/terraform/language/files/dependency-lock).
