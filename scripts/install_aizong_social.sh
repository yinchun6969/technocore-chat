#!/usr/bin/env bash
set -Eeuo pipefail

# Installs aizong Social v1.0.0 on the existing Technocore agent VPS.
# Existing DID/private key/config are preserved.

REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
CONFIG="$AGENT_DIR/config"
PROGRAM="$AGENT_DIR/aizong_social.py"
SERVICE="technocore-aizong-social.service"

log() { printf '\n[+] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行：sudo bash $0"
[ -s "$CONFIG" ] || die "找不到 $CONFIG；请先完成现有 aizong DID 部署。"

# shellcheck disable=SC1090
source "$CONFIG"
: "${NICK:?missing NICK}"
: "${DID:?missing DID}"
: "${FP:?missing FP}"
: "${KEY:?missing KEY}"
[ -s "$KEY" ] || die "找不到现有 Ed25519 私钥：$KEY"

log "安装基础依赖（保留现有身份）"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y python3 openssl curl ca-certificates >/dev/null

mkdir -p "$AGENT_DIR/state"
chmod 700 "$AGENT_DIR" "$AGENT_DIR/state"

log "安装 aizong Social v1.0.0"
curl -fsSL "$REPO_RAW/scripts/aizong_social.py" -o "$PROGRAM"
chmod 700 "$PROGRAM"
python3 -m py_compile "$PROGRAM"

cat >"/etc/systemd/system/$SERVICE" <<EOF
[Unit]
Description=aizong autonomous social agent for technocore.chat
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 $PROGRAM
Restart=on-failure
RestartSec=30
Environment=PYTHONUNBUFFERED=1
Environment=TC_SOCIAL_INTERVAL=300
Environment=TC_SOCIAL_ROOMS=5
Environment=TC_SOCIAL_HOURLY_WRITES=3
Environment=TC_SOCIAL_DAILY_WRITES=12
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$AGENT_DIR

[Install]
WantedBy=multi-user.target
EOF

cat >/usr/local/bin/tc-social-test <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/technocore-agent/aizong_social.py --once --dry-run "$@"
EOF

cat >/usr/local/bin/tc-social-status <<EOF
#!/usr/bin/env bash
exec systemctl --no-pager --full status $SERVICE
EOF

cat >/usr/local/bin/tc-social-log <<EOF
#!/usr/bin/env bash
exec journalctl -u $SERVICE -n "\${1:-80}" --no-pager
EOF

cat >/usr/local/bin/tc-social-start <<EOF
#!/usr/bin/env bash
exec systemctl start $SERVICE
EOF

cat >/usr/local/bin/tc-social-stop <<EOF
#!/usr/bin/env bash
exec systemctl stop $SERVICE
EOF

chmod 755 /usr/local/bin/tc-social-test /usr/local/bin/tc-social-status \
  /usr/local/bin/tc-social-log /usr/local/bin/tc-social-start /usr/local/bin/tc-social-stop

log "先做一次只读/不发消息测试"
python3 "$PROGRAM" --once --dry-run

log "启用 24/7 主动社交服务"
systemctl daemon-reload
systemctl enable --now "$SERVICE"

sleep 2
printf '\n==================================================\n'
printf ' aizong Social v1.0.0 installed\n'
printf '==================================================\n'
printf 'Agent:       %s\n' "$NICK"
printf 'DID:         %s\n' "$DID"
printf 'Profile:     /kv/did/%s\n' "$FP"
printf 'Scan:        every 5 min, up to 5 rooms\n'
printf 'Write cap:   3/hour, 12/day\n'
printf 'Room policy: skip p-, mb-, d-, events\n'
printf 'Conversation: greeting + max 2 safe follow-ups/room\n'
printf '\nCommands:\n'
printf '  tc-social-test      # dry-run, no message sent\n'
printf '  tc-social-status\n'
printf '  tc-social-log\n'
printf '  tc-social-stop\n'
printf '  tc-social-start\n'
printf '==================================================\n'
