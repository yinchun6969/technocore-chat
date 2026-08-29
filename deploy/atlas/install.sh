#!/usr/bin/env bash
# First installation only. Never upgrades or overwrites an existing deployment.
set -Eeuo pipefail
umask 077
SOURCE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECK_ONLY=0
ATLAS_ROOM=
while (($#)); do
  case "$1" in
    --check) CHECK_ONLY=1; shift ;;
    --room) [[ $# -ge 2 ]] || exit 2; ATLAS_ROOM="$2"; shift 2 ;;
    *) echo 'Usage: install.sh [--check] [--room public-room]' >&2; exit 2 ;;
  esac
done
fail() { echo "STOP: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail 'Run with sudo on the AI2AI VPS.'
for command in python3 systemctl curl install; do
  command -v "$command" >/dev/null || fail "Missing prerequisite: $command (nothing installed)"
done
systemctl show-environment >/dev/null || fail 'A working systemd system instance is required.'
systemctl is-active --quiet technocore-a2a-rnd-v5.service || fail 'AI2AI v5 Director is not active. Do not install on Love8/Aizong.'
if [[ -z "$ATLAS_ROOM" ]]; then
  ROOM_FILE=/opt/technocore-a2a/rnd-v5-state/identity-room-name
  DROPIN=/etc/systemd/system/technocore-a2a-rnd-v5.service.d/95-identity-room-v520.conf
  if [[ -f "$ROOM_FILE" && ! -L "$ROOM_FILE" ]]; then
    IFS= read -r ATLAS_ROOM < "$ROOM_FILE" || true
  elif [[ -f "$DROPIN" && ! -L "$DROPIN" ]]; then
    ATLAS_ROOM="$(awk -F= '$1=="Environment" && $2=="RND_V5_DISCUSSION_ROOM" {print $3}' "$DROPIN" | tail -n1)"
  fi
fi
[[ -n "$ATLAS_ROOM" ]] || fail 'Cannot establish the current v5 identity room. Re-run with --room exact-public-room.'
TARGETS=(
  /opt/technocore-atlas
  /etc/technocore-atlas.conf
  /usr/local/bin/tc-atlas
  /var/lib/technocore-atlas
  /var/lib/private/technocore-atlas
  /etc/systemd/system/technocore-atlas-refresh.service
  /etc/systemd/system/technocore-atlas-refresh.timer
  /etc/systemd/system/technocore-atlas-web.service
)
for target in "${TARGETS[@]}"; do
  [[ ! -e "$target" && ! -L "$target" ]] || fail "Existing target retained: $target. Use tc-atlas status/start; do not reinstall."
done
for unit in technocore-atlas-refresh.service technocore-atlas-refresh.timer technocore-atlas-web.service; do
  [[ "$(systemctl show "$unit" -p LoadState --value)" == not-found ]] || fail "Existing unit retained: $unit"
done
for source in tools/__init__.py tools/technocore_atlas.py tools/atlas_observer.py deploy/atlas/tc-atlas deploy/atlas/technocore-atlas-refresh.service deploy/atlas/technocore-atlas-refresh.timer deploy/atlas/technocore-atlas-web.service; do
  [[ -f "$SOURCE_ROOT/$source" && ! -L "$SOURCE_ROOT/$source" ]] || fail "Missing source: $source"
done
(
  cd "$SOURCE_ROOT"
  PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - "$ATLAS_ROOM" <<'PY'
import socket
import sys
from tools.technocore_atlas import _is_public_room
if sys.version_info < (3, 12):
    raise SystemExit('Python 3.12+ required; no packages were installed')
if not _is_public_room(sys.argv[1]):
    raise SystemExit('Refusing private/mailbox/invalid room name')
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 8787))
print('PREFLIGHT_OK: Python, public room and loopback port checked')
PY
)
if [[ "$CHECK_ONLY" == 1 ]]; then
  echo 'CHECK_ONLY: no files written, no units changed, no network collection'
  exit 0
fi
# No targets existed before this point. On failure stop only these new units;
# leave any partial files for inspection, with no deletion of user state.
on_error() {
  trap - ERR
  systemctl disable --now technocore-atlas-refresh.timer technocore-atlas-web.service >/dev/null 2>&1 || true
  systemctl stop technocore-atlas-refresh.service >/dev/null 2>&1 || true
  echo 'INSTALL_FAILED: Atlas stopped; partial files retained. Existing A2A services unchanged.' >&2
  exit 1
}
trap on_error ERR
install -d -m 0755 /opt/technocore-atlas /opt/technocore-atlas/tools
install -m 0644 "$SOURCE_ROOT/tools/__init__.py" "$SOURCE_ROOT/tools/technocore_atlas.py" "$SOURCE_ROOT/tools/atlas_observer.py" /opt/technocore-atlas/tools/
printf 'ATLAS_ROOM=%s\n' "$ATLAS_ROOM" > /etc/technocore-atlas.conf
chmod 0600 /etc/technocore-atlas.conf
install -m 0755 "$SOURCE_ROOT/deploy/atlas/tc-atlas" /usr/local/bin/tc-atlas
for unit in technocore-atlas-refresh.service technocore-atlas-refresh.timer technocore-atlas-web.service; do
  install -m 0644 "$SOURCE_ROOT/deploy/atlas/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now technocore-atlas-web.service technocore-atlas-refresh.timer
systemctl is-active --quiet technocore-atlas-web.service
systemctl is-active --quiet technocore-atlas-refresh.timer
systemctl start --no-block technocore-atlas-refresh.service
trap - ERR
echo 'ATLAS_INSTALLED: 127.0.0.1:8787 only; initial collection pending.'
echo "room=$ATLAS_ROOM; no model calls, keys, mailbox reads or A2A/TG restarts"
echo 'Check: tc-atlas status | View: SSH tunnel to localhost:8787 | Rollback: tc-atlas stop'
