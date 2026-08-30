#!/usr/bin/env bash
set -Eeuo pipefail

# Review-ready, role-aware convergence release for Love8, Aizong and AI2AI.
VERSION="5.4.0"
SOURCE_REF="a4dd808c5bda994d9d33a1d8aa48c5dc9d37ef36"
SOURCE_BASE="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5"
MODE="check"

declare -A HASHES=(
  [install-autonomous-rnd-v5.sh]="95946896cb52efb7a09d59ac85b6d77024bfed14476a896aae39621bab02ebbd"
  [install-research-context-v3.2.sh]="21a35cd5dc4d19a46134d34cb1eca2255f19e4775a7e9ecf85e1b32644a7297a"
  [install-research-cadence-v3.2.1.sh]="bcab7a4eb39a09eeeeecf20e440805b428e6f856eff21673f092a9b9a43dd923"
  [install-wire-room-v3.1.sh]="1d827996c65df85177d7d45c0b46c98778bf6212f83c161bbd68411a685ec8c2"
  [install-progress-delivery-fix-v3.sh]="24af7cd1ace9516b32a1909d6b310d3620319248bc4594436445e91b3613e9de"
  [install-curator-reliability-v5.2.sh]="8272d30a8720f3a79de76e02f3c87e464495748bbaf55068a486e2f27cbe449d"
  [install-telegram-pr-notify-v5.3.sh]="4f6d2e6dfb04699f0bd3e6e23493ed14cb311a8875c2dc844a147b50a4ce6007"
  [telegram-control-v1.py]="1d6a0f3f40cae1c06b6d667a7ffde6bd56c48d4947de9aad5b7c7a81019a100a"
  [repair-aizong-wire-v3.4.py]="eac39d02138a6b6ab5ff1671aafaa85ab5b49c13683931ea5e8f8e71ffe69757"
  [repair-aizong-evidence-mirror-v3.5.py]="42541137e471403f2662790afd6161ca22cfb75f96d0db06219b76c648fb5991"
  [repair-love8-peer-bridge-v243.py]="c55f05dee451e42c2b7f16ae52d8527ae76b271f320d989b779074ee9912e17c"
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
