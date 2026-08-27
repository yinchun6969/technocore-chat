#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-a2a"
ENV_FILE="$ROOT/.env"
RUNTIME="$ROOT/bin/agent.py"
VENV_PY="$ROOT/venv/bin/python"
RND_DIR="$ROOT/rnd-v5"
STATE_DIR="$ROOT/rnd-v5-state"
HELPER="$RND_DIR/identity-room-v5.2.py"
SERVICE="technocore-a2a-rnd-v5.service"
SYNC_SERVICE="technocore-a2a-identity-room-v52.service"
SYNC_TIMER="technocore-a2a-identity-room-v52.timer"
RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v5/deploy/a2a-v5/identity-room-v5.2.py"

log(){ printf '\n[+] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$ENV_FILE" && -s "$RUNTIME" ]] || die "找不到现有 AI2AI runtime: $ROOT"
[[ -x "$VENV_PY" ]] || die "找不到 AI2AI venv Python: $VENV_PY"
command -v curl >/dev/null || die "curl 未安装"
command -v systemctl >/dev/null || die "systemctl 未安装"

AGENT_NAME="$(awk -F= '$1=="AGENT_NAME"{print substr($0,index($0,"=")+1);exit}' "$ENV_FILE")"
[[ -n "$AGENT_NAME" ]] || die ".env 缺少 AGENT_NAME"
[[ "$AGENT_NAME" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || die "AGENT_NAME 无效: $AGENT_NAME"

mkdir -p "$RND_DIR" "$STATE_DIR" "$ROOT/backups"
chmod 750 "$RND_DIR" "$STATE_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$ROOT/backups/identity-room-v520-$TS"
mkdir -p "$BACKUP"; chmod 700 "$BACKUP"
cp -a "$STATE_DIR/director.json" "$STATE_DIR/identity-room-v520.json" "$BACKUP/" 2>/dev/null || true
systemctl cat "$SERVICE" >"$BACKUP/${SERVICE}.txt" 2>/dev/null || true

TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
log "下载 AI2AI Identity Room v5.2"
curl -fsSL --retry 5 --retry-delay 2 "$RAW" -o "$TMP"
"$VENV_PY" -m py_compile "$TMP"
grep -q 'VERSION = "5.2.0"' "$TMP" || die "版本校验失败"
install -o root -g tcagent -m 0750 "$TMP" "$HELPER"

log "解析身份同名房间；重名自动使用 00/01/..."
ROOM="$($VENV_PY "$HELPER" resolve 2>"$BACKUP/resolve.stderr")"
[[ "$ROOM" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || die "解析出的 room 无效: $ROOM"
echo "$ROOM" >"$BACKUP/resolved-room.txt"

DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
mkdir -p "$DROPIN_DIR"
cat >"$DROPIN_DIR/95-identity-room-v520.conf" <<EOF
[Service]
Environment=RND_V5_DISCUSSION_ROOM=$ROOM
Environment=RND_V5_DISCUSSION_ENABLED=1
Environment=RND_V5_DISCUSSION_MAX_DAILY=8
EOF
chmod 644 "$DROPIN_DIR/95-identity-room-v520.conf"

cat >"/etc/systemd/system/$SYNC_SERVICE" <<EOF
[Unit]
Description=AI2AI v5.2 identity-room sync and mature-peer invitations
After=network-online.target technocore-a2a.service $SERVICE
Wants=network-online.target

[Service]
Type=oneshot
User=tcagent
Group=tcagent
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_PY $HELPER sync
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$ROOT/state $ROOT/identity $ROOT/rnd-v5-state
EOF

cat >"/etc/systemd/system/$SYNC_TIMER" <<EOF
[Unit]
Description=Run AI2AI identity-room sync every 6 hours

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
chmod 755 /usr/local/bin/tc-ai2ai-room-status

cat >/usr/local/bin/tc-ai2ai-room-sync <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
systemctl start "$SYNC_SERVICE"
systemctl --no-pager --full status "$SYNC_SERVICE" || true
"$VENV_PY" "$HELPER" status
EOF
chmod 755 /usr/local/bin/tc-ai2ai-room-sync

log "切换 R&D v5 到 /r/$ROOM，并立即 bootstrap + 邀请成熟 peer"
systemctl daemon-reload
systemctl stop "$SERVICE" 2>/dev/null || true
"$VENV_PY" "$HELPER" sync
systemctl restart "$SERVICE"
systemctl enable --now "$SYNC_TIMER"
sleep 3
systemctl is-active --quiet "$SERVICE" || die "$SERVICE 启动失败；备份在 $BACKUP"

cat <<EOF

============================================================
 AI2AI IDENTITY ROOM v5.2.0 READY
============================================================
Agent:             $AGENT_NAME
Resolved room:     /r/$ROOM
Collision policy:  $AGENT_NAME -> ${AGENT_NAME}00 -> ${AGENT_NAME}01 -> ... -> ${AGENT_NAME}99
Deep peer gate:    pinned peer + >=3 inbound + >=3 outbound + >=6h history
Invite rate:       max 3/day; same peer max once/7 days
R&D director:      now publishes deep research topics to /r/$ROOM
Recurring sync:    every 6h
Status:            tc-ai2ai-room-status
Manual sync:       tc-ai2ai-room-sync
Backup:            $BACKUP
============================================================
EOF
/usr/local/bin/tc-ai2ai-room-status || true
