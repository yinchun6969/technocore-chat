#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

VERSION="5.5.3-action-center.2"
SOURCE_REF="83d4a740f8e04c76df977359252dc1a97448dec3"
SOURCE_BASE="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5"
ROOT="/opt/technocore-a2a"
RND="$ROOT/rnd-v5"
ENV_FILE="$ROOT/.env"
CURATOR="$RND/autonomous-curator-v5.py"
ACTION="$RND/human_action_center_v1.py"
TELEGRAM="$RND/telegram-control-v1.py"
CONTEXT="$RND/research_context_v32.py"
CURATOR_SERVICE="technocore-a2a-rnd-curator-v5.service"
TELEGRAM_SERVICE="technocore-a2a-telegram.service"
BACKUP_ROOT="/root/tc-a2a-human-action-v1-backups"
ROLLBACK="/usr/local/bin/tc-a2a-human-action-v1-rollback"
MODE="check"

declare -A HASHES=(
  [autonomous-curator-v5.py]="2042230cf6c72e75eafd8d163b2f972753053d3a0de49ace0a5aa08f3cfc6576"
  [human_action_center_v1.py]="85d3a0f5a9f43ff1b2d4e498fd0a7fa98af52923ec5fb23af383d7aff2e2bb82"
  [telegram-control-v1.py]="a8fb584e4d1b7e303e7eaed1a8528384b1a53d2edf312d73ee7ec188d043af30"
  [research_context_v32.py]="e99374699198a72b31f18e6958bbf02c248523b216d39c67a0f4b683db95589a"
  [patch-research-context-v3.2.py]="149e34478b37d53208111ac7b7815dc965e15da5799ac0c2f95f66711d025beb"
  [patch-verified-brief-v5.5.1.py]="770909c5646d47086b142a52f802711eaef158b4facc60a15a3766d771638294"
  [compose-human-action-telegram-v1.py]="0c8e70d11fb50b9f99d14d0dad8219706376a7536cf2f402668022485689597e"
  [test_human_action_center_v1.py]="dd9c249d54d42c28b256ed698fed012ca3ee121d50a50ee78875f11f89e51391"
  [test_telegram_notifications_v53.py]="dd2e1eae17059c9e2a84a02dd37de525db641dd313f4065417df14211844dc37"
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

[[ $EUID -eq 0 ]] || die "run as root on AI2AI"
for command in curl sha256sum flock systemctl; do command -v "$command" >/dev/null || die "$command is required"; done
[[ -f "$ENV_FILE" && -f "$CURATOR" && -f "$TELEGRAM" && -x "$ROOT/venv/bin/python" ]] || die "existing AI2AI v5.5.2 runtime not found"
set -a; source "$ENV_FILE"; set +a
[[ "${AGENT_NAME:-}" == ai2ai ]] || die "Human Action Center installs only on AI2AI"
id tcagent >/dev/null 2>&1 || die "tcagent user missing"

service_state() {
  local value
  value="$(systemctl is-active "$1" 2>/dev/null || true)"
  [[ "$value" == active || "$value" == inactive ]] || die "$1 is in unsupported state: $value"
  printf '%s' "$value"
}

stage="$(mktemp -d /root/tc-a2a-human-action-v1.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
chmod 0700 "$stage"
for file in "${!HASHES[@]}"; do
  curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 \
    "$SOURCE_BASE/$file" -o "$stage/$file"
  printf '%s  %s\n' "${HASHES[$file]}" "$stage/$file" | sha256sum -c -
done

"$ROOT/venv/bin/python" -m py_compile "$stage"/*.py
"$ROOT/venv/bin/python" "$stage/compose-human-action-telegram-v1.py" \
  "$stage/telegram-control-v1.py" --output "$stage/telegram-final.py" \
  | grep -q 'HUMAN_ACTION_TELEGRAM_COMPOSE=PASS'
mv "$stage/telegram-final.py" "$stage/telegram-control-v1.py"
"$ROOT/venv/bin/python" -m py_compile "$stage/telegram-control-v1.py"
"$ROOT/venv/bin/python" "$stage/test_human_action_center_v1.py"
"$ROOT/venv/bin/python" "$stage/test_telegram_notifications_v53.py"
grep -Fq 'def action_inbox()' "$stage/telegram-control-v1.py" || die "action inbox missing"
grep -Fq 'human_action_created' "$stage/autonomous-curator-v5.py" || die "Curator action projection missing"
grep -Fq 'auto_pr": False' "$stage/human_action_center_v1.py" || die "automatic PR boundary missing"

echo "A2A_HUMAN_ACTION_V1_PREFLIGHT=PASS"
echo "version=$VERSION"
echo "source_ref=$SOURCE_REF"
echo "alerts=P0/P1/P2-immediate;routine=daily-digest"
echo "authority=record-human-intent-only;auto-pr=false;server-write=false;public-post=false"
[[ "$MODE" == apply ]] || { echo "CHECK_ONLY: no installed files, services or live state changed"; exit 0; }

exec 9>/run/lock/tc-a2a-human-action-v1.lock
flock -n 9 || die "another Human Action Center install is running"
curator_was="$(service_state "$CURATOR_SERVICE")"
telegram_was="$(service_state "$TELEGRAM_SERVICE")"
stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$stamp"
install -d -m 0700 "$backup/prior"

backup_one() {
  local source="$1" name="$2"
  if [[ -e "$source" || -L "$source" ]]; then cp -a -- "$source" "$backup/prior/$name"
  else : >"$backup/$name.absent"; fi
}
backup_one "$CURATOR" curator
backup_one "$ACTION" action
backup_one "$TELEGRAM" telegram
backup_one "$CONTEXT" context
backup_one "$ROLLBACK" rollback_cli
cat >"$backup/MANIFEST" <<EOF
version=$VERSION
source_ref=$SOURCE_REF
curator_was=$curator_was
telegram_was=$telegram_was
preserved=did,private-key,mailbox,peers,cursors,nonces,provenance,stage-cache,retries,artifacts,human-action-queue,telegram-offsets,drafts
rollback_policy=code-only;never-rewind-or-delete-live-state
EOF
chmod 0600 "$backup/MANIFEST"

restore_one() {
  local destination="$1" name="$2"
  if [[ -e "$backup/prior/$name" || -L "$backup/prior/$name" ]]; then cp -a --remove-destination -- "$backup/prior/$name" "$destination"
  elif [[ -f "$backup/$name.absent" ]]; then rm -f -- "$destination"
  else return 1; fi
}
restore_services() {
  [[ "$curator_was" == active ]] && systemctl restart "$CURATOR_SERVICE" || systemctl stop "$CURATOR_SERVICE"
  [[ "$telegram_was" == active ]] && systemctl restart "$TELEGRAM_SERVICE" || systemctl stop "$TELEGRAM_SERVICE"
}
rollback_transaction() {
  local status="${1:-1}"
  trap - ERR
  set +e
  restore_one "$CURATOR" curator
  restore_one "$ACTION" action
  restore_one "$TELEGRAM" telegram
  restore_one "$CONTEXT" context
  restore_one "$ROLLBACK" rollback_cli
  restore_services
  echo "A2A_HUMAN_ACTION_V1_TRANSACTION_ROLLBACK=COMPLETE; status=$status; live state preserved" >&2
  exit "$status"
}
trap 'rollback_transaction $?' ERR

[[ "$curator_was" == active ]] && systemctl stop "$CURATOR_SERVICE"
[[ "$telegram_was" == active ]] && systemctl stop "$TELEGRAM_SERVICE"
install -o root -g tcagent -m 0750 "$stage/autonomous-curator-v5.py" "$CURATOR"
install -o root -g tcagent -m 0640 "$stage/human_action_center_v1.py" "$ACTION"
install -o root -g tcagent -m 0640 "$stage/research_context_v32.py" "$CONTEXT"
install -o root -g tcagent -m 0750 "$stage/telegram-control-v1.py" "$TELEGRAM"
canonical_telegram_sha="$(sha256sum "$TELEGRAM" | cut -d' ' -f1)"

cat >"$ROLLBACK" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP="$backup"
[[ $(sha256sum "$CURATOR" | cut -d' ' -f1) == "${HASHES[autonomous-curator-v5.py]}" ]] || { echo 'Curator drift; refusing rollback' >&2; exit 1; }
[[ $(sha256sum "$ACTION" | cut -d' ' -f1) == "${HASHES[human_action_center_v1.py]}" ]] || { echo 'Action module drift; refusing rollback' >&2; exit 1; }
[[ $(sha256sum "$TELEGRAM" | cut -d' ' -f1) == "$canonical_telegram_sha" ]] || { echo 'Telegram drift; refusing rollback' >&2; exit 1; }
restore_one() {
  local destination="\$1" name="\$2"
  if [[ -e "\$BACKUP/prior/\$name" || -L "\$BACKUP/prior/\$name" ]]; then cp -a --remove-destination -- "\$BACKUP/prior/\$name" "\$destination"
  elif [[ -f "\$BACKUP/\$name.absent" ]]; then rm -f -- "\$destination"
  else exit 1; fi
}
restore_one "$CURATOR" curator
restore_one "$ACTION" action
restore_one "$TELEGRAM" telegram
restore_one "$CONTEXT" context
if grep -q '^curator_was=active$' "\$BACKUP/MANIFEST"; then systemctl restart "$CURATOR_SERVICE"; else systemctl stop "$CURATOR_SERVICE"; fi
if grep -q '^telegram_was=active$' "\$BACKUP/MANIFEST"; then systemctl restart "$TELEGRAM_SERVICE"; else systemctl stop "$TELEGRAM_SERVICE"; fi
echo 'A2A_HUMAN_ACTION_V1_ROLLBACK=COMPLETE; code restored; live state preserved'
EOF
chmod 0700 "$ROLLBACK"
restore_services
[[ "$curator_was" != active ]] || systemctl is-active --quiet "$CURATOR_SERVICE"
[[ "$telegram_was" != active ]] || systemctl is-active --quiet "$TELEGRAM_SERVICE"
trap - ERR

echo "A2A_HUMAN_ACTION_V1_INSTALLED"
echo "curator_service=$curator_was"
echo "telegram_service=$telegram_was"
echo "telegram_commands=/inbox,/alert,/ack,/approve-pr,/snooze,/close"
echo "local_queue=$ROOT/rnd-v5-state/human-actions.json"
echo "live_identity_state_artifacts_action_queue=preserved"
echo "rollback=$ROLLBACK"
echo "backup=$backup"
