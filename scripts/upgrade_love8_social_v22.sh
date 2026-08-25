#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.2.0"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT="/opt/love8-agent"
SOCIAL="$ROOT/social"
STATE="$ROOT/state"
CFG="$SOCIAL/brain.env"
GUARD="$SOCIAL/love8_social.py"
BRAIN="$SOCIAL/love8_brain.py"
RUNNER="$SOCIAL/love8_brain_runner.py"
CRON_FILE="/etc/cron.d/love8-social-v2"
MODE_FILE="$SOCIAL/runtime-mode"
PAUSE_FILE="$STATE/social-v2.paused"
BRAIN_LOG="/var/log/love8-brain-v22.log"
LOCAL_WIZARD="$SOCIAL/upgrade_love8_social_v22.sh"

log(){ printf '\n[+] %s\n' "$*"; }
warn(){ printf '\n[!] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$SOCIAL/config.env" ]] || die "找不到 Love8 Social 配置；请先安装 v2.1.1"
[[ -s "$GUARD" ]] || die "找不到 $GUARD"
MODE="$(cat "$MODE_FILE" 2>/dev/null || echo cron)"
[[ "$MODE" == "cron" ]] || die "当前 v2.2 向导针对这台 cron 运行环境；检测到 Runtime=$MODE"
[[ -s "$CRON_FILE" ]] || die "找不到 $CRON_FILE"

mkdir -p "$SOCIAL/backups" "$STATE"
chmod 700 "$SOCIAL" "$STATE"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$SOCIAL/backups/v2.2-upgrade-$TS"
mkdir -p "$BACKUP"
cp -a "$GUARD" "$CFG" "$CRON_FILE" "$STATE/social-v2.json" "$STATE/brain-v22.json" "$BACKUP/" 2>/dev/null || true

WAS_PAUSED=0
[[ -f "$PAUSE_FILE" ]] && WAS_PAUSED=1
touch "$PAUSE_FILE"; chmod 600 "$PAUSE_FILE"
cleanup_pause(){
  if [[ "$WAS_PAUSED" == "0" ]]; then rm -f "$PAUSE_FILE"; fi
}
trap cleanup_pause EXIT

log "下载 Love8 Brain v$VERSION"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; cleanup_pause' EXIT
curl -fsSL "$REPO_RAW/scripts/love8_brain.py" -o "$TMP/love8_brain.py"
curl -fsSL "$REPO_RAW/scripts/love8_brain_runner.py" -o "$TMP/love8_brain_runner.py"
curl -fsSL "$REPO_RAW/scripts/test_love8_brain_v22.py" -o "$TMP/test_love8_brain_v22.py"
python3 -m py_compile "$TMP/love8_brain.py" "$TMP/love8_brain_runner.py" "$TMP/test_love8_brain_v22.py"
python3 "$TMP/test_love8_brain_v22.py"
grep -q 'VERSION = "2.2.0"' "$TMP/love8_brain.py" || die "Brain 版本检查失败"

# Read old values without exposing the API key.
OLD_BASE=""; OLD_MODEL=""; OLD_KEY=""; OLD_CALLS="4"; OLD_TOPICS="2"; OLD_ALLOW="yes"
if [[ -s "$CFG" ]]; then
  # shellcheck disable=SC1090
  source "$CFG" || true
  OLD_BASE="${BRAIN_API_BASE:-}"
  OLD_MODEL="${BRAIN_MODEL:-}"
  OLD_KEY="${BRAIN_API_KEY:-}"
  OLD_CALLS="${BRAIN_CALLS_PER_HOUR:-4}"
  OLD_TOPICS="${BRAIN_TOPICS_PER_DAY:-2}"
  OLD_ALLOW="${BRAIN_ALLOW_TOPICS:-yes}"
fi

printf '\n============================================================\n'
printf ' LOVE8 BRAIN v%s 配置向导\n' "$VERSION"
printf '============================================================\n'
printf 'API Key 不会显示，也不会写入 shell history；配置文件权限为 600。\n'
printf '支持 OpenAI-compatible /chat/completions API。\n\n'

read -r -p "1) API Base URL${OLD_BASE:+ [$OLD_BASE]}: " API_BASE
API_BASE="${API_BASE:-$OLD_BASE}"
[[ -n "$API_BASE" ]] || die "API Base URL 不能为空"

if [[ -n "$OLD_KEY" ]]; then
  read -r -s -p "2) API Key [直接回车保留现有 Key]: " API_KEY; echo
  API_KEY="${API_KEY:-$OLD_KEY}"
else
  read -r -s -p "2) API Key: " API_KEY; echo
fi
[[ -n "$API_KEY" ]] || die "API Key 不能为空"

read -r -p "3) Model${OLD_MODEL:+ [$OLD_MODEL]}: " MODEL
MODEL="${MODEL:-$OLD_MODEL}"
[[ -n "$MODEL" ]] || die "Model 不能为空"

read -r -p "4) Deep Brain 每小时最多 API 调用次数 [$OLD_CALLS]: " CALLS
CALLS="${CALLS:-$OLD_CALLS}"
[[ "$CALLS" =~ ^[0-9]+$ ]] || die "调用次数必须是数字"
(( CALLS >= 1 && CALLS <= 12 )) || die "建议范围 1-12"

read -r -p "5) 每天最多主动创建讨论话题数 [$OLD_TOPICS]: " TOPICS
TOPICS="${TOPICS:-$OLD_TOPICS}"
[[ "$TOPICS" =~ ^[0-9]+$ ]] || die "话题数必须是数字"
(( TOPICS >= 0 && TOPICS <= 6 )) || die "范围 0-6"

DEFAULT_TOPIC="Y"
[[ "${OLD_ALLOW,,}" =~ ^(no|false|0|off)$ ]] && DEFAULT_TOPIC="N"
read -r -p "6) 允许 Brain 主动发起讨论话题? [${DEFAULT_TOPIC}/$( [[ "$DEFAULT_TOPIC" == Y ]] && echo n || echo y )]: " TOPIC_ANSWER
if [[ -z "$TOPIC_ANSWER" ]]; then TOPIC_ANSWER="$DEFAULT_TOPIC"; fi
case "${TOPIC_ANSWER,,}" in
  y|yes) ALLOW_TOPICS=yes ;;
  n|no) ALLOW_TOPICS=no ;;
  *) die "请输入 y 或 n" ;;
