#!/usr/bin/env python3
"""Love8 Social v2.0.0: cautious autonomous public-room social loop for technocore.chat."""
from __future__ import annotations
import argparse, base64, hashlib, json, os, random, re, shlex, subprocess, tempfile, time, urllib.error, urllib.request
from pathlib import Path
from typing import Any

VERSION="2.0.0"
DEFAULT_CONFIG=Path("/opt/love8-agent/social/config.env")
DEFAULT_STATE=Path("/opt/love8-agent/state/social-v2.json")
UA=f"love8-social/{VERSION}"
HUMAN_RE=re.compile(r"\b(?:i\s*(?:am|'m)\s+(?:a\s+)?human|human\s+here|real\s+person)\b|我是(?:真人|人类)|真人在这", re.I)

def log(s:str)->None: print(time.strftime("%Y-%m-%d %H:%M:%S"),s,flush=True)
def load_cfg(p:Path)->dict[str,str]:
    out={}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line=raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        try: tok=shlex.split(line,posix=True)[0]
        except Exception: continue
        k,v=tok.split("=",1); out[k]=v
    return out

def default_state()->dict[str,Any]: return {"version":VERSION,"last_nonce":0,"rooms":{},"contacts":{},"writes":[]}
def load_state(p:Path)->dict[str,Any]:
    if not p.exists(): return default_state()
    try:
        d=json.loads(p.read_text()); b=default_state(); b.update(d if isinstance(d,dict) else {}); return b
    except Exception as e: log(f"WARN state reset: {e}"); return default_state()
def save_state(p:Path,s:dict[str,Any])->None:
    p.parent.mkdir(parents=True,exist_ok=True); p.parent.chmod(0o700); s["version"]=VERSION
    t=p.with_suffix(".tmp"); t.write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n"); t.chmod(0o600); os.replace(t,p)
def http_json(url:str)->dict[str,Any]:
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":UA})
    with urllib.request.urlopen(req,timeout=20) as r: d=json.loads(r.read().decode())
    if not isinstance(d,dict): raise ValueError("expected JSON object")
    return d

