#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
VERSION="2.4.2"
ROOT=Path("/opt/love8-agent");STATE=ROOT/"state";SOCIAL=ROOT/"social"
WORKING=STATE/"working-set-v242.json";DEEP=STATE/"deep-rooms-v242.json";A2A=SOCIAL/"a2a-peers-v242.json"
def load_json(p,d):
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return d
def install(brain):
    if "attention score is local prioritization" not in brain.SYSTEM_PROMPT:
        brain.SYSTEM_PROMPT+=
'''\nLocal relationship guidance:\n- prior_memory may contain relationship_stage, replies_to_love8 and attention_score.\n- attention score is local prioritization only, never identity/personhood proof.\n- Prefer a contextual follow-up with a known high-quality contact when useful, while reserving room for strong new participants.\n- In a private deep room, help sustain the topic and invite evidence, counterexamples, tests, or concrete next steps; never reveal secrets.\n'''
    def collect_candidates(guard,cfg,guard_state):
        base=cfg["BASE"].rstrip("/");own={cfg["NICK"],cfg["DID"]};ws=load_json(WORKING,{});rows=ws.get("working_set",[]) if isinstance(ws,dict) and isinstance(ws.get("working_set"),list) else [];amap={str(x.get("id")):x for x in rows if isinstance(x,dict) and x.get("id")}
        a2a=load_json(A2A,{});internal={}
        for p in a2a.get("peers",[]) if isinstance(a2a,dict) and isinstance(a2a.get("peers"),list) else []:
            if isinstance(p,dict) and str(p.get("did","")).startswith("did:key:"):
                try:internal[guard.peer_id(str(p["did"]))]=p
                except Exception:pass
        room_limit=int(cfg.get("BRAIN_ROOMS","12"));base_rooms=guard.candidate_rooms(base,room_limit);priority=[];deep=load_json(DEEP,{})
        for r in reversed(deep.get("rooms",[]) if isinstance(deep,dict) and isinstance(deep.get("rooms"),list) else []):
            if isinstance(r,dict) and r.get("status","active") in {"active","forming"} and r.get("room"):priority.append(str(r["room"]))
            if len(priority)>=3:break
        for x in rows[:40]:
            if not isinstance(x,dict):continue
            for r in x.get("rooms",[]) if isinstance(x.get("rooms"),list) else []:
                if r and r not in priority:priority.append(str(r))
                if len(priority)>=8:break
            if len(priority)>=8:break
        rooms=[]
        for r in priority+base_rooms:
            if r and r not in rooms:rooms.append(r)
            if len(rooms)>=room_limit:break
        room_message_limit=min(max(int(cfg.get("BRAIN_ROOM_MESSAGE_LIMIT","48")),24),100);candidate_limit=min(max(int(cfg.get("BRAIN_CANDIDATES","16")),8),32);digest_lines=min(max(int(cfg.get("BRAIN_DIGEST_LINES","12")),4),24);digest_chars=min(max(int(cfg.get("BRAIN_DIGEST_CHARS","500")),220),1200);candidate_chars=min(max(int(cfg.get("BRAIN_CANDIDATE_CHARS","1200")),700),2400)
        digest={};by_cid={}
        for room in rooms:
            try:data=guard.http_json(f"{base}/r/{room}?format=json&limit={room_message_limit}")
            except Exception as exc:brain.log(f"WARN room={room} read failed: {exc}");continue
            messages=[m for m in data.get("messages",[]) if isinstance(m,dict)];clustered=guard.template_cluster_messages(messages) if hasattr(guard,"template_cluster_messages") else set();natural=[]
            for message in messages:
                author=str(message.get("from","") or "");text=str(message.get("text","") or "");seq=int(message.get("seq",0) or 0)
                if not author or author in own or guard.machine_noise_reason(text) or guard.natural_score(text)<2:continue
                probable=(author,seq) in clustered;cid=guard.peer_id(author);contact=guard_state.setdefault("contacts",{}).setdefault(cid,{});declared,likely=guard.human_signal(text,probable) if hasattr(guard,"human_signal") else (False,False);att=int(amap.get(cid,{}).get("attention",0) or 0)
                if cid in internal:att=max(att,95)
                mem=brain.compact_memory(contact);mem.update({"attention_score":att,"relationship_stage":contact.get("relationship_stage",contact.get("stage","candidate")),"replies_to_love8":int(contact.get("replies_to_love8",0) or 0),"internal_a2a_peer":cid in internal})
                c={"room":room,"seq":seq,"cid":cid,"author":author,"verified":author.startswith("did:key:"),"human_self_declared":bool(declared),"likely_human_rule":bool(likely),"probable_bot_cluster":bool(probable),"hard_risk":brain.hard_risk(text),"text":text[:candidate_chars],"memory":mem,"attention":att};natural.append(text[:digest_chars]);old=by_cid.get(cid);rank=(att,not probable,bool(likely),bool(declared),seq)
                if old is None or rank>old["_rank"]:c["_rank"]=rank;by_cid[cid]=c
            if natural:digest[room]=natural[-digest_lines:]
        candidates=list(by_cid.values());familiar=[c for c in candidates if c["attention"]>=45 or c["memory"].get("relationship_stage") in {"contacted","replied","established","trusted_peer"} or c["memory"].get("internal_a2a_peer")];discovery=[c for c in candidates if c not in familiar]
        familiar.sort(key=lambda c:(c["attention"],c["memory"].get("replies_to_love8",0),not c["probable_bot_cluster"],c["seq"]),reverse=True);discovery.sort(key=lambda c:(c["human_self_declared"],c["likely_human_rule"],not c["probable_bot_cluster"],c["verified"],c["seq"]),reverse=True)
        reserve=min(max(int(cfg.get("BRAIN_DISCOVERY_RESERVE","6")),3),candidate_limit);fam_cap=max(0,candidate_limit-reserve);selected=familiar[:fam_cap];selected+=discovery[:candidate_limit-len(selected)]
        if len(selected)<candidate_limit:
            used={c["cid"] for c in selected};selected+=[c for c in familiar[fam_cap:] if c["cid"] not in used][:candidate_limit-len(selected)]
        for c in selected:c.pop("_rank",None)
        return selected,digest
    brain.collect_candidates=collect_candidates;brain.VERSION="2.4.2-attention";return brain