esac

# Write secret config atomically. %q makes values safe for both shell source and Python shlex.
UMASK_OLD="$(umask)"; umask 077
CFG_TMP="$TMP/brain.env"
{
  printf 'BRAIN_API_BASE=%q\n' "$API_BASE"
  printf 'BRAIN_API_KEY=%q\n' "$API_KEY"
  printf 'BRAIN_MODEL=%q\n' "$MODEL"
  printf 'BRAIN_CALLS_PER_HOUR=%q\n' "$CALLS"
  printf 'BRAIN_TOPICS_PER_DAY=%q\n' "$TOPICS"
  printf 'BRAIN_ALLOW_TOPICS=%q\n' "$ALLOW_TOPICS"
  printf 'BRAIN_ROOMS=8\n'
  printf 'BRAIN_TEMPERATURE=0.2\n'
  printf 'BRAIN_MAX_TOKENS=700\n'
} >"$CFG_TMP"
umask "$UMASK_OLD"
chmod 600 "$CFG_TMP"

install -m 700 "$TMP/love8_brain.py" "$BRAIN"
install -m 700 "$TMP/love8_brain_runner.py" "$RUNNER"
install -m 600 "$CFG_TMP" "$CFG"
cp -a "$0" "$LOCAL_WIZARD" 2>/dev/null || curl -fsSL "$REPO_RAW/scripts/upgrade_love8_social_v22.sh" -o "$LOCAL_WIZARD"
chmod 700 "$LOCAL_WIZARD"

touch "$BRAIN_LOG"; chmod 640 "$BRAIN_LOG"

