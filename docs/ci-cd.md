# Continuous integration and manual delivery

The current operating mode is **CI only**: CI is active, both delivery workflows
are disabled in GitHub, and the dedicated AWS role has federation and session
permission denies. The authenticated delivery sections describe the retained,
previously verified implementation. No deployment is authorized by this guide.

## Isolated recovery validation

The source job also runs the offline Linux recovery harness through the existing
validation entry point. Its 44 recovery cases and two readiness guards execute
production code unchanged inside an ephemeral chroot with isolated network/PID/mount
namespaces and no credentials or host mounts. Missing Linux isolation support fails CI. Thirteen additional portable
guard tests run with the existing regression suite. See
[the recovery test guide](recovery-testing.md) for prerequisites, safety boundaries,
expected exit codes, and the distinction between simulated and live recovery.
The published recovery baseline passed all 114 tests with zero skips: 81 ordinary tests,
31 recovery cases and two Linux readiness guards. See the recovery guide for
recorded results and limits; the separate 225 private offline checks are not
part of this CI count.

Verified correction CI passed **162 Python tests and one mocked Terraform test**,
with zero failures or skips: 116 ordinary Python tests, 44 recovery cases, two Linux
readiness guards, and a separate mocked Terraform run with seven assertions.
[CI run 46129410785](https://github.com/BirdIsOffline/aws-cloud-infrastructure/actions/runs/46129410785)
records that result for corrected source commit `90c34c6db41052706762eedfafd045ef0ce9dab9`.
The additional 13 recovery cases and nine portable verifier tests are described in
the [recovery coverage](recovery-testing.md#monitoring-rollback-regression-coverage).

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
  tests; those executed successfully on the hosted Linux runner. The real-GPG
  fixture test also passed on Linux in the verified hosted run above; it remains
  mandatory for future revisions.

Ubuntu runner images provide Bash, Python 3, Git, GPG, and ShellCheck. Their installed
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
repository tag refs. The current published pins, verified during the completed hardening rollout, are:

| Action | Release | Commit |
| --- | --- | --- |
| [actions/checkout](https://github.com/actions/checkout/releases/tag/v7.0.1) | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| [aws-actions/configure-aws-credentials](https://github.com/aws-actions/configure-aws-credentials/releases/tag/v6.3.1) (disabled CD only; excluded from allowlist) | v6.3.1 | `45666896f5d8e0f10ae255413f3a4cdd03bdc8f5` |

Setup Terraform was removed; the signature-verified official archive installer
replaces it. Checkout is the only action allowed by repository policy.

Update pins through reviewed changes after verifying the new commit belongs to the
official repository and reviewing release notes. Local workflow validation uses
actionlint where available; no unpinned lint action is introduced.

## Repository protections and solo maintenance

CI-only operation is independent of repository visibility. Both CD workflows
remain disabled and both AWS deployment denial controls remain in force. The
retained CD implementation still requires a private original repository; changing
visibility does not adapt that gate or authorize delivery.

Repository policy requires full-length action SHAs. The verified final allowlist
permits only the exact Checkout 7.0.1 pin above, with broad
GitHub-owned and verified-creator allowances disabled. The retained CD credential
action is not part of the CI allowlist. Keep default workflow tokens read-only,
workflow PR creation/approval disabled, and fork secrets/write tokens unavailable.
Require maintainer approval for all external-contributor workflows where supported.

The November 28, 2026 audit at `a68db8ed88bdfc2a2cf8261f437afdc0eecebc66`
found Checkout 6.1.0 and Setup Terraform 4.0.1 allowed, with dependency graph,
Dependabot alerts and private reporting disabled. The completed rollout at
`7cd4faf5e8fc9af0531e6e372ce1329cc41350a2` verified the updated controls below.
These recorded observations were not re-queried for the local rollback correction:

| Control | Verified state |
| --- | --- |
| Main branch | Pull requests, both named CI checks from GitHub Actions, strict up-to-date branches and resolved conversations required |
| Administrator enforcement | Enabled; no PR bypass users, teams or apps configured |
| Force pushes and branch deletion | Blocked |
| Reviewers | Zero required approving reviewers; solo maintenance is not independent two-person review |
| Actions | Exact Checkout 7.0.1 pin only; broad GitHub-owned/verified-creator allowances disabled; full-length SHA enforcement enabled |
| Workflow tokens | Read-only defaults; workflow PR creation/approval disabled |
| External contributors | Workflow approval required for all external contributors |
| Secret scanning and push protection | Enabled; no open secret-scanning alerts returned |
| Dependency graph | Enabled; SBOM contained the repository and two current action pins, with no Setup Terraform |
| Dependabot alerts | Enabled; zero open alerts returned; automatic dependency/security updates remain disabled |
| Private vulnerability reporting | Enabled |
| CD workflows | Both disabled; CI active |

These are repository observations, not independently verified live AWS state.
Published Terraform retains deny-only federation and an explicit deny-all in the
attached deployment policy. Neither source inspection nor earlier state snapshots
prove those controls are still applied in AWS. This review used no AWS credentials.

The original audit's source and Git-history privacy checks found no unintended sensitive values across
102 committed blob objects. Twelve retained log archives from 14 run records,
74 log members and 26 check outputs/annotation sets were reviewed. The previously
cleaned exposing archive remains unavailable and its run record is intact. The
other unavailable archive belongs to a startup-failure run. No artifacts or caches
were present. Numeric matches in generated annotation URLs were proven to be
GitHub check-run IDs, not AWS account values. No additional log cleanup was needed
or performed. Pattern scans are not a guarantee against every possible secret.

## Dependency review and open findings

The November 28, 2026 follow-up reviewed all **55 distinct npm advisories** from
previous lock audits, plus three Go advisory records. Severity and affected ranges
were checked against official advisory records; propagated npm dependency entries
were not counted as separate vulnerabilities. Official action source, shipped
`dist` bundles, call sites and local Go binary build metadata were inspected.
This is a static applicability review, not a proof that every runtime path is safe.

| Component | Audited baseline | Hardening change | Remaining findings |
| --- | --- | --- | --- |
| Checkout | 6.1.0 | 7.0.1, `3d3c42e5aac5ba805825da76410c181273ba90b1` | Undici 6.27.0 still has 11 advisory matches, including high-severity network-response DoS |
| Setup Terraform | 4.0.1 | Removed; verified official archive installer | Its Axios, redirect, multipart and Undici bundles no longer execute in CI |
| AWS Credentials, disabled CD only | 6.3.0 | 6.3.1, `45666896f5d8e0f10ae255413f3a4cdd03bdc8f5` | Zero current npm audit matches; this is not a vulnerability-free guarantee |
| Terraform CLI | 1.17.2 | Unchanged; latest stable | Two medium OpenTelemetry advisories; OpenPGP warning not applicable to the reviewed implementation |
| AWS provider | 6.74.0 | Unchanged; latest stable | No matches in the checked declared-module dataset; not a complete binary/standard-library audit |

The audit recorded the **baseline** Checkout/Setup Terraform allowlist above.
The completed rollout narrowed it to the replacement Checkout pin after successful
PR and main CI; effective repository settings were verified separately from source changes. Both CD
workflows remain disabled, and the credential action is excluded from the CI
allowlist. These repository observations do not verify live AWS controls.

### Action applicability and upstream fixes

- **Checkout:** 7.0.1 is a partial net improvement for this workflow, not an
  advisory-free release. The reviewed REST client moves from Undici 5.29.0 to
  6.27.0. It fixes [response-queue poisoning](https://github.com/nodejs/undici/security/advisories/GHSA-35p6-xmwp-9g52),
  which can misassociate responses on reused connections, and
  [unbounded response decompression](https://github.com/nodejs/undici/security/advisories/GHSA-g9mf-h72j-4rw9).
  Those paths can run during REST fallback/default-branch lookup and commit
  telemetry. Normal repository transfer uses Git. The benefit is removing an
  integrity failure and unbounded resource exhaustion from an occasionally used
  HTTP path, rather than merely reducing manifest counts. Removing Busboy/UUID
  findings is not counted as decisive: their vulnerable multipart and v3/v5/v6
  buffer APIs were not used here.

  The tradeoff is explicit: 6.27.0 still matches 11 advisories, including
  TLS 1.2 renegotiation DoS and a newer excessive-content-encoding crash. Both
  require malicious or compromised contacted endpoints. This does not provide
  an availability guarantee; the new crash is not treated as fixed. Other new
  matches involve unused WebSocket/EventSource APIs. Cookie helpers, retry
  interceptors, blob request bodies and custom TLS verification callbacks are
  also not configured. Fixed GitHub HTTPS destinations, read-only tokens,
  disabled credential persistence and no AWS authentication constrain impact.
  The completed rollout verified the exact allowlist and Node 24 hosted compatibility;
  future action changes require the same review.
- **Setup Terraform:** 4.0.1 remains the latest stable upstream action but its
  affected Axios/redirect/form/Undici bundles are removed from CI.
  Replacing the action also closes its installation path's missing explicit
  archive-verification step. No fork, transitive override or new package dependency
  is used; the replacement uses Ubuntu's Python standard library and GPG.
- **AWS Credentials:** 6.3.1 is an official patch release and raises basic-ftp to
  6.2.6, ip-address to 10.7.5 and Undici to 6.29.1, outside all reviewed ranges.
  The old FTP/listing and IP-classification findings were in the optional
  proxy/PAC/SOCKS chain, without a matching configured input. OIDC token retrieval
  uses the bundled HTTP client, but no credential action executes in active CI.
  The local patch does not enable CD or add this action to the CI allowlist.

See the official [Checkout release](https://github.com/actions/checkout/releases/tag/v7.0.1),
[AWS Credentials release](https://github.com/aws-actions/configure-aws-credentials/releases/tag/v6.3.1),
[Setup Terraform releases](https://github.com/hashicorp/setup-terraform/releases),
[Undici TLS advisory](https://github.com/nodejs/undici/security/advisories/GHSA-2m5v-pch6-74hx),
[Undici response DoS advisory](https://github.com/nodejs/undici/security/advisories/GHSA-xjj6-f33q-929c),
and [Axios advisories](https://github.com/axios/axios/security/advisories).

### Terraform applicability and artifact integrity

Terraform's binary includes OpenTelemetry 1.45.0/SDK log 0.21.0. Both
[GO-2026-6974](https://pkg.go.dev/vuln/GO-2026-6974) (attribute-limit bypass) and
[GO-2026-6975](https://pkg.go.dev/vuln/GO-2026-6975) (bounded baggage allocation
amplification) are medium severity, CVSS 5.3, and fixed upstream in 1.47.0.
The CLI enables exporting and baggage propagation only when
`OTEL_TRACES_EXPORTER=otlp`; CI sets neither that option nor inbound baggage.
The workflow runs formatting, initialization, validation and a fully mocked test,
not a public telemetry server. The affected code is included, but a hostile input
path was not established for these jobs. No patched stable Terraform CLI was
available, so its modules were not overridden or rebuilt locally.

The [GO-2026-5932](https://pkg.go.dev/vuln/GO-2026-5932) warning concerns the obsolete
`golang.org/x/crypto/openpgp` package. Terraform's source and reviewed Windows
binary use the maintained `github.com/ProtonMail/go-crypto/openpgp` implementation
instead. The old package path was absent from the binary; merely declaring
x/crypto 0.58.0 is not evidence of that OpenPGP exposure. The Go record supplies
no CVSS severity. Provider 6.74.0 has newer OpenTelemetry 1.47.0/x/crypto 0.59.0.
A complete Go standard-library and symbol-level vulnerability scan remains outside
this review; Linux binary execution was unavailable locally.

All reviewed action SHAs resolve to official stable tags; Checkout and AWS
Credentials commits have GitHub-verified signatures. Downloaded action files
matched official Git tree blob hashes. Locally recorded archive SHA-256 values
are evidence hashes, not signed upstream attestations or reproducible builds.
Official Windows/Linux Terraform and provider archive hashes matched HashiCorp's
manifests; provider hashes also matched the unchanged lock, and installed Windows
binaries matched their archives. Local detached-signature execution was unavailable
because the installed GPG runtime failed to start. The verified hosted run above subsequently passed real GPG checks and the
production installer; local GPG execution remains unavailable. Signature and hash
verification remain mandatory hosted gates for future revisions.

### Verified Terraform installation

`scripts/ci/install_terraform.py` supports only Linux x86_64 and Terraform 1.17.2.
It downloads from the fixed official HTTPS endpoints without redirects or retries.
Its trust anchors are:

- Primary signing fingerprint: `C874011F0AB405110D02105534365D9472D7468F`,
  independently checked against HashiCorp's
  [key-update bulletin](https://discuss.hashicorp.com/t/hcsec-2026-03-hashicorp-gpg-key-72d7468f-update/77237)
  and calculated from the downloaded public key. The bulletin extends expiry to
  March 1, 2030; an expired/revoked signing key still fails verification.
- Archive: `terraform_1.17.2_linux_amd64.zip`.
- Exact SHA-256: `e6f16b2f0b137ee5729caa8c4e79a3bae4ee261acd198a1fcfa8584a6296605b`,
  checked against the official release manifest and downloaded archive.

A private temporary GPG home excludes user configuration/keyrings and automatic
key retrieval/import. The installer checks the single primary fingerprint before
import, requires one valid detached manifest signature from that primary or its
GPG-authorized subkey, rejects expiration/revocation and weak signature digests,
then requires exactly one matching manifest entry with the pinned archive hash.
GnuPG's informational `KEYEXPIRED` can describe an unused subkey and does not
invalidate an otherwise verified signature. The signer-specific `EXPKEYSIG`,
`REVKEYSIG` and expired/invalid-signature statuses still stop verification, as does
any nonzero GPG exit. Rejection diagnostics include only fixed status names and
exit codes, excluding key IDs, identities and raw output. See the
[GnuPG status specification](https://github.com/gpg/gnupg/blob/master/doc/DETAILS).
Only after signature and hash checks does it extract the expected regular binary
into a private runner directory and append that directory to `GITHUB_PATH`.
Missing GPG, network errors, unexpected archive entries and verification failures
stop the job. No unverified binary is executed, no system installation is changed,
and no root privileges or additional packages are needed.

The existing formatting, `-backend=false -lockfile=readonly` initialization,
validation and fully mocked Terraform test steps remain unchanged. Provider
verification stays authoritative through the committed lock. Version, key or hash
changes require a reviewed update against official release evidence, never an
emergency verification bypass.

Nineteen artifact-verification tests cover wrong keys/signers, invalid/expired/revoked signatures,
missing/duplicate/malformed checksum entries, corrupted archives, unsafe entries,
download failures and verification-before-extraction/path-export ordering. Public
key/manifest/signature fixtures enable offline Linux GPG acceptance and tampering
checks, including actual-signer expiration at a synthetic future verification time
inside the negative test only. They contain no private keys. Actual download,
signature and archive checksum verification, Linux execution, locked initialization
and Terraform validation passed in the earlier
[dependency-hardening main run](https://github.com/BirdIsOffline/aws-cloud-infrastructure/actions/runs/46124737536).
All **140 Python tests
plus one mocked Terraform test** passed with zero skips in that historical
hardening run. The corrected monitoring release subsequently passed the complete
162-test suite and mocked Terraform test linked above. Earlier 121- and 140-test
results remain historical evidence.

### Safe rollout and alerting

This sequence records the completed dependency-hardening rollout. The original
failed run was preserved, the narrow GPG correction passed protected PR/main CI,
the final allowlist was reduced to Checkout alone, and the free reporting/alerting
features were enabled. Future changes require a fresh review of the same gates.

1. With separate settings approval, temporarily add only
   `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` beside the two
   existing baseline pins. Keep full-SHA enforcement and broad allowances disabled.
   The AWS credential action remains excluded; CD remains disabled.
2. Publish through the protected PR procedure. Require both jobs, all 140 Python
   tests and the mocked Terraform test on Ubuntu with zero skips. This includes
   real GPG positive/tampering checks and the actual verified installer before
   Terraform execution. Review Node 24 compatibility, runtime and logs.
3. After successful merge/main CI, remove both the old Checkout and Setup Terraform
   entries. The final allowlist contains **only**
   `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1`. Verify the effective settings after
   rollout. If verification fails, stop and retain the existing main;
   correct only through reviewed changes, never by restoring an unverified download
   fallback or disabling SHA enforcement. Rollback does not require AWS changes.
4. Separately approve free dependency graph, Dependabot alerts and private
   vulnerability reporting. Keep automated dependency/security-update PRs and
   auto-merge disabled. Dependabot does not alert on SHA-pinned action references,
   and coverage does not extend to every prebundled dependency or Terraform Go
   module; retain periodic bundle-aware review.

Residual Checkout and Terraform findings remain open for upstream remediation.
The completed dependency rollout changed no live AWS controls; local validation is not hosted or
live-AWS verification.

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
