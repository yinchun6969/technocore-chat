#!/usr/bin/env python3
from __future__ import annotations
import argparse,importlib.util,json
from pathlib import Path
VERSION="2.4.2"
ROOT=Path("/opt/love8-agent/social");LEGACY=ROOT/"love8_persistent_v240_core.py";MEMORY=ROOT/"love8_memory_v242.py";ATT=ROOT/"love8_attention_v242.py"
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
    p=argparse.ArgumentParser();p.add_argument("--hourly",action="store_true");p.add_argument("--finalize",action="store_true");p.add_argument("--dry-run",action="store_true");p.add_argument("--status",action="store_true");p.add_argument("--verify",nargs="?",const="latest");p.add_argument("--version",action="version",version=f"%(prog)s {VERSION}");a=p.parse_args();legacy=load("love8_v240",LEGACY);mem=load("love8_mem_v242",MEMORY);att=load("love8_att_v242",ATT)
    if a.status:
        print("===== LOVE8 PERSISTENT AGENT v2.4.2 =====");print("core: v2.4 relationship/topic/contribution");print("memory: v2.4.2 semantic-dedup permanent journal");print("attention: v2.4.2 active working set");legacy.status();print();mem.status();print();att.status();return 0
    if a.verify is not None:
        conf=mem.base.cfg();ok,n,h=mem.base.verify_event_chain(conf);ok2,l=mem.base.verify_canonical(conf);print("memory_chain:","OK" if ok else "FAIL","events=",n,"head=",h);print("canonical_ledger:","OK" if ok2 else "FAIL",l);return 0 if ok and ok2 else 2
    if a.hourly or a.finalize:
        rc=legacy.run_cycle(dry_run=a.dry_run,finalize=a.finalize)
        if rc!=0 or a.dry_run:return rc
        result=mem.sync_cycle(finalize=a.finalize);att.build(160);print("v2.4.2 persistent:",json.dumps(result,ensure_ascii=False));return 0
    raise SystemExit("use --hourly/--finalize/--status/--verify")
if __name__=="__main__":raise SystemExit(main())
