#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-a2a"
PYTHON="$ROOT/venv/bin/python"
SCRIPT="$ROOT/rnd-v5/telegram-control-v1.py"
CONFIG="/etc/technocore-a2a-telegram.env"
UNIT="/etc/systemd/system/technocore-a2a-telegram.service"
STATUS="/usr/local/bin/tc-a2a-telegram-status"
ROLLBACK="/usr/local/bin/tc-a2a-telegram-rollback"
REPO_RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat/b5901824d52d6630a47de68bf67934bb67075ea6/deploy/a2a-v5"
BACKUP_ROOT="/root/tc-a2a-telegram-backups"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ $EUID -eq 0 ]] || die "run as root"
[[ -f "$ROOT/.env" && -f "$ROOT/bin/agent.py" ]] || die "AI2AI runtime not found"
[[ -x "$PYTHON" ]] || die "AI2AI venv Python not found: $PYTHON"
[[ -f "$ROOT/rnd-v5/autonomous-rnd-v5.py" ]] || die "v5 Director is not installed"
grep -Eq '^AGENT_NAME=ai2ai([[:space:]]|$)' "$ROOT/.env" || die "this host is not AI2AI"
grep -q 'WORKFLOW_V3_REVIEWER_BEGIN' "$ROOT/bin/agent.py" || die "Reviewer v3 marker missing"
grep -q 'MANUAL_QUEUE' "$ROOT/rnd-v5/autonomous-rnd-v5.py" || die "install the updated v5 Director before installing Telegram control"
"$PYTHON" -c 'import requests' >/dev/null 2>&1 || die "requests is missing from the AI2AI venv"

read -rsp "Telegram Bot token (input directly here, never paste it into chat): " token
printf '\n'
[[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || die "Telegram Bot token format is invalid"

read -rp "Your Telegram numeric user ID (comma-separated allowlist): " allowed
[[ "$allowed" =~ ^[0-9]+(,[0-9]+)*$ ]] || die "Telegram user ID list is invalid"

old_active="$(systemctl is-active technocore-a2a-telegram.service 2>/dev/null || true)"
old_enabled="$(systemctl is-enabled technocore-a2a-telegram.service 2>/dev/null || true)"

stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$stamp"
install -d -o root -g root -m 0700 "$backup"
manifest="$backup/MANIFEST"
: >"$manifest"

for path in \
  opt/technocore-a2a/rnd-v5/telegram-control-v1.py \
  etc/technocore-a2a-telegram.env \
  etc/systemd/system/technocore-a2a-telegram.service \
  usr/local/bin/tc-a2a-telegram-status \
  usr/local/bin/tc-a2a-telegram-rollback
do
  if [[ -e "/$path" || -L "/$path" ]]; then
    printf '%s\n' "$path" >>"$manifest"
  fi
done
if [[ -s "$manifest" ]]; then
  tar -C / -czf "$backup/prechange.tgz" --files-from "$manifest"
else
  tar -C / -czf "$backup/prechange.tgz" --files-from /dev/null
fi
sha256sum "$backup/prechange.tgz" >"$backup/SHA256SUMS"
chmod 0600 "$backup/prechange.tgz" "$backup/SHA256SUMS" "$manifest"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fL --retry 5 --retry-delay 2 "$REPO_RAW/telegram-control-v1.py" -o "$tmp"
"$PYTHON" -m py_compile "$tmp"
install -d -m 0750 "$ROOT/rnd-v5"
install -o root -g root -m 0700 "$tmp" "$SCRIPT"

umask 077
printf '%s\n' \
  "TG_BOT_TOKEN=$token" \
  "TG_ALLOWED_USER_IDS=$allowed" \
  "TG_POLL_SECONDS=25" \
  >"$CONFIG"
chown root:root "$CONFIG"
chmod 0600 "$CONFIG"

# systemd refuses ReadWritePaths entries that do not exist yet.
install -d -o root -g root -m 0700 "$ROOT/tg-bot-state" "$ROOT/tg-bot-state/drafts"

cat >"$UNIT" <<EOF
[Unit]
Description=Technocore AI2AI Telegram human control bridge
After=network-online.target technocore-a2a.service technocore-a2a-rnd-v5.service
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
EnvironmentFile=$CONFIG
ExecStart=$PYTHON $SCRIPT run
Restart=always
RestartSec=15
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$ROOT/rnd-v5-state $ROOT/rnd-v5-artifacts $ROOT/tg-bot-state $ROOT/state $ROOT/identity

[Install]
WantedBy=multi-user.target
EOF
chown root:root "$UNIT"
chmod 0644 "$UNIT"

cat >"$STATUS" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
systemctl status technocore-a2a-telegram.service --no-pager -l
EOF
chown root:root "$STATUS"
chmod 0700 "$STATUS"

cat >"$ROLLBACK" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP=$backup
OLD_ACTIVE=$old_active
OLD_ENABLED=$old_enabled

systemctl disable --now technocore-a2a-telegram.service 2>/dev/null || true
rm -f "$SCRIPT" "$CONFIG" "$UNIT" "$STATUS" "$ROLLBACK"
if [[ -f "\$BACKUP/prechange.tgz" ]]; then
  tar -C / -xzf "\$BACKUP/prechange.tgz"
fi
systemctl daemon-reload
if [[ "\$OLD_ENABLED" == enabled ]]; then
  systemctl enable technocore-a2a-telegram.service
else
  systemctl disable technocore-a2a-telegram.service 2>/dev/null || true
fi
if [[ "\$OLD_ACTIVE" == active ]]; then
  systemctl start technocore-a2a-telegram.service
fi
echo "Telegram control bridge rolled back"
echo "AI2AI R&D services, DID, private key, mailbox, cursor, provenance, and tg-bot-state were preserved"
echo "backup=\$BACKUP"
EOF
chown root:root "$ROLLBACK"
chmod 0700 "$ROLLBACK"

rm -f "$tmp"
trap - EXIT
systemctl daemon-reload
# Reload the Python process after replacing the script; --now alone does not
# restart an already-active unit.
systemctl enable technocore-a2a-telegram.service
systemctl restart technocore-a2a-telegram.service
sleep 2
systemctl is-active --quiet technocore-a2a-telegram.service || die "Telegram bridge failed; run tc-a2a-telegram-rollback"

echo "=== AI2AI TELEGRAM CONTROL v1 READY ==="
echo "service=active"
echo "allowlist=configured"
echo "natural_language=read-only discussion plus safe queued research"
echo "public_post=human approval only"
echo "backup=$backup"
echo "rollback=tc-a2a-telegram-rollback"
