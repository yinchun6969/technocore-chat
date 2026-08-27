#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
ENV_FILE="$ROOT/.env"
AGENT_FILE="$ROOT/bin/collab.py"
SERVICE="technocore-collab"
WF_ID="${1:-}"

[[ ${EUID} -eq 0 ]] || { echo 'Run as root'; exit 1; }
[[ -n "$WF_ID" && "$WF_ID" == wf-* ]] || { echo 'usage: recover-aizong-challenge-v3.4.sh <wf-id>'; exit 1; }
[[ -f "$ENV_FILE" && -f "$AGENT_FILE" ]] || { echo 'Missing existing collab sidecar'; exit 1; }

set -a
source "$ENV_FILE"
set +a
[[ "${AGENT_NAME:-}" == "aizong" && "${ROLE:-}" == "builder" ]] || {
  echo "Refusing: expected aizong/builder, got ${AGENT_NAME:-unknown}/${ROLE:-unknown}"; exit 1;
}
[[ "${A2A_FALLBACK_INBOX:-}" == "d-aizong" ]] || {
  echo "Refusing: A2A_FALLBACK_INBOX is not d-aizong"; exit 1;
}

echo '=== AIZONG CHALLENGE RECOVERY v3.4 ==='
echo "workflow: $WF_ID"
echo 'mode: recover existing signed CHALLENGE only; no new workflow'

if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl stop "$SERVICE" 2>/dev/null || true
  trap 'systemctl start "$SERVICE" >/dev/null 2>&1 || true' EXIT
fi

"$ROOT/venv/bin/python" - "$WF_ID" <<'PY'
import importlib.util, json, os, sys
from pathlib import Path
from urllib.parse import quote
import requests

wf_id=sys.argv[1]
agent_path=Path('/opt/technocore-collab/bin/collab.py')
prov=Path('/opt/technocore-collab/state/provenance.jsonl')
cursor=Path('/opt/technocore-collab/state/cursor.txt')

# If the revised result already exists, recovery is intentionally a no-op.
if prov.exists():
    for line in prov.read_text(errors='replace').splitlines():
        if wf_id in line and '"event":"workflow_revised_result"' in line:
            print('REVISED_RESULT_ALREADY_PRESENT')
            raise SystemExit(0)

spec=importlib.util.spec_from_file_location('aizong_collab_recovery', agent_path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

inbox=os.environ.get('A2A_FALLBACK_INBOX','d-aizong').strip() or 'd-aizong'
r=requests.get(f"{mod.BASE}/r/{quote(inbox)}",params={'format':'json','limit':200},timeout=30)
r.raise_for_status()
msgs=r.json().get('messages',[])

def seq(m):
    try: return int(m.get('seq',0))
    except Exception: return 0

candidates=[]
for m in msgs:
    if m.get('from') != mod.AI2AI_DID:
        continue
    x=mod.parse(m.get('text'))
    if not x:
        continue
    if x.get('type')=='CHALLENGE' and x.get('task_id')==wf_id:
        candidates.append((seq(m),m,x))

if not candidates:
    print('VALID_CHALLENGE_NOT_FOUND')
    print('current_cursor:', cursor.read_text().strip() if cursor.exists() else 'missing')
    print('room_max_seq:', max([seq(m) for m in msgs] or [0]))
    raise SystemExit(2)

s,m,x=max(candidates,key=lambda z:z[0])
wire=m.get('text','')
print('challenge_seq:',s)
print('challenge_wire_bytes:',len(wire.encode('utf-8')) if isinstance(wire,str) else -1)
print('current_cursor:', cursor.read_text().strip() if cursor.exists() else 'missing')

key=mod.wf_key(mod.AI2AI_DID,x)
seen=mod.wf_seen()
if key in seen:
    print('CHALLENGE_ALREADY_MARKED_SEEN')
    raise SystemExit(3)

handled=mod.workflow_handle(mod.AI2AI_DID,x)
if not handled:
    raise SystemExit('workflow_handle did not accept recovered CHALLENGE')

# Advance only through the recovered challenge, never past unrelated later traffic.
try:
    cur=int(cursor.read_text().strip()) if cursor.exists() else 0
except Exception:
    cur=0
if s>cur:
    cursor.write_text(str(s))

mod.ledger('workflow_challenge_replayed',workflow_id=wf_id,peer_did=mod.AI2AI_DID,source_seq=s)

ok=False
if prov.exists():
    for line in prov.read_text(errors='replace').splitlines():
        if wf_id in line and '"event":"workflow_revised_result"' in line:
            ok=True
            break
if not ok:
    raise SystemExit('recovery returned without workflow_revised_result provenance')
print('REVISED_RESULT_RECOVERED',wf_id)
PY

if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl start "$SERVICE"
  trap - EXIT
  sleep 2
  echo "service: $(systemctl is-active "$SERVICE" || true)"
fi

echo '=== WORKFLOW PROVENANCE ==='
grep -F "$WF_ID" "$ROOT/state/provenance.jsonl" | tail -20 || true
echo 'AIZONG_RECOVERY_COMPLETE'
