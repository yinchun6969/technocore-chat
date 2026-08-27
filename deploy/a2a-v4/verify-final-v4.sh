#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -f /opt/technocore-a2a/.env ]]; then
  set -a; source /opt/technocore-a2a/.env; set +a
  if [[ "${AGENT_NAME:-}" == ai2ai ]]; then
    echo '=== AI2AI FINAL v4 VERIFY ==='
    tc-a2a-status || true
    echo
    tc-a2a-rnd-status || true
    echo
    echo '=== RECENT R&D EVENTS ==='
    grep -E 'scheduler_|rnd_|artifact_|workflow_' /opt/technocore-a2a/state/provenance.jsonl 2>/dev/null | tail -30 || true
    echo
    echo '=== ARTIFACTS ==='
    ls -lah /opt/technocore-a2a/artifacts 2>/dev/null || true
    exit 0
  fi
fi

if [[ -f /opt/technocore-collab/.env ]]; then
  set -a; source /opt/technocore-collab/.env; set +a
  echo '=== COLLAB FINAL v4 VERIFY ==='
  echo "agent=${AGENT_NAME:-unknown}"
  echo "role=${ROLE:-unknown}"
  tc-collab-status || true
  command -v tc-collab-process-status >/dev/null 2>&1 && tc-collab-process-status || true
  echo
  echo '=== RECOVERY COMMAND ==='
  command -v tc-collab-workflow-recover || true
  echo
  echo '=== RECENT WORKFLOW EVENTS ==='
  grep -E 'scheduler_|workflow_' /opt/technocore-collab/state/provenance.jsonl 2>/dev/null | tail -30 || true
  exit 0
fi

echo 'No known Technocore agent installation found.' >&2
exit 1
