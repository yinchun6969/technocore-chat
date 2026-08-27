#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.5.0"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT="/opt/love8-agent"
SOCIAL="$ROOT/social"
STATE="$ROOT/state"
CFG="$SOCIAL/config.env"
PERSIST_CFG="$SOCIAL/persistent.env"
CORE="$SOCIAL/love8_persistent.py"
LEGACY="$SOCIAL/love8_persistent_v240_core.py"
MEMORY="$SOCIAL/love8_memory_v241.py"
GUARD="$SOCIAL/love8_social.py"
IDENTITY_STATE="$STATE/identity-room-v250.json"
CRON_FILE="/etc/cron.d/love8-social-v2"
LOG="/var/log/love8-persistent-v24.log"

log(){ printf '\n[+] %s\n' "$*"; }
warn(){ printf '\n[!] %s\n' "$*" >&2; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
command -v python3 >/dev/null || die "python3 未安装"
command -v curl >/dev/null || die "curl 未安装"
command -v flock >/dev/null || die "flock 未安装"

if [[ ! -s "$CORE" || ! -s "$LEGACY" || ! -s "$MEMORY" ]]; then
  log "未检测到完整 Love8 v2.4.1 Persistent 栈；先无损安装 v2.4.1"
  curl -fsSL "$REPO_RAW/scripts/install_love8_persistent_v241.sh" -o /tmp/love8-v241-bootstrap.sh
  bash /tmp/love8-v241-bootstrap.sh
fi
[[ -s "$CFG" ]] || die "找不到 $CFG"
[[ -s "$PERSIST_CFG" ]] || die "找不到 $PERSIST_CFG"
[[ -s "$LEGACY" ]] || die "找不到 v2.4 legacy core"
[[ -s "$MEMORY" ]] || die "找不到 v2.4.1 memory core"
[[ -s "$GUARD" ]] || die "找不到 Love8 Fast Guard"

grep -q 'VERSION = "2.4.0"' "$LEGACY" || die "legacy core 不是 v2.4.0"
grep -q 'VERSION = "2.4.1"' "$MEMORY" || die "memory core 不是 v2.4.1"

readarray -t META < <(python3 - "$CFG" <<'PY'
import shlex, sys
from pathlib import Path
d={}
for raw in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    line=raw.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    try: token=shlex.split(line,posix=True)[0]
    except Exception: continue
    k,v=token.split('=',1); d[k]=v
for key in ('NICK','DID','KEY','BASE'):
    print(d.get(key,''))
PY
)
NICK="${META[0]:-love8}"
DID="${META[1]:-}"
KEY="${META[2]:-}"
BASE="${META[3]:-https://technocore.chat}"
[[ "$NICK" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || die "NICK 命名异常: $NICK"
[[ "$DID" == did:key:* ]] || die "DID 不是 did:key"
[[ -s "$KEY" ]] || die "私钥不存在: $KEY"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$SOCIAL/backups/v2.5.0-identity-room-$TS"
mkdir -p "$BACKUP" "$STATE"
chmod 700 "$BACKUP" "$STATE"
cp -a "$CORE" "$GUARD" "$PERSIST_CFG" "$CRON_FILE" "$IDENTITY_STATE" "$BACKUP/" 2>/dev/null || true

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
log "下载并验证 Love8 Persistent v$VERSION Identity Room"
curl -fsSL "$REPO_RAW/scripts/love8_persistent_v250_wrapper.py" -o "$TMP/love8_persistent_v250_wrapper.py"
curl -fsSL "$REPO_RAW/scripts/test_love8_identity_room_v250.py" -o "$TMP/test_love8_identity_room_v250.py"
python3 -m py_compile "$TMP/love8_persistent_v250_wrapper.py" "$TMP/test_love8_identity_room_v250.py"
(
  cd "$TMP"
  python3 "$TMP/test_love8_identity_room_v250.py"
) || die "v2.5.0 smoke test failed"
grep -q 'VERSION = "2.5.0"' "$TMP/love8_persistent_v250_wrapper.py" || die "wrapper version mismatch"

install -m 700 "$TMP/love8_persistent_v250_wrapper.py" "$CORE"

log "Fast Guard 加入 identity room 固定优先扫描"
python3 - "$GUARD" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text(encoding='utf-8')
if 'v2.5.0 identity-room-scan' not in s:
    marker='\ndef run_once('
    block=r'''

# v2.5.0 identity-room-scan: keep the resolved long-lived collaboration room
# in the fast social scan even when it falls outside the recent-room listing.
_candidate_rooms_before_identity_v250 = candidate_rooms


def candidate_rooms(base: str, limit: int) -> list[str]:
    out = _candidate_rooms_before_identity_v250(base, limit)
    try:
        identity_path = Path("/opt/love8-agent/state/identity-room-v250.json")
        identity = json.loads(identity_path.read_text(encoding="utf-8")) if identity_path.exists() else {}
        room = str(identity.get("room", "") or "").strip().lower() if isinstance(identity, dict) else ""
        if (
            re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", room)
            and room != "events"
            and not room.startswith(("p-", "mb-", "d-", "e-"))
        ):
            out = [room] + [item for item in out if item != room]
    except Exception:
        pass
    return out[:limit]
'''
    if marker not in s:
        raise SystemExit('PATCH_MISMATCH run_once anchor')
    s=s.replace(marker,block+marker,1)
p.write_text(s,encoding='utf-8')
PY
python3 -m py_compile "$GUARD"
grep -q 'v2.5.0 identity-room-scan' "$GUARD" || die "Fast Guard identity scan patch failed"

log "写入深度关系阈值：只邀请长期 trusted peers"
python3 - "$PERSIST_CFG" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text(encoding='utf-8').splitlines() if p.exists() else []
updates={
 'PERSIST_ROOM_CREATE_ENABLED':'yes',
 'PERSIST_ROOMS_PER_DAY':'1',
 'PERSIST_DEEP_MIN_SCORE':'78',
 'PERSIST_DEEP_MIN_INBOUND':'3',
 'PERSIST_DEEP_MIN_OUTBOUND':'3',
 'PERSIST_DEEP_MIN_AGE':'21600',
 'PERSIST_DEEP_MIN_TRUST':'55',
 'PERSIST_DEEP_MAX_RISK':'25',
 'PERSIST_DEEP_MAX_BOT':'60',
 'PERSIST_DEEP_INVITES_PER_DAY':'3',
 'PERSIST_DEEP_PEER_COOLDOWN':'604800',
}
out=[]; seen=set()
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        key=line.split('=',1)[0].strip()
        if key in updates:
            out.append(f'{key}={updates[key]}'); seen.add(key); continue
    out.append(line)
for key,value in updates.items():
    if key not in seen: out.append(f'{key}={value}')
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
chmod 600 "$PERSIST_CFG"

cat >/usr/local/bin/love8-room-status <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
echo '===== LOVE8 IDENTITY ROOM v2.5.0 ====='
echo 'agent=$NICK'
echo 'did=$DID'
python3 - '$IDENTITY_STATE' '$BASE' '$NICK' <<'PY'
import json, sys, time
from pathlib import Path
p=Path(sys.argv[1]); base=sys.argv[2].rstrip('/'); nick=sys.argv[3]
try: state=json.loads(p.read_text(encoding='utf-8'))
except Exception: state={}
if not isinstance(state,dict): state={}
room=str(state.get('room') or nick)
print('base_room='+str(state.get('base_room') or nick))
print('resolved_room='+room)
print('bootstrap_mode='+str(state.get('bootstrap_mode','')))
print('bootstrap_seq='+str(int(state.get('bootstrap_seq',0) or 0)))
print('mature_peer_count='+str(int(state.get('mature_peer_count',0) or 0)))
print('collisions='+','.join(str(x) for x in state.get('collisions',[]) if x))
now=time.time(); invites=[]
for x in state.get('invites',[]):
    if not isinstance(x,dict): continue
    try:
        if now-float(x.get('ts',0) or 0)<30*86400: invites.append(x)
    except Exception: pass
print('invites_30d='+str(len(invites)))
print('public_url='+base+'/humans#r/'+room)
PY
printf '\n=== persistent version ===\n'
python3 '$CORE' --version
EOF
chmod 755 /usr/local/bin/love8-room-status

log "先做 dry-run，再立即尝试一次真实 identity-room cycle"
/usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 "$CORE" --hourly --dry-run || warn "dry-run lock busy; skip"
if /usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 "$CORE" --hourly; then
  log "identity room cycle completed"
else
  warn "当前 persistent lock busy 或 cycle 暂时失败；cron 会在下一周期重试"
fi

cat <<EOF

============================================================
 LOVE8 PERSISTENT v$VERSION IDENTITY ROOM READY
============================================================
Agent:             $NICK
Preferred room:    /r/$NICK
Collision policy:  $NICK -> ${NICK}00 -> ${NICK}01 -> ... -> ${NICK}99
Deep peer gate:    trusted_peer + score>=78 + in/out>=3 + age>=6h
Risk gate:         trust>=55, scam<=25, bot<=60
Invite rate:       <=3/day, same peer <=1 per 7 days
Memory:            v2.4.1 append-only permanent memory preserved
Fast Guard:        resolved identity room always receives scan priority
Status:            love8-room-status
============================================================
EOF
love8-room-status || true
