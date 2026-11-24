#!/usr/bin/env bash
# Install only missing prerequisites; configuration/deployment are separate steps.
set -Eeuo pipefail
export LC_ALL=C
usage() { printf 'Usage: bash scripts/bootstrap.sh [--check]\n'; }
case "${1:-}" in --help|-h) usage; exit 0;; --check) check=1;; '') check=0;; *) usage >&2; exit 2;; esac
[[ $# -le 1 ]] || { usage >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo 'Run as root on Amazon Linux 2023.' >&2; exit 3; }
[[ -r /etc/os-release ]] || exit 3
# os-release is trusted OS metadata, not an application environment file.
# shellcheck source=/dev/null
. /etc/os-release
[[ $ID == amzn && $VERSION_ID == 2023 ]] || { echo 'Amazon Linux 2023 is required.' >&2; exit 3; }
for command in rpm dnf systemctl; do
  command -v "$command" >/dev/null || { printf 'Missing prerequisite: %s\n' "$command" >&2; exit 5; }
done
missing=()
for package in nginx amazon-cloudwatch-agent python3; do
  rpm -q "$package" >/dev/null 2>&1 || missing+=("$package")
done
# AL2023 supplies curl through curl-minimal; do not replace a working curl.
command -v curl >/dev/null || missing+=(curl-minimal)
command -v cmp >/dev/null || missing+=(diffutils)
for command in install mktemp realpath stat cp mv chmod chown rm rmdir date; do
  if ! command -v "$command" >/dev/null; then missing+=(coreutils); break; fi
done
if ((${#missing[@]})); then
  printf 'Missing required package: %s\n' "${missing[@]}"
  if ((check)); then exit 5; fi
  dnf install -y "${missing[@]}"
else
  echo 'Required packages already installed; no package transaction needed.'
fi
if ((check)); then
  echo 'Prerequisite check passed. No packages or service settings changed.'
  exit 0
fi
for service in nginx amazon-cloudwatch-agent; do
  if ! systemctl is-enabled --quiet "$service"; then systemctl enable "$service"; fi
done
echo 'Bootstrap complete. Services are enabled; deploy and configure them separately.'
