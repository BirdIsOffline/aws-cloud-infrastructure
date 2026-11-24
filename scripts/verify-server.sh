#!/usr/bin/env bash
# Read-only health checks. This generates one normal localhost HTTP request.
set -Eeuo pipefail
export LC_ALL=C
case "${1:-}" in --help|-h) echo 'Usage: bash scripts/verify-server.sh'; exit 0;; '') :;; *) exit 2;; esac
[[ $# -eq 0 ]] || exit 2
[[ $EUID -eq 0 ]] || { echo 'Root is required for nginx configuration validation.' >&2; exit 3; }
for command in systemctl nginx curl python3 mktemp; do
  command -v "$command" >/dev/null || { printf 'Missing command: %s\n' "$command" >&2; exit 5; }
done
systemctl is-active --quiet nginx || { echo 'Nginx is inactive.' >&2; exit 10; }
systemctl is-active --quiet amazon-cloudwatch-agent || { echo 'CloudWatch Agent is inactive.' >&2; exit 11; }
for service in nginx amazon-cloudwatch-agent; do
  systemctl is-enabled --quiet "$service" || { printf 'Service is not enabled: %s\n' "$service" >&2; exit 12; }
done
nginx -t || { echo 'Nginx configuration validation failed.' >&2; exit 20; }
ctl=/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl
[[ -x $ctl ]] || exit 5
umask 077
response=$(mktemp)
trap 'rm -f -- "$response"' EXIT
if ! "$ctl" -a status | python3 -c 'import json,sys; v=json.load(sys.stdin); sys.exit(0 if v.get("status")=="running" and v.get("configstatus")=="configured" else 1)'; then
  echo 'CloudWatch Agent is not running with a configured status.' >&2
  exit 21
fi
if ! code=$(curl --silent --show-error --noproxy '*' --max-time 10 --output "$response" --write-out '%{http_code}' http://127.0.0.1/); then
  echo 'Local HTTP connection failed.' >&2; exit 30
fi
[[ $code == 200 ]] || { printf 'Unexpected HTTP status: %s\n' "$code" >&2; exit 30; }
if ! python3 - "$response" <<'PY'
import pathlib, sys
from html.parser import HTMLParser
class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.in_title=False; self.title=[]; self.text=[]
    def handle_starttag(self, tag, attrs):
        if tag == 'title': self.in_title=True
    def handle_endtag(self, tag):
        if tag == 'title': self.in_title=False
    def handle_data(self, value):
        self.text.append(value)
        if self.in_title: self.title.append(value)
p=Page(); p.feed(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
text=' '.join(' '.join(p.text).split())
assert ''.join(p.title).strip() == 'AWS Cloud Infrastructure Lab', 'unexpected page title'
for expected in ('CloudWatch monitoring and Terraform integration are complete.', 'CI/CD integration is planned.'):
    assert expected in text, 'expected portfolio wording missing'
PY
then echo 'HTTP response is not the expected updated portfolio page.' >&2; exit 31; fi
echo 'PASS: services active/enabled, Nginx syntax valid, Agent configured, HTTP 200, expected portfolio content.'
