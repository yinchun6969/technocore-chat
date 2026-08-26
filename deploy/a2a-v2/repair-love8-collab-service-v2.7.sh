#!/usr/bin/env bash
set -Eeuo pipefail

# Restore only the Love8 A2A sidecar systemd unit.
# Existing identity, .env, peer mesh, cursor and workflow state are untouched.

ROOT="/opt/technocore-collab"
ENV_FILE="$ROOT/.env"
AGENT="$ROOT/bin/collab.py"
PYTHON="$ROOT/venv/bin/python"
SERVICE="technocore-collab"
UNIT="/etc/systemd/system/$SERVICE.service"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -f "$ENV_FILE" ] || die "找不到 $ENV_FILE；不会创建新身份"
[ -f "$AGENT" ] || die "找不到 $AGENT；不会重装 sidecar"
[ -x "$PYTHON" ] || die "找不到 sidecar Python runtime：$PYTHON；不会覆盖现有配置"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
[ "${AGENT_NAME:-}" = "love8" ] || die "当前 sidecar 不是 love8：${AGENT_NAME:-unknown}"
[ "${ROLE:-}" = "scout" ] || die "当前角色不是 scout：${ROLE:-unknown}"

"$PYTHON" -m py_compile "$AGENT"

if [ -f "$UNIT" ]; then
  cp -a "$UNIT" "$UNIT.before-v2.7-$STAMP"
fi

cat >"$UNIT" <<EOF
[Unit]
Description=Technocore signed A2A collaboration sidecar
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON $AGENT run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

if [ ! -x /usr/local/bin/tc-collab-status ]; then
  cat >/usr/local/bin/tc-collab-status <<EOF
#!/usr/bin/env bash
set -a; source $ENV_FILE; set +a
exec $PYTHON $AGENT status
EOF
  chmod 755 /usr/local/bin/tc-collab-status
fi

if [ ! -x /usr/local/bin/tc-collab-log ]; then
  cat >/usr/local/bin/tc-collab-log <<'EOF'
#!/usr/bin/env bash
exec journalctl -u technocore-collab -f
EOF
  chmod 755 /usr/local/bin/tc-collab-log
fi

systemctl daemon-reload
systemctl enable --now "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || {
  systemctl --no-pager --full status "$SERVICE" || true
  journalctl -u "$SERVICE" -n 50 --no-pager || true
  die "$SERVICE 启动失败"
}

echo "=== LOVE8 A2A SERVICE READY ==="
echo "agent=$AGENT_NAME"
echo "role=$ROLE"
echo "service=$(systemctl is-active "$SERVICE")"
"$PYTHON" "$AGENT" status
echo "--- recent log ---"
journalctl -u "$SERVICE" -n 30 --no-pager || true
echo "identity, .env, peers, cursor and workflow state were not replaced."
