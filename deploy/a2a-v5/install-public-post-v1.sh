#!/usr/bin/env bash
set -Eeuo pipefail

REPO_RAW="https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-autonomous-rnd-v5/deploy/a2a-v5"
AI_ROOT="/opt/technocore-a2a"
COLLAB_ROOT="/opt/technocore-collab"
BACKUP_ROOT="/root/tc-a2a-public-post-backups"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ $EUID -eq 0 ]] || die "run as root"

NODE=""
ROOT=""
PY=""
RUNTIME_MARKER=""
RUNTIME_GUARD=""
if [[ -f "$AI_ROOT/.env" ]] && grep -Eq '^AGENT_NAME=ai2ai([[:space:]]|$)' "$AI_ROOT/.env"; then
  NODE="ai2ai"
  ROOT="$AI_ROOT"
  PY="$ROOT/venv/bin/python"
  RUNTIME_MARKER="WORKFLOW_V3_REVIEWER_BEGIN"
  RUNTIME_GUARD="A2A_WIRE_GUARD_V20"
elif [[ -f "$COLLAB_ROOT/.env" ]] && grep -Eq '^AGENT_NAME=love8([[:space:]]|$)' "$COLLAB_ROOT/.env"; then
  NODE="love8"
  ROOT="$COLLAB_ROOT"
  PY="$ROOT/venv/bin/python"
  RUNTIME_MARKER="WORKFLOW_V3_BEGIN"
  RUNTIME_GUARD="A2A_WIRE_GUARD_V33"
else
  die "existing AI2AI or Love8 runtime not found"
fi

RUNTIME="$ROOT/bin/agent.py"
if [[ "$NODE" == love8 ]]; then
  RUNTIME="$ROOT/bin/collab.py"
fi
SCRIPT="$ROOT/bin/public-post-v1.py"
WRAPPER="/usr/local/bin/tc-a2a-public-post"
SEND_WRAPPER="/usr/local/bin/tc-a2a-public-post-send"
SHORT_WRAPPER="/usr/local/bin/tc-public-post-send"
ROLLBACK="/usr/local/bin/tc-a2a-public-post-rollback"

[[ -f "$ROOT/.env" && -f "$RUNTIME" ]] || die "existing runtime is incomplete"
[[ -x "$PY" ]] || die "existing venv Python not found: $PY"
grep -q "$RUNTIME_MARKER" "$RUNTIME" || die "workflow marker missing: $RUNTIME_MARKER"
grep -q "$RUNTIME_GUARD" "$RUNTIME" || die "wire guard marker missing: $RUNTIME_GUARD"

stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$NODE/$stamp"
install -d -o root -g root -m 0700 "$backup"
manifest="$backup/MANIFEST"
: >"$manifest"

if [[ "$NODE" == ai2ai ]]; then
  ROOT_REL="opt/technocore-a2a"
else
  ROOT_REL="opt/technocore-collab"
fi

existing_count=0
for path in \
  "$ROOT_REL/bin/public-post-v1.py" \
  "usr/local/bin/tc-a2a-public-post" \
  "usr/local/bin/tc-a2a-public-post-send" \
  "usr/local/bin/tc-public-post-send" \
  "usr/local/bin/tc-a2a-public-post-rollback"
do
  if [[ -e "/$path" || -L "/$path" ]]; then
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
install -d -o root -g root -m 0700 "$ROOT/bin"
install -o root -g root -m 0700 "$tmp" "$SCRIPT"

{
  echo '#!/usr/bin/env bash'
  echo 'set -Eeuo pipefail'
  printf 'A2A_ROOT=%q exec %q %q "$@"\n' "$ROOT" "$PY" "$SCRIPT"
} >"$WRAPPER"
chown root:root "$WRAPPER"
chmod 0700 "$WRAPPER"

{
  echo '#!/usr/bin/env bash'
  echo 'set -Eeuo pipefail'
  printf 'A2A_ROOT=%q exec %q %q --send "$@"\n' "$ROOT" "$PY" "$SCRIPT"
} >"$SEND_WRAPPER"
chown root:root "$SEND_WRAPPER"
chmod 0700 "$SEND_WRAPPER"

{
  echo '#!/usr/bin/env bash'
  echo 'set -Eeuo pipefail'
  printf 'A2A_ROOT=%q exec %q %q --send "$@"\n' "$ROOT" "$PY" "$SCRIPT"
} >"$SHORT_WRAPPER"
chown root:root "$SHORT_WRAPPER"
chmod 0700 "$SHORT_WRAPPER"

{
  echo '#!/usr/bin/env bash'
  echo 'set -Eeuo pipefail'
  printf 'BACKUP=%q\n' "$backup"
  printf 'SCRIPT=%q\n' "$SCRIPT"
  printf 'WRAPPER=%q\n' "$WRAPPER"
  printf 'SEND_WRAPPER=%q\n' "$SEND_WRAPPER"
  printf 'SHORT_WRAPPER=%q\n' "$SHORT_WRAPPER"
  printf 'ROLLBACK=%q\n' "$ROLLBACK"
  echo
  echo 'rm -f "$SCRIPT" "$WRAPPER" "$SEND_WRAPPER" "$SHORT_WRAPPER" "$ROLLBACK"'
  echo 'if [[ -f "$BACKUP/prechange.tgz" ]]; then'
  echo '  tar -C / -xzf "$BACKUP/prechange.tgz"'
  echo 'fi'
  echo 'echo "public-post addon rolled back"'
  echo 'echo "existing DID, private key, mailbox, nonce ledger, cursor, provenance, and services were not changed"'
  echo 'echo "backup=$BACKUP"'
} >"$ROLLBACK"
chown root:root "$ROLLBACK"
chmod 0700 "$ROLLBACK"
rm -f "$tmp"
trap - EXIT

echo "=== PUBLIC CHAT POST v1.1 READY ==="
echo "node=$NODE"
echo "component=$SCRIPT"
echo "preview_cli=$WRAPPER"
echo "one_line_send=$SEND_WRAPPER"
echo "short_send=$SHORT_WRAPPER"
echo "default_room=arxiv-jam"
echo "backup=$backup"
echo "rollback=tc-a2a-public-post-rollback"
echo "service_restart=none"
echo "default_mode=preview; direct send requires the explicit *-send command or --send"
