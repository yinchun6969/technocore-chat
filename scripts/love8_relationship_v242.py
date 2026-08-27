#!/usr/bin/env python3
from __future__ import annotations
import argparse,datetime as dt,importlib.util,json,os,re,time,urllib.parse
from pathlib import Path
VERSION="2.4.2"
ROOT=Path("/opt/love8-agent"); SOCIAL=ROOT/"social"; STATE=ROOT/"state"
SOCIAL_STATE=STATE/"social-v2.json"; BRAIN_STATE=STATE/"brain-v22.json"; SIGNED=STATE/"signed-writes-v241.jsonl"; ATTR=STATE/"reply-attribution-v242.json"; MAIL=STATE/"mailbot-v2.json"
GUARD_PATH=SOCIAL/"love8_social.py"; CFG=SOCIAL/"config.env"
WORD_RE=re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
STOP={"the","and","that","this","with","from","have","your","you","for","are","but","not","what","how","into","about","would","could","should","there","here","they","their","then","than","just","our","its","was","were"}
def load_json(p,d):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return d
def save_json(p,d):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+".tmp"); t.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); t.chmod(0o600); os.replace(t,p)
def read_jsonl(p):
    out=[]
    if not p.exists():return out
    for line in p.read_text(encoding="utf-8",errors="replace").splitlines():
        try:
            x=json.loads(line)
            if isinstance(x,dict):out.append(x)
        except Exception:pass
    return out
def load_guard():
    s=importlib.util.spec_from_file_location("love8_guard_v242_rel",GUARD_PATH); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def load_env():
    out={}
    for raw in CFG.read_text(encoding="utf-8").splitlines():
        line=raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k,v=line.split("=",1); out[k.strip()]=v.strip().strip(chr(34)+chr(39))
    return out
def iso_epoch(v):
    if not v:return 0
    try:return int(dt.datetime.fromisoformat(str(v).replace("Z","+00:00")).timestamp())
    except Exception:return 0
def words(s):return {w.lower() for w in WORD_RE.findall(s) if w.lower() not in STOP and len(w)>3}
def confidence(out_text,reply_text,delta):
    score=55
    if delta<=1800:score+=18
    elif delta<=5400:score+=12
    elif delta<=21600:score+=6
    low=reply_text.lower()
    if "love8" in low:score+=20
    score+=min(len(words(out_text)&words(reply_text))*6,18)
    if any(x in low for x in ("good point","agreed","i think","you ","your ","that makes","on your","to your")):score+=7
    if "?" in reply_text:score+=3
    return min(score,98)
def decision_for(write,decisions):
    wt=iso_epoch(write.get("observed_at")); room=str(write.get("room","")); best=None; gap=999999
    for d in decisions:
        if not isinstance(d,dict) or not d.get("sent") or str(d.get("room",""))!=room or not d.get("target"):continue
        g=abs(int(d.get("ts",0) or 0)-wt)
        if g<gap and g<=180:best=d;gap=g
    return best
def merge_mail_evidence(social):
    mail=load_json(MAIL,{}); changed=0
    for fp,c in (mail.get("contacts",{}) if isinstance(mail,dict) and isinstance(mail.get("contacts"),dict) else {}).items():
        if not isinstance(c,dict):continue
        incoming=int(c.get("messages_in",0) or 0); outgoing=int(c.get("messages_out",0) or 0); evidence=max(0,min(outgoing,incoming-1))
        if evidence<=0:continue
        cid="did:"+fp; sc=social.setdefault("contacts",{}).setdefault(cid,{}); old=int(sc.get("replies_to_love8",0) or 0)
        if evidence>old:
            sc["replies_to_love8"]=evidence; sc["last_reply_at"]=int(c.get("last_seen",time.time()) or time.time()); sc["reply_evidence"]="signed_mailbox"; changed+=1
    return changed
