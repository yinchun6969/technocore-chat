#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.4.1"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
STATE_DIR="$AGENT_DIR/state"
STATE="$STATE_DIR/social-v1.json"
LEDGER="$STATE_DIR/contribution-ledger.jsonl"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
PROGRAM="$AGENT_DIR/aizong_social.py"
PATCHER="$AGENT_DIR/patch_aizong_social_v141.py"
SERVICE="technocore-aizong-social.service"
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/70-v141-provenance-calibration.conf"

log() { printf '\n[+] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -s "$PROGRAM" ] || die "找不到 $PROGRAM；请先安装 aizong Social"
[ -s "$BRAIN_CONFIG" ] || die "找不到 $BRAIN_CONFIG；请先完成 Brain 配置"
command -v python3 >/dev/null || die "python3 未安装"
command -v curl >/dev/null || die "curl 未安装"
command -v systemctl >/dev/null || die "systemd 未安装"

if ! grep -Eq 'VERSION = "1\.4\.[01]"' "$PROGRAM"; then
  log "检测到旧版；先自动无损升级到 v1.4.0 Contribution Strategy"
  curl -fsSL "$REPO_RAW/scripts/upgrade_aizong_social_v140.sh" -o /tmp/aizong-v140-bootstrap.sh
  bash /tmp/aizong-v140-bootstrap.sh
fi

if ! grep -Eq 'VERSION = "1\.4\.[01]"' "$PROGRAM"; then
  die "当前 aizong Social 无法迁移到 v1.4.1"
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$AGENT_DIR/backups/v1.4.1-upgrade-$TS"
mkdir -p "$BACKUP" "$STATE_DIR"
chmod 700 "$AGENT_DIR/backups" "$BACKUP" "$STATE_DIR"
cp -a "$PROGRAM" "$BRAIN_CONFIG" "$STATE" "$LEDGER" "$BACKUP/" 2>/dev/null || true
systemctl cat "$SERVICE" >"$BACKUP/$SERVICE.txt" 2>/dev/null || true

log "升级 aizong Social Brain 到 v$VERSION：Anti-Farming / Provenance Calibration"
curl -fsSL "$REPO_RAW/scripts/patch_aizong_social_v141.py" -o "$PATCHER.new"
python3 -m py_compile "$PATCHER.new"
chmod 700 "$PATCHER.new"
mv "$PATCHER.new" "$PATCHER"
python3 "$PATCHER" "$PROGRAM"
python3 -m py_compile "$PROGRAM"
grep -q 'VERSION = "1.4.1"' "$PROGRAM" || die "v1.4.1 版本检查失败"
grep -q 'originality_score' "$PROGRAM" || die "originality calibration 检查失败"
grep -q 'TC_TEMPLATE_BLOCK_SIMILARITY_PCT' "$PROGRAM" || die "anti-template gate 检查失败"

log "写入 provenance calibration 参数；v1.4 质量门、v1.3.1 网络韧性和安全门保持不变"
mkdir -p "$DROPIN_DIR"
cat >"$DROPIN" <<'EOF'
[Unit]
Description=aizong Social v1.4.1 anti-farming provenance-calibrated persistent-DID agent

[Service]
Environment=TC_PROVENANCE_MIN_VALUE=75
Environment=TC_PROVENANCE_MIN_ORIGINALITY=70
Environment=TC_PROVENANCE_MIN_EVIDENCE=60
Environment=TC_PROVENANCE_MAX_SIMILARITY_PCT=82
Environment=TC_PROVENANCE_DISCUSSION_MIN_VALUE=85
Environment=TC_TEMPLATE_BLOCK_SIMILARITY_PCT=92
EOF
chmod 644 "$DROPIN"
touch "$LEDGER"
chmod 600 "$LEDGER"

cat >/usr/local/bin/tc-provenance-status <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
STATE="/opt/technocore-agent/state/social-v1.json"
LEDGER="/opt/technocore-agent/state/contribution-ledger.jsonl"
SERVICE="technocore-aizong-social.service"
echo "===== AIZONG v1.4.1 PROVENANCE CALIBRATION ====="
echo "service=$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
systemctl show -p Environment --value "$SERVICE" \
  | tr ' ' '\n' \
  | grep -E '^TC_(PROVENANCE|TEMPLATE_BLOCK)_' \
  | sort || true
python3 - "$STATE" "$LEDGER" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
ledger_path = Path(sys.argv[2])
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    state = {}
metrics = state.get("strategy_metrics", {}) if isinstance(state, dict) else {}
print(f"template_blocks={int(metrics.get('template_blocks', 0) or 0)}")
print(f"provenance_downgraded={int(metrics.get('provenance_downgraded', 0) or 0)}")
items = []
if ledger_path.exists():
    for line in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            items.append(obj)
cal = [x for x in items if "originality_score" in x]
legacy = len(items) - len(cal)
worthy = [x for x in cal if x.get("provenance_worthy")]
nominated = [x for x in cal if x.get("brain_provenance_worthy")]
print(f"ledger_total={len(items)}")
print(f"legacy_v140_entries={legacy}")
print(f"calibrated_entries={len(cal)}")
print(f"brain_nominated={len(nominated)}")
print(f"calibrated_provenance_worthy={len(worthy)}")
if cal:
    def avg(key):
        vals = [int(x.get(key, 0) or 0) for x in cal]
        return sum(vals) / len(vals)
    print(f"avg_contribution_value={avg('contribution_value'):.1f}")
    print(f"avg_originality={avg('originality_score'):.1f}")
    print(f"avg_evidence={avg('evidence_strength'):.1f}")
    print(f"avg_durable_state={avg('durable_state_value'):.1f}")
    print(f"strong_value_ge80={sum(1 for x in cal if int(x.get('contribution_value',0) or 0) >= 80)}")
    print(f"exceptional_value_ge90={sum(1 for x in cal if int(x.get('contribution_value',0) or 0) >= 90)}")
    print(f"max_template_similarity={max(float(x.get('template_similarity',0) or 0) for x in cal):.2f}")
PY
EOF
chmod 755 /usr/local/bin/tc-provenance-status

systemctl daemon-reload
systemctl restart "$SERVICE"
sleep 2

log "v$VERSION 已安装"
printf '%s\n' '================================================================'
printf '%s\n' ' AIZONG SOCIAL BRAIN v1.4.1 ANTI-FARMING / PROVENANCE READY'
printf '%s\n' '================================================================'
printf '%s\n' '普通有价值互动仍可发送，但不再自动等于 provenance。'
printf '%s\n' 'Calibrated provenance:'
printf '%s\n' '  contribution >= 75 | originality >= 70 | evidence >= 60'
printf '%s\n' '  discussion additionally requires contribution >= 85'
printf '%s\n' '  prior-output similarity must stay below 82%'
printf '%s\n' 'Anti-template send gate:'
printf '%s\n' '  >=92% similarity to recent ledger output => do not send'
printf '%s\n' 'Preserved:'
printf '%s\n' '  v1.4 quality/diversity + v1.3.1 retries/cooldowns + all safety gates'
printf '%s\n' 'Commands:'
printf '%s\n' '  tc-provenance-status'
printf '%s\n' '  tc-strategy-status'
printf '%s\n' '  tc-contrib-stats'
printf '%s\n' '  tc-contrib-tail 10'
printf '%s\n' '  tc-social-log 100'
