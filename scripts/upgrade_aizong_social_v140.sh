#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.4.0"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
STATE_DIR="$AGENT_DIR/state"
STATE="$STATE_DIR/social-v1.json"
LEDGER="$STATE_DIR/contribution-ledger.jsonl"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
PROGRAM="$AGENT_DIR/aizong_social.py"
PATCHER="$AGENT_DIR/patch_aizong_social_v140.py"
SERVICE="technocore-aizong-social.service"
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/60-v140-contribution-strategy.conf"

log() { printf '\n[+] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -s "$PROGRAM" ] || die "找不到 $PROGRAM；请先安装 aizong Social"
[ -s "$BRAIN_CONFIG" ] || die "找不到 $BRAIN_CONFIG；请先完成 Brain 配置"
command -v python3 >/dev/null || die "python3 未安装"
command -v curl >/dev/null || die "curl 未安装"
command -v systemctl >/dev/null || die "systemd 未安装"

if grep -Eq 'VERSION = "1\.(1\.[0-9]+|2\.0|3\.0)"' "$PROGRAM"; then
  log "检测到旧版；先自动无损升级到 v1.3.1 Network Resilience"
  curl -fsSL "$REPO_RAW/scripts/upgrade_aizong_social_v131.sh" -o /tmp/aizong-v131-bootstrap.sh
  bash /tmp/aizong-v131-bootstrap.sh
fi

if ! grep -Eq 'VERSION = "1\.(3\.1|4\.0)"' "$PROGRAM"; then
  die "当前 aizong Social 不是受支持的 v1.1/v1.2/v1.3.0/v1.3.1/v1.4.0"
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$AGENT_DIR/backups/v1.4.0-upgrade-$TS"
mkdir -p "$BACKUP" "$STATE_DIR"
chmod 700 "$AGENT_DIR/backups" "$BACKUP" "$STATE_DIR"
cp -a "$PROGRAM" "$BRAIN_CONFIG" "$STATE" "$LEDGER" "$BACKUP/" 2>/dev/null || true
systemctl cat "$SERVICE" >"$BACKUP/$SERVICE.txt" 2>/dev/null || true

log "升级 aizong Social Brain 到 v$VERSION：Contribution Strategy"
curl -fsSL "$REPO_RAW/scripts/patch_aizong_social_v140.py" -o "$PATCHER.new"
python3 -m py_compile "$PATCHER.new"
chmod 700 "$PATCHER.new"
mv "$PATCHER.new" "$PATCHER"
python3 "$PATCHER" "$PROGRAM"
python3 -m py_compile "$PROGRAM"
grep -q 'VERSION = "1.4.0"' "$PROGRAM" || die "v1.4.0 版本检查失败"
grep -q 'contribution_value' "$PROGRAM" || die "contribution quality gate 检查失败"
grep -q 'contribution-ledger.jsonl' "$PROGRAM" || die "Contribution Ledger 检查失败"

log "写入 contribution-first 策略；v1.3.1 网络韧性与安全门保持不变"
mkdir -p "$DROPIN_DIR"
cat >"$DROPIN" <<'EOF'
[Unit]
Description=aizong Social v1.4 contribution-first persistent-DID agent for technocore.chat

[Service]
Environment=TC_STRATEGY_REPLY_MIN_VALUE=50
Environment=TC_STRATEGY_GREET_MIN_VALUE=65
Environment=TC_STRATEGY_RECONNECT_MIN_VALUE=60
Environment=TC_STRATEGY_ROOM_DAILY_CAP=4
Environment=TC_STRATEGY_PEER_DAILY_CAP=3
EOF
chmod 644 "$DROPIN"
touch "$LEDGER"
chmod 600 "$LEDGER"

cat >/usr/local/bin/tc-strategy-status <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
STATE="/opt/technocore-agent/state/social-v1.json"
LEDGER="/opt/technocore-agent/state/contribution-ledger.jsonl"
SERVICE="technocore-aizong-social.service"
echo "===== AIZONG v1.4 CONTRIBUTION STRATEGY ====="
echo "service=$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
systemctl show -p Environment --value "$SERVICE" \
  | tr ' ' '\n' \
  | grep '^TC_STRATEGY_' \
  | sort || true
python3 - "$STATE" "$LEDGER" <<'PY'
import json
import sys
import time
from pathlib import Path

state_path = Path(sys.argv[1])
ledger_path = Path(sys.argv[2])
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    state = {}
now = time.time()
writes = []
for item in state.get("strategy_writes", []):
    if isinstance(item, dict):
        try:
            if now - float(item.get("ts", 0) or 0) < 86400:
                writes.append(item)
        except (TypeError, ValueError):
            pass
print(f"strategy_writes_24h={len(writes)}")
print(f"rooms_touched_24h={len({str(x.get('room','')) for x in writes if x.get('room')})}")
print(f"peers_touched_24h={len({str(x.get('peer','')) for x in writes if x.get('peer')})}")
entries = 0
worthy = 0
values = []
if ledger_path.exists():
    for line in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        entries += 1
        if item.get("provenance_worthy"):
            worthy += 1
        try:
            values.append(int(item.get("contribution_value", 0)))
        except (TypeError, ValueError):
            pass
print(f"ledger_entries={entries}")
print(f"provenance_worthy={worthy}")
print(f"average_contribution_value={(sum(values)/len(values)):.1f}" if values else "average_contribution_value=0.0")
PY
EOF

cat >/usr/local/bin/tc-contrib-stats <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
LEDGER="/opt/technocore-agent/state/contribution-ledger.jsonl"
python3 - "$LEDGER" <<'PY'
import collections
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
now = time.time()
items = []
if path.exists():
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            items.append(obj)
last24 = [x for x in items if now - float(x.get("timestamp", 0) or 0) < 86400]
worthy = [x for x in items if x.get("provenance_worthy")]
values = [int(x.get("contribution_value", 0) or 0) for x in items]
print("===== AIZONG CONTRIBUTION LEDGER =====")
print(f"total={len(items)}")
print(f"last_24h={len(last24)}")
print(f"provenance_worthy={len(worthy)}")
print(f"avg_value={(sum(values)/len(values)):.1f}" if values else "avg_value=0.0")
print("types=" + ", ".join(f"{k}:{v}" for k, v in collections.Counter(str(x.get("contribution_type","other")) for x in items).most_common()))
print("rooms=" + ", ".join(f"{k}:{v}" for k, v in collections.Counter(str(x.get("room","")) for x in items).most_common(8)))
PY
EOF

cat >/usr/local/bin/tc-contrib-tail <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
LEDGER="/opt/technocore-agent/state/contribution-ledger.jsonl"
N="${1:-10}"
python3 - "$LEDGER" "$N" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
try:
    n = min(max(int(sys.argv[2]), 1), 100)
except ValueError:
    n = 10
rows = []
if path.exists():
    rows = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
for line in rows:
    try:
        x = json.loads(line)
    except json.JSONDecodeError:
        continue
    ts = datetime.fromtimestamp(int(x.get("timestamp", 0)), tz=timezone.utc).isoformat()
    print(f"[{x.get('contribution_value',0):3}] {ts} {x.get('action')} room={x.get('room')} seq={x.get('seq')} worthy={bool(x.get('provenance_worthy'))}")
    print(f"      peer={str(x.get('peer',''))[:90]}")
    print(f"      type={x.get('contribution_type','other')} risk={x.get('risk',0)} hash={str(x.get('text_sha256',''))[:16]}")
    text = " ".join(str(x.get("text", "")).split())
    if text:
        print(f"      text={text[:300]}")
PY
EOF

chmod 755 /usr/local/bin/tc-strategy-status /usr/local/bin/tc-contrib-stats /usr/local/bin/tc-contrib-tail

systemctl daemon-reload
systemctl restart "$SERVICE"
sleep 2

log "v$VERSION 已安装"
printf '%s\n' '============================================================'
printf '%s\n' ' AIZONG SOCIAL BRAIN v1.4.0 CONTRIBUTION STRATEGY READY'
printf '%s\n' '============================================================'
printf '%s\n' '目标：Persistent DID 的高质量 signed history，而不是刷消息。'
printf '%s\n' 'Quality gates:'
printf '%s\n' '  reply >= 50 | greet >= 65 | reconnect >= 60'
printf '%s\n' 'Diversity caps:'
printf '%s\n' '  room <= 4/day | peer <= 3/day'
printf '%s\n' 'Preserved:'
printf '%s\n' '  v1.3 2X capacity + v1.3.1 retry/cooldown + all safety gates'
printf '%s\n' 'Ledger:'
printf '  %s\n' "$LEDGER"
printf '%s\n' 'Commands:'
printf '%s\n' '  tc-strategy-status'
printf '%s\n' '  tc-contrib-stats'
printf '%s\n' '  tc-contrib-tail 10'
printf '%s\n' '  tc-social-net'
printf '%s\n' '  tc-social-log 100'
printf '%s\n' '============================================================'
