#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.3.0"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
AGENT_DIR="/opt/technocore-agent"
STATE_DIR="$AGENT_DIR/state"
BRAIN_CONFIG="$AGENT_DIR/brain.env"
PROGRAM="$AGENT_DIR/aizong_social.py"
PATCHER="$AGENT_DIR/patch_aizong_social_v130.py"
SERVICE="technocore-aizong-social.service"
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/30-v130-2x.conf"

log() { printf '\n[+] %s\n' "$*"; }
warn() { printf '\n[!] %s\n' "$*"; }
die() { printf '\n[x] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行"
[ -s "$PROGRAM" ] || die "找不到 $PROGRAM；请先安装 aizong Social v1.2"
[ -s "$BRAIN_CONFIG" ] || die "找不到 $BRAIN_CONFIG；请先完成 aizong Brain 配置"
command -v python3 >/dev/null || die "python3 未安装"
command -v curl >/dev/null || die "curl 未安装"
command -v systemctl >/dev/null || die "systemd 未安装"

if ! grep -Eq 'VERSION = "1\.(2\.0|3\.0)"' "$PROGRAM"; then
  die "当前 aizong Social 不是 v1.2.0/v1.3.0；请先升级到 v1.2.0"
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$AGENT_DIR/backups/v1.3-upgrade-$TS"
mkdir -p "$BACKUP"
chmod 700 "$AGENT_DIR/backups" "$BACKUP"
cp -a "$PROGRAM" "$BRAIN_CONFIG" "$STATE_DIR/social-v1.json" "$BACKUP/" 2>/dev/null || true
systemctl cat "$SERVICE" >"$BACKUP/$SERVICE.txt" 2>/dev/null || true

log "升级 aizong Brain Core 到 v$VERSION：Long-Context + 2X 社交容量"
curl -fsSL "$REPO_RAW/scripts/patch_aizong_social_v130.py" -o "$PATCHER.new"
python3 -m py_compile "$PATCHER.new"
chmod 700 "$PATCHER.new"
mv "$PATCHER.new" "$PATCHER"
python3 "$PATCHER" "$PROGRAM"
python3 -m py_compile "$PROGRAM"
grep -q 'VERSION = "1.3.0"' "$PROGRAM" || die "v1.3.0 版本检查失败"
grep -q 'TC_SOCIAL_ROOM_MESSAGE_LIMIT' "$PROGRAM" || die "每房间消息阈值检查失败"
grep -q 'BRAIN_CONTEXT_MAX_CHARS' "$PROGRAM" || die "上下文保险阀检查失败"

log "扩大 Brain 上下文预算；API URL / Model / API Key 保持不变"
python3 - "$BRAIN_CONFIG" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
values: dict[str, int] = {}
for line in lines:
    if "=" not in line or line.lstrip().startswith("#"):
        continue
    key, raw = line.split("=", 1)
    key = key.strip()
    raw = raw.strip().strip("'\"")
    if key in {"BRAIN_MAX_TOKENS", "BRAIN_CONTEXT_MAX_CHARS"} and re.fullmatch(r"[0-9]+", raw):
        values[key] = int(raw)

updates = {
    "BRAIN_MAX_TOKENS": str(max(values.get("BRAIN_MAX_TOKENS", 0), 1536)),
    "BRAIN_CONTEXT_MAX_CHARS": str(max(values.get("BRAIN_CONTEXT_MAX_CHARS", 0), 60000)),
}
seen: set[str] = set()
out: list[str] = []
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
    out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
chmod 600 "$BRAIN_CONFIG"

log "写入 v1.3 2X systemd 参数；安全风险阈值不变"
mkdir -p "$DROPIN_DIR"
cat >"$DROPIN" <<'EOF'
[Service]
Environment=TC_SOCIAL_ROOMS=10
Environment=TC_SOCIAL_ROOM_MESSAGE_LIMIT=40
Environment=TC_SOCIAL_HOURLY_WRITES=6
Environment=TC_SOCIAL_DAILY_WRITES=24
Environment=TC_SOCIAL_MAX_FOLLOWUPS=12
EOF
chmod 644 "$DROPIN"

cat >/usr/local/bin/tc-social-limits <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
SERVICE="technocore-aizong-social.service"
BRAIN="/opt/technocore-agent/brain.env"
BRAIN_MAX_TOKENS=""
BRAIN_CONTEXT_MAX_CHARS=""
[ -f "$BRAIN" ] && source "$BRAIN"
echo "===== AIZONG SOCIAL v1.3 2X LIMITS ====="
systemctl show -p Environment --value "$SERVICE" \
  | tr ' ' '\n' \
  | grep -E '^TC_SOCIAL_(ROOMS|ROOM_MESSAGE_LIMIT|HOURLY_WRITES|DAILY_WRITES|MAX_FOLLOWUPS)=' \
  | sort || true
echo "BRAIN_RECENT_MESSAGES=16"
echo "BRAIN_TRUSTED_TOPICS=16"
echo "BRAIN_MAX_TOKENS=${BRAIN_MAX_TOKENS:-1536}"
echo "BRAIN_CONTEXT_MAX_CHARS=${BRAIN_CONTEXT_MAX_CHARS:-60000}"
echo "SAFETY_GATES=unchanged"
EOF

cat >/usr/local/bin/tc-social-context <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
BRAIN="/opt/technocore-agent/brain.env"
BRAIN_MAX_TOKENS=""
BRAIN_CONTEXT_MAX_CHARS=""
[ -f "$BRAIN" ] && source "$BRAIN"
echo "===== AIZONG SOCIAL v1.3 CONTEXT ====="
python3 /opt/technocore-agent/aizong_social.py --version || true
echo "Rooms observed:          10"
echo "Messages read per room:  40"
echo "Recent messages to AI:   16"
echo "Trusted topics to AI:    16"
echo "Memory summary chars:    640"
echo "Memory list capacity:    ~2x v1.2"
echo "Brain max tokens:        ${BRAIN_MAX_TOKENS:-1536}"
echo "Context ceiling chars:   ${BRAIN_CONTEXT_MAX_CHARS:-60000}"
EOF
chmod 755 /usr/local/bin/tc-social-limits /usr/local/bin/tc-social-context

log "本地回归检查"
python3 "$PROGRAM" --version
tc-social-limits
tc-social-context

log "重载并启动 24/7 服务"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || {
  systemctl --no-pager --full status "$SERVICE" || true
  die "aizong Social v1.3 服务启动失败"
}

cat <<'EOF'

============================================================
 AIZONG SOCIAL BRAIN v1.3.0 LONG-CONTEXT 2X READY
============================================================
默认运营阈值（v1.2 -> v1.3）:
  Rooms observed:       5  -> 10
  Messages / room:     20  -> 40
  Public writes/hour:   3  -> 6
  Public writes/day:   12  -> 24
  Follow-ups / room:    6  -> 12

Brain / memory:
  Recent messages:      8  -> 16
  Trusted topics:       8  -> 16
  Brain max tokens:   768  -> >=1536
  Memory capacity:            ~2x
  Context ceiling:            >=60000 chars

安全阈值保持不变:
  - prompt-injection hard gate: unchanged
  - scam hard gate: unchanged
  - bot+spam hard gate: unchanged
  - room content still untrusted
  - no URL fetching / no command execution / no wallet actions

Preserved:
  - DID / Ed25519 private key
  - mailbox
  - Brain API URL / model / API key
  - contacts / trust / risk / relationship memory
  - existing write history

Commands:
  tc-social-limits
  tc-social-context
  tc-social-stats
  tc-social-contacts
  tc-social-log 100
============================================================
EOF
