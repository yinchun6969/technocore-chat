#!/usr/bin/env bash
set -euo pipefail

# Additive v3.2 installer. The commit and hashes are replaced with the
# immutable release values before publication. No credentials are printed.
REPO="yinchun6969/technocore-chat"
REF="3f5dd06df0784f8f0919265e49c055a5fd042fea"
BASE="https://raw.githubusercontent.com/${REPO}/${REF}/deploy/a2a-v5"
MODE="install"
READ_PUBLIC=0
TOPIC="Technocore protocol bug reproducible reliability"

usage() {
  echo "usage: $0 [--audit [--read-public-room] [--topic TOPIC]]"
}

while (($#)); do
  case "$1" in
    --audit) MODE="audit" ;;
    --read-public-room) READ_PUBLIC=1 ;;
    --topic)
      (($# >= 2)) || { usage >&2; exit 2; }
      TOPIC="$2"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "$REF" == __RELEASE_REF__ ]]; then
  echo "release ref is not pinned" >&2
  exit 2
fi

if [[ "$MODE" == install && "$(id -u)" != 0 ]]; then
  echo "install mode must run as root on AI2AI" >&2
  exit 2
fi

if [[ "$MODE" == install ]]; then
  config="/opt/technocore-a2a/.env"
  [[ -r "$config" ]] || { echo "AI2AI configuration is missing; no changes made" >&2; exit 1; }
  agent_name="$(sed -n 's/^AGENT_NAME=["'"']\{0,1\}\([^"'"']*\)["'"']\{0,1\}[[:space:]]*$/\1/p' "$config" | head -n 1)"
  [[ "$agent_name" == ai2ai ]] || { echo "AI2AI configuration required; no changes made" >&2; exit 1; }
fi

if [[ "$(id -u)" == 0 ]]; then
  stage="$(mktemp -d /root/tc-research-context-v32-stage.XXXXXX)"
else
  stage="$(mktemp -d /tmp/tc-research-context-v32-stage.XXXXXX)"
fi
chmod 700 "$stage"
trap 'rm -rf -- "$stage"' EXIT

fetch_pinned() {
  local name="$1" expected="$2"
  curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 90 \
    "$BASE/$name" -o "$stage/$name"
  printf '%s  %s\n' "$expected" "$stage/$name" | sha256sum -c -
  chmod 700 "$stage/$name"
}

if [[ "$MODE" == audit ]]; then
  fetch_pinned "audit-research-rooms-v3.2.py" "d98ec5048176577c3fa0658ab11910cbb847caa87d43119fcd06c4b640aa7df4"
  args=("$stage/audit-research-rooms-v3.2.py" "--topic" "$TOPIC")
  ((READ_PUBLIC)) && args+=(--read-public-room)
  exec python3 "${args[@]}"
fi

fetch_pinned "research_context_v32.py" "e99374699198a72b31f18e6958bbf02c248523b216d39c67a0f4b683db95589a"
fetch_pinned "patch-research-context-v3.2.py" "6d3b83823c25f86a21f5499237c2440eee12164c848033d9bd51a4a2acada7af"
fetch_pinned "deploy-research-context-v3.2.py" "e860399e27e9d07ad910d08c3ed78274fcd0947d40140ed6be7a083c68f92423"

python3 -m py_compile \
  "$stage/research_context_v32.py" \
  "$stage/patch-research-context-v3.2.py" \
  "$stage/deploy-research-context-v3.2.py"

python3 "$stage/deploy-research-context-v3.2.py" --install "$stage"
