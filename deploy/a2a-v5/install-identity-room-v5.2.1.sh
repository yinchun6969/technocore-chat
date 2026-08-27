#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-a2a"
ENV_FILE="$ROOT/.env"
RUNTIME="$ROOT/bin/agent.py"
VENV_PY="$ROOT/venv/bin/python"
RND_DIR="$ROOT/rnd-v5"
STATE_DIR="$ROOT/rnd-v5-state"
CORE="$RND_DIR/identity-room-v5.2.py"
HELPER="$RND_DIR/identity-room-v5.2.1.py"
SERVICE="technocore-a2a-rnd-v5.service"
SYNC_SERVICE="technocore-a2a-identity-room-v52.service"
SYNC_TIMER="technocore-a2a-identity-room-v52.timer"
RAW_BASE="https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v5/deploy/a2a-v5"
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/95-identity-room-v520.conf"

log(){ printf '\n[+] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$ENV_FILE" && -s "$RUNTIME" ]] || die "找不到现有 AI2AI runtime: $ROOT"
[[ -x "$VENV_PY" ]] || die "找不到 AI2AI venv Python: $VENV_PY"
command -v curl >/dev/null || die "curl 未安装"
command -v systemctl >/dev/null || die "systemctl 未安装"

AGENT_NAME="$(awk -F= '$1=="AGENT_NAME"{print substr($0,index($0,"=")+1);exit}' "$ENV_FILE")"
OWNED_ROOM="$(awk -F= '$1=="OWNED_ROOM"{print substr($0,index($0,"=")+1);exit}' "$ENV_FILE")"
[[ "$AGENT_NAME" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || die "AGENT_NAME 无效: $AGENT_NAME"
[[ "$OWNED_ROOM" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || die "OWNED_ROOM 无效: $OWNED_ROOM"

mkdir -p "$RND_DIR" "$STATE_DIR" "$ROOT/backups" "$DROPIN_DIR"
chmod 750 "$RND_DIR" "$STATE_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$ROOT/backups/identity-room-v521-$TS"
mkdir -p "$BACKUP"; chmod 700 "$BACKUP"
cp -a "$CORE" "$HELPER" "$STATE_DIR/identity-room-v520.json" "$DROPIN" "$BACKUP/" 2>/dev/null || true

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if [[ ! -s "$CORE" ]]; then
  log "补齐 v5.2 core helper"
  curl -fsSL --retry 5 --retry-delay 2 "$RAW_BASE/identity-room-v5.2.py" -o "$TMP/core.py"
  "$VENV_PY" -m py_compile "$TMP/core.py"
  install -o root -g tcagent -m 0750 "$TMP/core.py" "$CORE"
fi

log "下载 AI2AI Identity Room v5.2.1 capacity-aware helper"
curl -fsSL --retry 5 --retry-delay 2 "$RAW_BASE/identity-room-v5.2.1.py" -o "$TMP/helper.py"
"$VENV_PY" -m py_compile "$TMP/helper.py" "$CORE"
grep -q 'VERSION = "5.2.1"' "$TMP/helper.py" || die "版本校验失败"
install -o root -g tcagent -m 0750 "$TMP/helper.py" "$HELPER"

cat >/usr/local/bin/tc-ai2ai-room-sync-internal <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
VENV_PY="$VENV_PY"
HELPER="$HELPER"
DROPIN="$DROPIN"
SERVICE="$SERVICE"
"\$VENV_PY" "\$HELPER" sync
ROOM="\$("\$VENV_PY" "\$HELPER" current)"
[[ "\$ROOM" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || { echo "invalid resolved room: \$ROOM" >&2; exit 2; }
CURRENT="\$(awk -F= '/Environment=RND_V5_DISCUSSION_ROOM=/{print \$3}' "\$DROPIN" 2>/dev/null | tail -n1 || true)"
if [[ "\$CURRENT" != "\$ROOM" ]]; then
  mkdir -p "$(dirname "$DROPIN")"
  cat >"\$DROPIN" <<EOD
[Service]
Environment=RND_V5_DISCUSSION_ROOM=\$ROOM
Environment=RND_V5_DISCUSSION_ENABLED=1
Environment=RND_V5_DISCUSSION_MAX_DAILY=8
EOD
  chmod 644 "\$DROPIN"
  systemctl daemon-reload
  systemctl restart "\$SERVICE"
fi
EOF
chmod 755 /usr/local/bin/tc-ai2ai-room-sync-internal

cat >"/etc/systemd/system/$SYNC_SERVICE" <<EOF
[Unit]
Description=AI2AI v5.2.1 capacity-aware identity-room sync
After=network-online.target technocore-a2a.service
Wants=network-online.target

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/bin/tc-ai2ai-room-sync-internal
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
EOF

cat >"/etc/systemd/system/$SYNC_TIMER" <<EOF
[Unit]
Description=Run AI2AI capacity-aware identity-room sync every 6 hours

[Timer]
OnBootSec=5min
OnUnitActiveSec=6h
RandomizedDelaySec=10min
Persistent=true
Unit=$SYNC_SERVICE

[Install]
WantedBy=timers.target
EOF

cat >/usr/local/bin/tc-ai2ai-room-status <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$VENV_PY" "$HELPER" status
EOF
cat >/usr/local/bin/tc-ai2ai-room-sync <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
systemctl start "$SYNC_SERVICE"
systemctl --no-pager --full status "$SYNC_SERVICE" || true
"$VENV_PY" "$HELPER" status
EOF
chmod 755 /usr/local/bin/tc-ai2ai-room-status /usr/local/bin/tc-ai2ai-room-sync

log "立即同步；若 20480/20480 则自动复用已有 /r/$OWNED_ROOM"
systemctl daemon-reload
/usr/local/bin/tc-ai2ai-room-sync-internal
systemctl enable --now "$SYNC_TIMER"
sleep 2
systemctl is-active --quiet "$SERVICE" || die "$SERVICE 未运行；备份在 $BACKUP"

cat <<EOF

============================================================
 AI2AI IDENTITY ROOM v5.2.1 CAPACITY-AWARE READY
============================================================
Desired room:       /r/$AGENT_NAME
Capacity fallback: /r/$OWNED_ROOM (must already be owned by the same DID)
Retry migration:   every 6h
Collision policy:  $AGENT_NAME -> ${AGENT_NAME}00 -> ${AGENT_NAME}01 -> ...
Deep peer gate:    pinned peer + >=3 inbound + >=3 outbound + >=6h
Invite rate:       max 3/day; same peer max once/7 days
Status:            tc-ai2ai-room-status
Manual sync:       tc-ai2ai-room-sync
Backup:            $BACKUP
============================================================
EOF
tc-ai2ai-room-status
