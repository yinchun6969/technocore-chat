#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.5.1"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/main}"
SELECTOR="${1:-aizong}"

log(){ printf '\n[+] %s\n' "$*"; }
warn(){ printf '\n[!] %s\n' "$*" >&2; }
die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
command -v python3 >/dev/null || die "python3 未安装"
command -v curl >/dev/null || die "curl 未安装"

if [[ "$SELECTOR" == "love8" ]]; then
  log "Love8 使用独立 v2.4.1 永久记忆架构，切换到兼容的 Identity Room v2.5.0 安装器"
  exec bash -c "curl -fsSL https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2/scripts/upgrade_love8_identity_room_v250.sh | bash"
fi

find_first_file(){
  local p
  for p in "$@"; do [[ -s "$p" ]] && { printf '%s\n' "$p"; return 0; }; done
  return 1
}

case "$SELECTOR" in
  aizong)
    AGENT_DIR="${AGENT_DIR:-/opt/technocore-agent}"
    CONFIG_PATH="${CONFIG_PATH:-$AGENT_DIR/config}"
    PROGRAM_PATH="${PROGRAM_PATH:-$AGENT_DIR/aizong_social.py}"
    SERVICE="${SERVICE:-technocore-aizong-social.service}"
    ;;
  ai2ai)
    if [[ -z "${AGENT_DIR:-}" ]]; then
      for candidate in /opt/ai2ai-agent /opt/technocore-ai2ai-agent /opt/technocore-agent-ai2ai; do
        if [[ -d "$candidate" ]]; then AGENT_DIR="$candidate"; break; fi
      done
    fi
    AGENT_DIR="${AGENT_DIR:-/opt/ai2ai-agent}"
    CONFIG_PATH="${CONFIG_PATH:-$(find_first_file "$AGENT_DIR/config" "$AGENT_DIR/social/config.env" 2>/dev/null || true)}"
    PROGRAM_PATH="${PROGRAM_PATH:-$(find_first_file "$AGENT_DIR/aizong_social.py" "$AGENT_DIR/social/aizong_social.py" 2>/dev/null || true)}"
    SERVICE="${SERVICE:-technocore-ai2ai-social.service}"
    ;;
  *)
    AGENT_DIR="${AGENT_DIR:-/opt/${SELECTOR}-agent}"
    CONFIG_PATH="${CONFIG_PATH:-$(find_first_file "$AGENT_DIR/config" "$AGENT_DIR/social/config.env" 2>/dev/null || true)}"
    PROGRAM_PATH="${PROGRAM_PATH:-$(find_first_file "$AGENT_DIR/aizong_social.py" "$AGENT_DIR/social/aizong_social.py" 2>/dev/null || true)}"
    SERVICE="${SERVICE:-technocore-${SELECTOR}-social.service}"
    ;;
esac

[[ -n "${CONFIG_PATH:-}" && -s "$CONFIG_PATH" ]] || die "找不到 $SELECTOR 的 config；可用 CONFIG_PATH=/path 显式指定"
[[ -n "${PROGRAM_PATH:-}" && -s "$PROGRAM_PATH" ]] || die "找不到 $SELECTOR 的 Social Brain 程序；可用 PROGRAM_PATH=/path 显式指定"

