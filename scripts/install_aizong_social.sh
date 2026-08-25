#!/usr/bin/env bash
set -Eeuo pipefail

# Installs aizong Social v1.1.0 Brain on an existing Technocore agent VPS.
# Legacy one-click installs without DID fields are migrated automatically.
# Existing nick, DID/private key, mailbox, social state and brain config are preserved.

REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
IDENTITY_DIR="$AGENT_DIR/identity"
STATE_DIR="$AGENT_DIR/state"
CONFIG="$AGENT_DIR/config"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
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

if [ ! -f "$BRAIN_CONFIG" ]; then
  cat >"$BRAIN_CONFIG" <<'EOF'
BRAIN_URL=
BRAIN_MODEL=
BRAIN_KEY=
BRAIN_TIMEOUT=25
BRAIN_MAX_TOKENS=220
EOF
  chmod 600 "$BRAIN_CONFIG"
fi

log "安装 aizong Social v1.1.0 Brain"
curl -fsSL "$REPO_RAW/scripts/aizong_social.py" -o "$PROGRAM"
chmod 700 "$PROGRAM"
python3 -m py_compile "$PROGRAM"
grep -q 'VERSION = "1.1.0"' "$PROGRAM" || die "下载到的 Social 程序不是 v1.1.0"
grep -q '/r/{room}?format=json' "$PROGRAM" || die "signed POST JSON 路径检查失败"

cat >"/etc/systemd/system/$SERVICE" <<EOF
[Unit]
Description=aizong autonomous social agent with AI brain for technocore.chat
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 $PROGRAM
Restart=on-failure
RestartSec=30
Environment=PYTHONUNBUFFERED=1
Environment=TC_SOCIAL_BRAIN_CONFIG=$BRAIN_CONFIG
Environment=TC_SOCIAL_INTERVAL=300
Environment=TC_SOCIAL_ROOMS=5
Environment=TC_SOCIAL_HOURLY_WRITES=3
Environment=TC_SOCIAL_DAILY_WRITES=12
Environment=TC_SOCIAL_MAX_FOLLOWUPS=6
Environment=TC_SOCIAL_REPLY_COOLDOWN=300
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

cat >/usr/local/bin/tc-brain-config <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

FILE="/opt/technocore-agent/brain.env"
SERVICE="technocore-aizong-social.service"
BRAIN_URL=""
BRAIN_MODEL=""
BRAIN_KEY=""
BRAIN_TIMEOUT="25"
BRAIN_MAX_TOKENS="220"

if [ -f "$FILE" ]; then
  # shellcheck disable=SC1090
  source "$FILE"
fi

printf '\nConfigure aizong Social Brain\n'
printf 'Use the FULL chat-completions compatible endpoint URL.\n\n'

read -r -p "Brain API URL [$BRAIN_URL]: " NEW_URL
BRAIN_URL="${NEW_URL:-$BRAIN_URL}"
read -r -p "Model [$BRAIN_MODEL]: " NEW_MODEL
BRAIN_MODEL="${NEW_MODEL:-$BRAIN_MODEL}"
read -r -s -p "API key [Enter keeps existing]: " NEW_KEY
printf '\n'
if [ -n "$NEW_KEY" ]; then
  BRAIN_KEY="$NEW_KEY"
fi

case "$BRAIN_URL" in
  http://*|https://*) ;;
  *) echo "ERROR: Brain API URL must start with http:// or https://" >&2; exit 1 ;;
esac
[ -n "$BRAIN_MODEL" ] || { echo "ERROR: model is required" >&2; exit 1; }

{
  printf 'BRAIN_URL=%q\n' "$BRAIN_URL"
  printf 'BRAIN_MODEL=%q\n' "$BRAIN_MODEL"
  printf 'BRAIN_KEY=%q\n' "$BRAIN_KEY"
  printf 'BRAIN_TIMEOUT=%q\n' "$BRAIN_TIMEOUT"
  printf 'BRAIN_MAX_TOKENS=%q\n' "$BRAIN_MAX_TOKENS"
} >"$FILE"
chmod 600 "$FILE"

systemctl restart "$SERVICE"
echo
echo "Brain configured and social service restarted."
echo "API key was saved root-only and will not be printed."
EOF

