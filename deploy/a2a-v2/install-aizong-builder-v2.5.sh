#!/usr/bin/env bash
set -Eeuo pipefail

REPO_RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-collab-v2/deploy/a2a-v2"
ROOT="/opt/technocore-collab"
AIZONG_KEY="/opt/technocore-agent/identity/ed25519_private.pem"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo -i, then bash install-aizong-builder-v2.5.sh"
  exit 1
fi

[[ -f "$AIZONG_KEY" ]] || {
  echo "ABORT: expected aizong private key is missing: $AIZONG_KEY"
  echo "No files were changed. Run this only on the existing aizong VPS."
  exit 1
}

if [[ -e "$ROOT/.env" ]]; then
  echo "ABORT: $ROOT/.env already exists."
  echo "Refusing to overwrite an existing A2A sidecar."
  exit 1
fi

echo "=== AIZONG BUILDER PREFLIGHT ==="
echo "existing_key: $AIZONG_KEY"
echo "identity: reuse only; no new DID, room, or mailbox"
echo "role: builder"
echo

tmp_install=/tmp/install-existing-agent-sidecar.sh
tmp_harden=/tmp/harden-task-state-v2.3.sh
curl -fsSL "$REPO_RAW/install-existing-agent-sidecar.sh" -o "$tmp_install"
curl -fsSL "$REPO_RAW/harden-task-state-v2.3.sh" -o "$tmp_harden"
chmod 0700 "$tmp_install" "$tmp_harden"

echo "Starting interactive sidecar install."
echo "At the prompts, keep the detected aizong key/name/builder role/mailbox by pressing Enter."
echo "Enter the existing external AI URL/model/API key when asked."
echo

set +e
bash "$tmp_install"
install_rc=$?
set -e

if [[ ! -f "$ROOT/.env" || ! -f "$ROOT/bin/collab.py" ]]; then
  echo "Installer did not create a usable sidecar (rc=$install_rc)."
  exit "$install_rc"
fi

# If systemd is available, the base installer should already have started the service.
# If the host is non-systemd, install the existing watchdog runner before hardening.
if ! command -v systemctl >/dev/null 2>&1 || ! systemctl show-environment >/dev/null 2>&1; then
  echo "Non-systemd host detected; installing watchdog runner."
  curl -fsSL "$REPO_RAW/repair-nosystemd-v2.2.sh" -o /tmp/repair-nosystemd-v2.2.sh
  bash /tmp/repair-nosystemd-v2.2.sh
fi

echo
echo "Applying reliable task state machine v2.3..."
bash "$tmp_harden"

echo
echo "=== FINAL AIZONG BUILDER STATUS ==="
tc-collab-status
if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl is-active technocore-collab || true
else
  tc-collab-process-status || true
fi

echo
echo "AIZONG_BUILDER_READY"
echo "No DID/private key/mailbox was replaced or created."
echo "Do not pin peers yet; verify the DID and mailbox shown above first."
