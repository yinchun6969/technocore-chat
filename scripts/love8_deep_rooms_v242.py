#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,importlib.util,json,os,re,secrets,subprocess,time,urllib.parse,shutil
from pathlib import Path
VERSION="2.4.2"
ROOT=Path("/opt/love8-agent");SOCIAL=ROOT/"social";STATE=ROOT/"state";MEMORY=ROOT/"memory"
CFG=SOCIAL/"config.env";PERSIST=SOCIAL/"persistent.env";GUARD_PATH=SOCIAL/"love8_social.py";PEERS=SOCIAL/"a2a-peers-v242.json";WORKING=STATE/"working-set-v242.json";DEEP=STATE/"deep-rooms-v242.json";TOPICS=MEMORY/"topics.json";SOCIAL_STATE=STATE/"social-v2.json"
DID_RE=re.compile(r"did:key:z6Mk[1-9A-HJ-NP-Za-km-z]+");MAIL_RE=re.compile(r"mb-p-[a-z0-9_-]{8,47}|mb-[a-z0-9_-]{8,47}");SENSITIVE=("secret","private","identity.pem","api_key","apikey","password","token","key.pem")
def load_json(p,d):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return d
def save_json(p,d):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+".tmp");t.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");t.chmod(0o600);os.replace(t,p)
def load_env(p):
    out={}
    if not p.exists():return out
    for raw in p.read_text(encoding="utf-8").splitlines():
        line=raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k,v=line.split("=",1);out[k.strip()]=v.strip().strip(chr(34)+chr(39))
    return out
def guard():
    s=importlib.util.spec_from_file_location("love8_guard_v242_deep",GUARD_PATH);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def fp(did):return hashlib.sha256(did.encode()).hexdigest()[:16]
def role_for(name):
    n=name.lower()
    if "aizong" in n:return "builder"
    if "ai2ai" in n:return "reviewer/challenger"
    if "love8" in n:return "scout"
    return "a2a-peer"
def record_peer(name,did,mailbox=""):
    d=load_json(PEERS,{"schema":"love8-a2a-peers-v1","peers":[]});peers=d.setdefault("peers",[]);own=load_env(CFG).get("DID","")
    if not did.startswith("did:key:") or did==own:return False
    rec={"name":name[:40] or ("peer-"+fp(did)[:6]),"did":did,"fingerprint":fp(did),"mailbox":mailbox[:64],"role":role_for(name),"updated_at":int(time.time())}
    for i,p in enumerate(peers):
        if isinstance(p,dict) and p.get("did")==did:
            old=dict(p);old.update({k:v for k,v in rec.items() if v});peers[i]=old;save_json(PEERS,d);return True
    peers.append(rec);d["peers"]=peers[:20];save_json(PEERS,d);return True
def extract_json_objects(obj,path=""):
    out=[]
    if isinstance(obj,dict):
        dids=[];mailboxes=[];names=[]
        for k,v in obj.items():
            lk=str(k).lower()
            if isinstance(v,str):
                if "did" in lk:dids+=DID_RE.findall(v)
                if "mail" in lk:mailboxes+=MAIL_RE.findall(v)
                if lk in {"name","nick","agent","peer","agent_name","peer_name"}:names.append(v)
        if dids:
            name=str(names[0] if names else Path(path).stem);mb=str(mailboxes[0] if len(mailboxes)==1 else "")
            for did in dids:out.append((name,did,mb))
        for v in obj.values():out+=extract_json_objects(v,path)
    elif isinstance(obj,list):
        for v in obj:out+=extract_json_objects(v,path)
    return out
def import_peers():
    roots=[Path("/opt/technocore-collab"),Path("/opt/technocore-a2a")];found=[]
    for root in roots:
        if not root.exists():continue
        count=0
        for p in root.rglob("*"):
            if count>=250:break
            if not p.is_file() or p.stat().st_size>1024*1024:continue
            low=p.name.lower()
            if any(x in low for x in SENSITIVE) or p.suffix.lower() in {".pem",".key"}:continue
            if p.suffix.lower() not in {".json",".env",".conf",".txt",".md",""}:continue
            count+=1
            try:text=p.read_text(encoding="utf-8",errors="ignore")
            except Exception:continue
            try:found+=extract_json_objects(json.loads(text),str(p))
            except Exception:
                dids=DID_RE.findall(text);mbs=MAIL_RE.findall(text)
                if len(dids)==1:
                    name="aizong" if "aizong" in text.lower() else "ai2ai" if "ai2ai" in text.lower() else p.stem;found.append((name,dids[0],mbs[0] if len(mbs)==1 else ""))
    tool=shutil.which("tc-a2a-peer-list")
    if tool:
        try:
            output=subprocess.run([tool],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=20).stdout
            for line in output.splitlines():
                ds=DID_RE.findall(line);mbs=MAIL_RE.findall(line)
                if ds:
                    low=line.lower();name="aizong" if "aizong" in low else "ai2ai" if "ai2ai" in low else "a2a-peer"
                    for did in ds:found.append((name,did,mbs[0] if mbs else ""))
        except Exception:pass
    unique={}
    for name,did,mb in found:
        if did not in unique or mb:unique[did]=(name,did,mb)
    n=0
    for item in unique.values():
        if record_peer(*item):n+=1
    return n
