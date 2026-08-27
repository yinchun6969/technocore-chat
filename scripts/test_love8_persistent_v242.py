#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
from pathlib import Path
root=Path(__file__).resolve().parent
def load(name,file):
    s=importlib.util.spec_from_file_location(name,root/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
att=load("att","love8_attention_v242.py");rel=load("rel","love8_relationship_v242.py");deep=load("deep","love8_deep_rooms_v242.py");overlay=load("overlay","love8_brain_v242_overlay.py")
assert att.VERSION=="2.4.2"
assert att.STAGE_BONUS["trusted_peer"]>att.STAGE_BONUS["contacted"]
assert rel.confidence("capacity ceiling room replay","good point on capacity ceiling; I think room replay matters",900)>=70
assert deep.role_for("aizong")=="builder"
assert "reviewer" in deep.role_for("AI2AI")
assert overlay.VERSION=="2.4.2"
print("LOVE8 v2.4.2 STATIC TESTS OK")
