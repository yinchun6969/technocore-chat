#!/usr/bin/env bash
set -Eeuo pipefail

echo "=== TECHNCORE AUTONOMOUS R&D v5 VERIFY ==="
if [[ -f /opt/technocore-a2a/.env ]]; then
  set -a; source /opt/technocore-a2a/.env; set +a
  if [[ "${AGENT_NAME:-}" == ai2ai ]]; then
    echo "node=ai2ai role=${ROLE:-unknown}"
    systemctl is-active technocore-a2a.service technocore-a2a-rnd-v5.service technocore-a2a-rnd-curator-v5.service
    tc-a2a-rnd-v5-status
    echo "--- recent autonomous events ---"
    grep -E 'rnd_objective_selected|scheduler_request_sent|rnd_artifact|director_error|curator_error' \
      /opt/technocore-a2a/state/provenance.jsonl \
      /opt/technocore-a2a/rnd-v5-state/director.log \
      /opt/technocore-a2a/rnd-v5-state/curator.log 2>/dev/null | tail -30 || true
    exit 0
  fi
fi

if [[ -f /opt/technocore-collab/.env ]]; then
  set -a; source /opt/technocore-collab/.env; set +a
  case "${AGENT_NAME:-}" in
    love8)
      echo "node=love8 role=${ROLE:-unknown}"
      grep -q 'AUTONOMOUS_SCHEDULER_GATE_V29' /opt/technocore-collab/bin/collab.py && echo 'signed_scheduler_gate=present'
      grep -q 'SCHEDULER_REQUEST' /opt/technocore-collab/bin/collab.py && echo 'scheduler_request_handler=present'
      command -v tc-collab-process-status >/dev/null 2>&1 && tc-collab-process-status || true
      exit 0
      ;;
    aizong)
      echo "node=aizong role=${ROLE:-unknown}"
      systemctl is-active technocore-collab.service technocore-aizong-social.service 2>/dev/null || true
      grep -q 'WORKFLOW_V3_BEGIN' /opt/technocore-collab/bin/collab.py && echo 'builder_workflow_v3=present'
      exit 0
      ;;
  esac
fi

echo "unknown node or missing existing installation" >&2
exit 1
