#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
AGENT="$ROOT/bin/collab.py"
ENV_FILE="$ROOT/.env"
SERVICE="technocore-collab"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
WFID="${1:-}"

[[ ${EUID} -eq 0 ]] || { echo 'Run as root'; exit 1; }
[[ -n "$WFID" && "$WFID" == wf-* ]] || { echo 'Usage: bash recover-aizong-revision-v3.4.sh <wf-id>'; exit 2; }
[[ -f "$AGENT" && -f "$ENV_FILE" ]] || { echo 'Missing existing collab sidecar'; exit 1; }
set -a; source "$ENV_FILE"; set +a
[[ "${AGENT_NAME:-}" == "aizong" && "${ROLE:-}" == "builder" ]] || {
  echo "This recovery is only for aizong Builder (found agent=${AGENT_NAME:-unknown} role=${ROLE:-unknown})"; exit 1;
}
grep -q 'WORKFLOW_V3_BEGIN' "$AGENT" || { echo 'Workflow v3 is not installed'; exit 1; }
grep -q 'A2A_WIRE_GUARD_V33' "$AGENT" || { echo 'Envelope guard v3.3 is not installed'; exit 1; }

restart_service() {
  if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl start "$SERVICE" >/dev/null 2>&1 || true
  elif command -v tc-collab-start >/dev/null 2>&1; then
    tc-collab-start >/dev/null 2>&1 || true
  fi
}
trap restart_service EXIT

if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl stop "$SERVICE" 2>/dev/null || true
elif command -v tc-collab-stop >/dev/null 2>&1; then
  tc-collab-stop || true
fi

cp -a "$AGENT" "$AGENT.before-v3.4-$STAMP"

python3 - "$AGENT" <<'PY'
from pathlib import Path
import sys

p=Path(sys.argv[1]); s=p.read_text()
if 'def workflow_recover_revision(task_id):' not in s:
    marker='\ndef run():\n'
    pos=s.find(marker)
    if pos < 0:
        raise SystemExit('Could not locate run(); no changes written')
    block=r'''
# AIZONG_WORKFLOW_RECOVERY_V34
def workflow_recover_revision(task_id):
    task_id=str(task_id).strip()
    if AGENT!='aizong' or ROLE!='builder':
        raise SystemExit('workflow-recover-revision is allowed only on aizong Builder')
    if not task_id.startswith('wf-'):
        raise SystemExit('workflow id must start with wf-')
    if not trusted(AI2AI_DID):
        raise SystemExit('ai2ai DID is not pinned as a trusted peer')

    # Idempotency first: if a valid revised result is already on love8's inbox,
    # never call the model or send another one.
    love8_route=wf_mailbox(LOVE8_DID)
    if outbound_seen(love8_route,task_id,'REVISED_RESULT'):
        ledger('workflow_revision_recovery_already_complete',workflow_id=task_id,peer_did=LOVE8_DID)
        print('REVISED_RESULT_ALREADY_VALID',task_id)
        return

    inbox=(globals().get('FALLBACK_INBOX','') or MAILBOX).strip()
    r=requests.get(f'{BASE}/r/{quote(inbox)}',params={'format':'json','limit':200},timeout=30)
    r.raise_for_status()
    found=[]
    for m in r.json().get('messages',[]):
        if m.get('from')!=AI2AI_DID:
            continue
        obj=parse(m.get('text'))
        if obj and obj.get('type')=='CHALLENGE' and obj.get('task_id')==task_id:
            try: n=int(m.get('seq',0))
            except Exception: n=0
            found.append((n,obj))
    if not found:
        ledger('workflow_revision_recovery_missing_challenge',workflow_id=task_id,peer_did=AI2AI_DID,inbox=inbox)
        raise SystemExit('RECOVERY_NO_VALID_CHALLENGE: no parseable recovered CHALLENGE found on '+inbox)

    found.sort(key=lambda z:z[0])
    source=found[-1][1]
    k=wf_key(AI2AI_DID,source)

    # If an earlier run marked this exact stage seen but never produced a valid
    # REVISED_RESULT, clear only that stale stage marker. This does not alter the
    # mailbox cursor and cannot reopen any other workflow/stage.
    d=wf_seen()
    if k in d:
        d.pop(k,None)
        savej(WF_SEEN,d)
        ledger('workflow_revision_recovery_cleared_stale_seen',workflow_id=task_id,peer_did=AI2AI_DID)

    ledger('workflow_revision_recovery_started',workflow_id=task_id,peer_did=AI2AI_DID,inbox=inbox)
    handled=workflow_handle(AI2AI_DID,source)
    if not handled:
        raise RuntimeError('workflow_handle did not accept recovered CHALLENGE')
    if not outbound_seen(love8_route,task_id,'REVISED_RESULT'):
        raise RuntimeError('recovery ran but no valid REVISED_RESULT is visible on love8 route')
    ledger('workflow_revision_recovered',workflow_id=task_id,peer_did=LOVE8_DID)
    print('REVISION_RECOVERED',task_id)
'''
    s=s[:pos]+block+s[pos:]

needle="    elif cmd=='workflow-start': workflow_start(' '.join(sys.argv[2:]))\n"
branch="    elif cmd=='workflow-recover-revision' and len(sys.argv)==3: workflow_recover_revision(sys.argv[2])\n"
if branch not in s:
    if needle not in s:
        raise SystemExit('Could not locate workflow-start CLI branch; no changes written')
    s=s.replace(needle,needle+branch,1)

p.write_text(s)
print('patched:',p)
PY

"$ROOT/venv/bin/python" -m py_compile "$AGENT"
chmod 0700 "$AGENT"

cat > /usr/local/bin/tc-collab-workflow-recover-revision <<EOF
#!/usr/bin/env bash
set -a; source $ENV_FILE; set +a
exec $ROOT/venv/bin/python $AGENT workflow-recover-revision "\$@"
EOF
chmod 0755 /usr/local/bin/tc-collab-workflow-recover-revision

set -a; source "$ENV_FILE"; set +a

echo '=== AIZONG WORKFLOW RECOVERY v3.4 ==='
echo "workflow_id: $WFID"
echo "receive_inbox: ${A2A_FALLBACK_INBOX:-$MAILBOX}"
echo 'mode: targeted stage recovery; no cursor rewind; idempotent outbound check enabled'

tc-collab-workflow-recover-revision "$WFID"

restart_service
trap - EXIT
sleep 3

echo '=== SERVICE ==='
if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl is-active "$SERVICE" || true
else
  command -v tc-collab-process-status >/dev/null 2>&1 && tc-collab-process-status || true
fi

echo '=== WORKFLOW PROVENANCE ==='
grep -F "$WFID" "$ROOT/state/provenance.jsonl" | tail -20 || true
echo 'AIZONG_REVISION_RECOVERY_V34_DONE'
echo 'DID/private key/mailbox/peer config/cursor were not replaced or rewound.'
