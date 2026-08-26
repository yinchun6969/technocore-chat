#!/usr/bin/env bash
set -Eeuo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run as root'; exit 1; }

AROOT=/opt/technocore-autonomy
mkdir -p "$AROOT/bin" "$AROOT/state" "$AROOT/log"
chmod 0700 "$AROOT" "$AROOT/bin" "$AROOT/state" "$AROOT/log"

NODE=''; AGENT_ROOT=''; PY=''; PROV=''
if [[ -f /opt/technocore-collab/.env ]]; then
  AGENT_ROOT=/opt/technocore-collab
  set -a; source "$AGENT_ROOT/.env"; set +a
  NODE="${AGENT_NAME:-unknown}"
  PY="$AGENT_ROOT/venv/bin/python"
  PROV="$AGENT_ROOT/state/provenance.jsonl"
  [[ "$NODE" == love8 || "$NODE" == aizong ]] || { echo "Unsupported collab node: $NODE"; exit 1; }
  if ! command -v tc-collab-workflow-recover >/dev/null 2>&1; then
    curl -fsSL https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-collab-v2/deploy/a2a-v3/install-workflow-endgame-recovery-v3.4.sh -o /tmp/endgame-v34.sh
    bash /tmp/endgame-v34.sh
  fi
elif [[ -f /opt/technocore-a2a/.env ]]; then
  AGENT_ROOT=/opt/technocore-a2a
  set -a; source "$AGENT_ROOT/.env"; set +a
  NODE=ai2ai
  PY="$AGENT_ROOT/venv/bin/python"
  PROV="$AGENT_ROOT/state/provenance.jsonl"
  if ! command -v tc-a2a-workflow-retry-challenge >/dev/null 2>&1; then
    curl -fsSL https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-deploy-v1/deploy/a2a-v1/harden-workflow-envelope-recover-v2.0.sh -o /tmp/a2a-v20.sh
    bash /tmp/a2a-v20.sh
  fi
else
  echo 'No supported Technocore A2A node found'; exit 1
fi
[[ -x "$PY" ]] || { echo "Missing Python runtime: $PY"; exit 1; }

cat > "$AROOT/autonomy.env" <<EOF
AUTO_NODE=$NODE
AUTO_ENABLED=0
AUTO_SCAN_INTERVAL=300
AUTO_MIN_WORKFLOW_GAP=5400
AUTO_DAILY_MAX=8
AUTO_RECOVER_AFTER=180
AUTO_RECOVERY_COOLDOWN=900
AUTO_SOURCE_LOOKBACK=5
AUTO_QUALITY_MIN=75
AUTO_CANONICAL_WF=wf-1787757470-5f882e70e2
AUTO_AGENT_ROOT=$AGENT_ROOT
AUTO_PROVENANCE=$PROV
EOF
chmod 0600 "$AROOT/autonomy.env"

cat > "$AROOT/bin/autonomy.py" <<'PY'
#!/usr/bin/env python3
import os, sys, json, time, hashlib, random, subprocess, re
from pathlib import Path
from urllib.parse import quote
import requests

AROOT=Path('/opt/technocore-autonomy'); STATE=AROOT/'state'; LOG=AROOT/'log'/'autonomy.jsonl'
NODE=os.environ.get('AUTO_NODE','unknown')
BASE='https://technocore.chat'
LOVE8='did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p'
AIZONG='did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e'
AI2AI='did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje'
LOVE8_MB='mb-p-610459b4e1262e4a95dce4ec'; AI2AI_MB='mb-p-611da800aa892112c88cd6da6e0fc065'; AIZONG_ROOM='d-aizong'
S=requests.Session(); S.headers['User-Agent']='technocore-a2a-autonomy/4.0'

def now(): return time.time()
def log(event,**kw):
    row={'ts':now(),'node':NODE,'event':event,**kw}
    with LOG.open('a') as f: f.write(json.dumps(row,separators=(',',':'))+'\n')

def load(name,default):
    p=STATE/name
    try: return json.loads(p.read_text())
    except Exception: return default

def save(name,obj):
    p=STATE/name; t=p.with_suffix('.tmp'); t.write_text(json.dumps(obj,indent=2,sort_keys=True)); os.replace(t,p)

def room(room):
    err=None
    for n in range(4):
        try:
            r=S.get(f'{BASE}/r/{quote(room)}',params={'format':'json','limit':200},timeout=25)
            if r.status_code in (429,500,502,503,504): time.sleep(min(10,2**n)); continue
            r.raise_for_status(); return r.json().get('messages',[])
        except Exception as e:
            err=e; time.sleep(min(10,2**n))
    raise RuntimeError(f'room read failed {room}: {err}')

