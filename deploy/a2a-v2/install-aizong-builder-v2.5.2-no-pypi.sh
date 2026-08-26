#!/usr/bin/env bash
set -Eeuo pipefail

RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-collab-v2/deploy/a2a-v2"
KEY="/opt/technocore-agent/identity/ed25519_private.pem"
AGENT_ROOT="/opt/technocore-agent"
ROOT="/opt/technocore-collab"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo -i"
  exit 1
fi

[[ -f "$KEY" ]] || {
  echo "ABORT: expected aizong key missing: $KEY"
  echo "Run this only on the existing aizong VPS."
  exit 1
}

if [[ -f "$ROOT/.env" ]]; then
  echo "ABORT: $ROOT/.env already exists; refusing to overwrite an existing sidecar."
  exit 1
fi

MAILBOX=$(grep -RhoE 'mb-p-[a-z0-9]{16,64}' "$AGENT_ROOT" 2>/dev/null | head -n1 || true)
[[ "$MAILBOX" =~ ^mb-p-[a-z0-9]{16,64}$ ]] || {
  echo "ABORT: could not safely auto-detect the existing aizong mailbox."
  exit 1
}

echo "=== AIZONG BUILDER v2.5.2 / NO-PYPI BOOTSTRAP ==="
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

# Previous attempts may have left only an empty/partial venv. Preserve it for
# inspection, but never touch the existing Technocore identity tree.
if [[ -d "$ROOT" && ! -f "$ROOT/.env" ]]; then
  mv "$ROOT" "${ROOT}.partial-${STAMP}"
  echo "preserved previous partial install: ${ROOT}.partial-${STAMP}"
fi

BASE=/tmp/install-existing-agent-sidecar-nopypi.sh
curl -fsSL "$RAW/install-existing-agent-sidecar.sh" -o "$BASE"

python3 - "$BASE" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
s=p.read_text()
old='''export DEBIAN_FRONTEND=noninteractive\napt-get update -y >/dev/null\napt-get install -y python3 python3-venv ca-certificates >/dev/null\ninstall -d -m 0700 "$ROOT" "$ROOT/bin" "$ROOT/state"\npython3 -m venv "$ROOT/venv"\n"$ROOT/venv/bin/pip" install -q --upgrade pip\n"$ROOT/venv/bin/pip" install -q requests cryptography\n'''
new='''export DEBIAN_FRONTEND=noninteractive\ninstall -d -m 0700 "$ROOT" "$ROOT/bin" "$ROOT/state"\n\n# Prefer already-installed Ubuntu/system packages. PyPI is intentionally not\n# contacted because some VPS/proxy environments block or intermittently fail it.\nif ! python3 -c "import requests, cryptography" >/dev/null 2>&1; then\n  echo "System Python is missing requests/cryptography; trying Ubuntu packages..."\n  apt-get update -y >/dev/null\n  apt-get install -y python3 python3-venv python3-requests python3-cryptography ca-certificates >/dev/null\nfi\npython3 -c "import requests, cryptography; print('SYSTEM_PY_DEPS_OK')"\npython3 -m venv --system-site-packages "$ROOT/venv"\n"$ROOT/venv/bin/python" -c "import requests, cryptography; print('A2A_RUNTIME_DEPS_OK')"\n'''
if old not in s:
    raise SystemExit('Expected dependency block not found; refusing blind patch')
p.write_text(s.replace(old,new,1))
PY
chmod 0700 "$BASE"

# Feed prompt order of the base installer: key, name, role, mailbox, URL,
# model, API key, header, prefix, poll interval.
printf '%s\n' \
  "" "" "" "" \
  "$AI_URL" "$AI_MODEL" "$AI_KEY" \
  "" "" "" \
  | bash "$BASE"
unset AI_KEY

[[ -f "$ROOT/.env" && -f "$ROOT/bin/collab.py" ]] || {
  echo "ABORT: sidecar files were not created. Existing DID/key/mailbox were not changed."
  exit 1
}

# Apply the reliable task state machine already validated on love8.
HARDEN=/tmp/harden-task-state-v2.3.sh
curl -fsSL "$RAW/harden-task-state-v2.3.sh" -o "$HARDEN"
chmod 0700 "$HARDEN"
bash "$HARDEN"

echo
echo "=== FINAL AIZONG BUILDER STATUS ==="
tc-collab-status
if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  echo -n "service: "
  systemctl is-active technocore-collab || true
else
  tc-collab-process-status || true
fi

echo
echo "AIZONG_BUILDER_READY"
echo "No DID/private key/mailbox was replaced or created."
