#!/usr/bin/env bash
set -Eeuo pipefail

RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-collab-v2/deploy/a2a-v2"
KEY="/opt/technocore-agent/identity/ed25519_private.pem"
ROOT="/opt/technocore-collab"
AGENT_ROOT="/opt/technocore-agent"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo -i"
  exit 1
fi

[[ -f "$KEY" ]] || {
  echo "ABORT: expected aizong key missing: $KEY"
  echo "Run this only on the existing aizong VPS."
  exit 1
}

if [[ -e "$ROOT/.env" ]]; then
  echo "ABORT: $ROOT/.env already exists; refusing to overwrite an existing sidecar."
  exit 1
fi

MAILBOX=$(grep -RhoE 'mb-p-[a-z0-9]{16,64}' "$AGENT_ROOT" 2>/dev/null | head -n1 || true)
[[ "$MAILBOX" =~ ^mb-p-[a-z0-9]{16,64}$ ]] || {
  echo "ABORT: could not safely auto-detect the existing aizong mailbox."
  exit 1
}

echo "=== AIZONG BUILDER SAFE INSTALL v2.5.1 ==="
echo "key: $KEY"
echo "mailbox: $MAILBOX"
echo "role: builder"
echo "identity: REUSE ONLY"
echo

AI_URL=""
while [[ -z "$AI_URL" ]]; do
  read -rp "External AI endpoint/base URL: " AI_URL
  [[ -n "$AI_URL" ]] || echo "URL cannot be empty; try again."
done

AI_MODEL=""
while [[ -z "$AI_MODEL" ]]; do
  read -rp "External AI model: " AI_MODEL
  [[ -n "$AI_MODEL" ]] || echo "Model cannot be empty; try again."
done

AI_KEY=""
while [[ -z "$AI_KEY" ]]; do
  read -rsp "External AI API key: " AI_KEY
  echo
  [[ -n "$AI_KEY" ]] || echo "API key cannot be empty; try again."
done

echo
echo "Inputs captured. API key will not be printed."
echo "Launching the existing v2.5 installer with detected identity defaults..."

V25=/tmp/install-aizong-builder-v2.5.sh
curl -fsSL "$RAW/install-aizong-builder-v2.5.sh" -o "$V25"
chmod 0700 "$V25"

# Feed the base installer in exact prompt order:
# key path, agent name, role, mailbox, AI URL, model, API key,
# Authorization header, Bearer prefix, poll seconds.
printf '%s\n' \
  "" \
  "" \
  "" \
  "" \
  "$AI_URL" \
  "$AI_MODEL" \
  "$AI_KEY" \
  "" \
  "" \
  "" \
  | bash "$V25"

unset AI_KEY

echo
echo "=== SAFE INSTALL WRAPPER COMPLETE ==="
tc-collab-status || true
