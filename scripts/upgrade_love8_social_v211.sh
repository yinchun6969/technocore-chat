#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.1.1"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT="/opt/love8-agent"
SOCIAL="$ROOT/social"
STATE="$ROOT/state"
SOCIAL_PY="$SOCIAL/love8_social.py"
MAIL_PY="$SOCIAL/love8_mailbot.py"
CFG="$SOCIAL/config.env"
MODE_FILE="$SOCIAL/runtime-mode"
PAUSE_FILE="$STATE/social-v2.paused"
SOCIAL_SVC="love8-social.service"
CRON_FILE="/etc/cron.d/love8-social-v2"
SOCIAL_LOG="/var/log/love8-social-v2.log"
MAIL_LOG="/var/log/love8-mailbot-v2.log"

log(){ printf '\n[+] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$CFG" ]] || die "找不到 $CFG；请先安装 Love8 Social v2.1"
[[ -s "$SOCIAL_PY" ]] || die "找不到现有 love8_social.py"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log "备份当前 Social 代码与状态"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$SOCIAL/backups/v2.1.1-upgrade-$TS"
mkdir -p "$BACKUP"
cp -a "$SOCIAL_PY" "$BACKUP/"
cp -a "$STATE/social-v2.json" "$BACKUP/" 2>/dev/null || true

log "下载 Love8 Social v$VERSION"
curl -fsSL "$REPO_RAW/scripts/love8_social.py" -o "$TMP/love8_social.py"
curl -fsSL "$REPO_RAW/scripts/test_love8_social_v211.py" -o "$TMP/test_love8_social_v211.py"
chmod 700 "$TMP/love8_social.py"

log "语法、版本与回归测试"
python3 -m py_compile "$TMP/love8_social.py" "$TMP/test_love8_social_v211.py"
python3 "$TMP/love8_social.py" --version | grep -q "$VERSION" || die "版本检查失败"
python3 "$TMP/test_love8_social_v211.py"

install -m 700 "$TMP/love8_social.py" "$SOCIAL_PY"

log "执行一次 dry-run：重算 likely_human + 检测模板 Bot，不发送消息"
python3 "$SOCIAL_PY" --once --dry-run

cat >/usr/local/bin/love8-social-version <<EOF
#!/usr/bin/env bash
python3 "$SOCIAL_PY" --version
python3 "$MAIL_PY" --version 2>/dev/null || true
EOF

cat >/usr/local/bin/love8-social-contacts <<'PY'
#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path

sources = [
    ("public", Path("/opt/love8-agent/state/social-v2.json")),
    ("mail", Path("/opt/love8-agent/state/mailbot-v2.json")),
]
for label, path in sources:
    print(f"=== {label} contacts ===")
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    contacts = data.get("contacts", {}) if isinstance(data, dict) else {}
    stages = Counter()
    rows = []
    for cid, value in contacts.items():
        if not isinstance(value, dict):
            continue
        stages[str(value.get("stage", "observed"))] += 1
        rows.append((int(value.get("last_seen", 0) or 0), cid, value))
    for _, cid, value in sorted(rows, reverse=True)[:100]:
        print(
            cid,
            "stage="+str(value.get("stage", "observed")),
            "verified="+str(value.get("verified", "?")),
            "likely_human="+str(value.get("likely_human", False)),
            "human_self_declared="+str(value.get("human_self_declared", False)),
            "probable_bot_cluster="+str(value.get("probable_bot_cluster", False)),
            "room="+str(value.get("last_room", "-")),
            "natural="+str(value.get("natural_messages", 0)),
            "in="+str(value.get("messages_in", value.get("messages_seen", 0))),
            "out="+str(value.get("messages_out", 0)),
        )
    print("stages:", dict(stages))
    print("count:", len(contacts))
    print()
PY

cat >/usr/local/bin/love8-social-stats <<'PY'
#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path

p = Path("/opt/love8-agent/state/social-v2.json")
try:
    data = json.loads(p.read_text())
except Exception:
    data = {}
contacts = data.get("contacts", {}) if isinstance(data, dict) else {}
stages = Counter(
    str(v.get("stage", "observed"))
    for v in contacts.values()
    if isinstance(v, dict)
)
stats = data.get("stats", {}) if isinstance(data, dict) else {}

print("===== LOVE8 SOCIAL v2.1.1 QUALITY STATS =====")
print("version:", data.get("version", "unknown"))
print("contacts:", len(contacts))
print("stages:", dict(stages))
print("natural_seen:", stats.get("natural_seen", 0))
print("noise_skipped:", stats.get("noise_skipped", 0))
print("machine_heavy_rooms_rejected:", stats.get("rooms_rejected", 0))
print("template_cluster_messages:", stats.get("template_cluster_messages", 0))
print("template_clusters_rejected:", stats.get("template_clusters_rejected", 0))
print("v2.0_contacts_pruned:", data.get("v21_pruned_contacts", 0))
print("v2.1_likely_human_reset:", data.get("v211_likely_human_reset", 0))
print("likely_human:", sum(
    1 for v in contacts.values()
    if isinstance(v, dict) and v.get("likely_human")
))
print("human_self_declared:", sum(
    1 for v in contacts.values()
    if isinstance(v, dict) and v.get("human_self_declared")
))
print("probable_bot_cluster:", sum(
    1 for v in contacts.values()
    if isinstance(v, dict) and v.get("probable_bot_cluster")
))
print("established:", stages.get("established", 0))
PY

cat >/usr/local/bin/love8-social-status <<EOF
#!/usr/bin/env bash
MODE="\$(cat "$MODE_FILE" 2>/dev/null || echo unknown)"
echo "===== LOVE8 SOCIAL STATUS ====="
python3 "$SOCIAL_PY" --version 2>/dev/null || true
python3 "$MAIL_PY" --version 2>/dev/null || true
echo "Runtime: \$MODE"
echo "Paused: \$([ -f "$PAUSE_FILE" ] && echo yes || echo no)"
echo "Legacy inbox cursor: \$(cat "$STATE/inbox.seq" 2>/dev/null || echo none)"
echo "Mailbot cursor: \$(cat "$STATE/mailbot-v2.seq" 2>/dev/null || echo none)"
if [[ "\$MODE" == "systemd" ]]; then
  echo
  systemctl --no-pager --full status "$SOCIAL_SVC" || true
elif [[ "\$MODE" == "cron" ]]; then
  echo
  echo "=== cron daemon ==="
  pgrep -a cron || pgrep -a crond || true
  echo
  echo "=== schedule ==="
  cat "$CRON_FILE" 2>/dev/null || true
  echo
  echo "=== recent public-social log ==="
  tail -n 15 "$SOCIAL_LOG" 2>/dev/null || true
  echo
  echo "=== recent mailbot log ==="
  tail -n 15 "$MAIL_LOG" 2>/dev/null || true
fi
EOF

chmod 755 \
  /usr/local/bin/love8-social-version \
  /usr/local/bin/love8-social-contacts \
  /usr/local/bin/love8-social-stats \
  /usr/local/bin/love8-social-status

MODE="$(cat "$MODE_FILE" 2>/dev/null || echo cron)"
if [[ "$MODE" == "systemd" ]] && command -v systemctl >/dev/null 2>&1; then
    log "重启 Love8 Social systemd 服务"
    systemctl restart "$SOCIAL_SVC"
else
    log "cron 模式：下一轮自动使用 v$VERSION，无需重启 cron"
fi

log "最终自检"
love8-social-version
love8-social-stats

cat <<'EOF'

============================================================
 LOVE8 SOCIAL v2.1.1 UPGRADED
============================================================
修正:
  - "What do you think..." 不再单独触发 likely_human
  - likely_human 必须出现第一人称项目/设备/经历上下文
  - 不同 DID 的重复通用问句会标记 probable_bot_cluster
  - 模板 Bot 不再消耗新的主动问候预算
  - v2.1 旧 likely_human 推断自动重置并重新学习
  - self-declared human 仍保持最高优先级，但不声称已验证真人
  - 原 2/hour、6/day 限速不变
  - Mailbot 保持原版本和行为不变

Commands:
  love8-social-version
  love8-social-status
  love8-social-stats
  love8-social-contacts
  love8-social-log 100
  love8-social-test
============================================================
EOF
