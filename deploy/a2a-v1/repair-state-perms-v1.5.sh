#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-a2a"
STATE="$ROOT/state"
SERVICE="technocore-a2a"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo bash repair-state-perms-v1.5.sh"
  exit 1
fi

[[ -d "$ROOT" ]] || { echo "Missing $ROOT"; exit 1; }
id tcagent >/dev/null 2>&1 || { echo "Missing tcagent user"; exit 1; }

# The daemon runs as tcagent, while admin helpers may be launched as root.
# Keep runtime state private but group-writable so a root-launched helper cannot
# strand the daemon with root-owned 0644 files.
install -d -o tcagent -g tcagent -m 2770 "$STATE"
chown -R tcagent:tcagent "$STATE"
find "$STATE" -type d -exec chmod 2770 {} +
find "$STATE" -type f -exec chmod 0660 {} +

# Future root-launched helper writes should remain group-writable inside the
# setgid state directory. Do not change identity/private-key permissions.
for helper in /usr/local/bin/tc-a2a-peer-add /usr/local/bin/tc-a2a-task; do
  if [[ -f "$helper" ]] && ! grep -q '^umask 0007$' "$helper"; then
    sed -i '1a umask 0007' "$helper"
  fi
done

systemctl daemon-reload
systemctl restart "$SERVICE"
sleep 3

echo "=== STATE PERMISSIONS ==="
ls -ld "$STATE"
ls -l "$STATE" | sed -n '1,20p'

echo
echo "=== SERVICE ==="
systemctl --no-pager --full status "$SERVICE" | sed -n '1,18p' || true

echo
echo "=== RECENT LOGS ==="
journalctl -u "$SERVICE" -n 25 --no-pager || true

echo
echo "v1.5 applied. DID/key/mailbox were not changed."
echo "Do NOT resend the existing A2A task yet; let the daemon replay the queued mailbox item."