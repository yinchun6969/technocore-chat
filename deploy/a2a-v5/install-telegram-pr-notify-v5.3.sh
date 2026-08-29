#!/usr/bin/env bash
set -Eeuo pipefail

# Upgrade an existing AI2AI Telegram bridge with recovered-stage and PR alerts.
# Existing credentials, offsets, drafts, identity and workflow state are preserved.
ROOT="/opt/technocore-a2a"
SCRIPT="$ROOT/rnd-v5/telegram-control-v1.py"
PYTHON="$ROOT/venv/bin/python"
CONFIG="/etc/technocore-a2a-telegram.env"
UNIT="technocore-a2a-telegram.service"
BACKUPS="/root/tc-a2a-telegram-pr-notify-v53-backups"
SOURCE_URL="${A2A_V53_TELEGRAM_SOURCE_URL:-}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root"
[[ -n "$SOURCE_URL" ]] || die "A2A_V53_TELEGRAM_SOURCE_URL is required"
[[ -x "$PYTHON" && -f "$SCRIPT" && -f "$CONFIG" ]] || die "existing AI2AI Telegram bridge not found"
grep -Eq '^TG_BOT_TOKEN=' "$CONFIG" || die "Telegram token configuration missing"
grep -Eq '^TG_ALLOWED_USER_IDS=' "$CONFIG" || die "Telegram allowlist configuration missing"

work="$(mktemp -d /root/tc-a2a-tg-v53.XXXXXX)"
trap 'rm -rf "$work"' EXIT
curl -fL --retry 5 --retry-delay 2 "$SOURCE_URL" -o "$work/telegram-control-v1.py"
grep -Fq 'github_pr_created' "$work/telegram-control-v1.py" || die "PR notification marker missing"
grep -Fq 'workflow_revised_result_recovered' "$work/telegram-control-v1.py" || die "recovery notification marker missing"
"$PYTHON" -m py_compile "$work/telegram-control-v1.py"

stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUPS/$stamp"
install -d -m 0700 "$backup"
cp -a "$SCRIPT" "$backup/telegram-control-v1.py"
sha256sum "$backup/telegram-control-v1.py" > "$backup/SHA256SUMS"
chmod 0600 "$backup/telegram-control-v1.py" "$backup/SHA256SUMS"

cat > /usr/local/bin/tc-a2a-telegram-pr-notify-v53-rollback <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
install -o root -g root -m 0700 "$backup/telegram-control-v1.py" "$SCRIPT"
systemctl restart "$UNIT"
systemctl is-active --quiet "$UNIT"
echo "rollback=completed"
echo "preserved=telegram-config,offsets,drafts,identity,mailbox,cursor,provenance"
echo "backup=$backup"
EOF
chmod 0700 /usr/local/bin/tc-a2a-telegram-pr-notify-v53-rollback

install -o root -g root -m 0700 "$work/telegram-control-v1.py" "$SCRIPT"
if ! systemctl restart "$UNIT" || ! systemctl is-active --quiet "$UNIT"; then
  install -o root -g root -m 0700 "$backup/telegram-control-v1.py" "$SCRIPT"
  systemctl restart "$UNIT" || true
  die "Telegram bridge failed after update; previous script restored"
fi

echo "=== AI2AI TELEGRAM PR NOTIFY v5.3 READY ==="
echo "service=active"
echo "workflow_recovery_alerts=enabled"
echo "pr_candidate_created_ci_alerts=enabled"
echo "credentials=preserved"
echo "rollback=tc-a2a-telegram-pr-notify-v53-rollback"
echo "backup=$backup"
