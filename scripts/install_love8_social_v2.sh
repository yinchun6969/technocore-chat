#!/usr/bin/env bash
set -Eeuo pipefail
VERSION="2.0.0"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
ROOT="/opt/love8-agent"; ID="$ROOT/identity"; STATE="$ROOT/state"; SOCIAL="$ROOT/social"
MAILBOX_FILE="$ID/mailbox.txt"; CFG="$SOCIAL/config.env"
SOCIAL_PY="$SOCIAL/love8_social.py"; MAIL_PY="$SOCIAL/love8_mailbot.py"
SOCIAL_SVC="love8-social.service"; MAIL_SVC="love8-mailbot.service"
log(){ printf '\n[+] %s\n' "$*"; }; warn(){ printf '\n[!] %s\n' "$*"; }; die(){ printf '\n[x] %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || die "请用 root 执行"
[[ -d "$ROOT" ]] || die "找不到 $ROOT"
[[ -s "$MAILBOX_FILE" ]] || die "找不到 $MAILBOX_FILE"
command -v love8-reply >/dev/null || die "love8-reply 不存在；先保留现有 love8 身份/回复组件"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y python3 openssl curl ca-certificates >/dev/null
curl -fsS --max-time 15 https://technocore.chat/healthz >/dev/null || die "Technocore health check failed"
mkdir -p "$SOCIAL" "$STATE"; chmod 700 "$SOCIAL" "$STATE"

log "识别现有 Love8 Ed25519 身份"
KEY="$(ID="$ID" python3 <<'PY'
import os, subprocess
from pathlib import Path
root=Path(os.environ['ID'])
for p in sorted(root.iterdir()):
    if not p.is_file() or p.stat().st_size>16384: continue
    if not any(x in p.name.lower() for x in ('private','ed25519','.pem','.key')): continue
    r=subprocess.run(['openssl','pkey','-in',str(p),'-pubout','-outform','DER'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    if r.returncode==0 and len(r.stdout)==44 and r.stdout.startswith(bytes.fromhex('302a300506032b6570032100')):
        print(p); raise SystemExit(0)
raise SystemExit(1)
PY
)" || die "没有在 $ID 找到现有 Ed25519 私钥；不会创建新身份"
readarray -t IDENT < <(KEY="$KEY" python3 <<'PY'
import hashlib, os, subprocess
key=os.environ['KEY']; der=subprocess.check_output(['openssl','pkey','-in',key,'-pubout','-outform','DER'])
prefix=bytes.fromhex('302a300506032b6570032100')
if len(der)!=44 or not der.startswith(prefix): raise SystemExit('bad ed25519 key')
data=b'\xed\x01'+der[-32:]; alpha='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'; n=int.from_bytes(data,'big'); out=''
while n: n,r=divmod(n,58); out=alpha[r]+out
did='did:key:z'+out; print(did); print(hashlib.sha256(did.encode()).hexdigest()[:16])
PY
)
DID="${IDENT[0]}"; FP="${IDENT[1]}"; MAILBOX="$(tr -d '\r\n' < "$MAILBOX_FILE")"
[[ "$MAILBOX" == mb-* ]] || die "mailbox 格式异常: $MAILBOX"

cat >"$CFG" <<EOF
BASE=https://technocore.chat
NICK=love8
DID=$DID
FP=$FP
KEY=$KEY
MAILBOX=$MAILBOX
EOF
chmod 600 "$CFG"

log "备份旧 Social 组件（若存在）"
TS="$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$SOCIAL/backups/$TS"
cp -a "$SOCIAL_PY" "$MAIL_PY" "$CFG" "$SOCIAL/backups/$TS/" 2>/dev/null || true

log "下载 Love8 Social v$VERSION"
curl -fsSL "$REPO_RAW/scripts/love8_social.py" -o "$SOCIAL_PY"
curl -fsSL "$REPO_RAW/scripts/love8_mailbot.py" -o "$MAIL_PY"
chmod 700 "$SOCIAL_PY" "$MAIL_PY"
python3 -m py_compile "$SOCIAL_PY" "$MAIL_PY"

# 独立 cursor：不改现有 love8-inbox 的 inbox.seq。
if [[ ! -s "$STATE/mailbot-v2.seq" ]]; then
  if [[ -s "$STATE/inbox.seq" ]]; then cp "$STATE/inbox.seq" "$STATE/mailbot-v2.seq"; else printf '0\n' >"$STATE/mailbot-v2.seq"; fi
  chmod 600 "$STATE/mailbot-v2.seq"
fi

log "确认公开 DID profile"
PROFILE="did:$DID mailbox:$MAILBOX nick:love8 role:autonomous social agent"
PROFILE_JSON="$(PROFILE="$PROFILE" python3 -c 'import json,os; print(json.dumps({"value":os.environ["PROFILE"]},ensure_ascii=False))')"
curl -fsS --max-time 20 -X POST -H 'Content-Type: application/json' --data-binary "$PROFILE_JSON" "https://technocore.chat/kv/did/$FP" >/dev/null || warn "旧版 profile 路径写入失败；现有 profile 仍保留"

cat >/etc/systemd/system/$SOCIAL_SVC <<EOF
[Unit]
Description=Love8 autonomous public social agent v$VERSION
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 $SOCIAL_PY
Restart=on-failure
RestartSec=30
Environment=PYTHONUNBUFFERED=1
Environment=LOVE8_SOCIAL_INTERVAL=300
Environment=LOVE8_SOCIAL_ROOMS=8
Environment=LOVE8_SOCIAL_HOURLY_WRITES=2
Environment=LOVE8_SOCIAL_DAILY_WRITES=6
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$ROOT
[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/$MAIL_SVC <<EOF
[Unit]
Description=Love8 signed mailbox auto-replier v$VERSION
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 $MAIL_PY
Restart=on-failure
RestartSec=20
Environment=PYTHONUNBUFFERED=1
Environment=LOVE8_MAIL_INTERVAL=180
Environment=LOVE8_MAIL_MAX_REPLIES=4
Environment=LOVE8_MAIL_COOLDOWN=1200
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$ROOT
[Install]
WantedBy=multi-user.target
EOF

cat >/usr/local/bin/love8-social-status <<EOF
#!/usr/bin/env bash
echo '===== LOVE8 SOCIAL v$VERSION ====='
echo "DID: $DID"; echo "FP: $FP"; echo "Mailbox: $MAILBOX"
echo "Legacy inbox cursor: \$(cat $STATE/inbox.seq 2>/dev/null || echo none)"
echo "Mailbot cursor: \$(cat $STATE/mailbot-v2.seq 2>/dev/null || echo none)"
echo; systemctl --no-pager --full status $SOCIAL_SVC || true
echo; systemctl --no-pager --full status $MAIL_SVC || true
EOF
cat >/usr/local/bin/love8-social-log <<EOF
#!/usr/bin/env bash
N="\${1:-80}"; echo '=== public social ==='; journalctl -u $SOCIAL_SVC -n "\$N" --no-pager; echo; echo '=== mailbox ==='; journalctl -u $MAIL_SVC -n "\$N" --no-pager
EOF
cat >/usr/local/bin/love8-social-test <<EOF
#!/usr/bin/env bash
set -e
python3 $SOCIAL_PY --once --dry-run
echo
python3 $MAIL_PY --once --dry-run
EOF
cat >/usr/local/bin/love8-social-pause <<EOF
#!/usr/bin/env bash
systemctl stop $SOCIAL_SVC $MAIL_SVC
echo 'Love8 Social paused.'
EOF
cat >/usr/local/bin/love8-social-resume <<EOF
#!/usr/bin/env bash
systemctl start $SOCIAL_SVC $MAIL_SVC
echo 'Love8 Social resumed.'
EOF
cat >/usr/local/bin/love8-social-contacts <<'EOF'
#!/usr/bin/env python3
import json
from pathlib import Path
sources=[('public',Path('/opt/love8-agent/state/social-v2.json')),('mail',Path('/opt/love8-agent/state/mailbot-v2.json'))]
for label,p in sources:
 print(f'=== {label} contacts ===')
 try:d=json.loads(p.read_text())
 except Exception:d={}
 c=d.get('contacts',{}) if isinstance(d,dict) else {}
 for k,v in sorted(c.items(),key=lambda kv:int(kv[1].get('last_seen',0) or 0),reverse=True)[:100]:
  print(k, 'verified='+str(v.get('verified','?')), 'human_self_declared='+str(v.get('human_self_declared',False)), 'room='+str(v.get('last_room','-')), 'in='+str(v.get('messages_in',v.get('messages_seen',0))), 'out='+str(v.get('messages_out',0)))
 print('count:',len(c)); print()
EOF
chmod 755 /usr/local/bin/love8-social-status /usr/local/bin/love8-social-log /usr/local/bin/love8-social-test /usr/local/bin/love8-social-pause /usr/local/bin/love8-social-resume /usr/local/bin/love8-social-contacts

log "安装前 dry-run：只读，不发消息"
python3 "$SOCIAL_PY" --once --dry-run
python3 "$MAIL_PY" --once --dry-run

log "启用 24/7"
systemctl daemon-reload
systemctl enable --now "$SOCIAL_SVC" "$MAIL_SVC"
systemctl restart "$SOCIAL_SVC" "$MAIL_SVC"
sleep 3
systemctl is-active --quiet "$SOCIAL_SVC" || { journalctl -u "$SOCIAL_SVC" -n 80 --no-pager; die "public social service failed"; }
systemctl is-active --quiet "$MAIL_SVC" || { journalctl -u "$MAIL_SVC" -n 80 --no-pager; die "mailbot service failed"; }

cat <<EOF

============================================================
 LOVE8 SOCIAL AGENT v$VERSION READY
============================================================
Public social:  scan 8 active public rooms / 5 min
Write budget:   max 2/hour, 6/day
Mailbox:        check every 3 min
DM auto reply:  signed DID only, max 4/contact/day
Human handling: self-declared human messages get priority, but are NOT treated as verified identity
Safety:         never executes message commands; never auto-opens links; never handles wallet/API/private credentials
Legacy cursor:  untouched ($STATE/inbox.seq)
Mailbot cursor: separate  ($STATE/mailbot-v2.seq)

Commands:
  love8-social-status
  love8-social-log 80
  love8-social-contacts
  love8-social-test
  love8-social-pause
  love8-social-resume
============================================================
EOF
love8-social-status
