#!/usr/bin/env python3
from __future__ import annotations
import argparse,importlib.util,json,time,urllib.error
from pathlib import Path
VERSION="2.4.2"
ROOT=Path("/opt/love8-agent");SOCIAL=ROOT/"social";STATE=ROOT/"state";BASE_PATH=SOCIAL/"love8_memory_v241.py";DEEP_STATE=STATE/"deep-rooms-v242.json"
def load_base():
    s=importlib.util.spec_from_file_location("love8_memory_v241_base",BASE_PATH);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
base=load_base()
def band(v,a,b):return 0 if v<a else 1 if v<b else 2
def stable_contact_snapshot(new):
    return {"stage":new["relationship_stage"],"score":new["relationship_score"],"topics":new["topics"][-8:],"bot_band":band(new["bot_probability"],50,85),"risk_band":band(new["scam_risk"],30,60),"quality_band":band(new["conversation_quality"],40,70),"messages_out":new["messages_out"],"replies_to_love8":new["replies_to_love8"],"summary":new["summaries"][-1] if new["summaries"] else ""}
def significant(old_snap,new_snap,last_event_at):
    if not old_snap:return True
    keys=("stage","bot_band","risk_band","quality_band","messages_out","replies_to_love8")
    if any(old_snap.get(k)!=new_snap.get(k) for k in keys):return True
    if abs(int(old_snap.get("score",0) or 0)-int(new_snap.get("score",0) or 0))>=8:return True
    if set(old_snap.get("topics",[]))!=set(new_snap.get("topics",[])):return True
    if str(old_snap.get("summary",""))!=str(new_snap.get("summary","")) and time.time()-int(last_event_at or 0)>=6*3600:return True
    return time.time()-int(last_event_at or 0)>=24*3600
def sync_contacts_v242(conf,social):
    changed=0;contacts=social.get("contacts",{}) if isinstance(social.get("contacts"),dict) else {}
    for cid,c in contacts.items():
        if not isinstance(c,dict):continue
        brain=c.get("brain",{}) if isinstance(c.get("brain"),dict) else {};path=base.safe_contact_file(cid);old=base.load_json(path,{})
        if not isinstance(old,dict):old={}
        summary=str(brain.get("summary","") or "").strip()[:600];topics=[str(x)[:80] for x in (brain.get("topics",[]) if isinstance(brain.get("topics"),list) else [])];room=str(c.get("last_room","") or "")[:96]
        new={"schema":"love8-contact-memory-v2","contact_id":cid,"author":str(c.get("author","") or "")[:180],"first_remembered_at":old.get("first_remembered_at") or base.now_iso(),"last_updated_at":base.now_iso(),"relationship_stage":str(c.get("relationship_stage",c.get("stage","candidate"))),"relationship_score":int(c.get("relationship_score",0) or 0),"verified_signed_did":bool(c.get("verified")),"human_self_declared":bool(c.get("human_self_declared")),"messages_in":int(c.get("messages_in",c.get("natural_messages",0)) or 0),"messages_out":int(c.get("messages_out",0) or 0),"replies_to_love8":int(c.get("replies_to_love8",0) or 0),"bot_probability":int(brain.get("bot_probability",50) or 50),"human_likelihood":int(brain.get("human_likelihood",c.get("brain_human_likelihood",0)) or 0),"scam_risk":int(brain.get("scam_risk",0) or 0),"conversation_quality":int(brain.get("conversation_quality",0) or 0),"trust_score":int(brain.get("trust_score",50) or 50),"topics":base._uniq(list(old.get("topics",[]))+topics,60),"rooms":base._uniq(list(old.get("rooms",[]))+([room] if room else []),60),"summaries":base._uniq(list(old.get("summaries",[]))+([summary] if summary else []),100)}
        snap=stable_contact_snapshot(new);old_snap=old.get("journal_snapshot",{}) if isinstance(old.get("journal_snapshot"),dict) else {};migrating_existing=bool(old) and not old_snap
        emit=False if migrating_existing else significant(old_snap,snap,int(old.get("last_journal_event_at",0) or 0))
        if emit:
            if base.append_event(conf,"contact_memory",cid,snap):changed+=1
            new["journal_snapshot"]=snap;new["last_journal_event_at"]=int(time.time())
        else:
            new["journal_snapshot"]=snap if migrating_existing else old_snap;new["last_journal_event_at"]=int(old.get("last_journal_event_at",0) or 0)
        a=dict(old);b=dict(new);a.pop("last_updated_at",None);b.pop("last_updated_at",None)
        if a!=b:base.save_json(path,new)
    return changed
def sync_event_scout_v242(conf):
    data=base.load_json(base.EVENT_SCOUT,{});items=data.get("rooms",[]) if isinstance(data,dict) and isinstance(data.get("rooms"),list) else [];st=base.load_json(base.MEMORY_STATE,{})
    if not isinstance(st,dict):st={}
    if "v242_event_baseline_seq" not in st:
        st["v242_event_baseline_seq"]=max([int(x.get("event_seq",0) or 0) for x in items if isinstance(x,dict)] or [0]);base.save_json(base.MEMORY_STATE,st);return 0
    baseline=int(st.get("v242_event_baseline_seq",0) or 0);newest=baseline;changed=0
    for item in items:
        if not isinstance(item,dict):continue
        room=str(item.get("room","") or "")[:80];seq=int(item.get("event_seq",0) or 0);newest=max(newest,seq)
        if room and seq>baseline:
            stable={"room":room,"event_seq":seq}
            if base.append_event(conf,"technocore_room_discovered",f"{seq}:{room}",stable):changed+=1
    if newest>baseline:st["v242_event_baseline_seq"]=newest;base.save_json(base.MEMORY_STATE,st)
    return changed
