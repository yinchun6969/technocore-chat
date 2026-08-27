#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-a2a"
PYTHON="$ROOT/venv/bin/python"
DIRECTOR="$ROOT/rnd-v5/autonomous-rnd-v5.py"
BOT="$ROOT/rnd-v5/telegram-control-v1.py"
BACKUP_ROOT="/root/tc-a2a-push-fix-backups"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP="$BACKUP_ROOT/$STAMP"
ROLLBACK="/usr/local/bin/tc-a2a-push-fix-rollback"

DIRECTOR_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/95e6688b1c6d641d5adc6a1d89290d98c680f0f7/deploy/a2a-v5/autonomous-rnd-v5.py"
DIRECTOR_SHA256="b80c60de89099a1d50f1d066d8920a45c1e1e288"
BOT_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/fbf23ace991f5d2df59fa45874e87b547387554c/deploy/a2a-v5/telegram-control-v1.py"
BOT_SHA256="80fc6a4b9096e1a79a6bea66c29bd29d3dfdf14b"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root"
[[ -x "$PYTHON" ]] || die "AI2AI venv Python not found: $PYTHON"
[[ -f "$DIRECTOR" && -f "$BOT" ]] || die "v5 files are not installed"

install -d -o root -g root -m 0700 "$BACKUP"
tar -C / -czf "$BACKUP/prechange.tgz" \
  opt/technocore-a2a/rnd-v5/autonomous-rnd-v5.py \
  opt/technocore-a2a/rnd-v5/telegram-control-v1.py
sha256sum "$BACKUP/prechange.tgz" >"$BACKUP/SHA256SUMS"
chmod 0600 "$BACKUP/prechange.tgz" "$BACKUP/SHA256SUMS"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fL --retry 5 --retry-delay 2 "$DIRECTOR_URL" -o "$tmp/director.py"
curl -fL --retry 5 --retry-delay 2 "$BOT_URL" -o "$tmp/telegram.py"
echo "$DIRECTOR_SHA256  $tmp/director.py" | sha256sum -c -
echo "$BOT_SHA256  $tmp/telegram.py" | sha256sum -c -
"$PYTHON" -m py_compile "$tmp/director.py" "$tmp/telegram.py"

install -o root -g tcagent -m 0750 "$tmp/director.py" "$DIRECTOR"
install -o root -g root -m 0700 "$tmp/telegram.py" "$BOT"

cat >"$ROLLBACK" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP="$BACKUP"
DIRECTOR="$DIRECTOR"
BOT="$BOT"
if [[ -f "$BACKUP/prechange.tgz" ]]; then
  tar -C / -xzf "$BACKUP/prechange.tgz"
fi
systemctl restart technocore-a2a-rnd-v5.service technocore-a2a-telegram.service
echo "AI2AI Telegram push fix rolled back"
echo "DID, identity, mailbox, cursor, provenance, rnd-v5-state, rnd-v5-artifacts, and tg-bot-state were preserved"
echo "backup=$BACKUP"
EOF
chmod 0700 "$ROLLBACK"

systemctl restart technocore-a2a-rnd-v5.service technocore-a2a-telegram.service
sleep 3
systemctl is-active --quiet technocore-a2a-rnd-v5.service || die "Director failed; run $ROLLBACK"
systemctl is-active --quiet technocore-a2a-telegram.service || die "Telegram bridge failed; run $ROLLBACK"

echo "=== AI2AI TELEGRAM REMOTE-PROGRESS FIX READY ==="
echo "remote_stage_polling=enabled"
echo "delivery_timeout_alert=enabled"
echo "telegram_dedupe=enabled"
echo "backup=$BACKUP"
echo "rollback=$ROLLBACK"