log "连接模型做最小自检（会产生一次很小的 API 调用）"
if ! python3 "$RUNNER" --self-test; then
  warn "Brain API 自检失败，恢复原 cron；现有 v2.1.1 不受影响。"
  cp -a "$BACKUP/$(basename "$CRON_FILE")" "$CRON_FILE" 2>/dev/null || true
  exit 1
fi

log "做一次 Brain dry-run：会分析，但不会在 Technocore 发消息"
python3 "$RUNNER" --once --dry-run || die "Brain dry-run 失败"

log "把 public-social 从规则回复切换到 Brain；Mailbot 保持原样"
CRON_FILE="$CRON_FILE" RUNNER="$RUNNER" PAUSE_FILE="$PAUSE_FILE" BRAIN_LOG="$BRAIN_LOG" python3 <<'PY'
import os
from pathlib import Path
p=Path(os.environ['CRON_FILE'])
lines=p.read_text().splitlines()
out=[]
for line in lines:
    if 'love8_social.py --once' in line or 'love8_brain_runner.py --once' in line:
        continue
    out.append(line)
out.append(
    f"*/5 * * * * root test -f {os.environ['PAUSE_FILE']} || "
    f"/usr/bin/flock -n /run/lock/love8-social-v2.lock /usr/bin/python3 {os.environ['RUNNER']} --once "
    f">>{os.environ['BRAIN_LOG']} 2>&1"
)
p.write_text('\n'.join(out)+'\n')
PY
chmod 644 "$CRON_FILE"

cat >/usr/local/bin/love8-brain-status <<'EOF'
#!/usr/bin/env bash
set -e
CFG=/opt/love8-agent/social/brain.env
# shellcheck disable=SC1090
source "$CFG"
echo '===== LOVE8 BRAIN v2.2 ====='
echo "Model: $BRAIN_MODEL"
echo "API: $BRAIN_API_BASE"
echo "Calls/hour cap: $BRAIN_CALLS_PER_HOUR"
echo "Topics/day cap: $BRAIN_TOPICS_PER_DAY"
echo "Allow topics: $BRAIN_ALLOW_TOPICS"
echo "Config permissions: $(stat -c '%a' "$CFG")"
echo "API key: [hidden]"
echo
echo '=== cron ==='
grep -E 'love8_brain_runner|love8_mailbot' /etc/cron.d/love8-social-v2 || true
echo
echo '=== recent brain ==='
tail -n 25 /var/log/love8-brain-v22.log 2>/dev/null || true
EOF

cat >/usr/local/bin/love8-brain-test <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 /opt/love8-agent/social/love8_brain_runner.py --self-test
EOF

cat >/usr/local/bin/love8-brain-dry-run <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-social-v2.lock /usr/bin/python3 /opt/love8-agent/social/love8_brain_runner.py --once --dry-run
EOF

cat >/usr/local/bin/love8-brain-run-now <<'EOF'
#!/usr/bin/env bash
set -e
[ ! -f /opt/love8-agent/state/social-v2.paused ] || { echo 'Love8 Social is paused.'; exit 2; }
exec /usr/bin/flock -n /run/lock/love8-social-v2.lock /usr/bin/python3 /opt/love8-agent/social/love8_brain_runner.py --once
EOF

cat >/usr/local/bin/love8-brain-log <<'EOF'
#!/usr/bin/env bash
exec tail -n "${1:-100}" /var/log/love8-brain-v22.log
EOF

cat >/usr/local/bin/love8-brain-memory <<'PY'
#!/usr/bin/env python3
import json
from pathlib import Path
p=Path('/opt/love8-agent/state/social-v2.json')
try:d=json.loads(p.read_text())
except Exception:d={}
rows=[]
for cid,c in (d.get('contacts',{}) if isinstance(d,dict) else {}).items():
    if not isinstance(c,dict) or not isinstance(c.get('brain'),dict): continue
    b=c['brain']
    rows.append((int(b.get('last_brain_ts',0) or 0),cid,c,b))
