#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="5.2.0"
ROOT="/opt/technocore-a2a"
ENV_FILE="$ROOT/.env"
CURATOR="$ROOT/rnd-v5/autonomous-curator-v5.py"
SERVICE="technocore-a2a-rnd-curator-v5.service"
BACKUP_ROOT="/root/tc-a2a-curator-v52-backups"
SOURCE_REF="7f159d8c5129a30e801d8f8c121d4b369f1ee702"
SOURCE_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5/autonomous-curator-v5.py"
SOURCE_SHA256="fdef14baf1fad125b0c60c8e32dd254dc25309db44ef6ef7266933c59d5ab4c6"
MODE="check"

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
[[ -f "$ENV_FILE" && -f "$CURATOR" ]] || die "existing AI2AI Curator runtime not found"
[[ -x "$ROOT/venv/bin/python" ]] || die "AI2AI venv Python not found"
[[ "$(tr -d '\0' </proc/1/comm 2>/dev/null || true)" == systemd ]] || die "AI2AI Curator requires systemd"
set -a; source "$ENV_FILE"; set +a
[[ "${AGENT_NAME:-}" == ai2ai ]] || die "this host is not AI2AI"

stage="$(mktemp -d /root/tc-a2a-curator-v52.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
chmod 0700 "$stage"
curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 \
  "$SOURCE_URL" -o "$stage/autonomous-curator-v5.py"
printf '%s  %s\n' "$SOURCE_SHA256" "$stage/autonomous-curator-v5.py" | sha256sum -c -
"$ROOT/venv/bin/python" -m py_compile "$stage/autonomous-curator-v5.py"
grep -q 'curator-stage-cache.json' "$stage/autonomous-curator-v5.py" || die "stage cache marker missing"
grep -q 'room_cursors' "$stage/autonomous-curator-v5.py" || die "persistent cursor marker missing"
grep -q 'params\["since"\]' "$stage/autonomous-curator-v5.py" || die "incremental room-read marker missing"
grep -q 'save_cache(workflows, room_cursors)' "$stage/autonomous-curator-v5.py" || die "atomic checkpoint marker missing"

echo "A2A_CURATOR_V52_PREFLIGHT=PASS"
echo "source_ref=$SOURCE_REF"
echo "plan=verified-stage-cache,persistent-room-cursors,failed-read-no-advance,limit-200"
[[ "$MODE" == apply ]] || { echo "CHECK_ONLY: no files or services changed"; exit 0; }

stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$stamp"
install -d -m 0700 "$backup"
cp -a "$CURATOR" "$backup/autonomous-curator-v5.py"
sha256sum "$backup/autonomous-curator-v5.py" >"$backup/SHA256SUMS"
cat >"$backup/MANIFEST" <<EOF
version=$VERSION
host=$(hostname)
utc=$(date -u -Is)
preserved=identity,private-key,mailbox,cursor,peers,provenance,director-state,curator-state,artifacts
rollback_policy=restore-curator-code-only; retain-live-state-and-stage-cache
EOF
chmod 0600 "$backup/autonomous-curator-v5.py" "$backup/SHA256SUMS" "$backup/MANIFEST"

install -o root -g tcagent -m 0750 "$stage/autonomous-curator-v5.py" "$CURATOR"
cat >/usr/local/bin/tc-a2a-curator-v52-rollback <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP="$backup"
CURATOR="$CURATOR"
SERVICE="$SERVICE"
install -o root -g tcagent -m 0750 "\$BACKUP/autonomous-curator-v5.py" "\$CURATOR"
systemctl restart "\$SERVICE"
systemctl is-active "\$SERVICE"
echo "CURATOR_V52_ROLLED_BACK; code restored; state/cache/artifacts preserved"
echo "backup=\$BACKUP"
EOF
chmod 0700 /usr/local/bin/tc-a2a-curator-v52-rollback

systemctl restart "$SERVICE"
sleep 4
systemctl is-active --quiet "$SERVICE" || {
  systemctl --no-pager --full status "$SERVICE" || true
  die "Curator failed; run tc-a2a-curator-v52-rollback"
}

echo "A2A_CURATOR_V52_INSTALLED"
echo "service=active"
echo "existing_curator_state_artifacts=preserved"
echo "persistent_room_cursors=enabled"
echo "rollback=tc-a2a-curator-v52-rollback"
echo "backup=$backup"
