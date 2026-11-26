# Testing, resilience and recovery record

The resilience testing phase is concluded. Results below distinguish hosted
Linux simulations, private offline verification, and separately authorized live
tests. Earlier failed or incomplete reports remain preserved; later health
confirmation does not retroactively turn them into passing recovery tests.

## Verified outcomes

| Evidence | Result | Verification boundary |
| --- | --- | --- |
| Latest hosted Ubuntu CI | 121 Python tests passed, zero skips/failures/errors | 88 ordinary tests, 31 isolated recovery cases, two Linux readiness guards |
| Mocked Terraform test | One run passed with seven assertions | Offline denial, sensitivity, boundary/role and public-IP creation checks; no AWS apply |
| Historical hosted recovery baseline | 114 tests passed, zero skips/failures/errors | 81 ordinary tests, 31 isolated recovery cases, two Linux readiness guards |
| Private operator-wrapper checks | 225 passed: 170 server, 31 controller, 24 observer | Offline replay/adapters and negative cases; separate from repository CI and live recovery |
| OIDC-authenticated delivery | End-to-end success after telemetry correction | Exact-commit authorization, temporary role assumption, restricted SSM, four zero exits, HTTP, monitoring and masking |
| Live idempotency | Strict configuration idempotency demonstrated | Compliant-file content/metadata, packages, service identities and backup inventory unchanged |
| Live website restoration | Passed | Approved homepage restored through the existing rollback interface under the deployment lock |
| Live Agent restoration | Monitoring recovered; complete verification did not pass | Baseline/metadata-classification gaps and final preflight abort are recorded below |
| CloudWatch-to-SNS notification | Successful action and operator-confirmed matching email | One simulated ALARM transition; no genuine CPU threshold breach |

