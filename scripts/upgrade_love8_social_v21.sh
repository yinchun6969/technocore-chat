#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.1.0"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT="/opt/love8-agent"
SOCIAL="$ROOT/social"
STATE="$ROOT/state"
SOCIAL_PY="$SOCIAL/love8_social.py"
MAIL_PY="$SOCIAL/love8_mailbot.py"
MODE_FILE="$SOCIAL/runtime-mode"
PAUSE_FILE="$STATE/social-v2.paused"
SOCIAL_SVC="love8-social.service"
MAIL_SVC="love8-mailbot.service"
SOCIAL_LOG="/var/log/love8-social-v2.log"
MAIL_LOG="/var/log/love8-mailbot-v2.log"

log(){ printf '\n[+] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -d "$ROOT" ]] || die "找不到 $ROOT"
[[ -s "$SOCIAL/config.env" ]] || die "找不到 Love8 Social v2 配置；请先安装 v2.0.1"
command -v love8-reply >/dev/null || die "love8-reply 不存在"

mkdir -p "$SOCIAL/backups" "$STATE"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$SOCIAL/backups/v2.1-upgrade-$TS"
mkdir -p "$BACKUP"

log "备份 v2.0.x Social 代码与状态"
cp -a "$SOCIAL_PY" "$MAIL_PY" "$BACKUP/" 2>/dev/null || true
cp -a "$STATE/social-v2.json" "$STATE/mailbot-v2.json" "$BACKUP/" 2>/dev/null || true

log "下载 Love8 Social v$VERSION"
curl -fsSL "$REPO_RAW/scripts/love8_social.py" -o "$SOCIAL_PY.new"
curl -fsSL "$REPO_RAW/scripts/love8_mailbot.py" -o "$MAIL_PY.new"
chmod 700 "$SOCIAL_PY.new" "$MAIL_PY.new"

log "语法与版本检查"
python3 -m py_compile "$SOCIAL_PY.new" "$MAIL_PY.new"
python3 "$SOCIAL_PY.new" --version | grep -q "$VERSION" || die "social 版本检查失败"
python3 "$MAIL_PY.new" --version | grep -q "$VERSION" || die "mailbot 版本检查失败"

mv "$SOCIAL_PY.new" "$SOCIAL_PY"
mv "$MAIL_PY.new" "$MAIL_PY"
chmod 700 "$SOCIAL_PY" "$MAIL_PY"

log "v2.1 dry-run：迁移联系人 + 过滤机器流，不发送消息"
python3 "$SOCIAL_PY" --once --dry-run
python3 "$MAIL_PY" --once --dry-run

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
        stage = str(value.get("stage", "observed"))
        stages[stage] += 1
        rows.append((int(value.get("last_seen", 0) or 0), cid, value))
    for _, cid, value in sorted(rows, reverse=True)[:100]:
        print(
            cid,
            "stage="+str(value.get("stage", "observed")),
            "verified="+str(value.get("verified", "?")),
            "likely_human="+str(value.get("likely_human", False)),
            "human_self_declared="+str(value.get("human_self_declared", False)),
            "room="+str(value.get("last_room", "-")),
            "natural="+str(value.get("natural_messages", 0)),
            "in="+str(value.get("messages_in", value.get("messages_seen", 0))),
            "out="+str(value.get("messages_out", 0)),
        )
    print("stages:", dict(stages))
    print("count:", len(contacts))
    if label == "public":
        stats = data.get("stats", {}) if isinstance(data, dict) else {}
        print("noise_skipped:", stats.get("noise_skipped", 0))
        print("rooms_rejected:", stats.get("rooms_rejected", 0))
        print("v21_pruned_contacts:", data.get("v21_pruned_contacts", 0))
    else:
        print("noise_skipped:", data.get("noise_skipped", 0) if isinstance(data, dict) else 0)
    print()
PY
chmod 755 /usr/local/bin/love8-social-contacts

cat >/usr/local/bin/love8-social-stats <<'PY'
#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path
p=Path("/opt/love8-agent/state/social-v2.json")
try:d=json.loads(p.read_text())
except Exception:d={}
c=d.get("contacts",{}) if isinstance(d,dict) else {}
stages=Counter(str(v.get("stage","observed")) for v in c.values() if isinstance(v,dict))
print("===== LOVE8 SOCIAL v2.1 QUALITY STATS =====")
print("version:", d.get("version","unknown"))
print("contacts:", len(c))
print("stages:", dict(stages))
stats=d.get("stats",{}) if isinstance(d,dict) else {}
print("natural_seen:", stats.get("natural_seen",0))
print("noise_skipped:", stats.get("noise_skipped",0))
print("machine_heavy_rooms_rejected:", stats.get("rooms_rejected",0))
print("v2.0_contacts_pruned:", d.get("v21_pruned_contacts",0))
print("likely_human:", sum(1 for v in c.values() if isinstance(v,dict) and v.get("likely_human")))
print("human_self_declared:", sum(1 for v in c.values() if isinstance(v,dict) and v.get("human_self_declared")))
print("established:", stages.get("established",0))
PY
chmod 755 /usr/local/bin/love8-social-stats

cat >/usr/local/bin/love8-social-version <<EOF
#!/usr/bin/env bash
python3 "$SOCIAL_PY" --version
python3 "$MAIL_PY" --version
EOF
chmod 755 /usr/local/bin/love8-social-version

MODE="$(cat "$MODE_FILE" 2>/dev/null || echo cron)"
if [[ "$MODE" == "systemd" ]] && command -v systemctl >/dev/null 2>&1; then
    log "重启 systemd Social 服务"
    systemctl restart "$SOCIAL_SVC" "$MAIL_SVC"
else
    log "cron 模式：下一轮自动使用 v$VERSION，无需重启 cron"
fi

log "最终自检"
love8-social-version
love8-social-stats

cat <<EOF

============================================================
 LOVE8 SOCIAL v$VERSION UPGRADED
============================================================
新增:
  - env:v1 / enc:v1 / Base64 / Hex / JSON 机器流过滤
  - 机器流占比 >= 75% 的房间整房跳过
  - 只把自然语言参与者加入候选联系人
  - 真人自报优先（仍不声称已验证真人）
  - likely_human 自然语言启发式，仅作为优先级
  - 联系人阶段: candidate -> contacted -> replied -> established
  - 自动清理 v2.0 仅“看见过”但从未互动的联系人
  - Mailbox 加密/机器噪音不再自动回复
  - 保留原 2/hour、6/day 公共发言限速

Commands:
  love8-social-version
  love8-social-status
  love8-social-stats
  love8-social-contacts
  love8-social-log 100
  love8-social-test
  love8-social-run-now
============================================================
EOF
