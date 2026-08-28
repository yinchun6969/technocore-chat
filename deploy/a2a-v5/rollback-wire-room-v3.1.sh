#!/usr/bin/env bash
# Restore code only; never rewind identity, cursors, nonces or workflow state.
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
fix_backup=$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")
case "$fix_backup" in
  /root/tc-a2a-wire-room-v31-backups/*) ;;
  *) echo 'Rollback must run from its validated backup directory.' >&2; exit 1 ;;
esac
fix_root=/opt/technocore-a2a
fix_cli=/usr/local/bin/tc-a2a-wire-room-v31-rollback
[[ -f "$fix_backup/backup.complete" ]] || { echo 'Backup is incomplete.' >&2; exit 1; }
(cd "$fix_backup" && sha256sum -c SHA256SUMS)
read -r fix_reviewer_active < "$fix_backup/reviewer.active"
read -r fix_director_active < "$fix_backup/director.active"
[[ $fix_reviewer_active =~ ^[01]$ && $fix_director_active =~ ^[01]$ ]] || exit 1

restore_code() {
  local fix_source=$1 fix_target=$2 fix_temp
  [[ -f "$fix_target" && ! -L "$fix_target" ]] || return 1
  fix_temp=$(mktemp "$(dirname -- "$fix_target")/.wire-v31-restore.XXXXXX")
  cp --preserve=all -- "$fix_source" "$fix_temp"
  mv -f -- "$fix_temp" "$fix_target"
}

systemctl stop technocore-a2a-rnd-v5.service technocore-a2a.service
restore_code "$fix_backup/agent.py" "$fix_root/bin/agent.py"
restore_code "$fix_backup/autonomous-rnd-v5.py" "$fix_root/rnd-v5/autonomous-rnd-v5.py"
if [[ -e "$fix_backup/prior-rollback" || -L "$fix_backup/prior-rollback" ]]; then
  cp -a --remove-destination -- "$fix_backup/prior-rollback" "$fix_cli"
elif [[ -L "$fix_cli" && $(readlink -f -- "$fix_cli") == "$fix_backup/rollback.sh" ]]; then
  unlink "$fix_cli"
fi
if [[ $fix_reviewer_active == 1 ]]; then systemctl start technocore-a2a.service; fi
if [[ $fix_director_active == 1 ]]; then systemctl start technocore-a2a-rnd-v5.service; fi
echo 'WIRE_ROOM_V31_ROLLBACK=COMPLETE; code restored; current workflow state preserved'
echo "backup=$fix_backup"