def parse(m):
    t=m.get('text')
    if not isinstance(t,str) or not t.startswith('A2A1 '): return None
    try: return json.loads(t[5:])
    except Exception: return None

def hits(msgs,sender,kind):
    out=[]
    for m in msgs:
        if m.get('from')!=sender: continue
        o=parse(m)
        if o and o.get('type')==kind and str(o.get('task_id','')).startswith('wf-'):
            try: seq=int(m.get('seq',0))
            except Exception: seq=0
            out.append((seq,o))
    return sorted(out,key=lambda z:z[0],reverse=True)

def has(msgs,sender,kind,wf):
    return any(o.get('task_id')==wf for _,o in hits(msgs,sender,kind))

def run(cmd,timeout=240):
    p=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout)
    log('command',cmd=' '.join(cmd),rc=p.returncode,out=(p.stdout+p.stderr)[-1000:])
    return p.returncode,(p.stdout+p.stderr)

def recover_once(key,cmd):
    st=load('recoveries.json',{})
    t=now(); cooldown=int(os.environ.get('AUTO_RECOVERY_COOLDOWN','900'))
    if t-float(st.get(key,0)) < cooldown: return
    st[key]=t; save('recoveries.json',st)
    rc,out=run(cmd)
    log('recovery_attempt',key=key,rc=rc,out=out[-600:])

def watchdog():
    seen=load('watch_seen.json',{}); t=now(); after=int(os.environ.get('AUTO_RECOVER_AFTER','180'))
    try:
        da=room(AIZONG_ROOM); lm=room(LOVE8_MB); am=room(AI2AI_MB)
    except Exception as e:
        log('watch_read_error',error=str(e)); return
    if NODE=='ai2ai':
        for _,o in hits(am,AIZONG,'BUILD_RESULT')[:5]:
            wf=o.get('task_id'); key='build:'+wf
            seen.setdefault(key,t)
            if not has(da,AI2AI,'CHALLENGE',wf) and t-seen[key]>=after:
                recover_once('challenge:'+wf,['tc-a2a-workflow-retry-challenge',wf])
    elif NODE=='aizong':
        for _,o in hits(da,AI2AI,'CHALLENGE')[:5]:
            wf=o.get('task_id'); key='challenge:'+wf
            seen.setdefault(key,t)
            if not has(lm,AIZONG,'REVISED_RESULT',wf) and t-seen[key]>=after:
                recover_once('revision:'+wf,['tc-collab-workflow-recover','revision',wf])
    elif NODE=='love8':
        for _,o in hits(lm,AIZONG,'REVISED_RESULT')[:5]:
            wf=o.get('task_id'); key='revised:'+wf
            seen.setdefault(key,t)
            done=has(da,LOVE8,'COMPLETE',wf) and has(am,LOVE8,'COMPLETE',wf)
            if not done and t-seen[key]>=after:
                recover_once('finalize:'+wf,['tc-collab-workflow-recover','finalize',wf])
    # keep state bounded
    if len(seen)>200: seen=dict(sorted(seen.items(),key=lambda z:z[1],reverse=True)[:120])
    save('watch_seen.json',seen)

def provenance():
    p=Path(os.environ.get('AUTO_PROVENANCE',''))
    rows=[]
    if not p.exists(): return rows
    for line in p.read_text(errors='ignore').splitlines()[-2000:]:
        try: rows.append(json.loads(line))
        except Exception: pass
    return rows

def inflight(rows):
    starts=[r for r in rows if r.get('event')=='workflow_started' and str(r.get('workflow_id','')).startswith('wf-')]
    if not starts: return None
    last=max(starts,key=lambda r:float(r.get('ts',0)))
    wf=last.get('workflow_id')
    done=any(r.get('workflow_id')==wf and r.get('event') in ('workflow_complete','workflow_complete_recovered') for r in rows)
    return None if done else wf

def ai(prompt,max_tokens=420):
    url=os.environ.get('AI_BASE_URL','').strip(); model=os.environ.get('AI_MODEL','').strip(); key=os.environ.get('AI_API_KEY','')
    hdr=os.environ.get('AI_KEY_HEADER','Authorization'); pref=os.environ.get('AI_KEY_PREFIX','Bearer').strip()
    if not (url and model and key): raise RuntimeError('missing AI endpoint/model/key')
    auth=(pref+' '+key).strip() if pref else key
    headers={'Content-Type':'application/json',hdr:auth}
    body={'model':model,'messages':[{'role':'user','content':prompt}],'max_tokens':max_tokens}
    r=requests.post(url,headers=headers,json=body,timeout=90); r.raise_for_status()
    j=r.json(); return j['choices'][0]['message']['content'].strip()