def sync_deep_rooms(conf):
    d=base.load_json(DEEP_STATE,{});changed=0
    for room in d.get("rooms",[]) if isinstance(d,dict) and isinstance(d.get("rooms"),list) else []:
        if not isinstance(room,dict):continue
        rid=str(room.get("room",""))
        if rid and base.append_event(conf,"deep_room",rid,{k:room.get(k) for k in ("room","topic","created_at","status","external_peer_ids","a2a_peer_names","first_seq","last_seq")}):changed+=1
    return changed
def room_anchor_best_effort(conf,ledger_hash,memory_head):
    if conf.get("PERSIST_ROOM_ANCHOR_ENABLED","yes").lower() not in {"1","yes","true","on"}:return {"ok":False,"disabled":True}
    room=conf.get("PERSIST_ANCHOR_ROOM","love8-provenance");text=f"love8 provenance v2.4.2 date={base.today()} ledger_sha256={ledger_hash} memory_head={memory_head}"[:420];guard=base.load_guard();social=guard.load_state(base.SOCIAL_STATE)
    try:
        result=guard.signed_post(conf["BASE"].rstrip("/"),conf["DID"],conf["KEY"],room,text,social);social.setdefault("writes",[]).append(time.time());guard.save_state(base.SOCIAL_STATE,social);return {"ok":True,"room":room,"seq":int(result.get("last_seq",0) or 0)}
    except urllib.error.HTTPError as exc:
        try:body=exc.read().decode("utf-8","replace")[:1000]
        except Exception:body=""
        return {"ok":False,"room":room,"error":f"HTTP {exc.code}","body":body}
    except Exception as exc:return {"ok":False,"room":room,"error":f"{type(exc).__name__}: {exc}"[:500]}
def sync_cycle(finalize=False):
    conf=base.cfg();base.ensure_dirs();social=base.load_json(base.SOCIAL_STATE,{});persistent=base.load_json(base.PERSIST_STATE,{})
    counts={"contacts":sync_contacts_v242(conf,social if isinstance(social,dict) else {}),"topics":base.sync_topics(conf,persistent if isinstance(persistent,dict) else {}),"signed_writes":base.sync_signed_writes(conf),"contributions":base.sync_legacy_contributions(conf,persistent if isinstance(persistent,dict) else {}),"event_rooms":sync_event_scout_v242(conf),"upstream":base.sync_upstream_scout(conf),"deep_rooms":sync_deep_rooms(conf)}
    ledger=base.write_canonical_ledger(conf);published,profile=base.publish_profile(conf,force=finalize);room_anchor=None;backup=None;st=base.load_json(base.MEMORY_STATE,{})
    if not isinstance(st,dict):st={}
    if finalize and published:
        doc=base.load_json(ledger,{});prov=doc.get("provenance",{}) if isinstance(doc,dict) else {};idx=base.load_json(base.INDEX,{})
        st.update({"last_anchor_date":base.today(),"last_anchor_kind":"sharded_did_profile","last_anchor_profile":profile,"last_anchor_sha256":prov.get("sha256") if isinstance(prov,dict) else None})
        room_anchor=room_anchor_best_effort(conf,str(prov.get("sha256","")) if isinstance(prov,dict) else "",idx.get("head"));st["last_room_anchor"]=room_anchor;backup=base.backup_snapshot(conf)
    st.update({"version":VERSION,"last_sync_at":base.now_iso(),"last_sync_counts":counts,"profile_publish_result":profile});base.save_json(base.MEMORY_STATE,st)
    return {"counts":counts,"ledger":str(ledger),"profile_published":published,"profile":profile,"anchor_kind":st.get("last_anchor_kind"),"room_anchor":room_anchor,"backup":str(backup) if backup else None}
def status():
    base.status();st=base.load_json(base.MEMORY_STATE,{});print("memory_policy_v242: semantic-dedup + significant-change snapshots");print("anchor_kind:",st.get("last_anchor_kind","-"));print("last_room_anchor:",json.dumps(st.get("last_room_anchor",{}),ensure_ascii=False));return 0
def main():
    p=argparse.ArgumentParser();p.add_argument("--sync",action="store_true");p.add_argument("--finalize",action="store_true");p.add_argument("--status",action="store_true");p.add_argument("--verify",action="store_true");p.add_argument("--backup",action="store_true");p.add_argument("--search");p.add_argument("--version",action="version",version=f"%(prog)s {VERSION}");a=p.parse_args();conf=base.cfg()
    if a.status:return status()
    if a.verify:
        ok,n,h=base.verify_event_chain(conf);ok2,l=base.verify_canonical(conf);print("memory_chain:","OK" if ok else "FAIL","events=",n,"head=",h);print("canonical_ledger:","OK" if ok2 else "FAIL",l);return 0 if ok and ok2 else 2
    if a.backup:print(base.backup_snapshot(conf));return 0
    if a.search is not None:return base.search_memory(a.search)
    if a.sync or a.finalize:print(json.dumps(sync_cycle(finalize=a.finalize),ensure_ascii=False,indent=2));return 0
    raise SystemExit("use --sync/--finalize/--status/--verify/--backup/--search")
if __name__=="__main__":raise SystemExit(main())
