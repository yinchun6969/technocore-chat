#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.4.0"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT="/opt/love8-agent"
SOCIAL="$ROOT/social"
STATE="$ROOT/state"
PROVENANCE="$ROOT/provenance"
CORE="$SOCIAL/love8_persistent.py"
CFG="$SOCIAL/persistent.env"
CRON_FILE="/etc/cron.d/love8-social-v2"
LOG="/var/log/love8-persistent-v24.log"
PAUSE_FILE="$STATE/social-v2.paused"

log(){ printf '\n[+] %s\n' "$*"; }
warn(){ printf '\n[!] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$SOCIAL/config.env" ]] || die "找不到现有 Love8 Social 配置"
[[ -s "$SOCIAL/brain.env" ]] || die "找不到 Love8 Brain 配置；请先完成 v2.3"
[[ -s "$SOCIAL/love8_social.py" ]] || die "找不到 Fast Guard"
[[ -s "$SOCIAL/love8_brain.py" ]] || die "找不到 Brain Core"
[[ -s "$CRON_FILE" ]] || die "找不到 $CRON_FILE"

mkdir -p "$SOCIAL/backups" "$STATE" "$PROVENANCE"
chmod 700 "$SOCIAL" "$STATE" "$PROVENANCE"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$SOCIAL/backups/v2.4-persistent-$TS"
mkdir -p "$BACKUP"
cp -a "$CORE" "$CFG" "$CRON_FILE" "$STATE/persistent-v24.json" "$BACKUP/" 2>/dev/null || true

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log "下载 Love8 Persistent Agent v$VERSION"
curl -fsSL "$REPO_RAW/scripts/love8_persistent.py" -o "$TMP/love8_persistent.py"
curl -fsSL "$REPO_RAW/scripts/test_love8_persistent_v24.py" -o "$TMP/test_love8_persistent_v24.py"
chmod 700 "$TMP/love8_persistent.py"

log "语法与回归测试"
python3 -m py_compile "$TMP/love8_persistent.py" "$TMP/test_love8_persistent_v24.py"
cp "$TMP/love8_persistent.py" "$TMP/love8_persistent_for_test.py"
# Test expects the production filename next to itself.
python3 "$TMP/test_love8_persistent_v24.py"
grep -q 'VERSION = "2.4.0"' "$TMP/love8_persistent.py" || die "版本检查失败"

install -m 700 "$TMP/love8_persistent.py" "$CORE"

log "写入 Persistent Agent 策略参数（不修改 API Key / DID / 私钥）"
cat >"$CFG" <<'EOF'
# Love8 Persistent Agent v2.4 policy
PERSIST_CONTRIBUTION_MIN=45
PERSIST_TOPIC_MOMENTUM_MIN=4.5
PERSIST_ROOM_CREATE_ENABLED=yes
PERSIST_ROOM_MIN_PEERS=2
PERSIST_ROOMS_PER_DAY=1
PERSIST_ROOM_PREFIX=love8
PERSIST_INVITES_PER_ROOM=3
PERSIST_REFLECTION_MINUTE=17
PERSIST_LEDGER_ENABLED=yes
EOF
chmod 600 "$CFG"

touch "$LOG"; chmod 640 "$LOG"

log "安装运行命令"
cat >/usr/local/bin/love8-persistent-version <<'EOF'
#!/usr/bin/env bash
python3 /opt/love8-agent/social/love8_persistent.py --version
EOF

cat >/usr/local/bin/love8-persistent-status <<'EOF'
#!/usr/bin/env bash
python3 /opt/love8-agent/social/love8_persistent.py --status
printf '\n=== cron ===\n'
grep -E 'love8-persistent|love8_brain_runner|love8-mailbot' /etc/cron.d/love8-social-v2 2>/dev/null || true
printf '\n=== recent log ===\n'
tail -n 30 /var/log/love8-persistent-v24.log 2>/dev/null || true
EOF

cat >/usr/local/bin/love8-persistent-run-now <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 /opt/love8-agent/social/love8_persistent.py --hourly
EOF

cat >/usr/local/bin/love8-persistent-dry-run <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 /opt/love8-agent/social/love8_persistent.py --hourly --dry-run
EOF

cat >/usr/local/bin/love8-persistent-verify <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 /opt/love8-agent/social/love8_persistent.py --verify "${1:-latest}"
EOF

cat >/usr/local/bin/love8-persistent-log <<'EOF'
#!/usr/bin/env bash
N="${1:-100}"
case "$N" in (*[!0-9]*|'') N=100;; esac
tail -n "$N" /var/log/love8-persistent-v24.log 2>/dev/null || true
EOF

cat >/usr/local/bin/love8-persistent-ledger <<'PY'
#!/usr/bin/env python3
import json
from pathlib import Path
files=sorted(Path('/opt/love8-agent/provenance').glob('????-??-??.json'))
if not files:
 print('no provenance ledger yet'); raise SystemExit(0)
p=files[-1]
print('===== LOVE8 SIGNED PROVENANCE LEDGER =====')
print('file:',p)
print(json.dumps(json.loads(p.read_text()),ensure_ascii=False,indent=2))
PY

cat >/usr/local/bin/love8-persistent-relationships <<'PY'
#!/usr/bin/env python3
import json
from pathlib import Path
p=Path('/opt/love8-agent/state/social-v2.json')
try: d=json.loads(p.read_text())
except Exception: d={}
rows=[]
for cid,c in d.get('contacts',{}).items():
 if not isinstance(c,dict): continue
 b=c.get('brain',{}) if isinstance(c.get('brain'),dict) else {}
 rows.append((int(c.get('relationship_score',0) or 0),cid,c,b))
rows.sort(reverse=True)
print('===== LOVE8 RELATIONSHIPS =====')
for score,cid,c,b in rows[:50]:
 print(f"{score:3d} {c.get('relationship_stage','candidate'):12s} {cid} room={c.get('last_room','-')} out={c.get('messages_out',0)} replies={c.get('replies_to_love8',0)} bot={b.get('bot_probability','-')} risk={b.get('scam_risk','-')} topics={','.join(str(x) for x in b.get('topics',[])[:4])}")
print('count:',len(rows))
PY

cat >/usr/local/bin/love8-persistent-topics <<'PY'
#!/usr/bin/env python3
import importlib.util,json
from pathlib import Path
core=Path('/opt/love8-agent/social/love8_persistent.py')
s=importlib.util.spec_from_file_location('p24topics',core);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
try: d=json.loads(Path('/opt/love8-agent/state/social-v2.json').read_text())
except Exception: d={}
t=m.topic_momentum(d.get('contacts',{}) if isinstance(d.get('contacts'),dict) else {})
print('===== LOVE8 TOPIC MOMENTUM =====')
for x in t[:30]: print(f"{x['momentum']:6.2f} peers={x['peer_count']:2d} topic={x['topic']} rooms={','.join(x['rooms'][:3])}")
EOF

chmod 755 /usr/local/bin/love8-persistent-*

log "加入 cron：每小时 Relationship/Topic/Contribution Reflection + 每日签名归档"
python3 - "$CRON_FILE" "$CORE" "$LOG" "$PAUSE_FILE" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); core=sys.argv[2]; log=sys.argv[3]; pause=sys.argv[4]
lines=p.read_text().splitlines()
out=[line for line in lines if 'love8_persistent.py' not in line]
out.append(f"17 * * * * root test -f {pause} || /usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 {core} --hourly >>{log} 2>&1")
out.append(f"50 23 * * * root test -f {pause} || /usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 {core} --finalize >>{log} 2>&1")
p.write_text('\n'.join(out)+'\n')
PY
chmod 644 "$CRON_FILE"

