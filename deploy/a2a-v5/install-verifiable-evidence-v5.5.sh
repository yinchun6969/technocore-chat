#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="5.5.0"
SOURCE_REF="bf5fa73694dd42611cbd2f0aaadbf78a30a397d5"
SOURCE_BASE="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5"
ROOT="/opt/technocore-a2a"
ENV_FILE="$ROOT/.env"
RND="$ROOT/rnd-v5"
CURATOR="$RND/autonomous-curator-v5.py"
EVIDENCE="$RND/evidence_v55.py"
STATUS="$RND/task_status_v55.py"
SERVICE="technocore-a2a-rnd-curator-v5.service"
BACKUP_ROOT="/root/tc-a2a-verifiable-evidence-v55-backups"
ROLLBACK="/usr/local/bin/tc-a2a-verifiable-evidence-v55-rollback"
CLI="/usr/local/bin/tc-a2a-task-status"
SHORT_CLI="/usr/local/bin/technocore"
MODE="check"

declare -A HASHES=(
  [autonomous-curator-v5.py]="de5a95850324f478ce32def3dd2f164ecab2fd129e4b373532a8587e46a96cd1"
  [evidence_v55.py]="64e361389ff7a247f897f6536de89c640096c5e01b3d236e96d43a5ea1664b9e"
  [task_status_v55.py]="d22504ec648ca2a791d0353a14e4c487ca4535a6c8f08ad3a820988be62faa84"
  [demo_v55.py]="a10e20e68095eeb0d035dfb5139bf00e71055332b148b9c9fd63e8b39b63171f"
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
for command in curl sha256sum python3 flock; do command -v "$command" >/dev/null || die "$command is required"; done
[[ -f "$ENV_FILE" && -f "$CURATOR" && -x "$ROOT/venv/bin/python" ]] || die "existing AI2AI v5 runtime not found"
[[ "$(tr -d '\0' </proc/1/comm 2>/dev/null || true)" == systemd ]] || die "AI2AI v5.5 requires systemd"
set -a; source "$ENV_FILE"; set +a
[[ "${AGENT_NAME:-}" == ai2ai ]] || die "this installer runs only on the AI2AI Reviewer/Curator node"
id tcagent >/dev/null 2>&1 || die "tcagent user missing"

stage="$(mktemp -d /root/tc-a2a-evidence-v55.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
chmod 0700 "$stage"
for file in autonomous-curator-v5.py evidence_v55.py task_status_v55.py demo_v55.py; do
  curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 \
    "$SOURCE_BASE/$file" -o "$stage/$file"
  printf '%s  %s\n' "${HASHES[$file]}" "$stage/$file" | sha256sum -c -
done
"$ROOT/venv/bin/python" -m py_compile \
  "$stage/autonomous-curator-v5.py" "$stage/evidence_v55.py" \
  "$stage/task_status_v55.py" "$stage/demo_v55.py"
PYTHONPATH="$stage" "$ROOT/venv/bin/python" "$stage/demo_v55.py" --output "$stage/demo-output" \
  | grep -q 'A2A_V55_OFFLINE_DEMO=PASS' || die "offline evidence verification failed"
grep -q 'technocore.a2a/evidence-bundle-v1' "$stage/evidence_v55.py" || die "Evidence schema marker missing"
grep -q 'room_sequence_gap' "$stage/autonomous-curator-v5.py" || die "cursor gap guard missing"
grep -q 'evidence_merkle_root' "$stage/task_status_v55.py" || die "task status Merkle marker missing"

echo "A2A_V55_EVIDENCE_PREFLIGHT=PASS"
echo "version=$VERSION"
echo "source_ref=$SOURCE_REF"
echo "plan=strict-evidence-schema,deterministic-merkle,saga-checkpoints,replay-guard,structured-task-status"
[[ "$MODE" == apply ]] || { echo "CHECK_ONLY: no installed files, services or live state changed"; exit 0; }

exec 9>/run/lock/tc-a2a-verifiable-evidence-v55.lock
flock -n 9 || die "another v5.5 evidence install is running"
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
preserved=identity,private-key,mailbox,cursors,nonces,peers,provenance,director-state,curator-state,stage-cache,artifacts
rollback_policy=restore-v5.5-code-and-cli-only;never-rewind-live-state
EOF
chmod 0600 "$backup/MANIFEST"

install -o root -g tcagent -m 0750 "$stage/autonomous-curator-v5.py" "$CURATOR"
install -o root -g tcagent -m 0640 "$stage/evidence_v55.py" "$EVIDENCE"
install -o root -g tcagent -m 0750 "$stage/task_status_v55.py" "$STATUS"
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
ROOT="$ROOT"
CURATOR="$CURATOR"
EVIDENCE="$EVIDENCE"
STATUS="$STATUS"
CLI="$CLI"
SHORT_CLI="$SHORT_CLI"
SERVICE="$SERVICE"

expected_curator="${HASHES[autonomous-curator-v5.py]}"
expected_evidence="${HASHES[evidence_v55.py]}"
expected_status="${HASHES[task_status_v55.py]}"
[[ \$(sha256sum "\$CURATOR" | cut -d' ' -f1) == "\$expected_curator" ]] || { echo 'installed Curator changed; refusing rollback' >&2; exit 1; }
[[ \$(sha256sum "\$EVIDENCE" | cut -d' ' -f1) == "\$expected_evidence" ]] || { echo 'installed Evidence module changed; refusing rollback' >&2; exit 1; }
[[ \$(sha256sum "\$STATUS" | cut -d' ' -f1) == "\$expected_status" ]] || { echo 'installed status CLI changed; refusing rollback' >&2; exit 1; }

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
restore_one "\$CLI" cli
if grep -q '^managed_short_cli=1$' "\$BACKUP/MANIFEST"; then
  restore_one "\$SHORT_CLI" short_cli
fi
systemctl restart "\$SERVICE"
systemctl is-active --quiet "\$SERVICE"
echo 'A2A_V55_EVIDENCE_ROLLBACK=COMPLETE; code/CLI restored; live state and artifacts preserved'
echo "backup=\$BACKUP"
EOF
chmod 0700 "$ROLLBACK"

systemctl restart "$SERVICE"
sleep 4
if ! systemctl is-active --quiet "$SERVICE"; then
  systemctl --no-pager --full status "$SERVICE" || true
  "$ROLLBACK" || true
  die "v5.5 Curator failed; rollback attempted"
fi

echo "A2A_V55_EVIDENCE_INSTALLED"
echo "service=active"
echo "cli=$CLI status --task-id wf-..."
if [[ $manage_short -eq 1 ]]; then
  echo "short_cli=technocore status --task-id wf-..."
else
  echo "short_cli=not-replaced; existing unrelated /usr/local/bin/technocore preserved"
fi
echo "evidence_schema=technocore.a2a/evidence-bundle-v1"
echo "live_identity_state_artifacts=preserved"
echo "rollback=$ROLLBACK"
echo "backup=$backup"
