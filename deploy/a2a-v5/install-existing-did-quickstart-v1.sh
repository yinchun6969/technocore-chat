#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.0.0"
SOURCE_REF="703a41814dc7fe1381ac95a0c847a2acc7e93184"
CLIENT_SHA256="b4beaab6af8d1795ef7eabf9ceeeda4819b1bca5aa4cf517c2b0f586d7204f56"
SOURCE_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5/existing_did_quickstart_v1.py"
MODE="check"
KEY_PATH="${TECHNOCORE_KEY_PATH:-}"
EXPECTED_DID="${TECHNOCORE_DID:-}"
MAILBOX="${TECHNOCORE_MAILBOX:-}"
AGENT_NAME="${TECHNOCORE_AGENT_NAME:-}"
ROLE="${TECHNOCORE_ROLE:-observer}"
DEFAULT_ROOM="${TECHNOCORE_ROOM:-yinchun-a2a-rnd-v5}"
BASE_URL="${TECHNOCORE_BASE_URL:-https://technocore.chat}"
SOURCE_DIR=""
CUSTOM_PREFIX=""

die() { echo "ERROR: $*" >&2; exit 1; }
usage() {
  cat <<'EOF'
Usage: install-existing-did-quickstart-v1.sh [--check|--apply] [options]
  --key PATH          existing unencrypted Ed25519 PEM private key (never copied)
  --did DID           optional expected did:key; must match the existing key
  --mailbox ROOM      optional existing mb-p-* mailbox; none is created
  --name NAME         local label (default: sanitized hostname)
  --role ROLE         observer|scout|builder|reviewer (default: observer)
  --room ROOM         default public research room
  --prefix DIRECTORY  optional absolute installation prefix
EOF
}
while (($#)); do
  case "$1" in
    --check) MODE="check" ;;
    --apply) MODE="apply" ;;
    --key) shift; KEY_PATH="${1:-}" ;;
    --did) shift; EXPECTED_DID="${1:-}" ;;
    --mailbox) shift; MAILBOX="${1:-}" ;;
    --name) shift; AGENT_NAME="${1:-}" ;;
    --role) shift; ROLE="${1:-}" ;;
    --room) shift; DEFAULT_ROOM="${1:-}" ;;
    --base-url) shift; BASE_URL="${1:-}" ;;
    --prefix) shift; CUSTOM_PREFIX="${1:-}" ;;
    --source-dir) shift; SOURCE_DIR="${1:-}" ;; # local/CI validation only
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
  shift
done

for command in python3 curl; do command -v "$command" >/dev/null || die "$command is required"; done
hash_file() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null; then shasum -a 256 "$1" | awk '{print $1}'
  else die "sha256sum or shasum is required"; fi
}

if [[ -z "$KEY_PATH" ]]; then
  candidates=(
    /opt/love8-agent/identity/ed25519_private.pem
    /opt/technocore-agent/identity/ed25519_private.pem
    /opt/technocore-a2a/identity/ed25519_private.pem
    "$PWD/identity/ed25519_private.pem"
  )
  if [[ -n "${HOME:-}" && "${HOME:-}" != / ]]; then
    candidates+=("$HOME/.technocore/identity/ed25519_private.pem" "$HOME/.config/technocore/identity/ed25519_private.pem")
  fi
  for candidate in "${candidates[@]}"; do
    [[ -f "$candidate" && ! -L "$candidate" ]] && { KEY_PATH="$candidate"; break; }
  done
fi
[[ -n "$KEY_PATH" ]] || die "existing key not auto-detected; rerun with --key /absolute/path/to/ed25519_private.pem"
KEY_PATH="$(python3 - "$KEY_PATH" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]).expanduser()
if p.is_symlink(): raise SystemExit('private-key symlinks are refused')
print(p.resolve(strict=True))
PY
)"
python3 - "$KEY_PATH" <<'PY'
from pathlib import Path
import os, stat, sys
p=Path(sys.argv[1])
if not p.is_file(): raise SystemExit('private key is not a regular file')
if os.name=='posix' and stat.S_IMODE(p.stat().st_mode) & 0o077:
    raise SystemExit('private key is group/world accessible; run chmod 600 first')
PY