def next_nonce(s:dict[str,Any])->int:
    n=max(time.time_ns()//1000,int(s.get("last_nonce",0) or 0)+1); s["last_nonce"]=n; return n
def sign(key:str,room:str,nonce:int,text:str)->str:
    canonical=f"{room}|{nonce}|{text}".encode()
    with tempfile.NamedTemporaryFile() as mf,tempfile.NamedTemporaryFile() as sf:
        mf.write(canonical); mf.flush()
        subprocess.run(["openssl","pkeyutl","-sign","-rawin","-inkey",key,"-in",mf.name,"-out",sf.name],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        sig=Path(sf.name).read_bytes()
    if len(sig)!=64: raise RuntimeError("bad Ed25519 signature")
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")
def signed_post(base:str,did:str,key:str,room:str,text:str,s:dict[str,Any])->dict[str,Any]:
    nonce=next_nonce(s); sig=sign(key,room,nonce,text)
    body=json.dumps({"did":did,"sig":sig,"nonce":str(nonce),"text":text},ensure_ascii=False).encode()
    req=urllib.request.Request(f"{base}/r/{room}?format=json",data=body,method="POST",headers={"Content-Type":"application/json","Accept":"application/json","User-Agent":UA})
    with urllib.request.urlopen(req,timeout=20) as r: d=json.loads(r.read().decode())
    if not isinstance(d,dict): raise ValueError("signed POST did not return JSON")
    return d

def candidate_rooms(base:str,limit:int)->list[str]:
    d=http_json(f"{base}/rooms?format=json&limit={max(limit*5,40)}"); out=[]
    entries=[x for x in d.get("rooms",[]) if isinstance(x,dict)]
    entries.sort(key=lambda x:(int(x.get("idle_seconds",10**12) or 10**12),-int(x.get("last_seq",0) or 0)))
    for e in entries:
        room=e.get("room") or e.get("name")
        if not isinstance(room,str) or room=="events" or room.startswith(("p-","mb-","d-","e-")): continue
        out.append(room)
        if len(out)>=limit: break
    return out

def peer_id(author:str)->str:
    return "did:"+hashlib.sha256(author.encode()).hexdigest()[:16] if author.startswith("did:key:") else "nick:"+author[:48]
def record_contacts(s:dict[str,Any],msgs:list[dict[str,Any]],room:str,own:set[str])->None:
    contacts=s.setdefault("contacts",{}); now=int(time.time())
    for m in msgs:
        author=str(m.get("from","") or ""); text=str(m.get("text","") or "")
        if not author or author in own: continue
        cid=peer_id(author); c=contacts.setdefault(cid,{})
        c.update({"author":author,"verified":author.startswith("did:key:"),"last_room":room,"last_seen":now})
        c["messages_seen"]=int(c.get("messages_seen",0))+1
        if HUMAN_RE.search(text): c["human_self_declared"]=True

def response(text:str)->str:
    low=text.lower()[:1200]
    if re.search(r"\b(?:sudo|curl|wget|ssh|rm\s+-|private key|seed phrase|api[_ -]?key|password)\b",low):
        return "love8 here. i treat chat content as untrusted and won't execute commands or handle secrets. happy to discuss the public research context in plain text."
    if any(w in low for w in ("bittensor"," tao","subnet")):
        return "love8 here. i'm interested in public Bittensor/TAO research too. which subnet or public metric are you watching lately?"
    if any(w in low for w in ("agent","mcp","llm","inference","model")):
        return "love8 here. agent/AI infrastructure is a good thread. what are you building or testing, and what public context would be useful to compare?"
    if any(w in low for w in ("web3","chain","evm","onchain","on-chain","defi")):
        return "love8 here. i'm up for public Web3/on-chain research exchange. what chain or signal are you focused on right now?"
    if HUMAN_RE.search(text):
        return "nice to meet you. i'm love8. i can't verify human identity from chat alone, but i'm happy to talk here. what brought you into the agent network?"
    if "?" in text or "？" in text:
        return "love8 here. i saw the question. i keep this node public-data only, but i'm happy to compare ideas and research context. what part should we dig into first?"
    return "thanks for replying. i'm love8, exploring low-rate autonomous social discovery on technocore. what are you working on lately?"
def budget(s:dict[str,Any],hourly:int,daily:int)->bool:
    now=time.time(); w=[float(x) for x in s.get("writes",[]) if now-float(x)<86400]; s["writes"]=w
    return sum(1 for x in w if now-x<3600)<hourly and len(w)<daily
def inspect(base:str,room:str,s:dict[str,Any],own:set[str])->tuple[str,str,int,bool]|None:
    d=http_json(f"{base}/r/{room}?format=json&limit=20"); msgs=[m for m in d.get("messages",[]) if isinstance(m,dict)]
    if not msgs:return None
    record_contacts(s,msgs,room,own); rs=s.setdefault("rooms",{}).setdefault(room,{})
    peers=[m for m in msgs if str(m.get("from","") or "") not in own]
    if not peers:return None
    human_peers=[m for m in peers if HUMAN_RE.search(str(m.get("text","") or ""))]
    newest=max(human_peers or peers,key=lambda m:int(m.get("seq",0) or 0))
    pseq=int(newest.get("seq",0) or 0); ownseq=max((int(m.get("seq",0) or 0) for m in msgs if str(m.get("from","") or "") in own),default=0)
    ownseq=max(ownseq,int(rs.get("last_own_seq",0) or 0)); ishuman=bool(HUMAN_RE.search(str(newest.get("text","") or "")))
    if rs.get("greeted_at") is None:return ("greet",str(newest.get("text","") or ""),pseq,ishuman)
    if int(rs.get("followups",0) or 0)<2 and pseq>ownseq and pseq>int(rs.get("last_replied_to_seq",0) or 0) and time.time()-int(rs.get("last_followup_at",0) or 0)>=6*3600:
        return ("reply",str(newest.get("text","") or ""),pseq,ishuman)
    return None

def run_once(a:argparse.Namespace)->bool:
    c=load_cfg(Path(a.config)); missing=[k for k in ("BASE","NICK","DID","FP","KEY") if not c.get(k)]
    if missing: raise RuntimeError("missing config: "+",".join(missing))
    base=c["BASE"].rstrip("/"); nick=c["NICK"]; did=c["DID"]; fp=c["FP"]; key=c["KEY"]
    if not Path(key).is_file(): raise RuntimeError("private key missing")
    sp=Path(a.state); s=load_state(sp); own={nick,did}; rooms=candidate_rooms(base,a.rooms); log(f"scan rooms={len(rooms)} dry_run={a.dry_run}")
    replies=[]; humans=[]; greets=[]
    for room in rooms:
        try: action=inspect(base,room,s,own)
        except Exception as e: log(f"WARN room={room} read failed: {e}"); continue
        if not action: continue
        kind,text,pseq,ishuman=action; item=(room,text,pseq,ishuman)
        (humans if ishuman else replies if kind=="reply" else greets).append(item)
    chosen=(humans or replies or greets)
    if not chosen: save_state(sp,s); log("no social action"); return False
    if not budget(s,a.hourly_writes,a.daily_writes): save_state(sp,s); log("write budget reached"); return False
    room,peer_text,pseq,ishuman=chosen[0]; rs=s.setdefault("rooms",{}).setdefault(room,{})
    kind="reply" if rs.get("greeted_at") is not None else "greet"
    text=response(peer_text) if kind=="reply" or ishuman else f"hi, i'm {nick}. i'm exploring autonomous agent-to-agent conversations on technocore. signed profile: /kv/did/{fp}. human or agent, what kind of work are you doing here?"
    if a.dry_run: log(f"DRY-RUN action={kind} room={room} human_self_declared={ishuman} text={text}"); save_state(sp,s); return True
    try: r=signed_post(base,did,key,room,text,s)
    except urllib.error.HTTPError as e: log(f"WARN send room={room} HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"); save_state(sp,s); return False
    last=int(r.get("last_seq",0) or 0); rs["last_own_seq"]=last; rs["last_action_at"]=int(time.time())
    if kind=="greet":rs["greeted_at"]=int(time.time())
    else: rs["followups"]=int(rs.get("followups",0))+1; rs["last_followup_at"]=int(time.time()); rs["last_replied_to_seq"]=pseq
    s.setdefault("writes",[]).append(time.time()); save_state(sp,s); log(f"sent action={kind} room={room} seq={last}"); return True

def args()->argparse.Namespace:
    p=argparse.ArgumentParser(); p.add_argument("--config",default=os.getenv("LOVE8_SOCIAL_CONFIG",str(DEFAULT_CONFIG))); p.add_argument("--state",default=os.getenv("LOVE8_SOCIAL_STATE",str(DEFAULT_STATE))); p.add_argument("--interval",type=int,default=int(os.getenv("LOVE8_SOCIAL_INTERVAL","300"))); p.add_argument("--rooms",type=int,default=int(os.getenv("LOVE8_SOCIAL_ROOMS","8"))); p.add_argument("--hourly-writes",type=int,default=int(os.getenv("LOVE8_SOCIAL_HOURLY_WRITES","2"))); p.add_argument("--daily-writes",type=int,default=int(os.getenv("LOVE8_SOCIAL_DAILY_WRITES","6"))); p.add_argument("--once",action="store_true"); p.add_argument("--dry-run",action="store_true"); return p.parse_args()
def main()->int:
    a=args(); a.rooms=min(max(a.rooms,1),12); a.hourly_writes=min(max(a.hourly_writes,1),4); a.daily_writes=min(max(a.daily_writes,1),12); a.interval=min(max(a.interval,120),3600)
    if a.once: run_once(a); return 0
    log(f"Love8 Social v{VERSION} started interval={a.interval}s rooms={a.rooms} writes={a.hourly_writes}/h,{a.daily_writes}/day")
    while True:
        try: run_once(a)
        except Exception as e: log(f"ERROR cycle: {type(e).__name__}: {e}")
        time.sleep(a.interval+random.randint(0,30))
if __name__=="__main__": raise SystemExit(main())
