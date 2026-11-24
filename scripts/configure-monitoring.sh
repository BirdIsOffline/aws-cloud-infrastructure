#!/usr/bin/env bash
# Manage one Agent source; log-group retention remains Terraform-owned.
set -Eeuo pipefail
export LC_ALL=C
usage() { echo 'Usage: bash scripts/configure-monitoring.sh [--check | --rollback BACKUP_DIRECTORY]'; }
mode=deploy; restore_from=''
case "${1:-}" in
  --help|-h) usage; exit 0;;
  --check) [[ $# == 1 ]] || exit 2; mode=check;;
  --rollback) [[ $# == 2 ]] || exit 2; mode=rollback; restore_from=$2;;
  '') [[ $# == 0 ]] || exit 2;;
  *) usage >&2; exit 2;;
esac
[[ $EUID -eq 0 ]] || { echo 'Root is required.' >&2; exit 3; }
for command in python3 systemctl install mktemp realpath stat cmp; do
  command -v "$command" >/dev/null || { printf 'Missing command: %s\n' "$command" >&2; exit 5; }
done
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
agent=/opt/aws/amazon-cloudwatch-agent
target=$agent/etc/amazon-cloudwatch-agent.json
cached=$agent/etc/amazon-cloudwatch-agent.d/file_amazon-cloudwatch-agent.json
backup_root=/var/backups/aws-portfolio-lab/monitoring
ctl=$agent/bin/amazon-cloudwatch-agent-ctl
for command in "$ctl" "$agent/bin/config-translator" "$agent/bin/amazon-cloudwatch-agent"; do [[ -x $command ]] || exit 5; done
[[ ! -L $target && ! -L $cached && ( ! -e $target || -f $target ) ]] || exit 3
# fetch-config replaces the configuration set. Refuse unknown additional sources.
shopt -s nullglob
for fragment in "$agent/etc/amazon-cloudwatch-agent.d/"*; do
  [[ $fragment == "$cached" && -f $fragment && ! -L $fragment ]] || { echo 'Unmanaged Agent fragment found; review multi-config behavior before proceeding.' >&2; exit 3; }
done
shopt -u nullglob
umask 077
stage=$(mktemp -d /var/tmp/aws-portfolio-monitoring.XXXXXX)
mkdir "$stage/fragments"
backup=''; transaction=0; was_active=0
systemctl is-active --quiet amazon-cloudwatch-agent && was_active=1
cleanup() {
  local status=$?
  if ((status != 0)) && [[ -s $stage/validation.log ]]; then
    printf 'Private validation files retained for diagnosis: %s\n' "$stage" >&2
    return
  fi
  rm -f -- "$stage/amazon-cloudwatch-agent.json" "$stage/amazon-cloudwatch-agent.toml" "$stage/amazon-cloudwatch-agent.yaml" "$stage/validation.log"
  rmdir -- "$stage/fragments" "$stage" 2>/dev/null || true
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
  local source=$1 temporary
  temporary=$(mktemp "$agent/etc/.aws-portfolio.XXXXXX") || return 1
  if ! install -o root -g root -m 0644 -- "$source" "$temporary"; then rm -f -- "$temporary"; return 1; fi
  if ! mv -fT -- "$temporary" "$target"; then rm -f -- "$temporary"; return 1; fi
}
on_error() {
  local code=$?
  trap - ERR
  set +e
  if ((transaction)); then
    echo 'Agent activation failed; attempting configuration rollback.' >&2
    if [[ -f $backup/amazon-cloudwatch-agent.json ]]; then
      if ! atomic_install "$backup/amazon-cloudwatch-agent.json" || ! "$ctl" -a fetch-config -m ec2 -c "file:$target" -s > "$backup/rollback.log" 2>&1; then
        echo "Rollback failed; inspect private backup $backup" >&2; exit 41
      fi
    else
      systemctl stop amazon-cloudwatch-agent || exit 41
      rm -f -- "$target" "$cached"
    fi
    if (( ! was_active )); then systemctl stop amazon-cloudwatch-agent || exit 41; fi
    printf 'Prior telemetry configuration restored. Backup: %s\n' "$backup" >&2
    exit 40
  fi
  exit "$code"
}
trap on_error ERR
source=$repo/config/cloudwatch/amazon-cloudwatch-agent.json
if [[ $mode == rollback ]]; then
  restore_from=$(realpath -e -- "$restore_from")
  [[ $restore_from == "$backup_root/"* && -d $restore_from && ! -L $restore_from && $(stat -c %u "$restore_from") == 0 && $(stat -c %a "$restore_from") == 700 ]] || exit 3
  source=$restore_from/amazon-cloudwatch-agent.json
fi
[[ -f $source && ! -L $source ]] || exit 3
cp -- "$source" "$stage/amazon-cloudwatch-agent.json"
if ! python3 - "$stage/amazon-cloudwatch-agent.json" <<'PY'
import json, pathlib, sys
v=json.loads(pathlib.Path(sys.argv[1]).read_text())
def inspect(value):
    if isinstance(value,dict):
        assert 'retention_in_days' not in value, 'retention must remain Terraform-owned'
        for k,item in value.items():
            assert k not in ('credentials','role_arn','shared_credential_file'), 'unexpected authentication configuration'
            inspect(item)
    elif isinstance(value,list):
        for item in value: inspect(item)
inspect(v)
assert v['agent']['region']=='us-east-2'
assert v['agent']['metrics_collection_interval']==300
m=v['metrics']; assert m['namespace']=='AWSPortfolioLab'
assert m['append_dimensions']=={'InstanceId':'${aws:InstanceId}'}
assert set(m['metrics_collected'])=={'mem','disk'}
assert m['metrics_collected']['mem']=={'measurement':['mem_used_percent'],'metrics_collection_interval':300}
assert m['metrics_collected']['disk']=={'measurement':['used_percent'],'resources':['/'],'drop_device':True,'metrics_collection_interval':300}
expected=[{'file_path':'/var/log/nginx/'+name+'.log','log_group_name':'/aws/portfolio-lab/nginx/'+name,'log_stream_name':'{instance_id}'} for name in ('access','error')]
assert v['logs']['logs_collected']['files']['collect_list']==expected
PY
then echo 'Candidate JSON does not satisfy the approved monitoring contract.' >&2; exit 20; fi
# Validate in a private staging directory. Neither command activates the service.
if ! "$agent/bin/config-translator" --input "$stage/amazon-cloudwatch-agent.json" --input-dir "$stage/fragments" --output "$stage/amazon-cloudwatch-agent.toml" --mode ec2 --config "$agent/etc/common-config.toml" --multi-config default > "$stage/validation.log" 2>&1; then
  echo 'Agent translation failed; no live files changed. Review the installed Agent version/options.' >&2; exit 20
fi
if ! "$agent/bin/amazon-cloudwatch-agent" -schematest -config "$stage/amazon-cloudwatch-agent.toml" >> "$stage/validation.log" 2>&1; then
  echo 'Agent schema test failed; no live files changed.' >&2; exit 20
fi
if [[ $mode == check ]]; then echo 'JSON, Agent translation, and Agent schema tests passed; nothing activated.'; exit 0; fi
same=0
if [[ -f $cached ]] && python3 - "$stage/amazon-cloudwatch-agent.json" "$cached" <<'PY'
import json, pathlib, sys
sys.exit(0 if json.loads(pathlib.Path(sys.argv[1]).read_text())==json.loads(pathlib.Path(sys.argv[2]).read_text()) else 1)
PY
then same=1; fi
healthy=0
if ((was_active)) && "$ctl" -a status | python3 -c 'import json,sys;v=json.load(sys.stdin);sys.exit(0 if v.get("status")=="running" and v.get("configstatus")=="configured" else 1)'; then healthy=1; fi
if ((same && healthy)); then
  if ! cmp -s -- "$stage/amazon-cloudwatch-agent.json" "$target"; then atomic_install "$stage/amazon-cloudwatch-agent.json"; fi
  ensure_metadata "$target" 644
  echo 'Validated configuration already active; source synchronized without restarting Agent.'
  exit 0
fi
for directory in /var/backups/aws-portfolio-lab "$backup_root"; do
  [[ ! -L $directory ]] || exit 3
  if [[ -d $directory ]]; then
    ensure_metadata "$directory" 700
  else
    install -d -o root -g root -m 0700 -- "$directory"
  fi
done
backup=$(mktemp -d "$backup_root/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
previous=$cached
[[ ! -f $previous ]] || cp -p -- "$previous" "$backup/original.json"
if [[ ! -f $previous && -f $target ]]; then previous=$target; cp -p -- "$target" "$backup/original.json"; fi
if [[ -f $previous ]]; then
  # Legacy Agent configurations contained retention. Rollback must not reclaim it.
  python3 - "$previous" "$backup/amazon-cloudwatch-agent.json" <<'PY'
import json,pathlib,sys
v=json.loads(pathlib.Path(sys.argv[1]).read_text())
def clean(item):
    if isinstance(item,dict): return {k:clean(x) for k,x in item.items() if k!='retention_in_days'}
    if isinstance(item,list): return [clean(x) for x in item]
    return item
pathlib.Path(sys.argv[2]).write_text(json.dumps(clean(v),indent=2)+'\n')
PY
fi
transaction=1
atomic_install "$stage/amazon-cloudwatch-agent.json"
"$ctl" -a fetch-config -m ec2 -c "file:$target" -s > "$backup/activation.log" 2>&1
systemctl is-active --quiet amazon-cloudwatch-agent
"$ctl" -a status | python3 -c 'import json,sys;v=json.load(sys.stdin);sys.exit(0 if v.get("status")=="running" and v.get("configstatus")=="configured" else 1)'
python3 - "$stage/amazon-cloudwatch-agent.json" "$cached" <<'PY'
import json,pathlib,sys
assert json.loads(pathlib.Path(sys.argv[1]).read_text())==json.loads(pathlib.Path(sys.argv[2]).read_text()), 'activated source does not match the candidate'
PY
transaction=0
printf 'Agent configuration activated and verified. Rollback directory: %s\n' "$backup"
