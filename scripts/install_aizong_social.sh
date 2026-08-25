#!/usr/bin/env bash
set -Eeuo pipefail

# Installs or upgrades aizong Social Brain v1.2.0.
# Legacy Technocore one-click installs are migrated to DID/mailbox first.

REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
IDENTITY_DIR="$AGENT_DIR/identity"
STATE_DIR="$AGENT_DIR/state"
CONFIG="$AGENT_DIR/config"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
MAILBOX_FILE="$AGENT_DIR/mailbox"
DEFAULT_KEY="$IDENTITY_DIR/ed25519_private.pem"
UPGRADE="/tmp/upgrade_aizong_social_v120.sh"

log() { printf '\n[+] %s\n' "$*"; }
warn() { printf '\n[!] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行：sudo bash $0"
[ -s "$CONFIG" ] || die "找不到 $CONFIG；请先完成 Technocore agent 基础部署。"

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
  warn "检测到旧版 Agent 配置，补全 DID / mailbox；NICK=$NICK 保持不变"

  if [ ! -s "$KEY" ]; then
    KEY="$DEFAULT_KEY"
    openssl genpkey -algorithm Ed25519 -out "$KEY"
    chmod 600 "$KEY"
    log "已创建 Ed25519 私钥"
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
  log "DID profile 已发布"
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
BRAIN_MAX_TOKENS=768
EOF
  chmod 600 "$BRAIN_CONFIG"
fi

log "安装 Relationship Intelligence v1.2"
curl -fsSL "$REPO_RAW/scripts/upgrade_aizong_social_v120.sh" -o "$UPGRADE"
chmod 700 "$UPGRADE"
bash -n "$UPGRADE"
REPO_RAW="$REPO_RAW" bash "$UPGRADE"

printf '\nIdentity migrated this run: %s\n' "$migrate_identity"
