# Continuous integration and manual delivery

## Current scope

`.github/workflows/ci.yml` validates public source only. It runs on pushes to
`main`, pull requests targeting `main`, and manual workflow dispatch. Both jobs
use GitHub-hosted `ubuntu-24.04` runners. The workflow grants only `contents: read`,
does not persist checkout credentials, and has no AWS credentials, OIDC permission,
environment secrets, deployment commands, or infrastructure deployment step.

Concurrent runs for the same ref cancel superseded CI work. Source validation has
a ten-minute timeout; Terraform validation has twenty minutes. Every failed check
fails its job. Terraform runs only after the source checks pass. There are no path
filters that could skip checks while reporting a successful required workflow.

Hosted CI passed after the reviewed Windows/Linux provider checksum correction.
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
  tests, including protections for all seven pinned files. These do not execute
  the privileged deployment entry point. Native Windows skips real POSIX metadata
  tests; those execute on a Linux CI runner after publication.

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
```

Initialization needs public Terraform registry/release network access. It installs
providers without initializing a backend or updating the lock file. Validation
checks configuration/schema consistency; it does not evaluate live AMI, account,
or KMS lookups. It cannot establish live parity, cost, least privilege, server
health, or drift. No state, saved plan, or Terraform directory is uploaded as an
artifact or cached by this workflow.

The existing lock includes release archive checksums for multiple platforms. Local
compatibility verification uses an isolated configuration copy, clean initialization,
and Terraform's Linux AMD64 provider mirror download, comparing the archive against
the unchanged lock and HashiCorp's release checksum manifest. Hosted Ubuntu CI
subsequently passed initialization and validation. New workflow/helper changes
still require a successful hosted run after separately approved publication.

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

## Authenticated manual delivery

The six restricted IAM/OIDC/SSM resources were separately provisioned and verified.
Terraform now retains parity across 33 managed resources and four data sources.
The manual caller and reusable executor workflows are implemented locally; they
have not been published, dispatched or authenticated. See the
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
Publishing, authenticating or executing these workflows requires separate approval.
The CI entry point now runs all `test_*.py` suites, including synthetic CD gating,
input, private staging and polling tests. No test makes live deployment calls.

See the [manual delivery runbook](manual-deployment.md) for the seven required
repository variables, all eight trust conditions, exact-CI gate, pinned release
procedure, failure handling and remaining live acceptance tests.

References: [GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use),
[GitHub OIDC with AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws),
[SSM Run Command setup](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command-setting-up.html),
[Terraform init](https://developer.hashicorp.com/terraform/cli/commands/init),
[Terraform dependency lock file](https://developer.hashicorp.com/terraform/language/files/dependency-lock).