readarray -t META < <(python3 - "$CONFIG_PATH" <<'PY'
import shlex, sys
from pathlib import Path
p=Path(sys.argv[1]); d={}
for raw in p.read_text(encoding='utf-8').splitlines():
    line=raw.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    try: token=shlex.split(line,posix=True)[0]
    except Exception: continue
    k,v=token.split('=',1); d[k]=v
for key in ('NICK','DID','KEY','BASE'):
    print(d.get(key,''))
PY
)
NICK="${META[0]:-}"
DID="${META[1]:-}"
KEY="${META[2]:-}"
BASE="${META[3]:-https://technocore.chat}"
[[ -n "$NICK" ]] || die "config 缺少 NICK"
[[ "$NICK" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || die "NICK 不符合 Technocore 命名规则: $NICK"
[[ "$DID" == did:key:* ]] || die "config DID 不是 did:key"
[[ -s "$KEY" ]] || die "私钥文件不存在: $KEY"

STATE_PATH="${STATE_PATH:-$AGENT_DIR/state/social-v1.json}"
BRAIN_CONFIG="${BRAIN_CONFIG:-$(find_first_file "$AGENT_DIR/brain.env" "$AGENT_DIR/social/brain.env" 2>/dev/null || true)}"
TOPICS_PATH="${TOPICS_PATH:-$AGENT_DIR/state/trusted-topics.json}"
LEDGER_PATH="${LEDGER_PATH:-$AGENT_DIR/state/contribution-ledger.jsonl}"
mkdir -p "$AGENT_DIR/backups" "$(dirname "$STATE_PATH")"
chmod 700 "$AGENT_DIR/backups" "$(dirname "$STATE_PATH")"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$AGENT_DIR/backups/identity-room-v151-$TS"
mkdir -p "$BACKUP"; chmod 700 "$BACKUP"
cp -a "$PROGRAM_PATH" "$CONFIG_PATH" "$STATE_PATH" "$LEDGER_PATH" "$BACKUP/" 2>/dev/null || true

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
for v in 130 131 140 141 142 150 151; do
  curl -fsSL "$REPO_RAW/scripts/patch_aizong_social_v${v}.py" -o "$TMP/patch_v${v}.py"
  python3 -m py_compile "$TMP/patch_v${v}.py"
done

version(){ grep -Eo 'VERSION = "[0-9.]+"' "$PROGRAM_PATH" | head -n1 | cut -d'"' -f2; }
log "升级 $NICK Social Brain：当前 $(version) → v$VERSION"
for _ in 1 2 3 4 5 6 7 8; do
  current="$(version)"
  case "$current" in
    1.2.0) python3 "$TMP/patch_v130.py" "$PROGRAM_PATH" ;;
    1.3.0) python3 "$TMP/patch_v131.py" "$PROGRAM_PATH" ;;
    1.3.1) python3 "$TMP/patch_v140.py" "$PROGRAM_PATH" ;;
    1.4.0) python3 "$TMP/patch_v141.py" "$PROGRAM_PATH" ;;
    1.4.1) python3 "$TMP/patch_v142.py" "$PROGRAM_PATH" ;;
    1.4.2) python3 "$TMP/patch_v150.py" "$PROGRAM_PATH" ;;
    1.5.0) python3 "$TMP/patch_v151.py" "$PROGRAM_PATH" ;;
    1.5.1) break ;;
    *) die "不支持从 Social $current 自动迁移；备份在 $BACKUP" ;;
  esac
done
python3 -m py_compile "$PROGRAM_PATH"
[[ "$(version)" == "$VERSION" ]] || die "升级后版本不是 $VERSION"

grep -q '_select_identity_room' "$PROGRAM_PATH" || die "identity room allocator 未安装"
grep -q 'TC_HUB_MIN_RELATIONSHIP_AGE' "$PROGRAM_PATH" || die "mature relationship gate 未安装"
grep -q 'Do not optimize public behavior for faucets' "$PROGRAM_PATH" || die "anti-farming policy 丢失"

if ! systemctl cat "$SERVICE" >/dev/null 2>&1; then
  detected="$(systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -E "${NICK}.*social.*\.service$" | head -n1 || true)"
  [[ -n "$detected" ]] && SERVICE="$detected"
fi

if systemctl cat "$SERVICE" >/dev/null 2>&1; then
  DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
  DROPIN="$DROPIN_DIR/95-identity-room-v151.conf"
  mkdir -p "$DROPIN_DIR"
  cat >"$DROPIN" <<EOF
[Unit]
Description=$NICK Social v1.5.1 identity-named deep collaboration room

