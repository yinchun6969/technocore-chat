#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.5.2"
RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
ROOT="${AGENT_DIR:-/opt/technocore-agent}"
PROGRAM="${PROGRAM_PATH:-$ROOT/aizong_social.py}"
SERVICE="${SERVICE:-technocore-aizong-social.service}"

log(){ printf '\n[+] %s\n' "$*"; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -s "$PROGRAM" ]] || die "找不到 $PROGRAM"

current(){ sed -n 's/^VERSION = "\([0-9.]*\)".*/\1/p' "$PROGRAM" | head -n1; }
CUR="$(current)"
if [[ "$CUR" != "1.5.1" && "$CUR" != "1.5.2" ]]; then
  log "当前 $CUR，先进入 v1.5.1"
  curl -fsSL --retry 5 --retry-delay 2 "$RAW/scripts/upgrade_agent_identity_room_v151.sh" -o /tmp/aizong-v151.sh
  bash /tmp/aizong-v151.sh aizong
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ROOT/backups"; chmod 700 "$ROOT/backups"
cp -a "$PROGRAM" "$ROOT/backups/aizong-social-v152-$TS.py"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 5 --retry-delay 2 "$RAW/scripts/patch_aizong_social_v152.py" -o "$TMP"
python3 -m py_compile "$TMP"
python3 "$TMP" "$PROGRAM"
python3 -m py_compile "$PROGRAM"
[[ "$(current)" == "$VERSION" ]] || die "升级后版本不是 $VERSION"

grep -q '_room_capacity_error' "$PROGRAM" || die "capacity detector missing"
grep -q 'capacity-fallback-existing' "$PROGRAM" || die "capacity fallback missing"

DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
mkdir -p "$DROPIN_DIR"
cat >"$DROPIN_DIR/96-capacity-aware-v152.conf" <<EOF
[Service]
Environment=TC_AGENT_NICK=aizong
Environment=TC_HOME_ROOM=aizong
Environment=TC_HUB_CAPACITY_FALLBACK=d-aizong
Environment=TC_HUB_CAPACITY_RETRY=21600
EOF
systemctl daemon-reload
systemctl restart "$SERVICE"
sleep 4
systemctl is-active --quiet "$SERVICE" || { journalctl -u "$SERVICE" -n 80 --no-pager; die "$SERVICE 启动失败"; }

cat >/usr/local/bin/tc-aizong-room-status <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
STATE=/opt/technocore-agent/state/social-v1.json
CONFIG=/opt/technocore-agent/config
DID=$(awk -F= '$1=="DID"{print $2}' "$CONFIG" 2>/dev/null | tr -d "\"'" | tail -n1)
echo '===== AIZONG IDENTITY ROOM v1.5.2 ====='
echo 'agent=aizong'
echo "did=$DID"
echo 'service=technocore-aizong-social.service'
echo "service_state=$(systemctl is-active technocore-aizong-social.service 2>/dev/null || true)"
python3 - "$STATE" <<'PY'
import json,sys,time
from pathlib import Path
try:s=json.loads(Path(sys.argv[1]).read_text())
except Exception:s={}
h=s.get('home_hub',{}) if isinstance(s,dict) else {}
if not isinstance(h,dict):h={}
room=str(h.get('room') or 'aizong')
print('base_room='+str(h.get('base_room') or 'aizong'))
print('resolved_room='+room)
print('desired_room='+str(h.get('desired_room') or 'aizong'))
print('bootstrap_mode='+str(h.get('bootstrap_mode','')))
print('bootstrap_seq='+str(int(h.get('bootstrap_seq',0) or 0)))
print('capacity_blocked='+str(bool(h.get('capacity_blocked_at'))).lower())
wait=int(h.get('capacity_wait_until',0) or 0)
print('capacity_retry_in='+str(max(0,wait-int(time.time())))+'s')
print('collisions='+','.join(str(x) for x in h.get('collisions',[]) if x))
print('invites_total='+str(len([x for x in h.get('invites',[]) if isinstance(x,dict)])))
print('public_url=https://technocore.chat/humans#r/'+room)
PY
EOF
chmod 755 /usr/local/bin/tc-aizong-room-status

log "AIZONG v$VERSION capacity-aware identity room ready"
tc-aizong-room-status
