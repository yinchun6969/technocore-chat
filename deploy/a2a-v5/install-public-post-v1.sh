#!/usr/bin/env bash
set -Eeuo pipefail

REPO_RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v5/deploy/a2a-v5"
ROOT="/opt/technocore-a2a"
PY="$ROOT/venv/bin/python"
SCRIPT="$ROOT/bin/public-post-v1.py"
WRAPPER="/usr/local/bin/tc-a2a-public-post"
ROLLBACK="/usr/local/bin/tc-a2a-public-post-rollback"
BACKUP_ROOT="/root/tc-a2a-public-post-backups/ai2ai"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ $EUID -eq 0 ]] || die "run as root"
[[ -f "$ROOT/.env" && -f "$ROOT/bin/agent.py" ]] || die "existing AI2AI runtime not found"
[[ -x "$PY" ]] || die "existing AI2AI venv Python not found: $PY"
grep -Eq '^AGENT_NAME=ai2ai([[:space:]]|$)' "$ROOT/.env" || die "this host is not AI2AI"
grep -q 'WORKFLOW_V3_REVIEWER_BEGIN' "$ROOT/bin/agent.py" || die "AI2AI Reviewer v3 marker missing"
grep -q 'A2A_WIRE_GUARD_V20' "$ROOT/bin/agent.py" || die "AI2AI wire guard marker missing"

stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$stamp"
install -d -o root -g root -m 0700 "$backup"
manifest="$backup/MANIFEST"
: >"$manifest"

existing_count=0
for path in \
  opt/technocore-a2a/bin/public-post-v1.py \
  usr/local/bin/tc-a2a-public-post \
  usr/local/bin/tc-a2a-public-post-rollback
do
  if [[ -e "/$path" ]]; then
    existing_count=$((existing_count + 1))
    printf '%s\n' "$path" >>"$manifest"
  fi
done
if ((existing_count > 0)); then
  tar -C / -czf "$backup/prechange.tgz" --files-from "$manifest"
else
  tar -C / -czf "$backup/prechange.tgz" --files-from /dev/null
fi
sha256sum "$backup/prechange.tgz" >"$backup/SHA256SUMS"
chmod 0600 "$backup/prechange.tgz" "$backup/SHA256SUMS" "$manifest"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fL --retry 5 --retry-delay 2 "$REPO_RAW/public-post-v1.py" -o "$tmp"
"$PY" -m py_compile "$tmp"
install -d -o root -g tcagent -m 0750 "$ROOT/bin"
install -o root -g tcagent -m 0750 "$tmp" "$SCRIPT"

{
  echo '#!/usr/bin/env bash'
  echo 'set -Eeuo pipefail'
  printf 'exec %q %q "$@"\n' "$PY" "$SCRIPT"
} >"$WRAPPER"
chown root:root "$WRAPPER"
chmod 0700 "$WRAPPER"

{
  echo '#!/usr/bin/env bash'
  echo 'set -Eeuo pipefail'
  printf 'BACKUP=%q\n' "$backup"
  printf 'SCRIPT=%q\n' "$SCRIPT"
  printf 'WRAPPER=%q\n' "$WRAPPER"
  printf 'ROLLBACK=%q\n' "$ROLLBACK"
  echo
  echo 'rm -f "$SCRIPT" "$WRAPPER" "$ROLLBACK"'
  echo 'if [[ -f "$BACKUP/prechange.tgz" ]]; then'
  echo '  tar -C / -xzf "$BACKUP/prechange.tgz"'
  echo 'fi'
  echo 'echo "AI2AI public-post addon rolled back"'
  echo 'echo "existing DID, private key, mailbox, nonce ledger, cursor, provenance, and services were not changed"'
  echo 'echo "backup=$BACKUP"'
} >"$ROLLBACK"
chown root:root "$ROLLBACK"
chmod 0700 "$ROLLBACK"
rm -f "$tmp"
trap - EXIT

echo "=== AI2AI PUBLIC CHAT POST v1 READY ==="
echo "component=$SCRIPT"
echo "cli=$WRAPPER"
echo "backup=$backup"
echo "rollback=tc-a2a-public-post-rollback"
echo "service_restart=none"
echo "mode=preview by default; explicit --send is required to publish"
