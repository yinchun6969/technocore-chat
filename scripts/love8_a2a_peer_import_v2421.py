#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, re, time, urllib.request
from pathlib import Path
VERSION="2.4.2.1"
ROOT=Path('/opt/love8-agent'); SOCIAL=ROOT/'social'; OUT=SOCIAL/'a2a-peers-v242.json'; LOVE8_CFG=SOCIAL/'config.env'
A2A=Path('/opt/technocore-a2a'); STRATEGY=A2A/'strategy.json'; ENV=A2A/'.env'; PROV=A2A/'state/provenance.jsonl'
DID_RE=re.compile(r'did:key:z6Mk[1-9A-HJ-NP-Za-km-z]+'); MB_RE=re.compile(r'mb-p-[a-z0-9_-]{8,47}|mb-[a-z0-9_-]{8,47}',re.I)
def env_keys(path,allowed):
    out={}
    if not path.exists():return out
    for raw in path.read_text(encoding='utf-8',errors='ignore').splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        k,v=line.split('=',1);k=k.strip();v=v.strip().strip(chr(34)+chr(39))
        if k in allowed:out[k]=v
    return out
def fp(did):return hashlib.sha256(did.encode()).hexdigest()[:16]
def role(name):
    n=name.lower()
    if 'aizong' in n:return 'builder'
    if 'ai2ai' in n:return 'reviewer/challenger'
    return 'a2a-peer'
def load_json(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default
def save_json(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.chmod(0o600);tmp.replace(path)
def add(found,did,name='',mailbox='',source=''):
    if not isinstance(did,str) or not did.startswith('did:key:'):return
    rec=found.setdefault(did,{'did':did,'name':'','mailbox':'','sources':[]})
    if name and (not rec['name'] or rec['name'].startswith('peer-')):rec['name']=name[:40]
    if mailbox and mailbox.startswith('mb-'):rec['mailbox']=mailbox[:64]
    if source and source not in rec['sources']:rec['sources'].append(source)
def walk_strategy(obj,found,path='strategy'):
    if isinstance(obj,dict):
        # Canonical v1 shape: a2a.allowed_dids plus pinned mailbox mappings.
        allowed=obj.get('allowed_dids')
        if isinstance(allowed,list):
            for d in allowed:
                if isinstance(d,str):add(found,d,source=path+'.allowed_dids')
        for k,v in obj.items():
            lk=str(k).lower()
            if isinstance(k,str) and k.startswith('did:key:'):
                if isinstance(v,str):
                    m=MB_RE.search(v);add(found,k,mailbox=m.group(0) if m else '',source=path+'.did_map')
                elif isinstance(v,dict):
                    name=str(v.get('name') or v.get('nick') or v.get('agent') or '')
                    mb=str(v.get('mailbox') or v.get('mb') or '')
                    add(found,k,name,mb,source=path+'.did_map')
            if lk in {'peer_mailboxes','mailboxes','pinned_mailboxes','did_mailboxes','peers','allowed_peers'}:
                if isinstance(v,dict):
                    for dk,dv in v.items():
                        if isinstance(dk,str) and dk.startswith('did:key:'):
                            if isinstance(dv,str):add(found,dk,mailbox=dv,source=path+'.'+lk)
                            elif isinstance(dv,dict):add(found,dk,str(dv.get('name') or dv.get('nick') or ''),str(dv.get('mailbox') or ''),source=path+'.'+lk)
                elif isinstance(v,list):
                    for item in v:
                        if isinstance(item,dict):
                            did=str(item.get('did') or '')
                            add(found,did,str(item.get('name') or item.get('nick') or ''),str(item.get('mailbox') or ''),source=path+'.'+lk)
            walk_strategy(v,found,path+'.'+str(k))
    elif isinstance(obj,list):
        for i,v in enumerate(obj):walk_strategy(v,found,path+f'[{i}]')
def scan_provenance(found):
    if not PROV.exists():return
    for line in PROV.read_text(encoding='utf-8',errors='ignore').splitlines()[-5000:]:
        try:o=json.loads(line)
        except Exception:continue
        text=json.dumps(o,ensure_ascii=False)
        ds=DID_RE.findall(text);mbs=MB_RE.findall(text)
        name='aizong' if 'aizong' in text.lower() else 'ai2ai' if 'ai2ai' in text.lower() else ''
        if len(ds)==1:add(found,ds[0],name,mbs[0] if len(mbs)==1 else '',source='provenance')
def profile_hint(did):
    # Best-effort metadata only. For routing, pinned mailbox from strategy remains preferred.
    f=fp(did);urls=[f'https://technocore.chat/kv/did-{f[:2]}/{f[2:]}',f'https://technocore.chat/kv/did/{f}']
    for url in urls:
        try:
            req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'love8-a2a-import/2.4.2.1'})
            with urllib.request.urlopen(req,timeout=8) as r:raw=r.read().decode('utf-8','replace')
        except Exception:continue
        try:o=json.loads(raw)
        except Exception:o={}
        value=o.get('value','') if isinstance(o,dict) else ''
        if isinstance(value,dict):text=json.dumps(value,ensure_ascii=False)
        else:text=str(value)
        mb=MB_RE.search(text);name=''
        for key in ('nick','name','agent'):
            m=re.search(rf'"?{key}"?\s*[:=]\s*"?([a-zA-Z0-9_-]{{1,40}})',text,re.I)
            if m:name=m.group(1);break
        if not name:
            low=text.lower();name='aizong' if 'aizong' in low else 'ai2ai' if 'ai2ai' in low else ''
        return name,mb.group(0) if mb else ''
    return '',''
