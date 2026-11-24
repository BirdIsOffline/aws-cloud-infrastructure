# Continuous integration and planned deployment

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

The first actual GitHub run awaits separate repository publication approval.
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
the unchanged lock and HashiCorp's release checksum manifest. A Windows initialization
and Linux package verification do not replace executing init/validate on Ubuntu;
the first GitHub-hosted run is still required for that end-to-end confirmation.

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
staged diff before publication; enable GitHub secret scanning/push protection and
branch protections before publishing and enabling deployment. Never commit runtime SSM output,
email subscription details, or recovery archives.

External actions are pinned to full commit SHAs verified against official
repository tag refs when this workflow was implemented:

| Action | Release | Commit |
| --- | --- | --- |
| `actions/checkout` | v6.1.0 | `d23441a48e516b6c34aea4fa41551a30e30af803` |
| `hashicorp/setup-terraform` | v4.0.1 | `dfe3c3f87815947d99a8997f908cb6525fc44e9e` |

Update pins through reviewed changes after verifying the new commit belongs to the
official repository and reviewing release notes. Local workflow validation uses
actionlint where available; no unpinned lint action is introduced.

## Proposed authenticated CD: separate approval required

Create a separate server-deployment workflow only after the CI workflow has run
successfully. Initially make deployment manual, limited to protected `main` and a
protected GitHub environment with required reviewers and restricted deployment
branches. Require CI success for the exact immutable commit being deployed. Never
deploy pull-request code, run privileged `pull_request_target` checkouts, or promote
untrusted PR artifacts through a privileged `workflow_run` without verifying their
origin and immutable source revision.

Use GitHub OIDC with a dedicated, short-lived AWS deployment role, not access-key
secrets or the EC2 instance role. Grant `id-token: write` only to the approved CD
job. Restrict the role trust to audience `sts.amazonaws.com` and the exact repository
and protected environment subject. Environment-based subjects do not also encode
the branch: enforce `main` through the environment's deployment-branch rule and
workflow conditions. Plan role/provider creation separately; this CI implementation
creates neither a role nor an OIDC provider.

Limit the future role to the required discovery, command execution/result polling,
and scoped monitoring reads. Scope `ssm:SendCommand` to the verified lab instance
and a reviewed deployment document; use resource/tag/region restrictions where
the API supports them. Some describe/poll APIs need wildcard resources, which
must be restricted to the smallest necessary action set. Sending arbitrary
`AWS-RunShellScript` commands still grants root execution on the instance; prefer
a dedicated SSM document with constrained parameters and an allowlisted deployment
sequence. IAM/document design requires its own review.

The proposed deployment path is:

1. Build the seven-file server bundle from the CI-validated immutable revision,
   with an integrity manifest. Keep all state, secrets, and logs out of the bundle.
2. Obtain temporary OIDC credentials after environment approval. Discover and verify
   the existing named instance, custom VPC membership, running state, and SSM health.
3. Transfer the small reviewed bundle using the validated compressed SSM wrapper,
   checking payload limits, private root-owned staging, paths, permissions, LF,
   checksums, and Linux syntax before executing anything. If future bundle growth
   needs an artifact store, separately approve private, encrypted, tightly scoped
   storage and immutable artifact references.
4. Run the approved bootstrap, website deployment, monitoring configuration, and
   verification scripts once in order. Preserve durable private recovery backups
   and documented recovery behavior. Serialize deployments; do not cancel a running
   deployment merely because a newer commit arrives.
5. Verify local/public content, HTTP 404 for the former backup URL, services, active
   cached Agent configuration, seven-day retention, and fresh telemetry. Emit only
   redacted summaries and retain sensitive command/recovery data privately.

The EC2 role continues to supply Agent permissions. CD needs neither inbound SSH
nor security-group changes. Keep server deployment separate from any future
Terraform infrastructure pipeline; automatic infrastructure deployment, Terraform
state access, and plan/apply permissions are outside this design.

References: [GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use),
[GitHub OIDC with AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws),
[SSM Run Command setup](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command-setting-up.html),
[Terraform init](https://developer.hashicorp.com/terraform/cli/commands/init),
[Terraform dependency lock file](https://developer.hashicorp.com/terraform/language/files/dependency-lock).
