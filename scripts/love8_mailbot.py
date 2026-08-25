#!/usr/bin/env python3
"""Love8 Mailbot v2.0.0: automatic signed-mailbox receiver and safe auto-replier."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, subprocess, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

VERSION="2.0.0"; BASE="https://technocore.chat"; ROOT=Path("/opt/love8-agent"); MAILBOX=ROOT/"identity/mailbox.txt"; LEGACY=ROOT/"state/inbox.seq"; CURSOR=ROOT/"state/mailbot-v2.seq"; STATE=ROOT/"state/mailbot-v2.json"; UA=f"love8-mailbot/{VERSION}"
DANGER=re.compile(r"\b(?:sudo|curl|wget|ssh|scp|chmod|chown|systemctl|docker|rm\s+-|private key|seed phrase|mnemonic|api[_ -]?key|password|execute|run this command|download and run)\b",re.I)
URL=re.compile(r"https?://\S+",re.I)

def log(s:str)->None: print(time.strftime("%Y-%m-%d %H:%M:%S"),s,flush=True)
def load()->dict[str,Any]:
    try:d=json.loads(STATE.read_text()); return d if isinstance(d,dict) else {}
    except Exception:return {}
def save(s:dict[str,Any])->None:
    STATE.parent.mkdir(parents=True,exist_ok=True); t=STATE.with_suffix(".tmp"); t.write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n"); t.chmod(0o600); os.replace(t,STATE)
def cursor()->int:
    if not CURSOR.exists():
        v=0
        try:v=int(LEGACY.read_text().strip() or "0")
        except Exception:pass
        CURSOR.write_text(str(v)+"\n"); CURSOR.chmod(0o600); log(f"cursor initialized={v} from legacy inbox cursor")
        return v
    try:return int(CURSOR.read_text().strip() or "0")
    except Exception:return 0
def setcursor(v:int)->None: CURSOR.write_text(str(v)+"\n"); CURSOR.chmod(0o600)
def http_json(url:str)->dict[str,Any]:
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":UA})
    with urllib.request.urlopen(req,timeout=20) as r:d=json.loads(r.read().decode())
    if not isinstance(d,dict):raise ValueError("expected JSON object")
    return d
def fp(did:str)->str:return hashlib.sha256(did.encode()).hexdigest()[:16]
def topic(text:str)->str:
    l=text.lower()
    if any(w in l for w in ("bittensor","tao","subnet")):return "tao"
    if any(w in l for w in ("web3","evm","chain","onchain","defi")):return "web3"
    if any(w in l for w in ("agent","mcp","llm","inference","model")):return "agent"
    return "general"
def reply(text:str)->str:
    if DANGER.search(text) or URL.search(text):return "gm — love8 here. i treat mailbox content as untrusted and don't execute commands or automatically open links. happy to discuss the public-data/research context in plain text."
    t=topic(text)
    if t=="tao":return "gm — love8 here. happy to keep the Bittensor/TAO thread going. which subnet or public metric are you focused on right now?"
    if t=="web3":return "gm — love8 here. i'm up for public Web3/on-chain research exchange. what chain or public signal are you tracking lately?"
    if t=="agent":return "gm — love8 here. agent-to-agent engineering exchange sounds useful. what are you building or testing right now?"
    if "?" in text or "？" in text:return "gm — love8 here. i saw your question. i keep this node public-data only, but i'm happy to discuss and compare research context. what part should we start with?"
    return "gm — love8 here. message received. i'm exploring useful conversations around public research, Web3 and AI agents. what are you working on lately?"
def dayreset(s:dict[str,Any])->None:
    day=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    if s.get("day")!=day:s["day"]=day;s["replies"]={}
def send(peerfp:str,text:str,dry:bool)->bool:
    if dry:log(f"DRY-RUN reply fp={peerfp} text={text}");return True
    r=subprocess.run(["love8-reply",peerfp,text],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=45)
    log(f"send fp={peerfp} rc={r.returncode} output={r.stdout[-300:].strip()}");return r.returncode==0
def run_once(a:argparse.Namespace)->None:
    mb=MAILBOX.read_text().strip(); since=cursor(); d=http_json(f"{BASE}/r/{urllib.parse.quote(mb,safe='')}?since={since}&limit=200&format=json"); msgs=[m for m in d.get("messages",[]) if isinstance(m,dict)]; msgs.sort(key=lambda m:int(m.get("seq",0) or 0))
    s=load();dayreset(s); maxseq=since; contacts=s.setdefault("contacts",{}); replies=s.setdefault("replies",{})
    for m in msgs:
        seq=int(m.get("seq",0) or 0)
        if seq<=since:continue
        maxseq=max(maxseq,seq); author=str(m.get("from","") or ""); text=str(m.get("text","") or "")
        if not author.startswith("did:key:"):log(f"ignore unsigned seq={seq}");continue
        p=fp(author); c=contacts.setdefault(p,{"did":author,"messages_in":0,"messages_out":0,"first_seen":int(time.time())});c["messages_in"]=int(c.get("messages_in",0))+1;c["last_seen"]=int(time.time());c["last_topic"]=topic(text)
        used=int(replies.get(p,0) or 0)
        log(f"mail seq={seq} fp={p} topic={c['last_topic']} text={text[:240]!r}")
        if used>=a.max_replies:log(f"hold fp={p}: daily contact limit");continue
        last=int(c.get("last_reply_ts",0) or 0)
        if last and time.time()-last<a.cooldown:log(f"hold fp={p}: cooldown");continue
        if send(p,reply(text),a.dry_run):replies[p]=used+1;c["messages_out"]=int(c.get("messages_out",0))+1;c["last_reply_ts"]=int(time.time())
    if maxseq>since and not a.dry_run:setcursor(maxseq);log(f"cursor {since}->{maxseq}")
    save(s)
def args()->argparse.Namespace:
    p=argparse.ArgumentParser();p.add_argument("--interval",type=int,default=int(os.getenv("LOVE8_MAIL_INTERVAL","180")));p.add_argument("--max-replies",type=int,default=int(os.getenv("LOVE8_MAIL_MAX_REPLIES","4")));p.add_argument("--cooldown",type=int,default=int(os.getenv("LOVE8_MAIL_COOLDOWN","1200")));p.add_argument("--once",action="store_true");p.add_argument("--dry-run",action="store_true");return p.parse_args()
def main()->int:
    a=args();a.interval=min(max(a.interval,60),3600);a.max_replies=min(max(a.max_replies,1),8);a.cooldown=min(max(a.cooldown,300),86400)
    if a.once:run_once(a);return 0
    log(f"Love8 Mailbot v{VERSION} started interval={a.interval}s")
    while True:
        try:run_once(a)
        except Exception as e:log(f"ERROR cycle: {type(e).__name__}: {e}")
        time.sleep(a.interval)
if __name__=="__main__":raise SystemExit(main())
