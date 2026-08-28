#!/usr/bin/env bash
set -Eeuo pipefail

# R&D v5 progress/delivery repair. Does not replace identity or state.
REPO_RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat"
SOURCE_REF="70bf99b6ae677a92adbab986f6b8019ec48ea723"
SOURCE_BASE="$REPO_RAW/$SOURCE_REF/deploy/a2a-v5"
ROOT="/opt/technocore-a2a"
BACKUP_ROOT="/root/tc-a2a-progress-fix-v3-backups"
DIRECTOR="$ROOT/rnd-v5/autonomous-rnd-v5.py"
TELEGRAM="$ROOT/rnd-v5/telegram-control-v1.py"
PYTHON="$ROOT/venv/bin/python"
ROLLBACK="/usr/local/bin/tc-a2a-progress-fix-v3-rollback"

die() { echo "[x] $*" >&2; exit 1; }
[[ "$EUID" -eq 0 ]] || die "Run as root"
[[ -x "$PYTHON" && -f "$ROOT/.env" ]] || die "Existing AI2AI runtime not found"
[[ -f "$DIRECTOR" && -f "$TELEGRAM" ]] || die "Existing v5 files not found"
id tcagent >/dev/null 2>&1 || die "tcagent user not found"

stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$stamp"
install -d -m 0700 "$backup"
items=(
  opt/technocore-a2a/rnd-v5/autonomous-rnd-v5.py
  opt/technocore-a2a/rnd-v5/telegram-control-v1.py
  opt/technocore-a2a/rnd-v5-state/director.json
  opt/technocore-a2a/rnd-v5-state/director.log
  opt/technocore-a2a/rnd-v5-state/notify.json
  etc/systemd/system/technocore-a2a-rnd-v5.service
  etc/systemd/system/technocore-a2a-telegram.service
)
existing=()
for item in "${items[@]}"; do
  [[ -e "/$item" ]] && existing+=( "$item" )
done
(("${#existing[@]}" > 0)) || die "No existing files available for backup"
tar -C / -czf "$backup/prechange.tgz" --ignore-failed-read "${existing[@]}"
sha256sum "$backup/prechange.tgz" > "$backup/SHA256SUMS"
chmod 0600 "$backup/prechange.tgz" "$backup/SHA256SUMS"
cat > "$backup/MANIFEST" <<EOF
version=progress-fix-v3
host=$(hostname)
utc=$(date -u -Is)
source_ref=$SOURCE_REF
policy=restore-code-only; preserve-identity-and-state
EOF
chmod 0600 "$backup/MANIFEST"

cat > "$ROLLBACK" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP="$backup"
ROOT="$ROOT"
if [[ -f "$BACKUP/prechange.tgz" ]]; then
  tar -C / -xzf "$BACKUP/prechange.tgz" \
    opt/technocore-a2a/rnd-v5/autonomous-rnd-v5.py \
    opt/technocore-a2a/rnd-v5/telegram-control-v1.py \
    etc/systemd/system/technocore-a2a-rnd-v5.service \
    etc/systemd/system/technocore-a2a-telegram.service 2>/dev/null || true
fi
systemctl daemon-reload
systemctl restart technocore-a2a-rnd-v5.service technocore-a2a-telegram.service 2>/dev/null || true
echo "rollback=completed"
echo "preserved=identity,mailbox,cursor,provenance,rnd-v5-state"
echo "backup=$BACKUP"
EOF
chmod 0700 "$ROLLBACK"

tmp="$(mktemp -d /root/tc-a2a-progress-fix-v3.XXXXXX)"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT

curl -fL --retry 5 --retry-delay 2 "$SOURCE_BASE/autonomous-rnd-v5.py" -o "$tmp/director.py"
curl -fL --retry 5 --retry-delay 2 "$SOURCE_BASE/telegram-control-v1.py" -o "$tmp/telegram.py"

grep -Fq "retry_after_delivery_timeout" "$tmp/director.py" || die "delivery retry patch missing"
grep -Fq "expired_workflows" "$tmp/director.py" || die "expiry dedupe patch missing"
grep -Fq "discussion_last_error" "$tmp/director.py" || die "room diagnostics patch missing"
grep -Fq "workflow_active_expired" "$tmp/telegram.py" || die "Telegram dedupe patch missing"
"$PYTHON" -m py_compile "$tmp/director.py" "$tmp/telegram.py"

install -o root -g tcagent -m 0750 "$tmp/director.py" "$DIRECTOR"
install -o root -g tcagent -m 0750 "$tmp/telegram.py" "$TELEGRAM"
systemctl daemon-reload
systemctl restart technocore-a2a-rnd-v5.service technocore-a2a-telegram.service
sleep 4

if ! systemctl is-active --quiet technocore-a2a-rnd-v5.service || ! systemctl is-active --quiet technocore-a2a-telegram.service; then
  echo "[x] A service failed after the update; restoring the backup" >&2
  "$ROLLBACK" || true
  exit 1
fi

echo "=== AI2AI PROGRESS/DELIVERY FIX v3 READY ==="
echo "director=active"
echo "telegram=active"
echo "delivery_timeout=1800s; one retry then normal 7200s cadence"
echo "expiry_notifications=deduplicated"
echo "backup=$backup"
echo "rollback=$ROLLBACK"