def peer_rows():
    d=load_json(PEERS,{});return [p for p in d.get("peers",[]) if isinstance(p,dict)] if isinstance(d,dict) else []
def internal_ids(g):
    out=set()
    for p in peer_rows():
        try:out.add(g.peer_id(str(p.get("did",""))))
        except Exception:pass
    return out
def send_invite(g,conf,social,peer,text):
    mb=str(peer.get("mailbox","") or "")
    if mb.startswith("mb-"):
        try:g.signed_post(conf["BASE"].rstrip("/"),conf["DID"],conf["KEY"],mb,text,social);social.setdefault("writes",[]).append(time.time());return True,"direct-mailbox"
        except Exception as exc:return False,f"{type(exc).__name__}: {exc}"[:200]
    binary=Path("/usr/local/bin/love8-reply")
    if binary.exists() and peer.get("fingerprint"):
        try:
            r=subprocess.run([str(binary),str(peer["fingerprint"]),text],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=45);return r.returncode==0,(r.stdout[-180:].strip() or f"rc={r.returncode}")
        except Exception as exc:return False,f"{type(exc).__name__}: {exc}"[:200]
    return False,"no mailbox/resolver"
def monitor(g,conf,state):
    now=int(time.time())
    for r in state.get("rooms",[]) if isinstance(state.get("rooms"),list) else []:
        if not isinstance(r,dict) or r.get("status") not in {"forming","active"}:continue
        room=str(r.get("room",""));since=int(r.get("last_seq",r.get("first_seq",0)) or 0)
        try:data=g.http_json(f"{conf['BASE'].rstrip('/')}/r/{urllib.parse.quote(room,safe='')}?since={since}&limit=200&format=json")
        except Exception:continue
        msgs=[m for m in data.get("messages",[]) if isinstance(m,dict)]
        if msgs:
            r["last_seq"]=max(int(m.get("seq",0) or 0) for m in msgs);r["last_activity_at"]=now;r["status"]="active";authors=set(r.get("participant_dids",[]))
            for m in msgs:
                a=str(m.get("from","") or "")
                if a.startswith("did:key:"):authors.add(a)
            r["participant_dids"]=sorted(authors)
        external=set(r.get("external_dids",[]))
        if external & set(r.get("participant_dids",[])):r["external_joined"]=True
        if now-int(r.get("created_at",now) or now)>24*3600 and not r.get("external_joined"):r["status"]="no-external-response"
        elif now-int(r.get("last_activity_at",r.get("created_at",now)) or now)>48*3600:r["status"]="idle"
def topic_table():
    d=load_json(TOPICS,{});return d.get("topics",{}) if isinstance(d,dict) and isinstance(d.get("topics"),dict) else {}
def choose_external(g,conf,state):
    ws=load_json(WORKING,{});rows=ws.get("working_set",[]) if isinstance(ws,dict) and isinstance(ws.get("working_set"),list) else [];internal=internal_ids(g);topics=topic_table();best=None;existing=state.get("rooms",[]) if isinstance(state.get("rooms"),list) else [];now=int(time.time())
    for x in rows:
        if not isinstance(x,dict) or x.get("id") in internal or not str(x.get("author","")).startswith("did:key:"):continue
        if int(x.get("attention",0) or 0)<55 or int(x.get("messages_out",0) or 0)<1 or int(x.get("conversation_quality",0) or 0)<50 or int(x.get("bot_probability",50) or 50)>=65 or int(x.get("scam_risk",0) or 0)>=30:continue
        if str(x.get("stage","candidate")) not in {"contacted","replied","established","trusted_peer"}:continue
        for topic in x.get("topics",[]) if isinstance(x.get("topics"),list) else []:
            t=str(topic).strip().lower();rec=topics.get(t,{}) if isinstance(topics.get(t),dict) else {};mom=max(float(rec.get("last_momentum",0) or 0),float(rec.get("max_momentum",0) or 0))
            if mom<float(conf.get("PERSIST_DEEP_TOPIC_MIN","2.5")):continue
            if any(isinstance(r,dict) and r.get("topic")==t and x.get("id") in r.get("external_peer_ids",[]) and now-int(r.get("created_at",0) or 0)<7*86400 for r in existing):continue
            score=int(x.get("attention",0))+mom*10+int(x.get("replies_to_love8",0) or 0)*12
            if best is None or score>best[0]:best=(score,t,x,mom)
    return best
