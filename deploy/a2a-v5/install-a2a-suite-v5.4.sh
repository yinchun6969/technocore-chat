#!/usr/bin/env bash
set -Eeuo pipefail

# Review-ready, role-aware convergence release for Love8, Aizong and AI2AI.
VERSION="5.4.0"
SOURCE_REF="__SUITE_REF__"
SOURCE_BASE="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5"
MODE="check"

declare -A HASHES=(
  [install-autonomous-rnd-v5.sh]="__HASH_CORE__"
  [install-research-context-v3.2.sh]="__HASH_CONTEXT__"
  [install-research-cadence-v3.2.1.sh]="__HASH_CADENCE__"
  [install-wire-room-v3.1.sh]="__HASH_WIRE_ROOM__"
  [install-progress-delivery-fix-v3.sh]="__HASH_DELIVERY__"
  [install-curator-reliability-v5.2.sh]="__HASH_CURATOR_INSTALLER__"
  [install-telegram-pr-notify-v5.3.sh]="__HASH_TELEGRAM_INSTALLER__"
  [telegram-control-v1.py]="__HASH_TELEGRAM__"
  [repair-aizong-wire-v3.4.py]="__HASH_AIZONG_WIRE__"
  [repair-aizong-evidence-mirror-v3.5.py]="__HASH_AIZONG_MIRROR__"
  [repair-love8-peer-bridge-v243.py]="__HASH_LOVE8_BRIDGE__"
)

die() { echo "ERROR: $*" >&2; exit 1; }
usage() { echo "usage: $0 --check | --apply"; }

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
for command in curl python3 sha256sum; do command -v "$command" >/dev/null || die "$command is required"; done

read_agent() {
  python3 - "$1" <<'PY'
from pathlib import Path
import shlex, sys
values=[]
for line in Path(sys.argv[1]).read_text().splitlines():
    parts=shlex.split(line, comments=True)
    if parts and parts[0]=='export': parts=parts[1:]
    for part in parts:
        key, sep, value=part.partition('=')
        if sep and key=='AGENT_NAME': values.append(value)
if len(values)!=1: raise SystemExit('expected exactly one AGENT_NAME')
print(values[0])
PY
}

if [[ -f /opt/technocore-a2a/.env ]]; then
  CONFIG=/opt/technocore-a2a/.env
elif [[ -f /opt/technocore-collab/.env ]]; then
  CONFIG=/opt/technocore-collab/.env
else
  die "existing Technocore A2A/collab runtime not found"
fi
AGENT="$(read_agent "$CONFIG")"
[[ "$AGENT" =~ ^(ai2ai|aizong|love8)$ ]] || die "unsupported AGENT_NAME: $AGENT"

stage="$(mktemp -d /root/tc-a2a-suite-v54.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
chmod 0700 "$stage"

fetch() {
  local remote="$1" local_name="${2:-${1##*/}}" expected="${HASHES[${2:-${1##*/}}]:-}"
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || die "invalid checksum for $local_name"
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
    fetch install-curator-reliability-v5.2.sh
    fetch install-telegram-pr-notify-v5.3.sh
    fetch telegram-control-v1.py
    ;;
  aizong)
    fetch aizong-wire-v34/repair-aizong-wire-v3.4.py repair-aizong-wire-v3.4.py
    fetch repair-aizong-evidence-mirror-v3.5.py
    ;;
  love8)
    fetch repair-love8-peer-bridge-v243.py
    ;;
esac

for file in "$stage"/*.sh; do bash -n "$file"; done
for file in "$stage"/*.py; do python3 -m py_compile "$file"; done

echo "A2A_SUITE_V54_PREFLIGHT=PASS"
echo "version=$VERSION"
echo "agent=$AGENT"
echo "source_ref=$SOURCE_REF"
case "$AGENT" in
  ai2ai) echo "plan=immutable-core,cursor-curator,director-cache,delivery-recovery,telegram" ;;
  aizong) echo "plan=3400-byte-wire,signed-builder-evidence-mirrors" ;;
  love8) echo "plan=scheduler-gate,delivery-recovery,pinned-peer-bridge" ;;
esac
[[ "$MODE" == apply ]] || { echo "CHECK_ONLY: no installed files or services changed"; exit 0; }

run() { echo "RUNNING: $*"; "$@"; }
run bash "$stage/install-autonomous-rnd-v5.sh"
case "$AGENT" in
  ai2ai)
    run bash "$stage/install-research-context-v3.2.sh"
    run bash "$stage/install-research-cadence-v3.2.1.sh"
    run bash "$stage/install-wire-room-v3.1.sh"
    run bash "$stage/install-progress-delivery-fix-v3.sh"
    run bash "$stage/install-curator-reliability-v5.2.sh" --apply
    A2A_V53_TELEGRAM_SOURCE_URL="$SOURCE_BASE/telegram-control-v1.py" \
      run bash "$stage/install-telegram-pr-notify-v5.3.sh"
    ;;
  aizong)
    run python3 "$stage/repair-aizong-wire-v3.4.py" --check
    run python3 "$stage/repair-aizong-wire-v3.4.py" --apply
    run python3 "$stage/repair-aizong-evidence-mirror-v3.5.py" --check
    run python3 "$stage/repair-aizong-evidence-mirror-v3.5.py" --apply
    ;;
  love8)
    run bash "$stage/install-progress-delivery-fix-v3.sh"
    run python3 "$stage/repair-love8-peer-bridge-v243.py" --check
    run python3 "$stage/repair-love8-peer-bridge-v243.py" --apply
    ;;
esac

echo "A2A_SUITE_V54_INSTALLED"
echo "agent=$AGENT"
echo "identity_private_keys_mailboxes_cursors_provenance_artifacts=preserved"
echo "component_rollbacks=installed"
