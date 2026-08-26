#!/usr/bin/env bash
set -Eeuo pipefail
WF_ID="${1:-wf-1787757470-5f882e70e2}"
[[ "$WF_ID" == wf-* ]] || { echo 'usage: promote-rc4.sh [wf-id]'; exit 2; }
RAW='https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-collab-v2/deploy/a2a-v3/install-workflow-endgame-recovery-v3.4.sh'
VERIFY='https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-rc4-autonomous/deploy/a2a-v4/verify-rc4.sh'

if [[ -f /opt/technocore-collab/.env ]]; then
  set -a; source /opt/technocore-collab/.env; set +a
  AG="${AGENT_NAME:-unknown}"
  [[ "$AG" == love8 || "$AG" == aizong ]] || { echo "unsupported collab agent: $AG"; exit 1; }
  if ! command -v tc-collab-workflow-recover >/dev/null 2>&1; then
    curl -fsSL "$RAW" -o /tmp/endgame-v34.sh
    bash /tmp/endgame-v34.sh
  fi
  echo "=== RC4 PROMOTION: $AG ==="
  tc-collab-workflow-recover audit "$WF_ID" || true
  if [[ "$AG" == aizong ]]; then
    set +e
    out=$(tc-collab-workflow-recover revision "$WF_ID" 2>&1); rc=$?
    set -e
    echo "$out"
    if [[ $rc -ne 0 && "$out" != *'REVISED_RESULT_ALREADY_REMOTE'* ]]; then exit $rc; fi
    echo 'AIZONG_RC4_REVISION_READY'
  else
    # Wait for Builder's revised result, then finalize without creating a new workflow.
    ok=0
    for _ in $(seq 1 12); do
      set +e
      out=$(tc-collab-workflow-recover finalize "$WF_ID" 2>&1); rc=$?
      set -e
      echo "$out"
      if [[ $rc -eq 0 || "$out" == *'COMPLETE_ALREADY_REMOTE'* ]]; then ok=1; break; fi
      if [[ "$out" != *'VALID_REVISED_RESULT_NOT_FOUND'* ]]; then exit $rc; fi
      sleep 20
    done
    [[ $ok -eq 1 ]] || { echo 'FINALIZE_PENDING: Builder revised result not visible yet'; exit 5; }
    echo 'LOVE8_RC4_FINALIZE_READY'
  fi
elif [[ -f /opt/technocore-a2a/.env ]]; then
  echo '=== RC4 PROMOTION: ai2ai ==='
  echo 'Reviewer does not create a new workflow. Waiting for terminal COMPLETE receipt.'
else
  echo 'No supported Technocore A2A installation found'; exit 1
fi

curl -fsSL "$VERIFY" -o /tmp/verify-rc4.sh
chmod +x /tmp/verify-rc4.sh
set +e
/tmp/verify-rc4.sh "$WF_ID"
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  echo 'A2A_RC4_NODE_VERIFIED'
else
  echo "RC4 promotion action completed; verification is not terminal on this node yet (rc=$rc). Continue the next node, then re-run verify-rc4.sh on all three nodes."
fi
exit 0
