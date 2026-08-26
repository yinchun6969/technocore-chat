#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.4.2"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
STATE_DIR="$AGENT_DIR/state"
STATE="$STATE_DIR/social-v1.json"
LEDGER="$STATE_DIR/contribution-ledger.jsonl"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
PROGRAM="$AGENT_DIR/aizong_social.py"
PATCHER="$AGENT_DIR/patch_aizong_social_v142.py"
SERVICE="technocore-aizong-social.service"
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/80-v142-memory-consolidation.conf"

log() { printf '\n[+] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -s "$PROGRAM" ] || die "找不到 $PROGRAM；请先安装 aizong Social"
[ -s "$BRAIN_CONFIG" ] || die "找不到 $BRAIN_CONFIG；请先完成 Brain 配置"
command -v python3 >/dev/null || die "python3 未安装"
command -v curl >/dev/null || die "curl 未安装"
command -v systemctl >/dev/null || die "systemd 未安装"
command -v openssl >/dev/null || die "openssl 未安装"

if ! grep -Eq 'VERSION = "1\.4\.[12]"' "$PROGRAM"; then
  log "检测到旧版；先自动无损升级到 v1.4.1 Anti-Farming / Provenance Calibration"
  curl -fsSL "$REPO_RAW/scripts/upgrade_aizong_social_v141.sh" -o /tmp/aizong-v141-bootstrap.sh
  bash /tmp/aizong-v141-bootstrap.sh
fi

if ! grep -Eq 'VERSION = "1\.4\.[12]"' "$PROGRAM"; then
  die "当前 aizong Social 无法迁移到 v1.4.2"
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$AGENT_DIR/backups/v1.4.2-upgrade-$TS"
mkdir -p "$BACKUP" "$STATE_DIR"
chmod 700 "$AGENT_DIR/backups" "$BACKUP" "$STATE_DIR"
cp -a "$PROGRAM" "$BRAIN_CONFIG" "$STATE" "$LEDGER" "$BACKUP/" 2>/dev/null || true
systemctl cat "$SERVICE" >"$BACKUP/$SERVICE.txt" 2>/dev/null || true

log "升级 aizong Social Brain 到 v$VERSION：Memory Consolidation / Durable State"
curl -fsSL "$REPO_RAW/scripts/patch_aizong_social_v142.py" -o "$PATCHER.new"
python3 -m py_compile "$PATCHER.new"
chmod 700 "$PATCHER.new"
mv "$PATCHER.new" "$PATCHER"
python3 "$PATCHER" "$PROGRAM"
python3 -m py_compile "$PROGRAM"
grep -q 'VERSION = "1.4.2"' "$PROGRAM" || die "v1.4.2 版本检查失败"
grep -q '_consolidate_contact_memory' "$PROGRAM" || die "memory consolidation 检查失败"
grep -q 'aizong-memory-checkpoint' "$PROGRAM" || die "durable checkpoint 检查失败"

log "写入 Memory Consolidation 参数；v1.4.1 provenance、v1.3.1 网络韧性与全部安全门保持不变"
mkdir -p "$DROPIN_DIR"
cat >"$DROPIN" <<'EOF'
[Unit]
Description=aizong Social v1.4.2 consolidated-memory persistent-DID agent

[Service]
Environment=TC_MEMORY_HISTORY_LIMIT=6
Environment=TC_MEMORY_MIN_IMPORTANCE=75
Environment=TC_MEMORY_MIN_CONFIDENCE=70
Environment=TC_MEMORY_MIN_DURABLE_VALUE=80
Environment=TC_MEMORY_MIN_EVIDENCE=60
Environment=TC_MEMORY_MIN_CONTRIBUTION=75
Environment=TC_MEMORY_MAX_RISK=25
Environment=TC_MEMORY_PUBLIC_SYNC=1
Environment=TC_MEMORY_DAILY_SYNC_CAP=2
Environment=TC_MEMORY_SYNC_MIN_INTERVAL=14400
Environment=TC_MEMORY_DURABLE_NS=aizong-memory
EOF
chmod 644 "$DROPIN"

cat >/usr/local/bin/tc-memory-status <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
STATE="/opt/technocore-agent/state/social-v1.json"
SERVICE="technocore-aizong-social.service"
echo "===== AIZONG v1.4.2 MEMORY CONSOLIDATION ====="
echo "service=$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
systemctl show -p Environment --value "$SERVICE" \
  | tr ' ' '\n' \
  | grep -E '^TC_MEMORY_' \
  | sort || true
python3 - "$STATE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    state = {}
contacts = state.get("contacts", {}) if isinstance(state, dict) else {}
rows = [x for x in contacts.values() if isinstance(x, dict)]
consolidated = []
public_safe = []
history_count = 0
for contact in rows:
    memory = contact.get("memory", {})
    if not isinstance(memory, dict):
        continue
    if memory.get("digest"):
        consolidated.append(contact)
    if memory.get("public_safe") and memory.get("public_summary"):
        public_safe.append(contact)
    history = memory.get("history", [])
    if isinstance(history, list):
        history_count += len(history)
metrics = state.get("strategy_metrics", {}) if isinstance(state, dict) else {}
durable = state.get("durable_memory", {}) if isinstance(state, dict) else {}
if not isinstance(durable, dict):
    durable = {}
print(f"contacts_total={len(rows)}")
print(f"contacts_consolidated={len(consolidated)}")
print(f"contacts_public_safe={len(public_safe)}")
print(f"memory_history_snapshots={history_count}")
print(f"memory_consolidations={int(metrics.get('memory_consolidations', 0) or 0)}")
print(f"durable_memory_syncs={int(metrics.get('durable_memory_syncs', 0) or 0)}")
print(f"durable_memory_sync_failures={int(metrics.get('durable_memory_sync_failures', 0) or 0)}")
print(f"durable_namespace={durable.get('namespace', '')}")
print(f"durable_note_key={durable.get('last_note_key', '')}")
print(f"durable_last_sync_at={int(durable.get('last_sync_at', 0) or 0)}")
print(f"durable_last_source={durable.get('last_source_room', '')}:{int(durable.get('last_source_seq', 0) or 0)}")
print(f"payload_signature={durable.get('payload_signature', '')}")
print(f"server_note_auth={durable.get('server_note_auth', 'unsigned-world-writable')}")
PY
EOF
chmod 755 /usr/local/bin/tc-memory-status

cat >/usr/local/bin/tc-memory-top <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
N="${1:-10}"
STATE="/opt/technocore-agent/state/social-v1.json"
python3 - "$STATE" "$N" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    limit = max(1, min(int(sys.argv[2]), 50))
except Exception:
    limit = 10
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    state = {}
rows = []
for contact in state.get("contacts", {}).values():
    if not isinstance(contact, dict):
        continue
    memory = contact.get("memory", {})
    if not isinstance(memory, dict) or not memory.get("digest"):
        continue
    rows.append((
        int(memory.get("importance", 0) or 0),
        int(memory.get("confidence", 0) or 0),
        str(contact.get("relationship_stage", "")),
        str(contact.get("author", "")),
        bool(memory.get("public_safe")),
        str(memory.get("summary", "")),
    ))
for importance, confidence, stage, author, public_safe, summary in sorted(rows, reverse=True)[:limit]:
    print(f"I{importance:02d} C{confidence:02d} public={public_safe} stage={stage} {author[:72]}")
    print(f"  memory={summary[:320]}")
PY
EOF
chmod 755 /usr/local/bin/tc-memory-top

systemctl daemon-reload
systemctl restart "$SERVICE"
sleep 2

log "v$VERSION 已安装"
printf '%s\n' '================================================================'
printf '%s\n' ' AIZONG SOCIAL BRAIN v1.4.2 MEMORY CONSOLIDATION READY'
printf '%s\n' '================================================================'
printf '%s\n' 'Local long-term memory:'
printf '%s\n' '  stable summaries + deduped facts + bounded history snapshots + memory digest'
printf '%s\n' 'Public durable checkpoint:'
printf '%s\n' '  one rolling note only; max 2 updates/day; min 4h between updates'
printf '%s\n' '  requires established DID relationship + strong value/evidence + public-safe memory'
printf '%s\n' '  payload is signed by aizong Ed25519 key'
printf '%s\n' 'Important protocol caveat:'
printf '%s\n' '  generic Technocore notes are world-writable; the server note itself is NOT authenticated'
printf '%s\n' '  authenticity comes from the Ed25519 signature embedded inside the checkpoint payload'
printf '%s\n' 'Preserved:'
printf '%s\n' '  v1.4.1 anti-farming/provenance + v1.3.1 resilience + v1.3 2X + all hard safety gates'
printf '%s\n' 'Commands:'
printf '%s\n' '  tc-memory-status'
printf '%s\n' '  tc-memory-top 10'
printf '%s\n' '  tc-provenance-status'
printf '%s\n' '  tc-contrib-stats'
printf '%s\n' '  tc-social-log 100'
