#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
from pathlib import Path
VERSION="2.4.2"
ROOT=Path("/opt/love8-agent/social")
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None:raise SystemExit(f"cannot load {path}")
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
brain=load("love8_brain_core",ROOT/"love8_brain.py");brain.guard=brain.load_guard();compat=ROOT/"love8_brain_compat.py"
if compat.exists():brain.chat=load("love8_compat",compat).make_chat(brain)
overlay=load("love8_v242_overlay",ROOT/"love8_brain_v242_overlay.py");overlay.install(brain)
if __name__=="__main__":raise SystemExit(brain.main())