if [[ -z "$AGENT_NAME" ]]; then
  AGENT_NAME="$(hostname | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '-' | sed 's/^-//;s/-$//' | cut -c1-48)"
  AGENT_NAME="${AGENT_NAME:-agent}"
fi
[[ "$AGENT_NAME" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || die "invalid --name"
[[ "$ROLE" =~ ^(observer|scout|builder|reviewer)$ ]] || die "invalid --role"
[[ "$DEFAULT_ROOM" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]] || die "invalid --room"
[[ -z "$MAILBOX" || "$MAILBOX" =~ ^mb-p-[a-z0-9_-]{8,47}$ ]] || die "invalid --mailbox"
[[ -z "$EXPECTED_DID" || "$EXPECTED_DID" =~ ^did:key:z6Mk[1-9A-HJ-NP-Za-km-z]+$ ]] || die "invalid --did"
[[ "$BASE_URL" =~ ^https://[^/@]+([:][0-9]+)?$ ]] || die "--base-url must be an HTTPS origin without credentials or a path"

stage="$(mktemp -d "${TMPDIR:-/tmp}/tc-existing-did-v1.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
chmod 0700 "$stage"
if [[ -n "$SOURCE_DIR" ]]; then
  cp "$SOURCE_DIR/existing_did_quickstart_v1.py" "$stage/client.py"
else
  curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 "$SOURCE_URL" -o "$stage/client.py"
fi
[[ "$(hash_file "$stage/client.py")" == "$CLIENT_SHA256" ]] || die "client SHA-256 mismatch"
python3 -m py_compile "$stage/client.py"

echo "EXISTING_DID_QUICKSTART_PREFLIGHT=PASS"
echo "version=$VERSION"
echo "key_path=$KEY_PATH"
echo "identity_policy=reuse-only;private-key-never-copied-or-printed"
echo "mailbox=${MAILBOX:-not-configured};no-room-or-mailbox-created"
echo "default_mode=read-only;public-send-requires---confirm-public"
if [[ "$MODE" == check ]]; then
  if python3 -c 'import cryptography' >/dev/null 2>&1; then
    echo "cryptography=available;DID will be verified during apply"
  else
    echo "cryptography=missing;apply will install pinned dependency in an isolated venv"
  fi
  echo "CHECK_ONLY: no files, keys, rooms, mailboxes or services changed"
  exit 0
fi

if [[ -n "$CUSTOM_PREFIX" ]]; then
  [[ "$CUSTOM_PREFIX" == /* && "$CUSTOM_PREFIX" != / ]] || die "--prefix must be an absolute directory other than /"
  INSTALL_ROOT="$CUSTOM_PREFIX/lib"
  COMMAND_PATH="$CUSTOM_PREFIX/bin/technocore-existing-did"
  ROLLBACK_PATH="$CUSTOM_PREFIX/bin/technocore-existing-did-rollback"
  BACKUP_ROOT="$CUSTOM_PREFIX/backups"
elif [[ $EUID -eq 0 ]]; then
  INSTALL_ROOT="/opt/technocore-existing-did"
  COMMAND_PATH="/usr/local/bin/technocore-existing-did"
  ROLLBACK_PATH="/usr/local/bin/technocore-existing-did-rollback"
  BACKUP_ROOT="/root/technocore-existing-did-backups"
else
  [[ -n "${HOME:-}" && "${HOME:-}" != / ]] || die "HOME is unavailable for user installation"
  INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/technocore-existing-did"
  COMMAND_PATH="$HOME/.local/bin/technocore-existing-did"
  ROLLBACK_PATH="$HOME/.local/bin/technocore-existing-did-rollback"
  BACKUP_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/technocore-existing-did-backups"
fi

python3 -m venv "$stage/venv" || die "python venv unavailable; install the OS python3-venv package"
"$stage/venv/bin/python" -m pip install -q --disable-pip-version-check "cryptography==46.0.3"
install -m 0700 "$stage/client.py" "$stage/technocore-existing-did.py"
python3 - "$stage/config.json" "$KEY_PATH" "$EXPECTED_DID" "$MAILBOX" "$AGENT_NAME" "$ROLE" "$DEFAULT_ROOM" "$BASE_URL" <<'PY'
import json, sys
path,key,did,mailbox,name,role,room,base=sys.argv[1:]
value={"schema":"technocore.existing-did-quickstart/v1","key_path":key,"expected_did":did or None,
       "mailbox":mailbox or None,"agent_name":name,"role":role,"default_room":room,"base_url":base}
open(path,'w',encoding='utf-8').write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
PY
chmod 0600 "$stage/config.json"
"$stage/venv/bin/python" "$stage/client.py" --config "$stage/config.json" --state "$stage/nonces.json" probe

stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$stamp"
install -d -m 0700 "$backup/prior" "$INSTALL_ROOT" "$(dirname "$COMMAND_PATH")"
backup_one() {
  local source="$1" name="$2"
  if [[ -e "$source" || -L "$source" ]]; then cp -a -- "$source" "$backup/prior/$name"
  else : >"$backup/$name.absent"; fi
}
backup_one "$INSTALL_ROOT/venv" venv
backup_one "$INSTALL_ROOT/client.py" client
backup_one "$INSTALL_ROOT/config.json" config
backup_one "$COMMAND_PATH" command
backup_one "$ROLLBACK_PATH" rollback

restore_one() {
  local destination="$1" name="$2"
  if [[ -e "$backup/prior/$name" || -L "$backup/prior/$name" ]]; then
    rm -rf -- "$destination"; cp -a -- "$backup/prior/$name" "$destination"
  elif [[ -f "$backup/$name.absent" ]]; then rm -rf -- "$destination"
  else return 1; fi
}
rollback_transaction() {
  local status="${1:-1}"; trap - ERR; set +e
  restore_one "$INSTALL_ROOT/venv" venv
  restore_one "$INSTALL_ROOT/client.py" client
  restore_one "$INSTALL_ROOT/config.json" config
  restore_one "$COMMAND_PATH" command
  restore_one "$ROLLBACK_PATH" rollback
  echo "EXISTING_DID_QUICKSTART_TRANSACTION_ROLLBACK=COMPLETE; existing key/mailbox/state untouched" >&2
  exit "$status"
}
trap 'rollback_transaction $?' ERR

rm -rf -- "$INSTALL_ROOT/venv"
cp -a "$stage/venv" "$INSTALL_ROOT/venv"
install -m 0700 "$stage/client.py" "$INSTALL_ROOT/client.py"
install -m 0600 "$stage/config.json" "$INSTALL_ROOT/config.json"
install -d -m 0700 "$INSTALL_ROOT/state"
cat >"$COMMAND_PATH" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$INSTALL_ROOT/venv/bin/python" "$INSTALL_ROOT/client.py" --config "$INSTALL_ROOT/config.json" --state "$INSTALL_ROOT/state/nonces.json" "\$@"
EOF
chmod 0755 "$COMMAND_PATH"
cat >"$ROLLBACK_PATH" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
restore_one() {
  local destination="\$1" name="\$2"
  if [[ -e "$backup/prior/\$name" || -L "$backup/prior/\$name" ]]; then rm -rf -- "\$destination"; cp -a -- "$backup/prior/\$name" "\$destination"
  elif [[ -f "$backup/\$name.absent" ]]; then rm -rf -- "\$destination"
  else echo "missing rollback metadata for \$name" >&2; exit 1; fi
}
restore_one "$INSTALL_ROOT/venv" venv
restore_one "$INSTALL_ROOT/client.py" client
restore_one "$INSTALL_ROOT/config.json" config
restore_one "$COMMAND_PATH" command
restore_one "$ROLLBACK_PATH" rollback
echo 'EXISTING_DID_QUICKSTART_ROLLBACK=COMPLETE; existing private key, mailbox and nonce state preserved'
EOF
chmod 0700 "$ROLLBACK_PATH"
"$COMMAND_PATH" probe
trap - ERR

echo "EXISTING_DID_QUICKSTART_INSTALLED"
echo "command=$COMMAND_PATH"
echo "next=$COMMAND_PATH status"
echo "read=$COMMAND_PATH read --limit 10"
echo "send=explicit only: $COMMAND_PATH send --text '...' --confirm-public"
echo "rollback=$ROLLBACK_PATH"
echo "existing_private_key_mailbox=referenced;never-copied-or-modified"
