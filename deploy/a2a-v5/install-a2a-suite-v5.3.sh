#!/usr/bin/env bash
set -Eeuo pipefail

# Unified, role-aware upgrade for the already installed Technocore three-agent
# stack. Component installers remain independently rollback-safe.
VERSION="5.3.0"
SOURCE_REF="30fb4c1b0bb6cd57f2abc32d477ed43ab6707e69"
SOURCE_BASE="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5"
MODE="check"

declare -A HASHES=(
  [install-autonomous-rnd-v5.sh]="0284d441a85bb2cdb17f5443c17efb8028b0fc85fdd439c4bcc84b887258a1a4"
  [install-research-context-v3.2.sh]="21a35cd5dc4d19a46134d34cb1eca2255f19e4775a7e9ecf85e1b32644a7297a"
  [install-research-cadence-v3.2.1.sh]="bcab7a4eb39a09eeeeecf20e440805b428e6f856eff21673f092a9b9a43dd923"
  [install-wire-room-v3.1.sh]="1d827996c65df85177d7d45c0b46c98778bf6212f83c161bbd68411a685ec8c2"
  [install-progress-delivery-fix-v3.sh]="24af7cd1ace9516b32a1909d6b310d3620319248bc4594436445e91b3613e9de"
  [install-telegram-pr-notify-v5.3.sh]="4f6d2e6dfb04699f0bd3e6e23493ed14cb311a8875c2dc844a147b50a4ce6007"
  [telegram-control-v1.py]="1d6a0f3f40cae1c06b6d667a7ffde6bd56c48d4947de9aad5b7c7a81019a100a"
  [repair-aizong-wire-v3.4.py]="eac39d02138a6b6ab5ff1671aafaa85ab5b49c13683931ea5e8f8e71ffe69757"
  [repair-love8-peer-bridge-v243.py]="c55f05dee451e42c2b7f16ae52d8527ae76b271f320d989b779074ee9912e17c"
)

usage() {
  echo "usage: $0 --check | --apply"
}

die() { echo "ERROR: $*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --check) MODE="check" ;;
    --apply) MODE="apply" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || die "run as root"
command -v curl >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required"
command -v sha256sum >/dev/null || die "sha256sum is required"

read_agent() {
  local config="$1"
  python3 - "$config" <<'PY'
from pathlib import Path
import sys

values = []
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    key, sep, value = line.partition("=")
    if sep and key.strip() == "AGENT_NAME":
        value = value.strip()
        if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        values.append(value)
if len(values) != 1:
    raise SystemExit("expected exactly one AGENT_NAME")
print(values[0])
PY
}

if [[ -f /opt/technocore-a2a/.env ]]; then
  CONFIG="/opt/technocore-a2a/.env"
elif [[ -f /opt/technocore-collab/.env ]]; then
  CONFIG="/opt/technocore-collab/.env"
else
  die "existing Technocore A2A/collab runtime not found"
fi
AGENT="$(read_agent "$CONFIG")"
case "$AGENT" in
  ai2ai|aizong|love8) ;;
  *) die "unsupported AGENT_NAME: $AGENT" ;;
esac

stage="$(mktemp -d /root/tc-a2a-suite-v53.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
chmod 0700 "$stage"

fetch() {
  local remote="$1" local_name="${2:-${1##*/}}" expected="${HASHES[${2:-${1##*/}}]:-}"
  [[ -n "$expected" ]] || die "missing checksum for $local_name"
  curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 \
    "$SOURCE_BASE/$remote" -o "$stage/$local_name"
  printf '%s  %s\n' "$expected" "$stage/$local_name" | sha256sum -c -
  chmod 0700 "$stage/$local_name"
}

fetch install-autonomous-rnd-v5.sh
fetch install-progress-delivery-fix-v3.sh
case "$AGENT" in
  ai2ai)
    fetch install-research-context-v3.2.sh
    fetch install-research-cadence-v3.2.1.sh
    fetch install-wire-room-v3.1.sh
    fetch install-telegram-pr-notify-v5.3.sh
    fetch telegram-control-v1.py
    ;;
  aizong)
    fetch aizong-wire-v34/repair-aizong-wire-v3.4.py repair-aizong-wire-v3.4.py
    ;;
  love8)
    fetch repair-love8-peer-bridge-v243.py
    ;;
esac

for file in "$stage"/*.sh; do bash -n "$file"; done
for file in "$stage"/*.py; do python3 -m py_compile "$file"; done

echo "A2A_SUITE_V53_PREFLIGHT=PASS"
echo "version=$VERSION"
echo "agent=$AGENT"
echo "source_ref=$SOURCE_REF"
case "$AGENT" in
  ai2ai) echo "plan=core,research-context,cadence,wire-room,delivery-recovery,tg-workflow-pr-alerts" ;;
  aizong) echo "plan=core-compatibility,3400-byte-wire,recovery-safe-workflow" ;;
  love8) echo "plan=core-gate,delivery-recovery,pinned-peer-room-invitations" ;;
esac

[[ "$MODE" == apply ]] || { echo "CHECK_ONLY: no installed files or services changed"; exit 0; }

run() {
  echo "RUNNING: $*"
  "$@"
}

run bash "$stage/install-autonomous-rnd-v5.sh"
case "$AGENT" in
  ai2ai)
    run bash "$stage/install-research-context-v3.2.sh"
    run bash "$stage/install-research-cadence-v3.2.1.sh"
    run bash "$stage/install-wire-room-v3.1.sh"
    run bash "$stage/install-progress-delivery-fix-v3.sh"
    A2A_V53_TELEGRAM_SOURCE_URL="$SOURCE_BASE/telegram-control-v1.py" \
      run bash "$stage/install-telegram-pr-notify-v5.3.sh"
    ;;
  aizong)
    run python3 "$stage/repair-aizong-wire-v3.4.py" --check
    run python3 "$stage/repair-aizong-wire-v3.4.py" --apply
    ;;
  love8)
    run bash "$stage/install-progress-delivery-fix-v3.sh"
    run python3 "$stage/repair-love8-peer-bridge-v243.py" --check
    run python3 "$stage/repair-love8-peer-bridge-v243.py" --apply
    ;;
esac

echo "A2A_SUITE_V53_INSTALLED"
echo "agent=$AGENT"
echo "identity_private_keys_mailboxes_cursors_provenance=preserved"
echo "component_rollbacks=installed"
