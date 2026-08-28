#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
AGENT="$ROOT/bin/collab.py"
ENV_FILE="$ROOT/.env"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

[[ ${EUID} -eq 0 ]] || { echo 'Run as root'; exit 1; }
[[ -f "$ENV_FILE" && -f "$AGENT" ]] || { echo 'Missing existing collab sidecar'; exit 1; }
set -a; source "$ENV_FILE"; set +a
[[ "${AGENT_NAME:-}" == "aizong" ]] || { echo "This recovery is only for aizong Builder (got ${AGENT_NAME:-unknown})"; exit 1; }

if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl stop technocore-collab 2>/dev/null || true
fi

cp -a "$AGENT" "$AGENT.before-v3.4-$STAMP"

python3 - "$AGENT" <<'PY'
from pathlib import Path
import sys

p=Path(sys.argv[1]); s=p.read_text()
if 'A2A_REVISION_RECOVERY_V34' not in s:
    marker='def workflow_start(goal):\n'
    pos=s.find(marker)
    if pos < 0:
        raise SystemExit('Could not locate workflow_start(); no changes made')

    block=r'''# A2A_REVISION_RECOVERY_V34

def _workflow_event_exists(tid, names):
    if not LEDGER.exists(): return False
    try:
        for line in LEDGER.read_text().splitlines():
            try: rec=json.loads(line)
            except Exception: continue
            if rec.get('workflow_id')==tid and rec.get('event') in names:
                return True
    except Exception:
        return False
    return False

def workflow_recover_revision(tid):
    if AGENT!='aizong' or ROLE!='builder':
        raise SystemExit('workflow revision recovery is allowed only on aizong Builder')
    tid=str(tid).strip()
    if not tid.startswith('wf-'):
        raise SystemExit('invalid workflow id')
    if _workflow_event_exists(tid, {'workflow_revised_result','workflow_revised_result_recovered'}):
        print('REVISION_ALREADY_COMPLETE',tid)
        return

    msgs=fetch_messages()
    candidates=[]
    for m in msgs:
        sender=m.get('from')
        x=parse(m.get('text'))
        if sender==AI2AI_DID and x and x.get('type')=='CHALLENGE' and x.get('task_id')==tid:
            candidates.append((seq(m),m,x))
    if not candidates:
        raise SystemExit('no valid recovered CHALLENGE found for '+tid)

    challenge_seq,m,x=max(candidates,key=lambda z:z[0])
    goal=str(x.get('goal',''))[:900]
    build=str(x.get('build_result',''))[:1100]
    challenge=str(x.get('challenge',''))[:1100]
    revised=ai('Workflow revision recovery stage. Revise the Builder result in response to the independent Reviewer challenge. Preserve uncertainty and do not claim unperformed execution.\nGOAL:\n'+goal+'\nBUILD:\n'+build+'\nCHALLENGE:\n'+challenge)[:1700]

    wf_send(LOVE8_DID,'REVISED_RESULT',tid,goal=goal,challenge=challenge,revised_result=revised,
            builder_did=AIZONG_DID,reviewer_did=AI2AI_DID)
    ledger('workflow_revised_result_recovered',workflow_id=tid,peer_did=LOVE8_DID,
           challenge_seq=challenge_seq,result_sha256=hashlib.sha256(revised.encode()).hexdigest())
    wf_mark(wf_key(AI2AI_DID,x))
    try:
        cur=int(CURSOR.read_text().strip()) if CURSOR.exists() else 0
    except Exception:
        cur=0
    if challenge_seq>cur:
        CURSOR.write_text(str(challenge_seq))
    print('REVISED_RESULT_RECOVERED',tid,'challenge_seq='+str(challenge_seq))

'''
    s=s[:pos]+block+s[pos:]

    # Record malformed signed envelopes from trusted peers instead of silently losing all evidence.
    old="                if m.get('from')!=DID: handle(m)\n                cur=max(cur,s)\n"
    new="                if m.get('from')!=DID:\n                    _sender=m.get('from'); _parsed=parse(m.get('text'))\n                    if trusted(_sender) and not _parsed:\n                        _raw=str(m.get('text',''))\n                        ledger('invalid_envelope_dead_letter',peer_did=_sender,seq=s,text_sha256=hashlib.sha256(_raw.encode()).hexdigest())\n                    handle(m)\n                cur=max(cur,s)\n"
    if old in s:
        s=s.replace(old,new,1)
    elif 'invalid_envelope_dead_letter' not in s:
        raise SystemExit('Could not patch run() dead-letter logging; no changes written')

    oldcli="    elif cmd=='workflow-start': workflow_start(' '.join(sys.argv[2:]))\n"
    newcli="    elif cmd=='workflow-start': workflow_start(' '.join(sys.argv[2:]))\n    elif cmd=='workflow-recover-revision': workflow_recover_revision(sys.argv[2])\n"
    if oldcli in s:
        s=s.replace(oldcli,newcli,1)
    elif "cmd=='workflow-recover-revision'" not in s:
        raise SystemExit('Could not patch recovery CLI; no changes written')

    p.write_text(s)
    print('patched:',p)
else:
    print('v3.4 recovery already installed')
PY

"$ROOT/venv/bin/python" -m py_compile "$AGENT"
chmod 0700 "$AGENT"

cat > /usr/local/bin/tc-collab-workflow-recover-revision <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
set -a; source $ROOT/.env; set +a
exec $ROOT/venv/bin/python $ROOT/bin/collab.py workflow-recover-revision "\$@"
EOF
chmod 0755 /usr/local/bin/tc-collab-workflow-recover-revision

if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl start technocore-collab
  sleep 2
  echo "service: $(systemctl is-active technocore-collab || true)"
fi

echo '=== AIZONG WORKFLOW RECOVERY v3.4 ==='
tc-collab-status || true
echo 'recovery_command: tc-collab-workflow-recover-revision <wf-id>'
echo 'dead_letter_logging: enabled'
echo 'DID/private key/mailbox/peer configuration unchanged.'