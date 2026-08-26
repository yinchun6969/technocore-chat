#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-a2a"
ENV_FILE="$ROOT/.env"
AGENT_PY="$ROOT/bin/agent.py"
HELPER="$ROOT/bin/capacity-retry.py"
SERVICE="technocore-a2a"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo bash repair-capacity-v1.4.sh"
  exit 1
fi

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
[[ -f "$AGENT_PY" ]] || { echo "Missing $AGENT_PY"; exit 1; }

cat > "$HELPER" <<'PY'
#!/usr/bin/env python3
import importlib.util
import os
import time
from pathlib import Path

ROOT = Path('/opt/technocore-a2a')
STATE = ROOT / 'state'
ENV_FILE = ROOT / '.env'
AGENT_PY = ROOT / 'bin' / 'agent.py'
MAILBOX_READY = STATE / 'mailbox.ready'
ROOM_READY = STATE / 'room.ready'
INIT_MARK = STATE / 'init.done'

for raw in ENV_FILE.read_text().splitlines():
    if not raw or raw.lstrip().startswith('#') or '=' not in raw:
        continue
    k, v = raw.split('=', 1)
    os.environ[k] = v

spec = importlib.util.spec_from_file_location('tc_a2a_agent', AGENT_PY)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def capacity_error(exc):
    return 'room limit reached' in str(exc).lower()


def mark(path):
    path.write_text(str(time.time()))

STATE.mkdir(parents=True, exist_ok=True)

# Profile and ownership note do not consume a room slot. Keep them refreshed/idempotent.
try:
    agent.publish_profile()
except Exception as e:
    print('profile refresh failed:', e)

try:
    agent.claim_room()
except Exception as e:
    print('room ownership check failed:', e)

# Mailbox is more important for A2A than the public owned-room intro, so reserve it first
# when a slot becomes available. Only one bootstrap write is made, guarded by a local mark.
if not MAILBOX_READY.exists():
    try:
        agent.signed_post(
            agent.MAILBOX,
            f'A2A mailbox online. did={agent.DID} protocol=A2A1',
        )
        mark(MAILBOX_READY)
        agent.ledger('mailbox_ready', mailbox=agent.MAILBOX)
        print('mailbox: READY')
    except Exception as e:
        if capacity_error(e):
            print('mailbox: PENDING — Technocore global room capacity is full')
            raise SystemExit(0)
        raise
else:
    print('mailbox: READY (existing local mark)')

if not ROOM_READY.exists():
    try:
        agent.signed_post(
            agent.ROOM,
            f'A2A agent online. role=reviewer did={agent.DID} mailbox={agent.MAILBOX} protocol=A2A1',
        )
        mark(ROOM_READY)
        agent.ledger('owned_room_ready', room=agent.ROOM)
        print('owned room: READY')
    except Exception as e:
        if capacity_error(e):
            print('owned room: PENDING — mailbox is ready; waiting for another free room slot')
            raise SystemExit(0)
        raise
else:
    print('owned room: READY (existing local mark)')

if MAILBOX_READY.exists() and ROOM_READY.exists():
    if not INIT_MARK.exists():
        mark(INIT_MARK)
        agent.ledger('initialized', room=agent.ROOM, mailbox=agent.MAILBOX)
    print('A2A bootstrap: READY')
    print('DID:', agent.DID)
    print('Room:', agent.ROOM)
    print('Mailbox:', agent.MAILBOX)
PY

chmod 0750 "$HELPER"
chown root:tcagent "$HELPER" 2>/dev/null || true

cat > /etc/systemd/system/technocore-a2a-capacity.service <<EOF
[Unit]
Description=Technocore A2A capacity bootstrap retry
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$ROOT/venv/bin/python $HELPER
EOF

cat > /etc/systemd/system/technocore-a2a-capacity.timer <<'EOF'
[Unit]
Description=Retry Technocore A2A bootstrap when room capacity frees

[Timer]
OnBootSec=45s
OnUnitActiveSec=15min
RandomizedDelaySec=60s
Persistent=true
Unit=technocore-a2a-capacity.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now technocore-a2a-capacity.timer
systemctl enable --now "$SERVICE" 2>/dev/null || true

# Run one capacity attempt now. Capacity-full is deliberately a successful pending state.
systemctl start technocore-a2a-capacity.service || true

echo
echo "=== CURRENT CAPACITY STATE ==="
systemctl --no-pager --full status technocore-a2a-capacity.service | sed -n '1,18p' || true

echo
echo "=== TIMER ==="
systemctl list-timers technocore-a2a-capacity.timer --no-pager || true

echo
echo "=== AGENT IDENTITY (no secrets) ==="
tc-a2a-status || true

echo
echo "v1.4 installed. No DID/key/mailbox was replaced."
echo "The helper retries every 15 minutes and stops creating duplicates via local readiness marks."