[Service]
Environment=TC_AGENT_NICK=$NICK
Environment=TC_HOME_ROOM=$NICK
Environment=TC_HUB_ENABLED=1
Environment=TC_HUB_ROOM_DAILY_CAP=6
Environment=TC_HUB_INVITES_DAILY_CAP=3
Environment=TC_HUB_PEER_INVITE_COOLDOWN=604800
Environment=TC_HUB_MIN_RELATIONSHIP_AGE=21600
Environment=TC_HUB_MIN_INBOUND=3
Environment=TC_HUB_MIN_OUTBOUND=3
Environment=TC_HUB_INVITE_MIN_VALUE=65
Environment=TC_HUB_INVITE_MIN_INTEREST=70
Environment=TC_HUB_INVITE_MIN_TRUST=55
Environment=TC_HUB_INVITE_MIN_DURABLE=65
Environment=TC_HUB_INVITE_MAX_RISK=25
Environment=TC_HUB_VERIFY_INTERVAL=21600
Environment=TC_SOCIAL_CONFIG=$CONFIG_PATH
Environment=TC_SOCIAL_STATE=$STATE_PATH
Environment=TC_SOCIAL_TOPICS=$TOPICS_PATH
Environment=TC_SOCIAL_LEDGER=$LEDGER_PATH
EOF
  if [[ -n "$BRAIN_CONFIG" ]]; then printf 'Environment=TC_SOCIAL_BRAIN_CONFIG=%s\n' "$BRAIN_CONFIG" >>"$DROPIN"; fi
  chmod 644 "$DROPIN"
  systemctl daemon-reload
  systemctl restart "$SERVICE"
  sleep 5
  systemctl is-active --quiet "$SERVICE" || { journalctl -u "$SERVICE" -n 80 --no-pager; die "$SERVICE 启动失败"; }
else
  warn "未找到 systemd service；程序已升级，但请手动重启 $NICK 的 Social 进程"
fi

STATUS_CMD="/usr/local/bin/tc-${NICK}-room-status"
cat >"$STATUS_CMD" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
echo '===== ${NICK} IDENTITY ROOM v1.5.1 ====='
echo 'agent=$NICK'
echo 'did=$DID'
echo 'service=$SERVICE'
echo 'service_state='"\$(systemctl is-active '$SERVICE' 2>/dev/null || echo unmanaged)"
python3 - '$STATE_PATH' '$BASE' '$NICK' <<'PY'
import json, sys
from pathlib import Path
state_path=Path(sys.argv[1]); base=sys.argv[2].rstrip('/'); nick=sys.argv[3]
try: state=json.loads(state_path.read_text(encoding='utf-8'))
except Exception: state={}
hub=state.get('home_hub',{}) if isinstance(state,dict) else {}
if not isinstance(hub,dict): hub={}
room=str(hub.get('room') or nick)
print('base_room='+str(hub.get('base_room') or nick))
print('resolved_room='+room)
print('bootstrap_mode='+str(hub.get('bootstrap_mode','')))
print('bootstrap_seq='+str(int(hub.get('bootstrap_seq',0) or 0)))
print('collisions='+','.join(str(x) for x in hub.get('collisions',[]) if x))
invites=[x for x in hub.get('invites',[]) if isinstance(x,dict)]
print('invites_total='+str(len(invites)))
print('public_url='+base+'/humans#r/'+room)
PY
EOF
chmod 755 "$STATUS_CMD"

log "$NICK v$VERSION 安装完成"
echo "Identity room base: /r/$NICK"
echo "Collision policy:   $NICK -> ${NICK}00 -> ${NICK}01 -> ... -> ${NICK}99"
echo "Deep invite gate:   trusted_peer/collaborator + >=3 in + >=3 out + >=6h + low risk"
echo "Invite rate:        max 3/day; same DID max once/7 days"
echo "Status:             tc-${NICK}-room-status"
"$STATUS_CMD" || true