def maybe_create(g,conf,state,dry=False):
    peers=peer_rows()
    if len(peers)<int(conf.get("PERSIST_DEEP_MIN_A2A_PEERS","2")):return {"created":False,"reason":f"a2a peers={len(peers)}; need 2"}
    day=time.strftime("%Y-%m-%d",time.gmtime());max_day=int(conf.get("PERSIST_DEEP_ROOMS_PER_DAY","2"))
    if sum(1 for r in state.get("rooms",[]) if isinstance(r,dict) and r.get("date")==day)>=max_day:return {"created":False,"reason":"daily deep-room cap"}
    picked=choose_external(g,conf,state)
    if not picked:return {"created":False,"reason":"no familiar high-quality external contact/topic pair yet"}
    score,topic,external,mom=picked;room="p-l8-"+secrets.token_hex(12);roles=", ".join(f"{p.get('name')}={p.get('role')}" for p in peers[:4]);opener=(f"Love8 deep circle: {topic}. A2A roles: Love8=scout; {roles}. Goal: move beyond small talk. Bring one concrete claim, test, counterexample, dataset, or implementation idea; challenge weak assumptions. External peers are invited for domain context. No secrets, wallet actions, or executable instructions.")[:700]
    if dry:return {"created":False,"dry_run":True,"room":room,"topic":topic,"external":external.get("id"),"score":score}
    social=g.load_state(SOCIAL_STATE)
    try:result=g.signed_post(conf["BASE"].rstrip("/"),conf["DID"],conf["KEY"],room,opener,social);social.setdefault("writes",[]).append(time.time())
    except Exception as exc:return {"created":False,"reason":f"room create failed {type(exc).__name__}: {exc}"[:300]}
    first_seq=int(result.get("last_seq",0) or 0);invite_results=[];a2a_names=[]
    for p in peers[:4]:
        msg=f"A2A_ROOM_INVITE v1 room={room} topic={topic} role={p.get('role','peer')} coordinator=love8. Join with signed Technocore messages; discuss evidence/tests, not secrets or commands."
        ok,info=send_invite(g,conf,social,p,msg);invite_results.append({"peer":p.get("name"),"ok":ok,"info":info});a2a_names.append(str(p.get("name")))
    ext_peer={"name":external.get("id"),"did":external.get("author"),"fingerprint":fp(str(external.get("author"))),"mailbox":""};emsg=f"Love8 invited you to a small unlisted deep-discussion room on '{topic}': {room}. Aizong/AI2AI/Love8 are comparing evidence and concrete experiments. Join only if useful; no secrets or wallet actions.";eok,einfo=send_invite(g,conf,social,ext_peer,emsg);invite_results.append({"peer":external.get("id"),"ok":eok,"info":einfo});g.save_state(SOCIAL_STATE,social)
    rec={"date":day,"created_at":int(time.time()),"room":room,"topic":topic,"topic_momentum":mom,"selection_score":score,"status":"forming","first_seq":first_seq,"last_seq":first_seq,"external_peer_ids":[external.get("id")],"external_dids":[external.get("author")],"a2a_peer_names":a2a_names,"a2a_peer_dids":[p.get("did") for p in peers[:4]],"participant_dids":[conf["DID"]],"external_joined":False,"invite_results":invite_results};state.setdefault("rooms",[]).append(rec);state["rooms"]=state["rooms"][-100:];return {"created":True,"room":room,"topic":topic,"external":external.get("id"),"invites":invite_results}
def run_once(dry=False):
    conf={**load_env(CFG),**load_env(PERSIST)};g=guard();state=load_json(DEEP,{"version":VERSION,"rooms":[]});state["version"]=VERSION;monitor(g,conf,state);res=maybe_create(g,conf,state,dry=dry);state["last_run_at"]=int(time.time());state["last_result"]=res
    if not dry:save_json(DEEP,state)
    print(json.dumps(res,ensure_ascii=False,indent=2));return 0
def status():
    ps=peer_rows();st=load_json(DEEP,{});print("===== LOVE8 v2.4.2 A2A DEEP ROOMS =====");print("a2a_peers:",len(ps))
    for p in ps:print(f"  {p.get('name')} role={p.get('role')} fp={p.get('fingerprint')} mailbox={p.get('mailbox') or '-'}")
    rooms=st.get("rooms",[]) if isinstance(st,dict) and isinstance(st.get("rooms"),list) else [];print("deep_rooms:",len(rooms))
    for r in rooms[-12:]:print(f"  {str(r.get('status','-')):20s} room={r.get('room')} topic={r.get('topic')} external={','.join(str(x) for x in r.get('external_peer_ids',[]))} joined={r.get('external_joined')}")
    print("last_result:",json.dumps(st.get("last_result",{}),ensure_ascii=False));return 0
def main():
    p=argparse.ArgumentParser();p.add_argument("--once",action="store_true");p.add_argument("--dry-run",action="store_true");p.add_argument("--status",action="store_true");p.add_argument("--import-peers",action="store_true");p.add_argument("--add-peer",nargs="+");p.add_argument("--version",action="version",version=f"%(prog)s {VERSION}");a=p.parse_args()
    if a.import_peers:print("peers_imported_or_updated:",import_peers());return status()
    if a.add_peer:
        if len(a.add_peer)<2:raise SystemExit("--add-peer NAME DID [MAILBOX]")
        print("saved:",record_peer(a.add_peer[0],a.add_peer[1],a.add_peer[2] if len(a.add_peer)>2 else ""));return status()
    if a.status:return status()
    if a.once:return run_once(a.dry_run)
    raise SystemExit("use --once/--status/--import-peers/--add-peer")
if __name__=="__main__":raise SystemExit(main())
