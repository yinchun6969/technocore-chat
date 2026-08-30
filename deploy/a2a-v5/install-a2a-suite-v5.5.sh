#!/usr/bin/env bash
set -Eeuo pipefail

# Role-aware v5.5 convergence: retain the proven v5.4 transport/runtime and
# add deterministic verification only on the AI2AI Reviewer/Curator node.
VERSION="5.5.0"
V54_REF="dc3f9d148ea18cb86af2417d036d3d7fadef39a5"
V54_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$V54_REF/deploy/a2a-v5/install-a2a-suite-v5.4.sh"
V54_SHA256="b9084ff51aa199ad50ad889c5ca6b60896acd6f679648608e065f304b7898b00"
SOURCE_REF="c4ef4156f9a1a8d66c09c43b1f728a39d0a20fa3"
SOURCE_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5/install-verifiable-evidence-v5.5.sh"
SOURCE_SHA256="1466766ffe0bc1ea3783d6ab0e602005720a8a7635bd3c2d4a0ca4096abee1a6"
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
for command in curl sha256sum python3; do command -v "$command" >/dev/null || die "$command is required"; done

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

stage="$(mktemp -d /root/tc-a2a-suite-v55.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
chmod 0700 "$stage"
curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 "$V54_URL" -o "$stage/v54.sh"
printf '%s  %s\n' "$V54_SHA256" "$stage/v54.sh" | sha256sum -c -
curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 "$SOURCE_URL" -o "$stage/v55.sh"
printf '%s  %s\n' "$SOURCE_SHA256" "$stage/v55.sh" | sha256sum -c -
bash -n "$stage/v54.sh" "$stage/v55.sh"

echo "A2A_SUITE_V55_PREFLIGHT=PASS"
echo "version=$VERSION"
echo "agent=$AGENT"
echo "v54_ref=$V54_REF"
echo "v55_ref=$SOURCE_REF"
case "$AGENT" in
  ai2ai) echo "plan=v54-convergence,strict-evidence,merkle-verification,saga-checkpoint,task-status-cli" ;;
  aizong) echo "plan=v54-convergence,v55-signed-stage-producer-compatible" ;;
  love8) echo "plan=v54-convergence,v55-signed-stage-producer-compatible" ;;
esac

echo "RUNNING: v5.4 convergence $MODE"
bash "$stage/v54.sh" "--$MODE"
if [[ "$AGENT" == ai2ai ]]; then
  echo "RUNNING: v5.5 verifiable evidence $MODE"
  bash "$stage/v55.sh" "--$MODE"
fi
[[ "$MODE" == apply ]] || { echo "CHECK_ONLY: no installed files or services changed"; exit 0; }

echo "A2A_SUITE_V55_INSTALLED"
echo "agent=$AGENT"
if [[ "$AGENT" == ai2ai ]]; then
  echo "evidence=structured,signer-bound,merkle-verified"
  echo "task_cli=technocore status --task-id wf-..."
else
  echo "v55_role_change=none; existing signed-stage protocol retained"
fi
echo "identity_private_keys_mailboxes_cursors_nonces_provenance_artifacts=preserved"
echo "component_rollbacks=installed"
