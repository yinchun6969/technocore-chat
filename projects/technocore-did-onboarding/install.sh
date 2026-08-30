#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.0.0"
SOURCE_REF="6c90b94cc74737c400351b8a689018768d219b33"
WIZARD_SHA256="b5ad6453bc9a63b05d5b233525f5fe7595d3fb9456334c0e16aa553bf95d0da3"
SOURCE_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/projects/technocore-did-onboarding/onboarding.py"
MODE="check"
RUN_WIZARD=1
LANGUAGE=""
CUSTOM_PREFIX=""
SOURCE_DIR=""

die() { echo "ERROR: $*" >&2; exit 1; }
usage() {
  cat <<'EOF'
Usage: install.sh [--check|--apply] [--lang zh|en] [--no-wizard]
                  [--prefix /absolute/directory]

Default mode is --check and changes nothing. --apply installs the local CLI and
starts the bilingual wizard. The wizard imports an existing DID key by path or
creates a new Ed25519 key locally with mode 0600.
EOF
}
while (($#)); do
  case "$1" in
    --check) MODE="check" ;;
    --apply) MODE="apply" ;;
    --lang) shift; LANGUAGE="${1:-}" ;;
    --no-wizard) RUN_WIZARD=0 ;;
    --prefix) shift; CUSTOM_PREFIX="${1:-}" ;;
    --source-dir) shift; SOURCE_DIR="${1:-}" ;; # local/CI validation only
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
  shift
done
[[ -z "$LANGUAGE" || "$LANGUAGE" =~ ^(zh|en)$ ]] || die "--lang must be zh or en"
for command in python3 curl; do command -v "$command" >/dev/null || die "$command is required"; done
hash_file() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null; then shasum -a 256 "$1" | awk '{print $1}'
  else die "sha256sum or shasum is required"; fi
}

stage="$(mktemp -d "${TMPDIR:-/tmp}/technocore-onboarding.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
chmod 0700 "$stage"
if [[ -n "$SOURCE_DIR" ]]; then
  cp "$SOURCE_DIR/onboarding.py" "$stage/onboarding.py"
else
  curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 "$SOURCE_URL" -o "$stage/onboarding.py"
fi
[[ "$(hash_file "$stage/onboarding.py")" == "$WIZARD_SHA256" ]] || die "wizard SHA-256 mismatch"
python3 -m py_compile "$stage/onboarding.py"

echo "TECHNOCORE_DID_ONBOARDING_PREFLIGHT=PASS"
echo "version=$VERSION"
echo "source_ref=$SOURCE_REF"
echo "modes=import-existing-did,create-local-did"
echo "room=use-existing-or-explicitly-create-owned-room"
echo "private_key=local-only;0600;never-uploaded-or-printed"
if [[ "$MODE" == check ]]; then
  echo "CHECK_ONLY: no files, keys, rooms, messages or services changed"
  exit 0
fi

