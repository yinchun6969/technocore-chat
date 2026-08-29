#!/usr/bin/env bash
# Upgrade only an existing isolated Atlas v1 deployment. Never restarts A2A/TG.
set -Eeuo pipefail
umask 077
SOURCE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
fail() { echo "STOP: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail 'Run with sudo on the AI2AI VPS.'
systemctl is-active --quiet technocore-a2a-rnd-v5.service || fail 'AI2AI v5 Director is not active.'
for target in /opt/technocore-atlas/tools /etc/technocore-atlas.conf /usr/local/bin/tc-atlas; do
  [[ -e "$target" && ! -L "$target" ]] || fail "Existing Atlas v1 target is absent or unsafe: $target"
done
if [[ -f /opt/technocore-atlas/tools/atlas_dashboard.py ]] && grep -q '^ATLAS_WORKFLOW_ROOMS=' /etc/technocore-atlas.conf; then
  echo 'ATLAS_V2_ALREADY_INSTALLED'
  exit 0
fi
for source in tools/__init__.py tools/technocore_atlas.py tools/atlas_dashboard.py tools/atlas_config.py tools/atlas_observer.py deploy/atlas/tc-atlas deploy/atlas/technocore-atlas-refresh.service deploy/atlas/technocore-atlas-refresh.timer deploy/atlas/technocore-atlas-web.service; do
  [[ -f "$SOURCE_ROOT/$source" && ! -L "$SOURCE_ROOT/$source" ]] || fail "Missing v2 source: $source"
done
ATLAS_ROOM="$(awk -F= '$1=="ATLAS_ROOM" {print $2; exit}' /etc/technocore-atlas.conf)"
PEERS_FILE="${ATLAS_PEERS_FILE:-/opt/technocore-a2a/state/peers.json}"
ATLAS_WORKFLOW_ROOMS="$(
  cd "$SOURCE_ROOT"
  PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m tools.atlas_config "$PEERS_FILE"
)" || fail 'Cannot resolve pinned v5 workflow mailboxes; existing Atlas retained.'
(
  cd "$SOURCE_ROOT"
  PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - "$ATLAS_ROOM" "$ATLAS_WORKFLOW_ROOMS" <<'PY'
import sys
from tools.technocore_atlas import _is_public_room, _is_workflow_room
if sys.version_info < (3, 12):
    raise SystemExit('Python 3.12+ required')
if not _is_public_room(sys.argv[1]):
    raise SystemExit('invalid public room')
rooms = sys.argv[2].split(',')
if len(rooms) < 3 or not all(_is_workflow_room(room) for room in rooms):
    raise SystemExit('expected the fixed room plus two pinned peer mailboxes')
PY
)

BACKUP="/opt/technocore-atlas/backups/v1-to-v2-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP/tools" "$BACKUP/units"
cp -a /opt/technocore-atlas/tools/. "$BACKUP/tools/"
cp -a /etc/technocore-atlas.conf "$BACKUP/technocore-atlas.conf"
cp -a /usr/local/bin/tc-atlas "$BACKUP/tc-atlas"
for unit in technocore-atlas-refresh.service technocore-atlas-refresh.timer technocore-atlas-web.service; do
  cp -a "/etc/systemd/system/$unit" "$BACKUP/units/$unit"
done

rollback() {
  trap - ERR
  systemctl stop technocore-atlas-refresh.timer technocore-atlas-web.service technocore-atlas-refresh.service >/dev/null 2>&1 || true
  cp -a "$BACKUP/tools/." /opt/technocore-atlas/tools/
  cp -a "$BACKUP/technocore-atlas.conf" /etc/technocore-atlas.conf
  cp -a "$BACKUP/tc-atlas" /usr/local/bin/tc-atlas
  cp -a "$BACKUP/units/." /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now technocore-atlas-web.service technocore-atlas-refresh.timer >/dev/null 2>&1 || true
  echo "UPGRADE_FAILED: Atlas v1 restored from $BACKUP; A2A/TG untouched." >&2
  exit 1
}
trap rollback ERR
systemctl stop technocore-atlas-refresh.timer technocore-atlas-web.service technocore-atlas-refresh.service
install -m 0644 "$SOURCE_ROOT/tools/__init__.py" "$SOURCE_ROOT/tools/technocore_atlas.py" "$SOURCE_ROOT/tools/atlas_dashboard.py" "$SOURCE_ROOT/tools/atlas_config.py" "$SOURCE_ROOT/tools/atlas_observer.py" /opt/technocore-atlas/tools/
printf 'ATLAS_ROOM=%s\nATLAS_WORKFLOW_ROOMS=%s\n' "$ATLAS_ROOM" "$ATLAS_WORKFLOW_ROOMS" > /etc/technocore-atlas.conf
chmod 0600 /etc/technocore-atlas.conf
install -m 0755 "$SOURCE_ROOT/deploy/atlas/tc-atlas" /usr/local/bin/tc-atlas
for unit in technocore-atlas-refresh.service technocore-atlas-refresh.timer technocore-atlas-web.service; do
  install -m 0644 "$SOURCE_ROOT/deploy/atlas/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now technocore-atlas-web.service technocore-atlas-refresh.timer
systemctl start --no-block technocore-atlas-refresh.service
systemctl is-active --quiet technocore-atlas-web.service
systemctl is-active --quiet technocore-atlas-refresh.timer
trap - ERR
echo 'ATLAS_V2_UPGRADED: dashboard=127.0.0.1:8787; refresh=30s'
echo "backup=$BACKUP; pinned workflow sources=3; A2A/TG not restarted"