def main():
    love8=env_keys(LOVE8_CFG,{'DID'}).get('DID','');found={}
    # Local A2A node itself may be Aizong/AI2AI and is a valid internal peer if its DID != Love8.
    local=env_keys(ENV,{'AGENT_NAME','NICK','DID','MAILBOX','AGENT_DID','AGENT_MAILBOX'})
    local_did=local.get('DID') or local.get('AGENT_DID') or ''
    local_name=local.get('AGENT_NAME') or local.get('NICK') or ''
    local_mb=local.get('MAILBOX') or local.get('AGENT_MAILBOX') or ''
    add(found,local_did,local_name,local_mb,'a2a.env')
    st=load_json(STRATEGY,{})
    if isinstance(st,dict):walk_strategy(st.get('a2a',st),found)
    scan_provenance(found)
    # Exclude Love8 itself; enrich only missing display/routing metadata.
    found.pop(love8,None)
    for did,rec in list(found.items()):
        if not rec['name'] or not rec['mailbox']:
            n,m=profile_hint(did)
            if n and not rec['name']:rec['name']=n;rec['sources'].append('profile_hint')
            if m and not rec['mailbox']:rec['mailbox']=m;rec['sources'].append('profile_hint_untrusted_routing_fallback')
        if not rec['name']:rec['name']='peer-'+fp(did)[:6]
    existing=load_json(OUT,{'schema':'love8-a2a-peers-v1','peers':[]});old={p.get('did'):p for p in existing.get('peers',[]) if isinstance(p,dict) and p.get('did')}
    peers=[]
    for did,rec in found.items():
        prev=old.get(did,{})
        name=rec['name'] or prev.get('name') or 'peer-'+fp(did)[:6]
        mailbox=rec['mailbox'] or prev.get('mailbox') or ''
        peers.append({'name':name,'did':did,'fingerprint':fp(did),'mailbox':mailbox,'role':role(name),'source':','.join(rec['sources'])[:240],'updated_at':int(time.time())})
    peers.sort(key=lambda p:(0 if p['role']=='builder' else 1 if 'reviewer' in p['role'] else 2,p['name']))
    save_json(OUT,{'schema':'love8-a2a-peers-v1','version':VERSION,'peers':peers[:20]})
    print('===== LOVE8 A2A PEER IMPORT v2.4.2.1 =====')
    print('strategy_exists:',STRATEGY.exists());print('a2a_env_exists:',ENV.exists());print('provenance_exists:',PROV.exists());print('love8_excluded:',bool(love8));print('peers_imported:',len(peers))
    for p in peers:print(f"{p['name']} role={p['role']} fp={p['fingerprint']} mailbox={p['mailbox'] or '-'} source={p['source']}")
    if len(peers)<2:
        print('NEED_PEERS: expected at least 2 internal A2A peers. Use: love8-a2a-peer-add NAME DID [MAILBOX]')
        return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