The latest verified hosted result is recorded at
[CI run 45759551505](https://github.com/BirdIsOffline/aws-cloud-infrastructure/actions/runs/45759551505)
for commit `f6a5976faaabb401aa06f056b9c06d74b2d3b156`: 121 Python tests plus
one mocked Terraform test, with zero skips. The historical recovery baseline is at
[CI run 45578485098](https://github.com/BirdIsOffline/aws-cloud-infrastructure/actions/runs/45578485098)
for source commit `0c02cb9f26449f93d147f49c1b324004a7249e04`. Run visibility
follows repository access settings. Private operator evidence and its
225-check harness are not included in the public source or the hosted test total.

## Live deployment and strict idempotency

The corrected authenticated deployment completed authorization, OIDC/STS,
exactly one restricted SSM execution, and all four server scripts at exit 0.
Local/public HTTP returned 200 with approved content; the former backup URL
returned 404. Fresh memory/disk observations, positive access-group ingestion,
expected streams, seven-day retention and runtime identifier masking passed.

Controlled repeat-run testing compared checksums, inodes, mtime/ctime, numeric
ownership, permissions, package versions, service processes/activation timestamps
and recovery backup inventory. Compliant targets were unchanged: no unnecessary
package transaction, file replacement, metadata write, reload, restart or backup.
Temporary staging/operation records, request logs and normal metric delivery are
expected activity and were distinguished from persistent configuration changes.

## Live website restoration

The operator held the existing deployment lock and verified durable private
copies before atomically adding one harmless HTML comment. The existing website
rollback interface returned 0 and restored the exact approved homepage, ownership
and permissions. Nginx configuration remained valid; local/public HTTP returned
200 and the former backup URL 404. Service identities and package inventory were
unchanged, with no unnecessary restart/reload and no residual latch or command.

The controlled comment was exposed for approximately 0.177 seconds; the normal
test sequence took 0.85 seconds, within its 120-second bound. Atomic restoration
changed homepage inode, mtime and ctime, and document-root directory timestamps.
Those intentional changes were recorded rather than described as idempotency.
Original content/security metadata and pre-existing backups were preserved.
This was a live reversible restoration exercise, not instance-loss recovery.

## Live CloudWatch Agent restoration: closed with limitations

Earlier controlled interruptions were followed by a successful unchanged
monitoring rollback interface and healthy Agent service. A recorded retest
completed activation in 1.506 seconds, with an inactive interval of 1.165 seconds,
below the 150-second activation bound. Read-only follow-up confirmed approved
configuration, fresh memory/disk metrics and positive access-group ingestion,
expected streams, seven-day retention, and continued website health.

The complete live verification did not pass:

- The first run lacked a persisted original `common-config.toml` fingerprint and
  rejected its ctime change. Installed-version investigation established that
  native activation can change metadata without changing configuration content.
- A later retest persisted ten original file fingerprints and verified their
  content/security metadata, but its private wrapper omitted native
  `log-config.json` regeneration from the permitted timestamp classification.
  It stopped verification despite unchanged bytes, ownership, permissions, file
  type, links and inode for that file.
- Investigation compared generated YAML semantics, allowing only the confirmed
  permutation of two independent host receivers. Unknown settings, duplicate
  receivers, processor reordering and other semantic changes were not accepted.
  The retest's generated TOML/YAML were byte-identical to its own baseline.
- The subsequent 225-check offline review exercised corrected file-by-file
  classifications and the complete verification path. Missing historical lock,
  directory, timing and final-observation evidence remained missing; synthetic
  completion data was labelled and used only in offline fixtures.
- The final authorized attempt aborted during preflight before stopping the
  Agent. Its website inventory predicate rejected existing package-owned
  directories/symlinks omitted from the file-only offline fixture. No recovery
  occurred in that attempt, and the full held-lock observation was not reached.

The outstanding read-only EC2/EBS checks were subsequently completed during the
alarm-test preflight, with unchanged identities/configuration and healthy
services. That closes the infrastructure query gap, not the incomplete recovery
verification. All previous evidence is preserved, and this testing phase is
closed without further interruptions or wrapper corrections. No complete live
Agent recovery pass, recovery-time guarantee, or proof of lossless telemetry is
claimed.

## CloudWatch alarm-to-email notification

On November 25, 2026, preflight established fresh healthy CPU observations and
an evaluated OK alarm baseline, enabled actions, the intended SNS topic and one
confirmed email subscription. The operator performed exactly one labelled
**simulated** ALARM transition with `SetAlarmState` at 4:09:23 p.m. EST. Alarm
history recorded a successful SNS action immediately afterward. The alarm
returned naturally to evaluated OK at 4:10:49 p.m., approximately 86 seconds later.
The operator subsequently confirmed receipt of the matching notification email.
This confirmation supplements the preserved execution report, which recorded
receipt as pending when it was written; that historical report is unchanged.

No artificial CPU load, direct SNS publish, repeated transition or alarm
configuration change was used. This verifies the alarm action, SNS path and
observed email receipt for that test. It does not test a genuine 80% CPU breach,
establish a notification-delivery SLA, or prove future mailbox delivery.
Infrastructure, Terraform state, the subscription configuration and protected
source hashes remained intact. No email address, message body or unsubscribe
link is published.

## Isolated Linux harness

The harness runs offline simulations, not live server tests. Bare `mktemp`, used
by unchanged server verification, requires `/tmp` when `TMPDIR` is unset. A failed
initial hosted run exposed its absence from the disposable root. The corrected
fixture creates/resets root-owned `/tmp` and `/var/tmp` with mode 1777. Two Linux
readiness guards reproduce the omission and verify safe bare `mktemp` behavior.

## Isolation and execution

Run the existing CI entry point from the repository root:

```bash
bash scripts/ci/validate.sh
```

It runs the existing security tests and portable harness guards, then invokes
`python3 -B tests/recovery_runner.py`. On Linux, the latter requires the existing
system Python, core utilities, `ldd`, `unshare`, and passwordless `sudo` (unless
already root). Hosted Ubuntu verified these prerequisites and namespace support.
Every execution checks them again. Missing
privileges, tools, or namespace support fail CI; Linux never silently skips the
recovery suite. No packages, distributions, images, or dependencies are installed.
On other platforms the runner explicitly reports that Linux cases did not execute.

The supervisor creates a unique private fixture under ignored `.local/tests`.
It copies only the seven release inputs, unchanged executor, release contract,
test code, and required system runtime files. Release hashes are checked.
It does not copy Terraform, credentials, Git metadata, host configuration, or home
directories. Synthetic account/group files provide only the fixture root identity.

The suite runs as namespace root in a disposable chroot with separate network,
PID, and mount namespaces. No host directories or devices are mounted. Network
interfaces are unavailable, and no AWS executable or credentials exist inside.
The runtime retains only ownership, file-access, and process-signal capabilities;
mount, namespace, network administration, and further chroot capabilities are
dropped. A root identity check prevents fixture execution on the host. This is
isolation for reviewed test code, not a claim that chroot replaces a VM against
arbitrary hostile kernel exploits.

Production Bash and executor bytes are unchanged. Nginx, systemd, RPM/DNF,
curl, and Agent commands are explicit fixture substitutes. The executor's HTTP
connection uses an in-memory response substitute; no HTTP server or AWS call is
needed. Bash file operations, atomic replacement, error traps, backup paths,
Linux permissions, executor records, latch files, `flock`, and subprocess groups
operate on real disposable files and processes.

The production contract permits only the current homepage baseline. Coordinator
recovery cases supply a synthetic predecessor allowance in an in-memory test
contract to reach the changed-release branch. The fixture also explicitly verifies
that the unchanged production contract rejects that predecessor. No modified
contract, injected command, or fault parameter is sent to a live document.

## Coverage and expected outcomes

Individual test names and outcomes appear in unittest output; every Linux case
is mandatory. The 31 Linux cases cover:

| Area | Cases | Expected evidence |
| --- | ---: | --- |
| Bootstrap prerequisites | 2 | Missing packages exit 5 in check mode; compliant bootstrap exits 0; DNF never runs |
| Website deployment/recovery | 5 | Invalid HTML/Nginx exit 20 before writes; post-replacement failure restores baseline and exits 40; failed rollback exits 41; explicit rollback restores bytes and 0644 ownership/mode |
| Agent validation/recovery | 7 | Invalid JSON, translation and schema failures exit 20; activation failure restores configuration and exits 40; failed recovery exits 41 with private backups; healthy cache avoids activation; consumed input is supported |
| Coordinator and latch | 12 | Modified bundles and unapproved baselines reject; prerequisite/candidate failure precedes latch/backups; success records four zero exits and clears latch; ordinary failure restores website/Agent/source presence; failure retains latch; replay and alternate operations are blocked; fixture-only operator recovery is explicit; timeout skips unsafe recovery |
| POSIX/process/isolation | 5 | Real lock contention rejects a second executor; subprocess timeout terminates its group; TERM-resistant child requires KILL; interrupted coordinator leaves durable latch after lock release; host escape and network access are unavailable |

Existing authorization and bundle tests cover denied actors/branches/CI results,
modified privileged inputs, paths, links, compression, sizes and metadata.
Existing orchestration tests verify single submission, ambiguous responses,
polling deadlines, and no redeployment after verification failure. Eleven portable
guard tests cover environment stripping, workspace/path identity, nonce checks,
namespace enforcement, argument rejection, source allowlist, platform handling,
and absence of skipped Linux cases. Two further portable tests verify diagnostic
redaction and bounded output, for 13 portable guards in total.

Temporary-directory metadata and a real bare `mktemp` are checked before every
recovery case, after fixture reset. No host temporary directory is mounted.
The verification HTTP fault targets the status-requesting invocation, rather than
an HTTP call count, and is injected only once. Recovery assertions verify that
it occurred; the fault cannot shift into a website rollback request.

Unexpected errors emit only allowlisted script exit codes, record/recovery states,
and fixed diagnostic categories from at most 32 KiB of private subprocess output.
Raw subprocess text, paths, payloads and identifiers are not forwarded. Diagnostics
are collected before fixture cleanup; they do not change failure status or retry.

Website backups may preserve 0644 files inside root-owned 0700 directories;
coordinator copies and private diagnostics use 0600. Assertions check content,
numeric ownership, modes, link counts, recovery records, and latch state. Recovery
is not expected to preserve the original inode or ctime after atomic replacement.

## Bounds and cleanup

Each Bash fixture has a 20-second bound and group termination on timeout.
Executor timeout tests use only disposable child processes. The interruption case
verifies why releasing a lock does not prove child quiescence, then terminates and
reaps its fixture children. PID namespace exit supplies a final process boundary.
The complete isolated suite has a 180-second bound and no automatic retry.

Before recursive cleanup, the supervisor revalidates the exact absolute path,
workspace containment, regular single-link marker, and unique nonce. A mismatched
identity stops cleanup. It never accepts an arbitrary deletion directory.

## Evidence boundaries and future operations

Local checks can establish syntax, source hygiene, release integrity, portable
guard behavior, regression results, and static tooling results. They cannot
establish Linux recovery success on Windows. The historical corrected recovery
run executed 81 ordinary tests, 31 recovery cases and two Linux readiness guards:
114 total, zero skips. The 225 private offline checks are a separate result and
must not be added to that hosted total or described as reproducible repository CI.
The latest verified suite adds seven Python lifecycle-contract tests, for 121
Python tests, plus one fully mocked Terraform test; it does not add another live
recovery outcome or change the Agent-verification limitations.

The Linux harness demonstrates simulated recovery with command substitutes.
The live outcomes and Agent limitations are documented above. Cancellation,
ambiguous timeout, failed automatic recovery, latch clearance, and concurrent
deployment failures were exercised in isolation, not deliberately on the instance.
Any additional live operations require separate scope and approval. This record
does not authorize repeating recovery tests or publishing notifications.

Public evidence should include source commit, case name, simulated/live label,
exit code, restoration/permission/latch assertions, and durations. Exclude raw
inventory, credentials, identifiers, addresses, emails, private payloads and backup
contents. Do not upload the disposable filesystem as an artifact.
