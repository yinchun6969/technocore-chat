#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
HELPER="$ROOT/bin/workflow_endgame_recover.py"

[[ ${EUID} -eq 0 ]] || { echo 'Run as root'; exit 1; }
[[ -f "$ROOT/.env" && -f "$ROOT/bin/collab.py" ]] || { echo 'Missing existing collab sidecar'; exit 1; }
set -a; source "$ROOT/.env"; set +a
[[ "${AGENT_NAME:-}" == "aizong" || "${AGENT_NAME:-}" == "love8" ]] || { echo "Unsupported agent: ${AGENT_NAME:-unknown}"; exit 1; }
grep -q 'WORKFLOW_V3_BEGIN' "$ROOT/bin/collab.py" || { echo 'Workflow v3 is not installed'; exit 1; }
grep -q 'A2A_WIRE_GUARD_V33' "$ROOT/bin/collab.py" || { echo 'Envelope guard v3.3 is not installed'; exit 1; }

cat > "$HELPER" <<'PY'
#!/usr/bin/env python3
import hashlib, importlib.util, json, os, sys, time
from pathlib import Path
from urllib.parse import quote

ROOT=Path('/opt/technocore-collab')
spec=importlib.util.spec_from_file_location('collab_runtime', ROOT/'bin/collab.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

if len(sys.argv)!=3 or sys.argv[1] not in ('audit','revision','finalize'):
    raise SystemExit('usage: workflow_endgame_recover.py audit|revision|finalize <wf-id>')
mode,tid=sys.argv[1],sys.argv[2].strip()
if not tid.startswith('wf-'): raise SystemExit('workflow id must start with wf-')

AI2AI=m.AI2AI_DID; AIZONG=m.AIZONG_DID; LOVE8=m.LOVE8_DID

def room_messages(room):
    r=m.requests.get(f'{m.BASE}/r/{quote(room)}',params={'format':'json','limit':200},timeout=30)
    r.raise_for_status(); return r.json().get('messages',[])

def seq(x):
    try: return int(x.get('seq',0))
    except Exception: return 0

def find_valid(room,sender,kind):
    found=[]
    malformed=[]
    for msg in room_messages(room):
        if msg.get('from')!=sender: continue
        text=msg.get('text')
        obj=m.parse(text)
        if obj and obj.get('task_id')==tid and obj.get('type')==kind:
            found.append((seq(msg),obj))
        elif isinstance(text,str) and text.startswith('A2A1 ') and tid in text:
            malformed.append(seq(msg))
    found.sort(key=lambda z:z[0])
    return (found[-1] if found else None), malformed

def audit():
    rooms=[]
    fb=os.environ.get('A2A_FALLBACK_INBOX','').strip()
    for r in (fb,m.MAILBOX,'d-aizong'):
        if r and r not in rooms: rooms.append(r)
    print('agent:',m.AGENT,'role:',m.ROLE,'workflow:',tid)
    for room in rooms:
        try:
            msgs=room_messages(room)
            print('room:',room,'messages:',len(msgs),'max_seq:',max([seq(x) for x in msgs] or [0]))
            for sender,kind,label in ((AI2AI,'CHALLENGE','challenge'),(AIZONG,'REVISED_RESULT','revised'),(LOVE8,'COMPLETE','complete')):
                hit,bad=find_valid(room,sender,kind)
                if hit: print(label+': VALID seq='+str(hit[0]))
                elif bad: print(label+': MALFORMED seqs='+','.join(map(str,bad[-5:])))
        except Exception as e:
            print('room:',room,'ERROR',str(e)[:180])

def recover_revision():
    if m.AGENT!='aizong' or m.ROLE!='builder': raise SystemExit('revision recovery must run on aizong Builder')
    love8_route=m.wf_mailbox(LOVE8)
    if m.outbound_seen(love8_route,tid,'REVISED_RESULT'):
        print('REVISED_RESULT_ALREADY_REMOTE',tid); return
    rooms=[]
    fb=os.environ.get('A2A_FALLBACK_INBOX','').strip()
    for r in (fb,'d-aizong',m.MAILBOX):
        if r and r not in rooms: rooms.append(r)
    hit=None; source_room=None; malformed=[]
    for room in rooms:
        try:
            h,bad=find_valid(room,AI2AI,'CHALLENGE'); malformed += [(room,x) for x in bad]
            if h and (hit is None or h[0]>hit[0]): hit=h; source_room=room
        except Exception:
            continue
    if not hit:
        if malformed:
            print('ONLY_MALFORMED_CHALLENGE_FOUND',malformed[-5:])
        raise SystemExit('VALID_CHALLENGE_NOT_FOUND: run ai2ai ensure-challenge, then retry revision recovery')
    s,obj=hit
    goal=str(obj.get('goal',''))[:900]
    build=str(obj.get('build_result',''))[:1100]
    challenge=str(obj.get('challenge',''))[:1100]
    revised=m.ai('Workflow revision recovery stage. Revise the Builder result in response to the independent Reviewer challenge. Preserve uncertainty and do not claim unperformed execution.\nGOAL:\n'+goal+'\nBUILD:\n'+build+'\nCHALLENGE:\n'+challenge)[:1700]
    m.wf_send(LOVE8,'REVISED_RESULT',tid,goal=goal,challenge=challenge,revised_result=revised,
              builder_did=AIZONG,reviewer_did=AI2AI,recovery=True)
    if not m.outbound_seen(love8_route,tid,'REVISED_RESULT'):
        raise SystemExit('REVISED_RESULT_SEND_NOT_VERIFIED')
    m.ledger('workflow_revised_result_recovered',workflow_id=tid,peer_did=LOVE8,
             source_room=source_room,source_seq=s,result_sha256=hashlib.sha256(revised.encode()).hexdigest())
    try: m.wf_mark(m.wf_key(AI2AI,obj))
    except Exception: pass
    print('REVISED_RESULT_RECOVERED',tid,'source='+source_room,'seq='+str(s))

def recover_finalize():
    if m.AGENT!='love8' or m.ROLE!='scout': raise SystemExit('finalize recovery must run on love8 Scout')
    aizong_route=m.wf_mailbox(AIZONG); ai2ai_route=m.wf_mailbox(AI2AI)
    a_done=m.outbound_seen(aizong_route,tid,'COMPLETE')
    r_done=m.outbound_seen(ai2ai_route,tid,'COMPLETE')
    if a_done and r_done:
        print('COMPLETE_ALREADY_REMOTE',tid); return
    hit,bad=find_valid(m.MAILBOX,AIZONG,'REVISED_RESULT')
    if not hit:
        if bad: print('MALFORMED_REVISED_RESULT_SEQS',bad[-5:])
        raise SystemExit('VALID_REVISED_RESULT_NOT_FOUND')
    s,obj=hit
    goal=str(obj.get('goal',''))[:900]
    challenge=str(obj.get('challenge',''))[:900]
    revised=str(obj.get('revised_result',''))[:1500]
    summary=m.ai('Workflow Scout completion recovery stage. Assess whether the revised result addresses the original goal and reviewer challenge. Produce a concise terminal summary including unresolved risks. Do not claim external execution.\nGOAL:\n'+goal+'\nCHALLENGE:\n'+challenge+'\nREVISED:\n'+revised)[:1200]
    m.wf_send(AIZONG,'COMPLETE',tid,status='complete',final_summary=summary,recovery=True)
    m.wf_send(AI2AI,'COMPLETE',tid,status='complete',final_summary=summary,recovery=True)
    if not m.outbound_seen(aizong_route,tid,'COMPLETE') or not m.outbound_seen(ai2ai_route,tid,'COMPLETE'):
        raise SystemExit('COMPLETE_SEND_NOT_VERIFIED')
    m.ledger('workflow_complete_recovered',workflow_id=tid,source_seq=s,
             final_sha256=hashlib.sha256(summary.encode()).hexdigest())
    try: m.wf_mark(m.wf_key(AIZONG,obj))
    except Exception: pass
    print('WORKFLOW_COMPLETE_RECOVERED',tid)

if mode=='audit': audit()
elif mode=='revision': recover_revision()
else: recover_finalize()
PY
chmod 0700 "$HELPER"

cat > /usr/local/bin/tc-collab-workflow-recover <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=/opt/technocore-collab
set -a; source "$ROOT/.env"; set +a
MODE="${1:-}"; WF="${2:-}"
[[ "$MODE" =~ ^(audit|revision|finalize)$ && "$WF" == wf-* ]] || { echo 'usage: tc-collab-workflow-recover audit|revision|finalize <wf-id>'; exit 2; }
restart='none'
cleanup(){
  if [[ "$restart" == systemd ]]; then systemctl start technocore-collab >/dev/null 2>&1 || true; fi
  if [[ "$restart" == runner ]]; then tc-collab-start >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
if [[ "$MODE" != audit ]]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1 && systemctl is-active --quiet technocore-collab; then
    systemctl stop technocore-collab; restart=systemd
  elif command -v tc-collab-stop >/dev/null 2>&1; then
    tc-collab-stop >/dev/null 2>&1 || true; restart=runner
  fi
fi
exec "$ROOT/venv/bin/python" "$ROOT/bin/workflow_endgame_recover.py" "$MODE" "$WF"
EOF
chmod 0755 /usr/local/bin/tc-collab-workflow-recover

echo '=== WORKFLOW ENDGAME RECOVERY v3.4 ==='
echo "agent: ${AGENT_NAME}"
echo "role: ${ROLE}"
echo 'commands:'
echo '  tc-collab-workflow-recover audit <wf-id>'
if [[ "$AGENT_NAME" == aizong ]]; then echo '  tc-collab-workflow-recover revision <wf-id>'; fi
if [[ "$AGENT_NAME" == love8 ]]; then echo '  tc-collab-workflow-recover finalize <wf-id>'; fi
echo 'No DID/private key/mailbox/peer configuration changed.'
echo 'ENDGAME_RECOVERY_READY'
