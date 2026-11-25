# Isolated failure and recovery tests

The recovery harness is implemented for offline Linux execution. The Windows
development machine has no installed WSL distribution; the 31 isolated Linux
cases have not yet executed. Hosted Ubuntu execution is pending approval to
publish. These tests are simulations, not completed live recovery tests.

## Isolation and execution

Run the existing CI entry point from the repository root:

```bash
bash scripts/ci/validate.sh
```

It runs the existing security tests and portable harness guards, then invokes
`python3 -B tests/recovery_runner.py`. On Linux, the latter requires the existing
system Python, core utilities, `ldd`, `unshare`, and passwordless `sudo` (unless
already root). Hosted Ubuntu is the intended execution environment; its first
run must verify these prerequisites and namespace support. Missing
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
and absence of skipped Linux cases.

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

## Evidence and remaining acceptance

Local checks can establish syntax, source hygiene, release integrity, portable
guard behavior, regression results, and static tooling results. They cannot
establish Linux recovery success on Windows. The next hosted run must execute
all 79 ordinary tests and all 31 isolated cases: 110 total, zero skips.

Even a successful Linux run demonstrates simulated recovery with command
substitutes. Actual Amazon Linux Nginx/Agent activation, live rollback, notification
delivery, and operator recovery remain separately approved live tests. The EC2
instance stays stopped during local implementation.

Public evidence should include source commit, case name, simulated/live label,
exit code, restoration/permission/latch assertions, and durations. Exclude raw
inventory, credentials, identifiers, addresses, emails, private payloads and backup
contents. Do not upload the disposable filesystem as an artifact.