if [[ -n "$CUSTOM_PREFIX" ]]; then
  [[ "$CUSTOM_PREFIX" == /* && "$CUSTOM_PREFIX" != / ]] || die "--prefix must be absolute and not /"
  INSTALL_ROOT="$CUSTOM_PREFIX/lib"
  COMMAND_PATH="$CUSTOM_PREFIX/bin/technocore-onboard"
  ROLLBACK_PATH="$CUSTOM_PREFIX/bin/technocore-onboard-rollback"
  BACKUP_ROOT="$CUSTOM_PREFIX/backups"
elif [[ $EUID -eq 0 ]]; then
  INSTALL_ROOT="/opt/technocore-did-onboarding"
  COMMAND_PATH="/usr/local/bin/technocore-onboard"
  ROLLBACK_PATH="/usr/local/bin/technocore-onboard-rollback"
  BACKUP_ROOT="/root/technocore-did-onboarding-backups"
else
  [[ -n "${HOME:-}" && "${HOME:-}" != / ]] || die "HOME is unavailable for user installation"
  INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/technocore-did-onboarding"
  COMMAND_PATH="$HOME/.local/bin/technocore-onboard"
  ROLLBACK_PATH="$HOME/.local/bin/technocore-onboard-rollback"
  BACKUP_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/technocore-did-onboarding-backups"
fi

python3 -m venv "$stage/venv" || die "python venv unavailable; install the OS python3-venv package"
"$stage/venv/bin/python" -m pip install -q --disable-pip-version-check "cryptography==46.0.3"

stamp="$(date -u +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$stamp"
install -d -m 0700 "$backup/prior" "$INSTALL_ROOT" "$INSTALL_ROOT/state" "$(dirname "$COMMAND_PATH")"
backup_one() {
  local source="$1" name="$2"
  if [[ -e "$source" || -L "$source" ]]; then cp -a -- "$source" "$backup/prior/$name"
  else : >"$backup/$name.absent"; fi
}
backup_one "$INSTALL_ROOT/venv" venv
backup_one "$INSTALL_ROOT/onboarding.py" wizard
backup_one "$INSTALL_ROOT/config.json" config
backup_one "$COMMAND_PATH" command
backup_one "$ROLLBACK_PATH" rollback

restore_one() {
  local destination="$1" name="$2"
  if [[ -e "$backup/prior/$name" || -L "$backup/prior/$name" ]]; then rm -rf -- "$destination"; cp -a -- "$backup/prior/$name" "$destination"
  elif [[ -f "$backup/$name.absent" ]]; then rm -rf -- "$destination"
  else return 1; fi
}
rollback_transaction() {
  local status="${1:-1}"; trap - ERR; set +e
  failed=0
  restore_one "$INSTALL_ROOT/venv" venv || failed=1
  restore_one "$INSTALL_ROOT/onboarding.py" wizard || failed=1
  restore_one "$INSTALL_ROOT/config.json" config || failed=1
  restore_one "$COMMAND_PATH" command || failed=1
  restore_one "$ROLLBACK_PATH" rollback || failed=1
  if [[ $failed -ne 0 ]]; then echo "TRANSACTION_ROLLBACK=INCOMPLETE" >&2; exit 70; fi
  echo "TRANSACTION_ROLLBACK=COMPLETE; identity and nonce state preserved" >&2
  exit "$status"
}
trap 'rollback_transaction $?' ERR

rm -rf -- "$INSTALL_ROOT/venv"
cp -a "$stage/venv" "$INSTALL_ROOT/venv"
install -m 0700 "$stage/onboarding.py" "$INSTALL_ROOT/onboarding.py"
cat >"$COMMAND_PATH" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$INSTALL_ROOT/venv/bin/python" "$INSTALL_ROOT/onboarding.py" --config "$INSTALL_ROOT/config.json" --state "$INSTALL_ROOT/state/nonces.json" "\$@"
EOF
chmod 0755 "$COMMAND_PATH"
cat >"$ROLLBACK_PATH" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
failed=0
restore_one() {
  local destination="\$1" name="\$2"
  if [[ -e "$backup/prior/\$name" || -L "$backup/prior/\$name" ]]; then rm -rf -- "\$destination"; cp -a -- "$backup/prior/\$name" "\$destination"
  elif [[ -f "$backup/\$name.absent" ]]; then rm -rf -- "\$destination"
  else return 1; fi
}
restore_one "$INSTALL_ROOT/venv" venv || failed=1
restore_one "$INSTALL_ROOT/onboarding.py" wizard || failed=1
restore_one "$INSTALL_ROOT/config.json" config || failed=1
restore_one "$COMMAND_PATH" command || failed=1
restore_one "$ROLLBACK_PATH" rollback || failed=1
[[ \$failed -eq 0 ]] || { echo 'ROLLBACK=INCOMPLETE' >&2; exit 70; }
echo 'ROLLBACK=COMPLETE; local identity/private key and nonce state preserved'
EOF
chmod 0700 "$ROLLBACK_PATH"

if [[ $RUN_WIZARD -eq 1 ]]; then
  [[ -t 0 ]] || die "interactive wizard requires a terminal; rerun --apply in a terminal or use --no-wizard"
  wizard_args=(wizard)
  [[ -n "$LANGUAGE" ]] && wizard_args+=(--lang "$LANGUAGE")
  "$COMMAND_PATH" "${wizard_args[@]}"
fi
trap - ERR

echo "TECHNOCORE_DID_ONBOARDING_INSTALLED"
echo "command=$COMMAND_PATH"
echo "wizard=$COMMAND_PATH wizard"
echo "probe=$COMMAND_PATH probe"
echo "rollback=$ROLLBACK_PATH"
echo "identity_private_key_nonce_state=preserved-by-rollback"
