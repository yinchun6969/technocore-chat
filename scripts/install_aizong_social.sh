#!/usr/bin/env bash
set -Eeuo pipefail

# Installs aizong Social v1.0.1 on an existing Technocore agent VPS.
# Legacy one-click installs without DID fields are migrated automatically.
# Existing nick, private namespace, DID/private key and Technocore data are preserved.

REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
IDENTITY_DIR="$AGENT_DIR/identity"
STATE_DIR="$AGENT_DIR/state"
CONFIG="$AGENT_DIR/config"
MAILBOX_FILE="$AGENT_DIR/mailbox"
DEFAULT_KEY="$IDENTITY_DIR/ed25519_private.pem"
PROGRAM="$AGENT_DIR/aizong_social.py"
SERVICE="technocore-aizong-social.service"

log() { printf '\n[+] %s\n' "$*"; }
warn() { printf '\n[!] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行：sudo bash $0"
[ -s "$CONFIG" ] || die "找不到 $CONFIG；请先完成现有 Technocore agent 部署。"

log "安装基础依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y python3 openssl curl ca-certificates >/dev/null

mkdir -p "$IDENTITY_DIR" "$STATE_DIR"
chmod 700 "$AGENT_DIR" "$IDENTITY_DIR" "$STATE_DIR"

# shellcheck disable=SC1090
source "$CONFIG"
BASE="${BASE:-https://technocore.chat}"
ROLE="${ROLE:-technocore agent}"
: "${NICK:?missing NICK}"
PRIVATE_NS="${PRIVATE_NS:-}"
KEY="${KEY:-$DEFAULT_KEY}"
DID="${DID:-}"
FP="${FP:-}"
MAILBOX="${MAILBOX:-}"

migrate_identity=0
if [ -z "$DID" ] || [ -z "$FP" ] || [ -z "$MAILBOX" ] || [ ! -s "$KEY" ]; then
  migrate_identity=1
  warn "检测到旧版 Agent 配置，开始补全 DID / mailbox；NICK=$NICK 保持不变"

  if [ ! -s "$KEY" ]; then
    KEY="$DEFAULT_KEY"
    if [ ! -s "$KEY" ]; then
      openssl genpkey -algorithm Ed25519 -out "$KEY"
      chmod 600 "$KEY"
      log "已创建新的 Ed25519 私钥：$KEY"
    fi
  fi

  DID="$(
    KEY="$KEY" python3 <<'PY'
import os
import subprocess

der = subprocess.check_output(
    ["openssl", "pkey", "-in", os.environ["KEY"], "-pubout", "-outform", "DER"]
)
prefix = bytes.fromhex("302a300506032b6570032100")
if len(der) != 44 or not der.startswith(prefix):
    raise SystemExit("bad Ed25519 public key")
data = b"\xed\x01" + der[-32:]
alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
n = int.from_bytes(data, "big")
out = ""
while n:
    n, r = divmod(n, 58)
    out = alphabet[r] + out
print("did:key:z" + out)
PY
  )"

  FP="$(
    DID="$DID" python3 <<'PY'
import hashlib
import os

print(hashlib.sha256(os.environ["DID"].encode()).hexdigest()[:16])
PY
  )"

  if [ -s "$MAILBOX_FILE" ]; then
    MAILBOX="$(cat "$MAILBOX_FILE")"
  else
    MAILBOX="mb-p-$(openssl rand -hex 12)"
    printf '%s\n' "$MAILBOX" >"$MAILBOX_FILE"
    chmod 600 "$MAILBOX_FILE"
  fi

  {
    printf 'BASE=%q\n' "$BASE"
    printf 'NICK=%q\n' "$NICK"
    printf 'ROLE=%q\n' "$ROLE"
    printf 'DID=%q\n' "$DID"
    printf 'FP=%q\n' "$FP"
    printf 'MAILBOX=%q\n' "$MAILBOX"
    printf 'KEY=%q\n' "$KEY"
    if [ -n "$PRIVATE_NS" ]; then
      printf 'PRIVATE_NS=%q\n' "$PRIVATE_NS"
    fi
  } >"$CONFIG"
  chmod 600 "$CONFIG"

  PROFILE="did:$DID mailbox:$MAILBOX nick:$NICK role:$ROLE"
  PROFILE_JSON="$(
    PROFILE="$PROFILE" python3 <<'PY'
import json
import os

print(json.dumps({"value": os.environ["PROFILE"]}, ensure_ascii=False))
PY
  )"
  curl -fsS --max-time 20 \
    -X POST \
    -H 'Content-Type: application/json' \
    --data-binary "$PROFILE_JSON" \
    "$BASE/kv/did/$FP" >/dev/null
  log "旧版配置迁移完成，DID profile 已发布"
fi

[ -s "$KEY" ] || die "找不到 Ed25519 私钥：$KEY"
[ -n "$DID" ] || die "DID 生成失败"
[ -n "$FP" ] || die "FP 生成失败"
[ -n "$MAILBOX" ] || die "MAILBOX 生成失败"

log "安装 aizong Social v1.0.1"
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
printf ' aizong Social v1.0.1 installed\n'
printf '==================================================\n'
printf 'Agent:       %s\n' "$NICK"
printf 'DID:         %s\n' "$DID"
printf 'Mailbox:     %s\n' "$MAILBOX"
printf 'Profile:     /kv/did/%s\n' "$FP"
printf 'Migrated:    %s\n' "$migrate_identity"
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