print('===== LOVE8 BRAIN CONTACT MEMORY =====')
for _,cid,c,b in sorted(rows,reverse=True)[:60]:
    print(cid,
          'stage='+str(c.get('stage','candidate')),
          'trust='+str(b.get('trust_score','?')),
          'bot='+str(b.get('bot_probability','?')),
          'human='+str(b.get('human_likelihood','?')),
          'risk='+str(b.get('scam_risk','?')),
          'quality='+str(b.get('conversation_quality','?')),
          'topics='+','.join(str(x) for x in b.get('topics',[])[:4]))
    s=str(b.get('summary','')).strip()
    if s: print('  memory:',s)
    r=str(b.get('last_reason','')).strip()
    if r: print('  reason:',r[:220])
print('brain_contacts:',len(rows))
PY

cat >/usr/local/bin/love8-brain-wizard <<'EOF'
#!/usr/bin/env bash
exec bash /opt/love8-agent/social/upgrade_love8_social_v22.sh
EOF

cat >/usr/local/bin/love8-brain-off <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
P=/etc/cron.d/love8-social-v2
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/cron.d/love8-social-v2')
lines=[x for x in p.read_text().splitlines() if 'love8_brain_runner.py --once' not in x and 'love8_social.py --once' not in x]
lines.append('*/5 * * * * root test -f /opt/love8-agent/state/social-v2.paused || /usr/bin/flock -n /run/lock/love8-social-v2.lock /usr/bin/python3 /opt/love8-agent/social/love8_social.py --once >>/var/log/love8-social-v2.log 2>&1')
p.write_text('\n'.join(lines)+'\n')
PY
chmod 644 "$P"
echo 'Brain disabled; reverted to v2.1.1 rule-only public social.'
EOF

cat >/usr/local/bin/love8-brain-on <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
P=/etc/cron.d/love8-social-v2
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/cron.d/love8-social-v2')
lines=[x for x in p.read_text().splitlines() if 'love8_brain_runner.py --once' not in x and 'love8_social.py --once' not in x]
lines.append('*/5 * * * * root test -f /opt/love8-agent/state/social-v2.paused || /usr/bin/flock -n /run/lock/love8-social-v2.lock /usr/bin/python3 /opt/love8-agent/social/love8_brain_runner.py --once >>/var/log/love8-brain-v22.log 2>&1')
p.write_text('\n'.join(lines)+'\n')
PY
chmod 644 "$P"
echo 'Brain enabled.'
EOF

chmod 755 /usr/local/bin/love8-brain-status /usr/local/bin/love8-brain-test \
  /usr/local/bin/love8-brain-dry-run /usr/local/bin/love8-brain-run-now \
  /usr/local/bin/love8-brain-log /usr/local/bin/love8-brain-memory \
  /usr/local/bin/love8-brain-wizard /usr/local/bin/love8-brain-off /usr/local/bin/love8-brain-on

cleanup_pause
trap 'rm -rf "$TMP"' EXIT

printf '\n============================================================\n'
printf ' LOVE8 BRAIN v%s READY\n' "$VERSION"
printf '============================================================\n'
printf 'Fast Brain: v2.1.1 rules/filters remain the safety shell\n'
printf 'Deep Brain: LLM understands context and chooses who/what to discuss\n'
printf 'Scam guard: wallet/secret/command risks can force IGNORE before sending\n'
printf 'Bot analysis: probability only; signed DID is never treated as proof of human identity\n'
printf 'Memory: per-contact topics/trust/risk/summary stored locally\n'
printf 'Topics: up to %s/day, existing active rooms only\n' "$TOPICS"
printf 'API budget: up to %s calls/hour\n' "$CALLS"
printf 'API key: stored only in %s (chmod 600)\n' "$CFG"
printf '\nCommands:\n'
printf '  love8-brain-status\n'
printf '  love8-brain-test\n'
printf '  love8-brain-dry-run\n'
printf '  love8-brain-run-now\n'
printf '  love8-brain-log 100\n'
printf '  love8-brain-memory\n'
printf '  love8-brain-wizard      # change URL/key/model later\n'
printf '  love8-brain-off         # fall back to v2.1.1 rules\n'
printf '  love8-brain-on\n'
printf '============================================================\n'
love8-brain-status
