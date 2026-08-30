#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="5.5.1"
SOURCE_REF="bee583c1691b641eeb5a84c3e58a9ae30582943b"
SOURCE_BASE="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5"
ROOT="/opt/technocore-a2a"
ENV_FILE="$ROOT/.env"
RND="$ROOT/rnd-v5"
CURATOR="$RND/autonomous-curator-v5.py"
EVIDENCE="$RND/evidence_v55.py"
STATUS="$RND/task_status_v55.py"
TELEGRAM="$RND/telegram-control-v1.py"
CURATOR_SERVICE="technocore-a2a-rnd-curator-v5.service"
TELEGRAM_SERVICE="technocore-a2a-telegram.service"
BACKUP_ROOT="/root/tc-a2a-verifiable-evidence-v551-backups"
ROLLBACK="/usr/local/bin/tc-a2a-verifiable-evidence-v551-rollback"
CLI="/usr/local/bin/tc-a2a-task-status"
SHORT_CLI="/usr/local/bin/technocore"
MODE="check"

declare -A HASHES=(
  [autonomous-curator-v5.py]="10b6db42538c754ba4a9fde906321d4ca437ced5470767a7347941bc6f49a48d"
  [evidence_v55.py]="64e361389ff7a247f897f6536de89c640096c5e01b3d236e96d43a5ea1664b9e"
  [task_status_v55.py]="38819807b98da67e01c4841a2939c1898294d4e92e2f541fa7a4e66c0b4a48be"
  [demo_v55.py]="a10e20e68095eeb0d035dfb5139bf00e71055332b148b9c9fd63e8b39b63171f"
  [patch-verified-brief-v5.5.1.py]="8b98157d353707b900dfc7dfceb7c42d0efe0e89edc0a9a399b0f79df8e10b2a"
)

die() { echo "ERROR: $*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --check) MODE="check" ;;
    --apply) MODE="apply" ;;
    *) die "usage: $0 --check | --apply" ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || die "run as root"
for command in curl sha256sum python3 flock systemctl; do command -v "$command" >/dev/null || die "$command is required"; done
[[ -f "$ENV_FILE" && -f "$CURATOR" && -f "$TELEGRAM" && -x "$ROOT/venv/bin/python" ]] || die "existing AI2AI v5.5 runtime not found"
[[ "$(tr -d '\0' </proc/1/comm 2>/dev/null || true)" == systemd ]] || die "AI2AI v5.5.1 requires systemd"
set -a; source "$ENV_FILE"; set +a
[[ "${AGENT_NAME:-}" == ai2ai ]] || die "v5.5.1 changes only the AI2AI Reviewer/Curator node"
id tcagent >/dev/null 2>&1 || die "tcagent user missing"

stage="$(mktemp -d /root/tc-a2a-evidence-v551.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
chmod 0700 "$stage"
for file in autonomous-curator-v5.py evidence_v55.py task_status_v55.py demo_v55.py patch-verified-brief-v5.5.1.py; do
  curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 \
    "$SOURCE_BASE/$file" -o "$stage/$file"
  printf '%s  %s\n' "${HASHES[$file]}" "$stage/$file" | sha256sum -c -
done
"$ROOT/venv/bin/python" -m py_compile \
  "$stage/autonomous-curator-v5.py" "$stage/evidence_v55.py" \
  "$stage/task_status_v55.py" "$stage/demo_v55.py" \
  "$stage/patch-verified-brief-v5.5.1.py"
PYTHONPATH="$stage" "$ROOT/venv/bin/python" "$stage/demo_v55.py" --output "$stage/demo-output" \
  | grep -q 'A2A_V55_OFFLINE_DEMO=PASS' || die "offline evidence verification failed"
"$ROOT/venv/bin/python" "$stage/patch-verified-brief-v5.5.1.py" "$TELEGRAM" \
  | grep -q 'VERIFIED_BRIEF_V551_PREFLIGHT=PASS; no writes' || die "Telegram verified-brief preflight failed"
grep -q 'cached_complete_workflows_available' "$stage/autonomous-curator-v5.py" || die "cached-stage recovery marker missing"
grep -q 'artifact_retries' "$stage/autonomous-curator-v5.py" || die "persistent retry marker missing"
grep -q 'verify_artifact' "$stage/task_status_v55.py" || die "fail-closed status verification marker missing"

echo "A2A_V551_EVIDENCE_PREFLIGHT=PASS"
echo "version=$VERSION"
echo "source_ref=$SOURCE_REF"
echo "plan=cached-503-recovery,provider-backoff,format-repair,receipt-reverification,verified-brief-only"
[[ "$MODE" == apply ]] || { echo "CHECK_ONLY: no installed files, services or live state changed"; exit 0; }

exec 9>/run/lock/tc-a2a-verifiable-evidence-v551.lock
flock -n 9 || die "another v5.5.1 evidence install is running"
stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$stamp"
install -d -m 0700 "$backup/prior"

backup_one() {
  local source="$1" name="$2"
  if [[ -e "$source" || -L "$source" ]]; then
    cp -a -- "$source" "$backup/prior/$name"
  else
    : >"$backup/$name.absent"
  fi
}
backup_one "$CURATOR" curator
backup_one "$EVIDENCE" evidence
backup_one "$STATUS" status
backup_one "$TELEGRAM" telegram
backup_one "$CLI" cli

manage_short=0
if [[ ! -e "$SHORT_CLI" && ! -L "$SHORT_CLI" ]]; then
  : >"$backup/short_cli.absent"
  manage_short=1
