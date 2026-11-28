# CI and repository checks

CI runs on pushes to main, pull requests targeting main and manual dispatch. The
[workflow](../.github/workflows/ci.yml) has two Ubuntu 24.04 jobs:

| Job | Checks |
| --- | --- |
| Source and server automation | Hygiene, Bash/ShellCheck, JSON and HTML contracts, release bundle, Python tests and isolated Linux recovery |
| Terraform formatting and validation | Verified CLI installation, formatting, locked initialization, validation and one fully mocked test |

Terraform waits for source validation. Timeouts are ten and twenty minutes,
respectively. New CI runs cancel superseded work for the same ref. CI has `contents: read`, disables checkout credential
persistence, and receives no AWS credentials, deployment secrets or OIDC permission.

## Running checks

On Linux, use Bash, Python 3, Git, GPG and ShellCheck:

```bash
bash scripts/ci/validate.sh
```

The recovery runner also needs `unshare`, `ldd`, core utilities and passwordless
sudo unless already root. It requires separate network, PID and mount namespaces
plus a disposable chroot. Missing Linux isolation fails the job. Windows can run
portable checks but cannot reproduce that environment; see
[recovery testing](recovery-testing.md#isolated-linux-tests).

For Terraform, from `terraform/`:

```bash
terraform fmt -check -recursive
terraform init -backend=false -input=false -lockfile=readonly
terraform validate
terraform test
```

CI uses Terraform 1.17.2 and the committed AWS 6.74.0 lock file. Initialization
requires public registry/release access but no AWS authentication. The mocked test
uses disposable test state and checks deployment denial, the permission boundary,
EC2 role, trust sensitivity and public-IP creation intent. It does not apply
against AWS or use the adopted state. CI never plans or deploys infrastructure.

The production packer requires release files to match committed Git HEAD bytes.
Before committing a release change, candidate decoding can check content and size,
but cannot prove the files belong to a commit. Do not relax the production check to make a
working-tree release pass.

## Repository hygiene and action pins

The scanner checks tracked and non-ignored source for private files, symlinks,
encoding, LF endings, syntax and sensitive-value patterns without printing matches.
It catches force-added state, plans, credentials and backups. Gitleaks and manual
review supplement these checks.
Keep `.terraform.lock.hcl` tracked; keep runtime evidence in ignored local storage.

The only allowed CI action is:

`actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` — v7.0.1.

The disabled executor also pins AWS Credentials v6.3.1 at
`45666896f5d8e0f10ae255413f3a4cdd03bdc8f5`; it is excluded from the allowlist.
Setup Terraform was removed. Future action changes need checks against official upstream releases,
a temporary exact-pin allowance if necessary, protected PR CI, and removal of
superseded entries after successful main CI.

## Repository protections and solo maintenance

Publication checks verified PRs, both named CI checks, up-to-date branches,
resolved conversations and administrator enforcement on main. Force pushes and
deletion are blocked. Zero independent approving reviewers are required.

Actions use full-length SHA enforcement, the exact allowlist, read-only default
tokens, disabled workflow PR creation/approval, and approval for all external
contributors. Broad GitHub-owned and verified-creator allowances are off. Secret
scanning, push protection, dependency graph, Dependabot alerts and private reporting
are enabled; automatic dependency/security updates remain disabled. Both CD
workflows remain individually disabled. These are recorded GitHub checks, not
independent verification of live AWS state.

## Verified Terraform installation

[install_terraform.py](../scripts/ci/install_terraform.py) downloads the official
Linux AMD64 1.17.2 archive. Before extraction or execution it requires the pinned
HashiCorp primary-key fingerprint, a valid detached signature on the checksum
manifest, its exact archive entry and the separately pinned archive SHA-256.
The key and hash constants in the installer are the reference values.

A private GPG home excludes user configuration and automatic key retrieval.
Invalid, revoked or expired actual signers/signatures and failed GPG commands
stop installation. Informational `KEYEXPIRED` for an unused subkey does not
invalidate an otherwise valid signature. Weak hashes, unexpected ZIP entries,
redirects and oversized downloads are rejected; there is no fallback. Only the
verified binary directory is added to `GITHUB_PATH`.

Nineteen tests cover these gates, including real Linux GPG acceptance, tampering
and actual-signer expiry. Hosted CI also verified the actual download, signature,
checksum and locked provider initialization. See the
[HashiCorp key bulletin](https://discuss.hashicorp.com/t/hcsec-2026-03-hashicorp-gpg-key-72d7468f-update/77237)
and [GnuPG status specification](https://github.com/gpg/gnupg/blob/master/doc/DETAILS).

## Dependency review and open findings

The November 28, 2026 review found Checkout 7.0.1 a net improvement: its Undici
update fixes response-queue poisoning and unbounded decompression. Remaining
response-handling DoS findings require hostile contacted endpoints. Unused
WebSocket, cookie and retry APIs were distinguished from reachable HTTP paths.
Fixed GitHub destinations and read-only tokens limit impact but do not remove it.

Terraform 1.17.2 includes two medium OpenTelemetry findings,
[GO-2026-6974](https://pkg.go.dev/vuln/GO-2026-6974) and
[GO-2026-6975](https://pkg.go.dev/vuln/GO-2026-6975). CI does not enable the affected
OTLP exporter/baggage path. The legacy OpenPGP warning concerned a different
implementation and did not apply to the inspected binary. AWS Credentials had
no matches in the reviewed npm dataset and runs only in disabled CD. Provider
module checks found no matching advisories, but were not a complete binary or
standard-library audit.
Dependabot returned no open alerts at publication; SHA-pinned actions and bundled
npm/Go dependencies are not fully covered. Detailed advisory, package and artifact
records remain private. The [testing record](recovery-testing.md) links the verified
162-test result and separates CI evidence from live deployment and recovery.
