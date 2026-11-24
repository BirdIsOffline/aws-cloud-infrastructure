#!/usr/bin/env bash
# Local/CI static validation only. Never run the server deployment entry points.
set -Eeuo pipefail
export LC_ALL=C
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd -- "$repo"
for tool in python3 bash shellcheck git; do
  command -v "$tool" >/dev/null || { printf 'Missing CI prerequisite: %s\n' "$tool" >&2; exit 5; }
done
python3 scripts/ci/validate.py
for script in scripts/*.sh scripts/ci/*.sh; do
  bash -n "$script"
  shellcheck "$script"
done
echo 'PASS: Bash syntax and ShellCheck (all severities).'
