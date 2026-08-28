#!/usr/bin/env bash
# AI2AI only. Fixed-content dependencies; no identity or cursor migration.
set -Eeuo pipefail
umask 077
[[ ${EUID} -eq 0 ]] || { echo 'Run as root on AI2AI only.' >&2; exit 1; }
fix_root=/opt/technocore-a2a
fix_python=$fix_root/venv/bin/python
fix_cli=/usr/local/bin/tc-a2a-wire-room-v31-rollback
fix_source_ref=c42edda3ec5b55c363dcabfed75daded2b42e5f4
fix_patch_sha=c2a3e5b41cf7df9d33f97606cb86a678b7dfbe3c1e08cbd1cb57a7e186b641ef
fix_rollback_sha=9c7dde0c5a9ed23d836a43cf5585f4c3c9acbb3ea73f4a5de501cc5281a98eea
fix_url="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$fix_source_ref/deploy/a2a-v5"
for fix_command in curl sha256sum systemctl runuser flock; do command -v "$fix_command" >/dev/null; done
for fix_path in "$fix_root/bin/agent.py" "$fix_root/rnd-v5/autonomous-rnd-v5.py" "$fix_root/.env"; do
  [[ -f "$fix_path" && ! -L "$fix_path" ]] || { echo "Missing or symbolic-link target: $fix_path" >&2; exit 1; }
done
[[ ! -d "$fix_cli" ]] || { echo 'Rollback command path is a directory; no changes made.' >&2; exit 1; }
[[ -x "$fix_python" ]] || { echo 'Existing AI2AI Python runtime missing.' >&2; exit 1; }
# Parse just the agent name; do not execute .env or display credentials.
"$fix_python" - "$fix_root/.env" <<'PY'
import sys
from pathlib import Path
values = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
if values.get('AGENT_NAME') != 'ai2ai':
    raise SystemExit('This installer is only for the existing AI2AI node.')
PY
install -d -m 0700 /root/tc-a2a-wire-room-v31-backups
exec 9>/root/tc-a2a-wire-room-v31-backups/install.lock
flock -n 9 || { echo 'Another wire/room repair is running.' >&2; exit 1; }
fix_work=$(mktemp -d /root/tc-a2a-wire-room-v31-backups/staging.XXXXXXXX)
curl -fLsS --connect-timeout 10 --max-time 120 --retry 3 "$fix_url/repair-wire-room-v3.1.py" -o "$fix_work/repair.py"
curl -fLsS --connect-timeout 10 --max-time 120 --retry 3 "$fix_url/rollback-wire-room-v3.1.sh" -o "$fix_work/rollback.sh"
printf '%s  %s\n' "$fix_patch_sha" "$fix_work/repair.py" "$fix_rollback_sha" "$fix_work/rollback.sh" | sha256sum -c -
bash -n "$fix_work/rollback.sh"
"$fix_python" "$fix_work/repair.py" --check
for fix_service in technocore-a2a.service technocore-a2a-rnd-v5.service; do
  [[ $(systemctl show "$fix_service" -p LoadState --value) == loaded ]] || { echo "Service not loaded: $fix_service" >&2; exit 1; }
  fix_user=$(systemctl show "$fix_service" -p User --value)
  fix_user=${fix_user:-root}
  fix_read_paths=("$fix_root/bin/agent.py")
  if [[ $fix_service == technocore-a2a-rnd-v5.service ]]; then fix_read_paths+=("$fix_root/rnd-v5/autonomous-rnd-v5.py"); fi
  for fix_path in "${fix_read_paths[@]}"; do
    runuser -u "$fix_user" -- test -r "$fix_path" || { echo "Permission preflight failed for $fix_user: $fix_path. No permissions changed." >&2; exit 1; }
  done
done
fix_backup=$(mktemp -d /root/tc-a2a-wire-room-v31-backups/backup.XXXXXXXX)
cp -a -- "$fix_root/bin/agent.py" "$fix_backup/agent.py"
cp -a -- "$fix_root/rnd-v5/autonomous-rnd-v5.py" "$fix_backup/autonomous-rnd-v5.py"
install -m 0700 "$fix_work/rollback.sh" "$fix_backup/rollback.sh"
if [[ -e "$fix_cli" || -L "$fix_cli" ]]; then cp -a -- "$fix_cli" "$fix_backup/prior-rollback"; fi
fix_reviewer_active=0
fix_director_active=0
if systemctl is-active --quiet technocore-a2a.service; then fix_reviewer_active=1; fi
if systemctl is-active --quiet technocore-a2a-rnd-v5.service; then fix_director_active=1; fi
printf '%s\n' "$fix_reviewer_active" > "$fix_backup/reviewer.active"
printf '%s\n' "$fix_director_active" > "$fix_backup/director.active"
(cd "$fix_backup" && sha256sum agent.py autonomous-rnd-v5.py > SHA256SUMS && sha256sum -c SHA256SUMS)
printf 'code-only restore; never restore diagnostic state automatically\n' > "$fix_backup/backup.complete"

repair_failed() {
  local fix_rc=$?
  trap - ERR INT TERM
  echo 'Install failed; restoring the backed-up code and previous service states.' >&2
  if ! bash "$fix_backup/rollback.sh"; then
    echo "AUTOMATIC ROLLBACK FAILED. Backup retained: $fix_backup" >&2
  fi
  exit "$fix_rc"
}
trap repair_failed ERR
trap 'false' INT TERM
systemctl stop technocore-a2a-rnd-v5.service technocore-a2a.service
# Diagnostic snapshots are never used by rollback (avoids replaying old tasks).
fix_snapshot_paths=()
for fix_relative in state/cursor.txt state/workflow_seen.json state/peers.json rnd-v5-state/director.json; do
  if [[ -f "$fix_root/$fix_relative" ]]; then fix_snapshot_paths+=("$fix_relative"); fi
done
if (( ${#fix_snapshot_paths[@]} )); then
  tar -C "$fix_root" -czf "$fix_backup/diagnostic-state.tgz" -- "${fix_snapshot_paths[@]}"
fi
"$fix_python" "$fix_work/repair.py" --apply
ln -sfn -- "$fix_backup/rollback.sh" "$fix_cli"
if [[ $fix_reviewer_active == 1 ]]; then systemctl start technocore-a2a.service; fi
if [[ $fix_director_active == 1 ]]; then systemctl start technocore-a2a-rnd-v5.service; fi
sleep 3
if [[ $fix_reviewer_active == 1 ]]; then systemctl is-active --quiet technocore-a2a.service; fi
if [[ $fix_director_active == 1 ]]; then systemctl is-active --quiet technocore-a2a-rnd-v5.service; fi
"$fix_python" "$fix_work/repair.py" --check
trap - ERR INT TERM
echo '=== AI2AI WIRE + ROOM v3.1 INSTALLED ==='
echo 'wire_limit_bytes=3400; JSON preserved; complete Reviewer answer cached before delivery'
echo 'room=existing configuration retained; deduplication and retry backoff installed'
echo 'identity/cursors/nonces/peers/workflow history/service settings=unchanged'
echo 'Aizong/Love8/Telegram/Curator=not restarted or modified'
echo "reviewer=$(systemctl is-active technocore-a2a.service || true)"
echo "director=$(systemctl is-active technocore-a2a-rnd-v5.service || true)"
echo "backup=$fix_backup"
echo 'rollback=tc-a2a-wire-room-v31-rollback'
echo 'Installation is not end-to-end proof: verify a new workflow_challenge and its completion.'
echo 'If room_capacity_full persists, the platform must free capacity or an existing writable room must be explicitly selected.'
