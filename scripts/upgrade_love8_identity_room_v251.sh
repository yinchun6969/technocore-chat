#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="2.5.1"
RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT=/opt/love8-agent
SOCIAL="$ROOT/social"
CORE="$SOCIAL/love8_persistent.py"
V250="$SOCIAL/love8_persistent_v250_core.py"
CFG="$SOCIAL/persistent.env"

log(){ printf '\n[+] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$CORE" ]] || die "找不到 $CORE"

CUR="$(python3 "$CORE" --version 2>/dev/null | awk '{print $2}' | tail -n1 || true)"
if [[ "$CUR" != "2.5.0" && "$CUR" != "2.5.1" ]]; then
  log "当前 persistent=$CUR，先进入 v2.5.0"
  curl -fsSL --retry 5 --retry-delay 2 "$RAW/scripts/upgrade_love8_identity_room_v250.sh" -o /tmp/love8-v250.sh
  bash /tmp/love8-v250.sh
  CUR="$(python3 "$CORE" --version 2>/dev/null | awk '{print $2}' | tail -n1 || true)"
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$SOCIAL/backups/v251-$TS"; chmod 700 "$SOCIAL/backups/v251-$TS"
cp -a "$CORE" "$CFG" "$SOCIAL/backups/v251-$TS/" 2>/dev/null || true
if [[ "$CUR" == "2.5.0" ]]; then
  cp -a "$CORE" "$V250"
  chmod 700 "$V250"
fi
[[ -s "$V250" ]] || die "缺少 $V250"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
curl -fsSL --retry 5 --retry-delay 2 "$RAW/scripts/love8_persistent_v251_wrapper.py" -o "$TMP/wrapper.py"
curl -fsSL --retry 5 --retry-delay 2 "$RAW/scripts/test_love8_capacity_v251.py" -o "$TMP/test.py"
python3 -m py_compile "$TMP/wrapper.py" "$TMP/test.py"
install -m 700 "$TMP/wrapper.py" "$CORE"

python3 - "$CFG" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text().splitlines() if p.exists() else []
updates={'PERSIST_CAPACITY_RETRY':'21600'}; out=[]; seen=set()
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        key=line.split('=',1)[0].strip()
        if key in updates:
            out.append(f'{key}={updates[key]}'); seen.add(key); continue
    out.append(line)
for k,v in updates.items():
    if k not in seen: out.append(f'{k}={v}')
p.write_text('\n'.join(out)+'\n')
PY
chmod 600 "$CFG"

python3 -m py_compile "$CORE" "$V250"
[[ "$(python3 "$CORE" --version | awk '{print $2}' | tail -n1)" == "$VERSION" ]] || die "版本检查失败"

cat >/usr/local/bin/love8-room-status <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
STATE=/opt/love8-agent/state/identity-room-v250.json
CFG=/opt/love8-agent/social/config.env
DID=$(awk -F= '$1=="DID"{print $2}' "$CFG" | tail -n1)
echo '===== LOVE8 IDENTITY ROOM v2.5.1 ====='
echo 'agent=love8'; echo "did=$DID"
python3 - "$STATE" <<'PY'
import json,sys,time
from pathlib import Path
try:s=json.loads(Path(sys.argv[1]).read_text())
except Exception:s={}
if not isinstance(s,dict):s={}
room=str(s.get('room') or 'love8')
print('base_room='+str(s.get('base_room') or 'love8'))
print('resolved_room='+room)
print('desired_room='+str(s.get('desired_room') or 'love8'))
print('bootstrap_mode='+str(s.get('bootstrap_mode','')))
print('bootstrap_seq='+str(int(s.get('bootstrap_seq',0) or 0)))
print('capacity_blocked='+str(bool(s.get('capacity_blocked_at'))).lower())
wait=int(s.get('capacity_wait_until',0) or 0)
print('capacity_retry_in='+str(max(0,wait-int(time.time())))+'s')
print('mature_peer_count='+str(int(s.get('mature_peer_count',0) or 0)))
print('collisions='+','.join(str(x) for x in s.get('collisions',[]) if x))
print('invites_30d='+str(len([x for x in s.get('invites',[]) if isinstance(x,dict)])))
print('public_url=https://technocore.chat/humans#r/'+room)
PY
echo '=== persistent version ==='
python3 /opt/love8-agent/social/love8_persistent.py --version
EOF
chmod 755 /usr/local/bin/love8-room-status

log "执行一次 capacity-aware cycle"
/usr/bin/flock -n /run/lock/love8-persistent-v24.lock /usr/bin/python3 "$CORE" --hourly || true
love8-room-status