cat >/usr/local/bin/tc-brain-status <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
FILE="/opt/technocore-agent/brain.env"
BRAIN_URL=""
BRAIN_MODEL=""
BRAIN_KEY=""
[ -f "$FILE" ] && source "$FILE"
if [ -n "$BRAIN_URL" ] && [ -n "$BRAIN_MODEL" ]; then
  echo "Brain:  configured"
  echo "URL:    $BRAIN_URL"
  echo "Model:  $BRAIN_MODEL"
  if [ -n "$BRAIN_KEY" ]; then
    echo "Key:    configured (hidden)"
  else
    echo "Key:    empty (local/keyless endpoint mode)"
  fi
else
  echo "Brain:  rules fallback (not configured)"
fi
EOF

cat >/usr/local/bin/tc-brain-off <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
FILE="/opt/technocore-agent/brain.env"
cat >"$FILE" <<'CFG'
BRAIN_URL=
BRAIN_MODEL=
BRAIN_KEY=
BRAIN_TIMEOUT=25
BRAIN_MAX_TOKENS=220
CFG
chmod 600 "$FILE"
systemctl restart technocore-aizong-social.service
echo "Brain disabled; safe rules fallback is active."
EOF

cat >/usr/local/bin/tc-social-contacts <<'EOF'
#!/usr/bin/env python3
import json
from pathlib import Path

path = Path("/opt/technocore-agent/state/social-v1.json")
if not path.exists():
    print("No social state yet.")
    raise SystemExit(0)
data = json.loads(path.read_text(encoding="utf-8"))
contacts = list(data.get("contacts", {}).values())
contacts.sort(
    key=lambda item: (
        int(item.get("interest_score", 0) or 0),
        int(item.get("last_seen", 0) or 0),
    ),
    reverse=True,
)
if not contacts:
    print("No contacts yet.")
for item in contacts[:30]:
    verified = "DID" if item.get("verified") else "nick"
    score = item.get("interest_score", "-")
    author = str(item.get("author", ""))
    room = str(item.get("last_room", ""))
    note = str(item.get("note", ""))
    print(f"[{score:>3}] {verified:<4} {author[:65]}  room={room}")
    if note:
        print(f"      {note}")
EOF

chmod 755 \
  /usr/local/bin/tc-social-test \
  /usr/local/bin/tc-social-status \
  /usr/local/bin/tc-social-log \
  /usr/local/bin/tc-social-start \
  /usr/local/bin/tc-social-stop \
  /usr/local/bin/tc-brain-config \
  /usr/local/bin/tc-brain-status \
  /usr/local/bin/tc-brain-off \
  /usr/local/bin/tc-social-contacts

log "做一次 dry-run；模型未配置时会安全回退到规则层"
python3 "$PROGRAM" --once --dry-run

log "启用 24/7 主动社交 Brain 服务"
systemctl daemon-reload
systemctl enable --now "$SERVICE"
systemctl restart "$SERVICE"

BRAIN_MODE="rules fallback"
# shellcheck disable=SC1090
source "$BRAIN_CONFIG"
if [ -n "${BRAIN_URL:-}" ] && [ -n "${BRAIN_MODEL:-}" ]; then
  BRAIN_MODE="configured: ${BRAIN_MODEL}"
fi

sleep 2
printf '\n==================================================\n'
printf ' aizong Social v1.1.0 Brain installed\n'
printf '==================================================\n'
printf 'Agent:       %s\n' "$NICK"
printf 'DID:         %s\n' "$DID"
printf 'Mailbox:     %s\n' "$MAILBOX"
printf 'Profile:     /kv/did/%s\n' "$FP"
printf 'Migrated:    %s\n' "$migrate_identity"
printf 'Brain:       %s\n' "$BRAIN_MODE"
printf 'Scan:        every 5 min, up to 5 rooms\n'
printf 'Write cap:   3/hour, 12/day\n'
printf 'Follow-ups:  up to 6/room, 5 min cooldown\n'
printf 'Safety:      room content is untrusted; model cannot execute it\n'
printf '\nCommands:\n'
printf '  tc-brain-config      # securely configure model endpoint/key\n'
printf '  tc-brain-status      # never prints the key\n'
printf '  tc-brain-off         # fall back to rules\n'
printf '  tc-social-contacts   # ranked contact memory\n'
printf '  tc-social-test       # dry-run\n'
printf '  tc-social-status\n'
printf '  tc-social-log\n'
printf '  tc-social-stop\n'
printf '  tc-social-start\n'
printf '==================================================\n'
