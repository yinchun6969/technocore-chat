#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/opt/technocore-collab"
AGENT="$ROOT/bin/collab.py"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: bash harden-task-state-v2.3.sh"
  exit 1
fi
[[ -f "$AGENT" ]] || { echo "Missing $AGENT"; exit 1; }

if command -v tc-collab-stop >/dev/null 2>&1; then tc-collab-stop || true; fi
cp -a "$AGENT" "$AGENT.before-v2.3-$STAMP"

python3 - "$AGENT" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
start = s.find("def processed_key(sender,x):")
end = s.find("\ndef fetch_messages():", start)
if start < 0 or end < 0:
    raise SystemExit("Could not locate sidecar task handler block; no changes made")

new = r'''def processed_key(sender,x): return sender+'|'+x.get('type','')+'|'+x.get('task_id','')
def already(k): return k in loadj(PROCESSED,{})
def mark(k):
    d=loadj(PROCESSED,{}); d[k]=time.time()
    if len(d)>1000: d=dict(sorted(d.items(),key=lambda z:z[1],reverse=True)[:800])
    savej(PROCESSED,d)

TASK_STATES = STATE / 'task_states.json'

def task_states(): return loadj(TASK_STATES,{})
def task_state(k):
    v=task_states().get(k,{})
    return v if isinstance(v,dict) else {}
def set_task_state(k,stage,**kw):
    d=task_states(); prev=d.get(k,{}) if isinstance(d.get(k,{}),dict) else {}
    d[k]={**prev,'stage':stage,'updated_at':time.time(),**kw}
    if len(d)>1000:
        d=dict(sorted(d.items(),key=lambda z:float(z[1].get('updated_at',0)) if isinstance(z[1],dict) else 0,reverse=True)[:800])
    savej(TASK_STATES,d)

def outbound_seen(mailbox,tid,kind):
    r=requests.get(f'{BASE}/r/{quote(mailbox)}',params={'format':'json','limit':200},timeout=25); r.raise_for_status()
    for m in r.json().get('messages',[]):
        if m.get('from')!=DID: continue
        x=parse(m.get('text'))
        if x and x.get('task_id')==tid and x.get('type')==kind: return True
    return False

def ensure_outbound(mailbox,kind,tid,**kw):
    if outbound_seen(mailbox,tid,kind): return False
    post(mailbox,payload(kind,tid,**kw)); return True

def transient_error(e):
    if isinstance(e,requests.HTTPError):
        status=e.response.status_code if e.response is not None else 0
        return status==429 or 500<=status<600
    return isinstance(e,requests.RequestException)

def handle(m):
    sender=m.get('from'); x=parse(m.get('text'))
    if not x or not trusted(sender): return
    k=processed_key(sender,x); typ=x['type']; tid=x['task_id']; p=peers(); reply=p.get(sender)

    if typ!='TASK':
        if already(k): return
        ledger('received',peer_did=sender,task_id=tid,message_type=typ)
        mark(k)
        return

    if already(k) or not reply: return
    st=task_state(k)
    if not st: set_task_state(k,'RECEIVED',peer_did=sender)

    ack_new=ensure_outbound(reply,'ACK',tid,accepted=True)
    set_task_state(k,'ACKED',peer_did=sender)
    if ack_new: ledger('task_accepted',peer_did=sender,task_id=tid)

    if outbound_seen(reply,tid,'RESULT'):
        mark(k); set_task_state(k,'COMPLETE',peer_did=sender,recovered=True)
        ledger('task_recovered_complete',peer_did=sender,task_id=tid)
        return

    goal=str(x.get('goal',''))[:3500]
    set_task_state(k,'RUNNING',peer_did=sender)
    try:
        result=ai('A2A task:\n'+goal)[:2600]; status='ok'
    except Exception as e:
        if transient_error(e):
            set_task_state(k,'RETRY',peer_did=sender,error=str(e)[:300])
            ledger('task_retry',peer_did=sender,task_id=tid,error=str(e)[:300])
            raise
        result=str(e)[:600]; status='error'

    ensure_outbound(reply,'RESULT',tid,status=status,result=result)
    h=hashlib.sha256(result.encode()).hexdigest()
    set_task_state(k,'RESULT_SENT',peer_did=sender,status=status,result_sha256=h)
    ledger('result',peer_did=sender,task_id=tid,status=status,result_sha256=h)
    mark(k); set_task_state(k,'COMPLETE',peer_did=sender,status=status)
'''

p.write_text(s[:start] + new + s[end:])
print('patched:',p)
PY

"$ROOT/venv/bin/python" -m py_compile "$AGENT"
chmod 0700 "$AGENT"

if command -v tc-collab-start >/dev/null 2>&1; then
  tc-collab-start
else
  echo "tc-collab-start missing; start your existing sidecar runner manually"
fi
sleep 3

echo "=== V2.3 RELIABLE TASK STATE ==="
tc-collab-status || true
if command -v tc-collab-process-status >/dev/null 2>&1; then tc-collab-process-status || true; fi
echo "task_states: $ROOT/state/task_states.json"
echo "remote ACK/RESULT lookup suppresses replay duplicates"
echo "v2.3 applied. DID/key/mailbox/role/AI/peer config unchanged."
