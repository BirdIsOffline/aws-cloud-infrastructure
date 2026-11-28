# Testing and recovery results

Testing combines automated checks, isolated Linux simulations and controlled live tests. A passing simulation does not establish complete live recovery.

## Verified results

[Main CI run 46129889618](https://github.com/BirdIsOffline/aws-cloud-infrastructure/actions/runs/46129889618)
passed **162 Python tests and one mocked Terraform test**, with zero failures or
skips. The Python total comprises 116 ordinary tests, 44 isolated recovery cases
and two Linux readiness guards. The mocked Terraform run contains seven assertions.
The production packer verified committed release bytes without candidate adapters.

Historical hosted totals were 114 tests for the initial recovery suite, 121 after
public-IP contract coverage, and 140 after artifact verification. A separate private
operator-wrapper review passed **225 offline checks**: 170 server, 31 controller
and 24 observer checks. Those are not repository CI tests or live recovery results.
Original reports, fingerprints, timing and detailed test evidence remain private.

## Live delivery and website restoration

Live delivery passed authorization, OIDC/STS, one restricted SSM execution and all
four scripts. HTTP, telemetry, retention and masking passed after an earlier
telemetry-check correction.

Repeat-run testing preserved content, metadata, packages, service identities and
backups, with no unnecessary writes, reloads or restarts. Temporary staging and
normal logs/metrics were distinguished from persistent changes.

For website recovery, the operator held the deployment lock, verified durable
private copies, atomically added a harmless HTML comment and used the existing
rollback interface. Exact homepage content, ownership and permissions were restored;
Nginx remained valid, local/public HTTP returned 200 and the former backup URL 404.
No restart/reload was needed. The comment lasted about 0.177 seconds; the sequence
took 0.85 seconds within a 120-second limit. Inode/timestamp changes were expected.
This was not instance-loss recovery.

## Live Agent restoration

**Monitoring recovered, but complete live recovery verification did not pass.**
One retest activated in 1.506 seconds with a 1.165-second inactive interval, below
the 150-second limit. Follow-up found healthy services, approved configuration,
fresh memory/disk metrics, positive access-group ingestion, expected streams,
seven-day retention and a healthy website.

The verification problems remain material:

- An early test lacked an original `common-config.toml` fingerprint and rejected
  its ctime change. Installed-Agent investigation confirmed that activation can
  change metadata without changing content; missing original values were not invented.
- A later wrapper omitted expected `log-config.json` regeneration from its file
  classification. It stopped verification despite unchanged content/security metadata.
  Generated TOML/YAML matched that retest's baseline. YAML comparison allowed only
  a confirmed independent host-receiver permutation, not unknown settings,
  duplicate receivers or reordered processors.
- The 225-check offline review covered corrected classifications and verification
  paths. Missing historical lock, directory, timing and final-observation evidence
  remained missing. Synthetic completion data was used only in labelled fixtures.
- The final attempt aborted before interruption because its inventory check
  rejected package-owned directories/symlinks omitted from the file-only fixture.
  It did not complete a held-lock recovery/telemetry observation.

Later read-only EC2/EBS checks closed the infrastructure query gap, not the recovery
verification gap. No further interruptions were performed to turn these reports
into a pass. There is no demonstrated full live Agent restoration, lossless-telemetry
claim or recovery-time guarantee.

## Alarm notification test

On November 25, 2026, fresh CPU observations and an evaluated OK baseline preceded
exactly one labelled simulated ALARM transition using `SetAlarmState`. Alarm
history recorded a successful SNS action; the alarm returned naturally to OK about
86 seconds later, and receipt of the matching email was confirmed.

No artificial CPU load, direct SNS publish or threshold change was used. This tested
the notification path, **not a genuine 80% CPU breach** or future email-delivery SLA.
The subscription endpoint and unsubscribe links remain private.

## Isolated Linux tests

Run `bash scripts/ci/validate.sh` on Linux with the prerequisites in the
[CI guide](ci-cd.md#running-checks). The runner creates a unique disposable root
under `.local/tests`, with separate network, PID and mount namespaces and no host
mounts, home, credentials, AWS executable or network access. It verifies root
identity and release hashes, strips the environment and drops unnecessary
capabilities. Missing isolation fails closed. This protects reviewed fixtures;
chroot is not a VM-level defense against arbitrary kernel exploits.

Production scripts and executor bytes are copied unchanged. Command substitutes
supply systemd/Nginx/Agent behavior, while real file operations, permissions,
atomic replacement, locks, records, latches and process groups run in isolation.
Failure injection never becomes a production input. Synthetic predecessor
allowances exist only in memory inside fixtures.

| Coverage | Cases |
| --- | ---: |
| Bootstrap prerequisites | 2 |
| Website validation and rollback | 5 |
| Agent validation and recovery | 20 |
| Coordinator, replay and latch | 12 |
| POSIX locks, process interruption and isolation | 5 |

Two readiness guards check root-owned 1777 temporary directories and bare `mktemp`;
a prior failed CI run exposed missing `/tmp`. Thirteen portable guards check runner
isolation and bounded, sanitized diagnostics. The complete isolated suite has a
180-second limit, individual Bash cases 20 seconds, and no automatic retry.
Cleanup rechecks the fixture path, nonce and marker before recursive deletion.

## Monitoring rollback regression coverage

The corrected release added 13 isolated cases for no-predecessor cleanup, failed
or incomplete removal, incorrect service state, mismatched/missing cache,
conflicting source, unconfigured/inactive Agent, prior inactivity, ignored stop,
consumed source and Terraform-owned retention. Nine portable tests execute the
actual JSON-verifier heredoc against malformed, mismatched, linked and non-regular
synthetic inputs. All passed on Ubuntu.

This corrected repository release is **not deployed to AWS**. It changes neither
the earlier live outcomes nor their limitations. Future live testing needs its own
baseline, recovery copies, lock, bounded timing and explicit authorization.