elif grep -q 'TECHNOCORE_A2A_V55_CLI' "$SHORT_CLI" 2>/dev/null; then
  cp -a -- "$SHORT_CLI" "$backup/prior/short_cli"
  manage_short=1
fi

cat >"$backup/MANIFEST" <<EOF
version=$VERSION
source_ref=$SOURCE_REF
host=$(hostname)
utc=$(date -u -Is)
managed_short_cli=$manage_short
preserved=identity,private-key,mailbox,cursors,nonces,peers,provenance,director-state,curator-state,retry-state,stage-cache,artifacts
rollback_policy=restore-v5.5-code-cli-telegram-only;never-rewind-live-state-or-artifacts
EOF
chmod 0600 "$backup/MANIFEST"

install -o root -g tcagent -m 0750 "$stage/autonomous-curator-v5.py" "$CURATOR"
install -o root -g tcagent -m 0640 "$stage/evidence_v55.py" "$EVIDENCE"
install -o root -g tcagent -m 0750 "$stage/task_status_v55.py" "$STATUS"
"$ROOT/venv/bin/python" "$stage/patch-verified-brief-v5.5.1.py" "$TELEGRAM" --apply \
  | grep -q 'VERIFIED_BRIEF_V551_PREFLIGHT=PASS; applied' || die "Telegram verified-brief apply failed"
telegram_sha="$(sha256sum "$TELEGRAM" | cut -d' ' -f1)"

cat >"$CLI" <<EOF
#!/usr/bin/env bash
# TECHNOCORE_A2A_V55_CLI
set -Eeuo pipefail
exec "$ROOT/venv/bin/python" "$STATUS" "\$@"
EOF
chmod 0755 "$CLI"
if [[ $manage_short -eq 1 ]]; then
  cat >"$SHORT_CLI" <<EOF
#!/usr/bin/env bash
# TECHNOCORE_A2A_V55_CLI
set -Eeuo pipefail
exec "$ROOT/venv/bin/python" "$STATUS" "\$@"
EOF
  chmod 0755 "$SHORT_CLI"
fi

cat >"$ROLLBACK" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP="$backup"
CURATOR="$CURATOR"
EVIDENCE="$EVIDENCE"
STATUS="$STATUS"
TELEGRAM="$TELEGRAM"
CLI="$CLI"
SHORT_CLI="$SHORT_CLI"
CURATOR_SERVICE="$CURATOR_SERVICE"
TELEGRAM_SERVICE="$TELEGRAM_SERVICE"

[[ \$(sha256sum "\$CURATOR" | cut -d' ' -f1) == "${HASHES[autonomous-curator-v5.py]}" ]] || { echo 'installed Curator changed; refusing rollback' >&2; exit 1; }
[[ \$(sha256sum "\$EVIDENCE" | cut -d' ' -f1) == "${HASHES[evidence_v55.py]}" ]] || { echo 'installed Evidence changed; refusing rollback' >&2; exit 1; }
[[ \$(sha256sum "\$STATUS" | cut -d' ' -f1) == "${HASHES[task_status_v55.py]}" ]] || { echo 'installed status changed; refusing rollback' >&2; exit 1; }
[[ \$(sha256sum "\$TELEGRAM" | cut -d' ' -f1) == "$telegram_sha" ]] || { echo 'installed Telegram changed; refusing rollback' >&2; exit 1; }

restore_one() {
  local destination="\$1" name="\$2"
  if [[ -e "\$BACKUP/prior/\$name" || -L "\$BACKUP/prior/\$name" ]]; then
    cp -a --remove-destination -- "\$BACKUP/prior/\$name" "\$destination"
  elif [[ -f "\$BACKUP/\$name.absent" ]]; then
    rm -f -- "\$destination"
  else
    echo "missing rollback metadata for \$name" >&2; exit 1
  fi
}
restore_one "\$CURATOR" curator
restore_one "\$EVIDENCE" evidence
restore_one "\$STATUS" status
restore_one "\$TELEGRAM" telegram
restore_one "\$CLI" cli
if grep -q '^managed_short_cli=1$' "\$BACKUP/MANIFEST"; then restore_one "\$SHORT_CLI" short_cli; fi
systemctl restart "\$CURATOR_SERVICE" "\$TELEGRAM_SERVICE"
systemctl is-active --quiet "\$CURATOR_SERVICE"
systemctl is-active --quiet "\$TELEGRAM_SERVICE"
echo 'A2A_V551_ROLLBACK=COMPLETE; code/CLI/Telegram restored; live state and artifacts preserved'
echo "backup=\$BACKUP"
EOF
chmod 0700 "$ROLLBACK"

systemctl restart "$CURATOR_SERVICE" "$TELEGRAM_SERVICE"
sleep 4
if ! systemctl is-active --quiet "$CURATOR_SERVICE" || ! systemctl is-active --quiet "$TELEGRAM_SERVICE"; then
  systemctl --no-pager --full status "$CURATOR_SERVICE" "$TELEGRAM_SERVICE" || true
  "$ROLLBACK" || true
  die "v5.5.1 service validation failed; rollback attempted"
fi

echo "A2A_V551_EVIDENCE_INSTALLED"
echo "curator_service=active"
echo "telegram_service=active"
echo "task_cli=technocore status --task-id wf-..."
echo "recovery=cached-stages,exponential-backoff,format-repair"
echo "verification=bundle-current-stages-artifact-sha256"
echo "brief=verified-artifacts-only"
echo "live_identity_state_artifacts=preserved"
echo "rollback=$ROLLBACK"
echo "backup=$backup"
