#!/usr/bin/env bash
# Deploy two owned files. Backups are private and outside the document root.
set -Eeuo pipefail
export LC_ALL=C
usage() { echo 'Usage: bash scripts/deploy-website.sh [--check | --rollback BACKUP_DIRECTORY]'; }
mode=deploy; restore_from=''
case "${1:-}" in
  --help|-h) usage; exit 0;;
  --check) [[ $# == 1 ]] || exit 2; mode=check;;
  --rollback) [[ $# == 2 ]] || exit 2; mode=rollback; restore_from=$2;;
  '') [[ $# == 0 ]] || exit 2;;
  *) usage >&2; exit 2;;
esac
[[ $EUID -eq 0 ]] || { echo 'Root is required.' >&2; exit 3; }
for command in nginx systemctl python3 curl install mktemp cmp realpath stat; do
  command -v "$command" >/dev/null || { printf 'Missing command: %s\n' "$command" >&2; exit 5; }
done
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
root=/usr/share/nginx/html
security=/etc/nginx/conf.d/security.conf
backup_root=/var/backups/aws-portfolio-lab/website
[[ -d $root && ! -L $root && -d /etc/nginx/conf.d && ! -L /etc/nginx/conf.d ]] || exit 3
for target in "$root/index.html" "$security"; do
  [[ ! -L $target && ( ! -e $target || -f $target ) ]] || { echo 'Refusing non-regular deployment target.' >&2; exit 3; }
done
umask 077
stage=$(mktemp -d /var/tmp/aws-portfolio-website.XXXXXX)
backup=''
transaction=0
was_active=0
systemctl is-active --quiet nginx && was_active=1
cleanup() {
  rm -f -- "$stage/index.html" "$stage/security.conf" "$stage/nginx-test.conf" "$stage/response"
  rmdir -- "$stage" 2>/dev/null || true
}
trap cleanup EXIT
ensure_metadata() {
  local target=$1 mode=$2 owner current_mode
  owner=$(stat -c '%u:%g' -- "$target")
  if [[ $owner != 0:0 ]]; then chown root:root -- "$target"; fi
  current_mode=$(stat -c '%a' -- "$target")
  if [[ $current_mode != "$mode" ]]; then chmod "$mode" -- "$target"; fi
}
atomic_install() {
  local source=$1 target=$2 temporary
  temporary=$(mktemp "$(dirname -- "$target")/.aws-portfolio.XXXXXX") || return 1
  if ! install -o root -g root -m 0644 -- "$source" "$temporary"; then rm -f -- "$temporary"; return 1; fi
  if ! mv -fT -- "$temporary" "$target"; then rm -f -- "$temporary"; return 1; fi
}
restore_files() {
  local directory=$1 name target
  for name in index.html security.conf; do
    target=$security; [[ $name != index.html ]] || target=$root/index.html
    if [[ -f $directory/$name.absent ]]; then
      rm -f -- "$target" || return 1
    else
      atomic_install "$directory/$name" "$target" || return 1
    fi
  done
}
on_error() {
  local code=$?
  trap - ERR
  set +e
  if ((transaction)); then
    echo 'Deployment failed; restoring the saved files.' >&2
    if ! restore_files "$backup" || ! nginx -t; then echo "Rollback failed; inspect $backup" >&2; exit 41; fi
    if ((was_active)); then
      systemctl reload nginx || { echo 'Rollback reload failed.' >&2; exit 41; }
    else
      systemctl stop nginx || { echo 'Could not restore the inactive service state.' >&2; exit 41; }
    fi
    printf 'Previous files restored. Backup: %s\n' "$backup" >&2
    exit 40
  fi
  exit "$code"
}
trap on_error ERR
if [[ $mode == rollback ]]; then
  restore_from=$(realpath -e -- "$restore_from")
  [[ $restore_from == "$backup_root/"* && -d $restore_from && ! -L $restore_from && $(stat -c %u "$restore_from") == 0 && $(stat -c %a "$restore_from") == 700 ]] || exit 3
  for name in index.html security.conf; do
    [[ ! -L $restore_from/$name && ! -L $restore_from/$name.absent ]] || exit 3
    [[ -f $restore_from/$name || -f $restore_from/$name.absent ]] || exit 3
  done
  # The normal deployment path backs up the current files before restoring these.
  [[ -f $restore_from/index.html ]] || { echo 'Backup has no homepage; manual recovery is required.' >&2; exit 20; }
  cp -- "$restore_from/index.html" "$stage/index.html"
  if [[ -f $restore_from/security.conf ]]; then cp -- "$restore_from/security.conf" "$stage/security.conf"; else : > "$stage/security.conf"; fi
else
  for file in "$repo/website/index.html" "$repo/config/nginx/security.conf"; do
    [[ -f $file && ! -L $file ]] || exit 3
  done
  cp -- "$repo/website/index.html" "$stage/index.html"
  cp -- "$repo/config/nginx/security.conf" "$stage/security.conf"
fi
if ! python3 - "$stage/index.html" "$stage/security.conf" "$mode" <<'PY'
import pathlib, sys
from html.parser import HTMLParser
text=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert text.lstrip().lower().startswith('<!doctype html'), 'missing HTML doctype'
parser=HTMLParser(convert_charrefs=True); parser.feed(text); parser.close()
assert '<html' in text.lower() and '</html>' in text.lower(), 'incomplete HTML document'
if sys.argv[3] != 'rollback':
    assert '<title>AWS Cloud Infrastructure Lab</title>' in text, 'wrong portfolio title'
    assert 'CI/CD integration is planned.' in ' '.join(text.split()), 'CI/CD wording is incorrect'
security=pathlib.Path(sys.argv[2]).read_text(encoding='utf-8').strip()
assert security in ('server_tokens off;', ''), 'unexpected security drop-in directives'
assert sys.argv[3] == 'rollback' or security, 'empty security drop-in'
PY
then echo 'Candidate HTML or security drop-in validation failed.' >&2; exit 20; fi
printf 'pid %s/nginx.pid;\nevents {}\nhttp { access_log off; include %s/security.conf; }\n' "$stage" "$stage" > "$stage/nginx-test.conf"
# First validate the candidate directive in its HTTP context, then current config.
nginx -t -p "$stage/" -c "$stage/nginx-test.conf" -e stderr || exit 20
nginx -t || exit 20
if [[ $mode == check ]]; then echo 'Staged HTML and security drop-in checks passed; nothing deployed.'; exit 0; fi
index_changed=0; config_changed=0
cmp -s -- "$stage/index.html" "$root/index.html" || index_changed=1
if [[ $mode == rollback && -f $restore_from/security.conf.absent ]]; then
  [[ ! -e $security ]] || config_changed=1
else
  cmp -s -- "$stage/security.conf" "$security" || config_changed=1
fi
if ((index_changed || config_changed)); then
  for directory in /var/backups/aws-portfolio-lab "$backup_root"; do
    [[ ! -L $directory ]] || exit 3
    if [[ -d $directory ]]; then
      ensure_metadata "$directory" 700
    else
      install -d -o root -g root -m 0700 -- "$directory"
    fi
  done
  backup=$(mktemp -d "$backup_root/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
  for name in index.html security.conf; do
    target=$security; [[ $name != index.html ]] || target=$root/index.html
    if [[ -f $target ]]; then cp -p -- "$target" "$backup/$name"; else : > "$backup/$name.absent"; fi
  done
  transaction=1
  if ((index_changed)); then atomic_install "$stage/index.html" "$root/index.html"; fi
  if ((config_changed)); then
    if [[ $mode == rollback && -f $restore_from/security.conf.absent ]]; then rm -f -- "$security"; else atomic_install "$stage/security.conf" "$security"; fi
  fi
fi
ensure_metadata "$root/index.html" 644
if [[ -f $security ]]; then ensure_metadata "$security" 644; fi
nginx -t
if ((was_active)); then
  if ((config_changed)); then systemctl reload nginx; fi
else
  systemctl start nginx
fi
# A static-file-only update needs no reload. Verify the exact served bytes.
curl --silent --show-error --fail --noproxy '*' --max-time 10 --output "$stage/response" http://127.0.0.1/
cmp -- "$stage/index.html" "$stage/response"
transaction=0
[[ ! -e $root/index.html.backup ]] || echo 'NOTICE: legacy index.html.backup is still in the public root; review separate removal/migration.' >&2
if [[ -n $backup ]]; then printf 'Deployment verified. Rollback directory: %s\n' "$backup"; else echo 'Files unchanged; no backup or reload needed. HTTP verified.'; fi