log "部署前 dry-run：只计算关系/话题/贡献，不创建房间、不发邀请"
python3 "$CORE" --hourly --dry-run

log "创建第一份 DID 签名 provenance ledger"
python3 "$CORE" --hourly

log "验证 ledger SHA256 + Ed25519 签名"
python3 "$CORE" --verify latest || die "provenance ledger 验证失败"

cat <<'EOF'

============================================================
 LOVE8 v2.4 PERSISTENT AGENT READY
============================================================
新增模块:
  1. Relationship Brain
     candidate -> contacted -> replied -> established -> trusted_peer

  2. Topic Momentum
     根据联系人历史、Brain topics、关系强度持续累计主题动量

  3. Contribution Score
     只把真正发送且质量足够的回复/话题记录为 useful contribution

  4. Signed Provenance Ledger
     /opt/love8-agent/provenance/YYYY-MM-DD.json
     SHA256 + Love8 Ed25519 signature + previous-ledger hash chain

  5. Conditional Social Circle Manager
     默认自动开启，但只有:
       - topic momentum >= 4.5
       - >= 2 established/trusted peers
       - scam/bot 风险低
       - <= 1 new room/day
     才创建专题 room，并最多邀请 3 个相关 peer。

运行节奏:
  Brain social:       原 v2.3 每 5 分钟
  Mailbox:            原 Mailbot 每 3 分钟
  Persistent reflect: 每小时 :17
  Daily finalize:     23:50 UTC

Commands:
  love8-persistent-version
  love8-persistent-status
  love8-persistent-run-now
  love8-persistent-dry-run
  love8-persistent-relationships
  love8-persistent-topics
  love8-persistent-ledger
  love8-persistent-verify
  love8-persistent-log 100
============================================================
EOF
love8-persistent-status
