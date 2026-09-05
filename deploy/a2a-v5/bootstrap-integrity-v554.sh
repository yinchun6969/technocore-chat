#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" != 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then exec sudo bash "$0" "$@"; fi
  echo 'Please run as root on AI2AI; sudo is not installed.' >&2
  exit 2
fi
TC_REF="e925e41236cb71daed92ce2c9c6111bd432b9f24"
TC_BASE="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$TC_REF/deploy/a2a-v5"
TC_STAGE="$(mktemp -d /root/tc-integrity-v554.XXXXXX)"
chmod 700 "$TC_STAGE"
TC_LOG="/root/tc-integrity-v554-$(date -u +%Y%m%dT%H%M%SZ).log"
main() {
  cd "$TC_STAGE"
  for TC_FILE in integrity-v554.sha256 repair-integrity-v554.py deploy-integrity-v554.py install-integrity-v554.sh test_integrity_v554.py autonomous-rnd-v5.py telegram-control-v1.py human_action_center_v1.py research_context_v32.py patch-research-context-v3.2.py; do
    curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 "$TC_BASE/$TC_FILE" -o "$TC_FILE"
  done
  printf '%s  %s\n' '44610dbb39b18546b027ae53067dfaac20b1c457bc3f3e1de774b22f470ace31' integrity-v554.sha256 | sha256sum -c -
  sha256sum -c integrity-v554.sha256
  bash install-integrity-v554.sh --install
  echo "REPAIR_SOURCE=$TC_REF"
  echo "REPAIR_LOG=$TC_LOG"
}
echo "Log: $TC_LOG"
main 2>&1 | tee "$TC_LOG"