def source_digest():
    look=max(2,min(10,int(os.environ.get('AUTO_SOURCE_LOOKBACK','5'))))
    parts=[]
    try:
        r=S.get('https://api.github.com/repos/flop-labs/technocore-chat/commits',params={'per_page':look},timeout=25)
        if r.ok:
            for c in r.json()[:look]:
                msg=(c.get('commit',{}).get('message') or '').splitlines()[0][:180]
                parts.append('COMMIT '+c.get('sha','')[:12]+' '+msg)
            if r.json():
                sha=r.json()[0].get('sha')
                d=S.get(f'https://api.github.com/repos/flop-labs/technocore-chat/commits/{sha}',timeout=25)
                if d.ok:
                    for f in d.json().get('files',[])[:3]:
                        patch=(f.get('patch') or '')[:650].replace('\x00','')
                        parts.append('PATCH '+f.get('filename','')+' '+patch)
        p=S.get('https://api.github.com/repos/flop-labs/technocore-chat/pulls',params={'state':'open','per_page':look},timeout=25)
        if p.ok:
            for x in p.json()[:look]: parts.append(f'OPEN_PR #{x.get("number")} {(x.get("title") or "")[:180]}')
    except Exception as e:
        log('source_error',error=str(e))
    return '\n'.join(parts)[:7000]

def director():
    if NODE!='love8': return
    if os.environ.get('AUTO_ENABLED','0')!='1': return
    if not (STATE/'rc4_verified').exists():
        log('director_blocked',reason='rc4 gate missing'); return
    rows=provenance(); active=inflight(rows)
    if active:
        log('director_wait',reason='workflow_inflight',workflow_id=active); return
    st=load('director.json',{'history':[],'starts':[]})
    t=now(); min_gap=int(os.environ.get('AUTO_MIN_WORKFLOW_GAP','5400')); daily=int(os.environ.get('AUTO_DAILY_MAX','8'))
    starts=[x for x in st.get('starts',[]) if t-float(x.get('ts',0))<86400]
    if starts and t-max(float(x.get('ts',0)) for x in starts)<min_gap: return
    if len(starts)>=daily: return
    digest=source_digest()
    prior='\n'.join('- '+h.get('goal','')[:300] for h in st.get('history',[])[-20:])
    prompt=("You are the autonomous Scout for a three-agent Technocore engineering research workflow. "
            "Choose ONE specific, testable, useful research question. Prefer a fresh upstream change or an unresolved reliability/protocol issue. "
            "Do not optimize for token rewards, airdrops, activity, posting, or volume. Do not claim execution. Avoid duplicating prior goals. "
            "The Builder and Reviewer need enough context in the goal to reason independently. Output strict JSON only: "
            '{"goal":"...","quality":0,"reason":"..."}. quality must be 0-100.\nPUBLIC SOURCE DIGEST:\n'+
            (digest or '[source unavailable: choose a concrete reliability/conformance question based on known A2A failure classes]')+
            '\nPRIOR GOALS:\n'+(prior or '[none]'))
    try:
        raw=ai(prompt); raw=re.sub(r'^```(?:json)?|```$','',raw.strip(),flags=re.I|re.M).strip(); obj=json.loads(raw)
        goal=' '.join(str(obj.get('goal','')).split())[:1700]; quality=int(obj.get('quality',0)); reason=str(obj.get('reason',''))[:500]
    except Exception as e:
        log('candidate_error',error=str(e)); return
    blocked=('airdrop','reward farming','sybil','farm activity','post to x')
    if not goal or quality<int(os.environ.get('AUTO_QUALITY_MIN','75')) or any(x in goal.lower() for x in blocked):
        log('candidate_rejected',quality=quality,goal=goal[:300]); return
    fp=hashlib.sha256(goal.lower().encode()).hexdigest()
    if any(h.get('fingerprint')==fp for h in st.get('history',[])):
        log('candidate_duplicate',fingerprint=fp); return
    rc,out=run(['tc-collab-workflow-start',goal],timeout=180)
    if rc!=0:
        log('workflow_start_error',rc=rc,out=out[-900:]); return
    m=re.search(r'(wf-\d+-[0-9a-f]+)',out)
    if not m:
        log('workflow_start_unparsed',out=out[-900:]); return
    wf=m.group(1)
    item={'ts':t,'workflow_id':wf,'goal':goal,'quality':quality,'reason':reason,'fingerprint':fp,'source_sha256':hashlib.sha256(digest.encode()).hexdigest() if digest else None}
    st.setdefault('history',[]).append(item); st['history']=st['history'][-200:]
    starts.append({'ts':t,'workflow_id':wf}); st['starts']=starts
    save('director.json',st); log('workflow_autonomous_started',**item)