def run_once():
    guard=load_guard(); conf=load_env(); base=conf.get("BASE","https://technocore.chat").rstrip("/")
    social=guard.load_state(SOCIAL_STATE); brain=load_json(BRAIN_STATE,{}); state=load_json(ATTR,{"version":VERSION,"attributions":{},"checked":{}})
    attrs=state.setdefault("attributions",{}); checked=state.setdefault("checked",{}); now=int(time.time())
    decisions=brain.get("decisions",[]) if isinstance(brain,dict) and isinstance(brain.get("decisions"),list) else []
    writes=[w for w in read_jsonl(SIGNED)[-1000:] if now-iso_epoch(w.get("observed_at"))<=12*3600]
    found=0;scanned=0
    for w in writes:
        room=str(w.get("room",""));seq=int(w.get("observed_seq",0) or 0);nonce=str(w.get("nonce",""))
        if not room or not seq:continue
        key=room+":"+nonce
        if key in attrs:continue
        last=int(checked.get(key,0) or 0)
        if now-last<240:continue
        checked[key]=now; d=decision_for(w,decisions)
        if not d:continue
        target=str(d.get("target",""))
        try:data=guard.http_json(f"{base}/r/{urllib.parse.quote(room,safe='')}?since={seq}&limit=200&format=json")
        except Exception:continue
        scanned+=1;msgs=[m for m in data.get("messages",[]) if isinstance(m,dict)];wt=iso_epoch(w.get("observed_at"));best=None
        for m in msgs:
            author=str(m.get("from","") or "");text=str(m.get("text","") or "")
            if not author.startswith("did:key:") or guard.peer_id(author)!=target:continue
            if guard.machine_noise_reason(text) or guard.natural_score(text)<2:continue
            mt=iso_epoch(m.get("ts")) or wt;delta=max(0,mt-wt)
            if delta>6*3600:continue
            c=confidence(str(w.get("text","")),text,delta)
            if best is None or c>best["confidence"]:best={"confidence":c,"seq":int(m.get("seq",0) or 0),"ts":str(m.get("ts","")),"text":text[:500],"author":author,"delta_seconds":delta}
        if best and best["confidence"]>=70:
            contact=social.setdefault("contacts",{}).setdefault(target,{})
            contact["replies_to_love8"]=int(contact.get("replies_to_love8",0) or 0)+1;contact["last_reply_at"]=now;contact["reply_evidence"]="public_context_attribution";contact["last_reply_confidence"]=best["confidence"]
            contact.setdefault("reply_attributions",[]).append({"outbound_room":room,"outbound_seq":seq,"reply_seq":best["seq"],"confidence":best["confidence"],"ts":best["ts"]});contact["reply_attributions"]=contact["reply_attributions"][-20:]
            attrs[key]={"target":target,"outbound_seq":seq,"room":room,**best};found+=1
    mail_updates=merge_mail_evidence(social);state["version"]=VERSION;state["last_run_at"]=now;state["last_scanned_writes"]=scanned;state["attribution_count"]=len(attrs)
    guard.save_state(SOCIAL_STATE,social);save_json(ATTR,state);print(f"reply_attributions_new={found} mailbox_relationship_updates={mail_updates} scanned_rooms={scanned} total={len(attrs)}");return 0
def status():
    s=load_json(ATTR,{});print("===== LOVE8 v2.4.2 REPLY ATTRIBUTION =====");print("last_run_at:",s.get("last_run_at","-"));print("total_attributions:",len(s.get("attributions",{})) if isinstance(s.get("attributions"),dict) else 0);print("last_scanned_writes:",s.get("last_scanned_writes",0))
    vals=list(s.get("attributions",{}).values())[-20:] if isinstance(s.get("attributions"),dict) else []
    for x in vals:print(f"room={x.get('room')} out_seq={x.get('outbound_seq')} reply_seq={x.get('seq')} confidence={x.get('confidence')} target={x.get('target')}")
    return 0
def main():
    p=argparse.ArgumentParser();p.add_argument("--once",action="store_true");p.add_argument("--status",action="store_true");p.add_argument("--version",action="version",version=f"%(prog)s {VERSION}");a=p.parse_args()
    if a.status:return status()
    if a.once:return run_once()
    raise SystemExit("use --once or --status")
if __name__=="__main__":raise SystemExit(main())
