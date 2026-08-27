#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,time
from pathlib import Path
from typing import Any
VERSION="2.4.2"
ROOT=Path("/opt/love8-agent"); STATE=ROOT/"state"; MEMORY=ROOT/"memory"
SOCIAL_STATE=STATE/"social-v2.json"; WORKING_SET=STATE/"working-set-v242.json"
STAGE_BONUS={"candidate":0,"contacted":18,"replied":34,"established":50,"trusted_peer":65}
def load_json(path,default):
    try:return json.loads(path.read_text(encoding="utf-8"))
    except Exception:return default
def save_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); tmp.chmod(0o600); os.replace(tmp,path)
def clamp(v,lo=0,hi=100): return int(min(max(round(v),lo),hi))
def recency(ts,now):
    if not ts:return 0
    age=max(0,now-ts)
    return 20 if age<=21600 else 15 if age<=86400 else 9 if age<=259200 else 4 if age<=604800 else 0
def attention_score(c,now):
    b=c.get("brain",{}) if isinstance(c.get("brain"),dict) else {}
    stage=str(c.get("relationship_stage",c.get("stage","candidate")))
    score=STAGE_BONUS.get(stage,0)+recency(int(c.get("last_seen",0) or 0),now)
    score+=min(int(c.get("messages_out",0) or 0),5)*3.2+min(int(c.get("replies_to_love8",0) or 0),5)*7
    score+=int(b.get("conversation_quality",0) or 0)*.18+int(b.get("human_likelihood",c.get("brain_human_likelihood",0)) or 0)*.08
    score+=int(b.get("trust_score",50) or 50)*.12+(4 if c.get("verified") else 0)
    score-=int(b.get("bot_probability",50) or 50)*.18+int(b.get("scam_risk",0) or 0)*.35
    if c.get("probable_bot_cluster") or c.get("brain_probable_bot"): score-=18
    if c.get("suspected_scam"): score-=35
    return clamp(score)
def build(limit=160):
    now=int(time.time()); social=load_json(SOCIAL_STATE,{})
    contacts=social.get("contacts",{}) if isinstance(social,dict) and isinstance(social.get("contacts"),dict) else {}
    rows=[]
    for cid,c in contacts.items():
        if not isinstance(c,dict):continue
        b=c.get("brain",{}) if isinstance(c.get("brain"),dict) else {}
        if int(b.get("scam_risk",0) or 0)>=60 or c.get("suspected_scam"):continue
        if int(b.get("bot_probability",50) or 50)>=92 or c.get("probable_bot_cluster"):continue
        topics=b.get("topics",[]) if isinstance(b.get("topics"),list) else []
        room=str(c.get("last_room","") or "")
        rows.append({"id":cid,"attention":attention_score(c,now),"stage":str(c.get("relationship_stage",c.get("stage","candidate"))),
        "verified_signed_did":bool(c.get("verified")),"messages_out":int(c.get("messages_out",0) or 0),"replies_to_love8":int(c.get("replies_to_love8",0) or 0),
        "bot_probability":int(b.get("bot_probability",50) or 50),"scam_risk":int(b.get("scam_risk",0) or 0),
        "conversation_quality":int(b.get("conversation_quality",0) or 0),"human_likelihood":int(b.get("human_likelihood",c.get("brain_human_likelihood",0)) or 0),
        "topics":[str(x)[:80] for x in topics[:8]],"rooms":[room] if room else [],"author":str(c.get("author","") or "")[:180],"last_seen":int(c.get("last_seen",0) or 0)})
    rows.sort(key=lambda x:(x["attention"],STAGE_BONUS.get(x["stage"],0),x["replies_to_love8"],x["conversation_quality"],x["last_seen"]),reverse=True)
    selected=rows[:max(20,min(limit,400))]
    doc={"schema":"love8-working-set-v1","version":VERSION,"generated_at":now,"total_contacts_seen":len(contacts),"working_set_size":len(selected),"working_set":selected}
    save_json(WORKING_SET,doc); return doc
def status():
    doc=load_json(WORKING_SET,{}); rows=doc.get("working_set",[]) if isinstance(doc,dict) else []
    print("===== LOVE8 v2.4.2 ATTENTION / WORKING SET ====="); print("generated_at:",doc.get("generated_at","-")); print("total_contacts_seen:",doc.get("total_contacts_seen",0)); print("working_set_size:",len(rows) if isinstance(rows,list) else 0)
    for r in rows[:25] if isinstance(rows,list) else []:
        print(f"{int(r.get('attention',0)):3d} {str(r.get('stage','candidate')):12s} {r.get('id')} out={r.get('messages_out',0)} replies={r.get('replies_to_love8',0)} q={r.get('conversation_quality',0)} bot={r.get('bot_probability',0)} risk={r.get('scam_risk',0)} topics={','.join(r.get('topics',[])[:4])}")
    return 0
def main():
    p=argparse.ArgumentParser(); p.add_argument("--build",action="store_true"); p.add_argument("--status",action="store_true"); p.add_argument("--limit",type=int,default=160); p.add_argument("--version",action="version",version=f"%(prog)s {VERSION}"); a=p.parse_args()
    if a.status:return status()
    if a.build:
        d=build(a.limit); print(f"working_set={d['working_set_size']} total={d['total_contacts_seen']}"); return 0
    raise SystemExit("use --build or --status")
if __name__=="__main__": raise SystemExit(main())