def main():
    log('daemon_start')
    while True:
        try: watchdog()
        except Exception as e: log('watchdog_exception',error=repr(e))
        try: director()
        except Exception as e: log('director_exception',error=repr(e))
        sec=max(60,int(os.environ.get('AUTO_SCAN_INTERVAL','300')))+random.randint(0,45)
        time.sleep(sec)

if __name__=='__main__': main()
PY
chmod 0700 "$AROOT/bin/autonomy.py"

cat > "$AROOT/bin/run-forever.sh" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
set -a
source "$AGENT_ROOT/.env"
source "$AROOT/autonomy.env"
set +a
exec "$PY" "$AROOT/bin/autonomy.py"
EOF
chmod 0700 "$AROOT/bin/run-forever.sh"

cat > /usr/local/bin/tc-autonomy-status <<'EOF'
#!/usr/bin/env bash
set -e
A=/opt/technocore-autonomy
source "$A/autonomy.env"
echo "node: $AUTO_NODE"
echo "enabled: $AUTO_ENABLED"
echo "rc4_gate: $([[ -f $A/state/rc4_verified ]] && echo VERIFIED || echo MISSING)"
if [[ -f $A/state/autonomy.pid ]] && kill -0 "$(cat $A/state/autonomy.pid)" 2>/dev/null; then echo "daemon: ACTIVE pid=$(cat $A/state/autonomy.pid)"; elif command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet technocore-autonomy 2>/dev/null; then echo 'daemon: ACTIVE(systemd)'; else echo 'daemon: INACTIVE'; fi
tail -n 8 "$A/log/autonomy.jsonl" 2>/dev/null || true
EOF
chmod 0755 /usr/local/bin/tc-autonomy-status

cat > /usr/local/bin/tc-autonomy-enable <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
A=/opt/technocore-autonomy
source "$A/autonomy.env"
[[ "$AUTO_NODE" == love8 ]] || { echo 'Only love8 Scout starts autonomous research workflows; other nodes run recovery watchdog only.'; exit 1; }
VERIFY=https://raw.githubusercontent.com/yinchun6969/technocore-chat/a2a-rc4-autonomous/deploy/a2a-v4/verify-rc4.sh
curl -fsSL "$VERIFY" -o /tmp/verify-rc4.sh
chmod +x /tmp/verify-rc4.sh
/tmp/verify-rc4.sh "$AUTO_CANONICAL_WF"
touch "$A/state/rc4_verified"; chmod 0600 "$A/state/rc4_verified"
sed -i 's/^AUTO_ENABLED=.*/AUTO_ENABLED=1/' "$A/autonomy.env"
echo 'AUTONOMOUS_RESEARCH_ENABLED'
echo 'Default policy: one workflow at a time, >=90m gap, max 8/day, quality>=75.'
EOF
chmod 0755 /usr/local/bin/tc-autonomy-enable

cat > /usr/local/bin/tc-autonomy-disable <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
sed -i 's/^AUTO_ENABLED=.*/AUTO_ENABLED=0/' /opt/technocore-autonomy/autonomy.env
echo 'AUTONOMOUS_RESEARCH_DISABLED (recovery watchdog remains running)'
EOF
chmod 0755 /usr/local/bin/tc-autonomy-disable

# Stop previous autonomy process/service before replacing it.
if command -v systemctl >/dev/null 2>&1 && systemctl show-environment >/dev/null 2>&1; then
  cat > /etc/systemd/system/technocore-autonomy.service <<EOF
[Unit]
Description=Technocore A2A 24/7 autonomous research and recovery watchdog
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$AROOT/bin/run-forever.sh
Restart=always
RestartSec=20
User=root
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now technocore-autonomy
  sleep 2
else
  if [[ -f "$AROOT/state/autonomy.pid" ]]; then kill "$(cat "$AROOT/state/autonomy.pid")" 2>/dev/null || true; fi
  nohup "$AROOT/bin/run-forever.sh" >>"$AROOT/log/stdout.log" 2>&1 &
  echo $! > "$AROOT/state/autonomy.pid"
  chmod 0600 "$AROOT/state/autonomy.pid"
  sleep 2
fi

echo '=== AUTONOMOUS RESEARCH v4.0 INSTALLED ==='
echo "node: $NODE"
echo 'mode: recovery watchdog ACTIVE; autonomous Scout director gated OFF until RC4 verification'
echo 'research policy: one workflow at a time; 90m minimum gap; max 8/day; quality threshold 75'
echo 'publication policy: no automatic GitHub PR, X post, airdrop/reward farming, or public promotion'
tc-autonomy-status
