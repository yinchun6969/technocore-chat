#!/usr/bin/env bash
set -Eeuo pipefail

WF_ID="${1:-wf-1787757470-5f882e70e2}"
[[ "$WF_ID" == wf-* ]] || { echo 'usage: verify-rc4.sh [wf-id]'; exit 2; }

BASE='https://technocore.chat'
LOVE8='did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p'
AIZONG='did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e'
AI2AI='did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje'
LOVE8_MB='mb-p-610459b4e1262e4a95dce4ec'
AI2AI_MB='mb-p-611da800aa892112c88cd6da6e0fc065'
AIZONG_ROOM='d-aizong'

PY=''
if [[ -x /opt/technocore-collab/venv/bin/python ]]; then PY=/opt/technocore-collab/venv/bin/python; fi
if [[ -z "$PY" && -x /opt/technocore-a2a/venv/bin/python ]]; then PY=/opt/technocore-a2a/venv/bin/python; fi
[[ -n "$PY" ]] || { echo 'No Technocore agent Python runtime found'; exit 1; }

"$PY" - "$WF_ID" "$BASE" "$LOVE8" "$AIZONG" "$AI2AI" "$LOVE8_MB" "$AI2AI_MB" "$AIZONG_ROOM" <<'PY'
import json, sys, time, hashlib
from pathlib import Path
from urllib.parse import quote
import requests

wf,base,love8,aizong,ai2ai,love8_mb,ai2ai_mb,aizong_room=sys.argv[1:]
S=requests.Session(); S.headers['User-Agent']='a2a-rc4-verifier/1.0'

def get_room(room):
    err=None
    for n in range(5):
        try:
            r=S.get(f'{base}/r/{quote(room)}',params={'format':'json','limit':200},timeout=30)
            if r.status_code in (429,500,502,503,504):
                time.sleep(min(12,2**n)); continue
            r.raise_for_status(); return r.json().get('messages',[])
        except Exception as e:
            err=e; time.sleep(min(12,2**n))
    raise RuntimeError(f'room read failed {room}: {err}')

def parse(msg):
    text=msg.get('text')
    if not isinstance(text,str) or not text.startswith('A2A1 '): return None
    try:
        obj=json.loads(text[5:])
    except Exception:
        return None
    if obj.get('task_id')!=wf: return None
    return obj

def find(room_msgs,sender,kind):
    hits=[]
    for m in room_msgs:
        if m.get('from')!=sender: continue
        o=parse(m)
        if o and o.get('type')==kind:
            try: seq=int(m.get('seq',0))
            except Exception: seq=0
            hits.append((seq,m,o))
    return max(hits,key=lambda x:x[0]) if hits else None

rooms={aizong_room:get_room(aizong_room), love8_mb:get_room(love8_mb), ai2ai_mb:get_room(ai2ai_mb)}
req=[
 ('WORKFLOW_TASK',aizong_room,love8),
 ('BUILD_RESULT',ai2ai_mb,aizong),
 ('CHALLENGE',aizong_room,ai2ai),
 ('REVISED_RESULT',love8_mb,aizong),
 ('COMPLETE_TO_BUILDER',aizong_room,love8,'COMPLETE'),
 ('COMPLETE_TO_REVIEWER',ai2ai_mb,love8,'COMPLETE'),
]
found={}; missing=[]
for row in req:
    label,room,sender=row[:3]; kind=row[3] if len(row)>3 else label
    h=find(rooms[room],sender,kind)
    if not h:
        missing.append(label); continue
    seq,msg,obj=h
    text=msg.get('text','')
    found[label]={'room':room,'seq':seq,'from':sender,'type':kind,'wire_sha256':hashlib.sha256(text.encode()).hexdigest()}

print('=== A2A-RC-1.0 RC4 REMOTE VERIFICATION ===')
print('workflow:',wf)
for label in [x[0] for x in req]:
    if label in found:
        x=found[label]; print(f'{label}: PASS room={x["room"]} seq={x["seq"]} sha256={x["wire_sha256"][:16]}')
    else:
        print(f'{label}: MISSING')

# Local evidence gate for whichever node this verifier runs on.
node='unknown'; prov=None; required=[]
if Path('/opt/technocore-collab/.env').exists():
    env={}
    for line in Path('/opt/technocore-collab/.env').read_text(errors='ignore').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1); env[k.strip()]=v.strip().strip('"').strip("'")
    node=env.get('AGENT_NAME','unknown')
    prov=Path('/opt/technocore-collab/state/provenance.jsonl')
    if node=='love8': required=['workflow_complete','workflow_complete_recovered']
    elif node=='aizong': required=['workflow_revised_result','workflow_revised_result_recovered']
elif Path('/opt/technocore-a2a/.env').exists():
    node='ai2ai'; prov=Path('/opt/technocore-a2a/state/provenance.jsonl'); required=['workflow_complete_received']

local_ok=False; matched=[]
if prov and prov.exists():
    for line in prov.read_text(errors='ignore').splitlines():
        if wf not in line: continue
        try: o=json.loads(line)
        except Exception: continue
        ev=o.get('event','')
        if ev in required: matched.append(ev)
    local_ok=bool(matched)
print('node:',node)
print('local_terminal_evidence:', 'PASS '+','.join(sorted(set(matched))) if local_ok else 'PENDING')

receipt={
 'spec':'A2A-RC-1.0','candidate':'RC4','workflow_id':wf,'remote_verified':not missing,
 'local_node':node,'local_terminal_verified':local_ok,'missing':missing,'stages':found,'verified_at':int(time.time())
}
out=Path('/tmp/a2a-rc4-verification.json'); out.write_text(json.dumps(receipt,indent=2,sort_keys=True))
print('receipt:',out)
if missing:
    print('RC4_NOT_VERIFIED: missing remote terminal stages:',','.join(missing)); raise SystemExit(3)
print('RC4_REMOTE_CHAIN_VERIFIED')
if local_ok:
    print('RC4_LOCAL_NODE_VERIFIED')
else:
    raise SystemExit(4)
PY
