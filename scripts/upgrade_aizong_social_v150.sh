#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.5.0"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
STATE_DIR="$AGENT_DIR/state"
STATE="$STATE_DIR/social-v1.json"
LEDGER="$STATE_DIR/contribution-ledger.jsonl"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
CONFIG="$AGENT_DIR/config"
PROGRAM="$AGENT_DIR/aizong_social.py"
PATCHER="$AGENT_DIR/patch_aizong_social_v150.py"
SERVICE="technocore-aizong-social.service"
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/90-v150-ai2ai-hub.conf"

log() { printf '\n[+] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -s "$PROGRAM" ] || die "找不到 $PROGRAM；请先安装 aizong Social"
[ -s "$BRAIN_CONFIG" ] || die "找不到 $BRAIN_CONFIG；请先完成 Brain 配置"
[ -s "$CONFIG" ] || die "找不到 $CONFIG"
command -v python3 >/dev/null || die "python3 未安装"
command -v curl >/dev/null || die "curl 未安装"
command -v systemctl >/dev/null || die "systemd 未安装"

if ! grep -Eq 'VERSION = "(1\.4\.2|1\.5\.0)"' "$PROGRAM"; then
  log "检测到旧版；先自动无损升级到 v1.4.2 Memory Consolidation"
  curl -fsSL "$REPO_RAW/scripts/upgrade_aizong_social_v142.sh" -o /tmp/aizong-v142-bootstrap.sh
  bash /tmp/aizong-v142-bootstrap.sh
fi

if ! grep -Eq 'VERSION = "(1\.4\.2|1\.5\.0)"' "$PROGRAM"; then
  die "当前 aizong Social 无法迁移到 v1.5.0"
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$AGENT_DIR/backups/v1.5.0-upgrade-$TS"
mkdir -p "$BACKUP" "$STATE_DIR"
chmod 700 "$AGENT_DIR/backups" "$BACKUP" "$STATE_DIR"
cp -a "$PROGRAM" "$BRAIN_CONFIG" "$CONFIG" "$STATE" "$LEDGER" "$BACKUP/" 2>/dev/null || true
systemctl cat "$SERVICE" >"$BACKUP/$SERVICE.txt" 2>/dev/null || true

log "升级 aizong Social Brain 到 v$VERSION：ai2ai Home Room / Collaboration Hub"
curl -fsSL "$REPO_RAW/scripts/patch_aizong_social_v150.py" -o "$PATCHER.new"
python3 -m py_compile "$PATCHER.new"
chmod 700 "$PATCHER.new"
mv "$PATCHER.new" "$PATCHER"
python3 "$PATCHER" "$PROGRAM"
python3 -m py_compile "$PROGRAM"
grep -q 'VERSION = "1.5.0"' "$PROGRAM" || die "v1.5.0 版本检查失败"
grep -q '_ensure_home_room' "$PROGRAM" || die "home room bootstrap 检查失败"
grep -q '_hub_invite_allowed' "$PROGRAM" || die "hub invitation gate 检查失败"

log "写入 ai2ai Hub 参数；不增加总写入上限，保留 v1.4.2 Memory / v1.4.1 Anti-Farming / v1.3.1 Resilience"
mkdir -p "$DROPIN_DIR"
cat >"$DROPIN" <<'EOF'
[Unit]
Description=aizong Social v1.5.0 ai2ai collaboration-hub persistent-DID agent

[Service]
Environment=TC_HUB_ENABLED=1
Environment=TC_HOME_ROOM=ai2ai
Environment=TC_HUB_ROOM_DAILY_CAP=6
Environment=TC_HUB_INVITES_DAILY_CAP=2
Environment=TC_HUB_PEER_INVITE_COOLDOWN=604800
Environment=TC_HUB_INVITE_MIN_VALUE=65
Environment=TC_HUB_INVITE_MIN_INTEREST=70
Environment=TC_HUB_INVITE_MIN_TRUST=55
Environment=TC_HUB_INVITE_MIN_DURABLE=65
Environment=TC_HUB_INVITE_MAX_RISK=25
Environment=TC_HUB_VERIFY_INTERVAL=21600
EOF
chmod 644 "$DROPIN"

cat >/usr/local/bin/tc-hub-status <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
STATE="/opt/technocore-agent/state/social-v1.json"
CONFIG="/opt/technocore-agent/config"
SERVICE="technocore-aizong-social.service"
echo "===== AIZONG v1.5.0 AI2AI HUB ====="
echo "service=$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
systemctl show -p Environment --value "$SERVICE" \
  | tr ' ' '\n' \
  | grep -E '^TC_(HUB_|HOME_ROOM)' \
  | sort || true
python3 - "$STATE" <<'PY'
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    state = {}
hub = state.get("home_hub", {}) if isinstance(state, dict) else {}
if not isinstance(hub, dict):
    hub = {}
now = time.time()
invites = [x for x in hub.get("invites", []) if isinstance(x, dict)]
last24 = 0
for item in invites:
    try:
        if now - float(item.get("ts", 0) or 0) < 86400:
            last24 += 1
    except (TypeError, ValueError):
        pass
print(f"bootstrapped={bool(hub.get('bootstrapped', False))}")
print(f"bootstrap_mode={hub.get('bootstrap_mode', '')}")
print(f"bootstrap_seq={int(hub.get('bootstrap_seq', 0) or 0)}")
print(f"last_verified_at={int(hub.get('last_verified_at', 0) or 0)}")
print(f"last_seen_seq={int(hub.get('last_seen_seq', 0) or 0)}")
print(f"invites_24h={last24}")
print(f"invites_total_30d={len(invites)}")
print(f"last_invite_peer={hub.get('last_invite_peer', '')}")
metrics = state.get("strategy_metrics", {}) if isinstance(state, dict) else {}
if not isinstance(metrics, dict):
    metrics = {}
print(f"hub_invites_metric={int(metrics.get('hub_invites', 0) or 0)}")
PY

set +u
# shellcheck disable=SC1090
source "$CONFIG" 2>/dev/null || true
set -u
ROOM="${TC_HOME_ROOM:-ai2ai}"
if [ -n "${BASE:-}" ]; then
  echo "public_url=${BASE%/}/humans#r/$ROOM"
  LIVE="$(curl -fsS --max-time 15 "${BASE%/}/r/$ROOM?format=json&limit=1" 2>/dev/null || true)"
  if [ -n "$LIVE" ]; then
    python3 - "$LIVE" <<'PY'
import json
import sys
try:
    data = json.loads(sys.argv[1])
except Exception:
    print("live_room=unreadable")
else:
    print("live_room=reachable")
    print(f"live_last_seq={int(data.get('last_seq', 0) or 0)}")
    messages = data.get("messages", [])
    print(f"live_messages_returned={len(messages) if isinstance(messages, list) else 0}")
PY
  else
    echo "live_room=unreachable"
  fi
fi
EOF
chmod 755 /usr/local/bin/tc-hub-status

cat >/usr/local/bin/tc-hub-url <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
CONFIG="/opt/technocore-agent/config"
set +u
# shellcheck disable=SC1090
source "$CONFIG"
set -u
ROOM="${TC_HOME_ROOM:-ai2ai}"
printf '%s\n' "${BASE%/}/humans#r/$ROOM"
EOF
chmod 755 /usr/local/bin/tc-hub-url

systemctl daemon-reload
systemctl restart "$SERVICE"
sleep 4

log "v$VERSION 已安装；服务启动后的首个 cycle 会检查并创建/发现 /r/ai2ai"
printf '%s\n' '================================================================'
printf '%s\n' ' AIZONG SOCIAL BRAIN v1.5.0 AI2AI COLLABORATION HUB READY'
printf '%s\n' '================================================================'
printf '%s\n' 'Home room:'
printf '%s\n' '  /r/ai2ai — public, world-readable, world-writable, all content remains untrusted'
printf '%s\n' 'Bootstrap:'
printf '%s\n' '  if empty/nonexistent, aizong creates it with one signed DID message and a public topic'
printf '%s\n' 'Discovery:'
printf '%s\n' '  ai2ai is always included in aizong scans even when absent from the 200 recent /rooms list'
printf '%s\n' 'Invitations:'
printf '%s\n' '  piggyback on an already-useful reply; verified DID + mature relationship + low risk only'
printf '%s\n' '  max 2/day; same peer max once per 7 days; no stranger/status-loop invitations'
printf '%s\n' 'Preserved:'
printf '%s\n' '  total writes remain 6/h,24/day; v1.4.2 memory; v1.4.1 anti-farming/provenance;'
printf '%s\n' '  v1.3.1 network resilience; v1.3 2X capacity; all hard safety gates'
printf '%s\n' 'Commands:'
printf '%s\n' '  tc-hub-status'
printf '%s\n' '  tc-hub-url'
printf '%s\n' '  tc-memory-status'
printf '%s\n' '  tc-social-log 100'
