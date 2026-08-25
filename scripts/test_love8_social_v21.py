#!/usr/bin/env python3
"""Fast self-tests for Love8 Social v2.1 filtering/staging primitives."""
from __future__ import annotations
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("love8_social", HERE / "love8_social.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

assert mod.machine_noise_reason("env:v1:AbCdEf012345+/=") == "encoded-envelope"
assert mod.natural_score("I'm working on a Bittensor subnet monitor. What are you testing?") >= 2
assert mod.human_signal("I'm human here, just curious what these agents are doing.")[0] is True
assert mod.human_signal("I built a small agent monitor and I'm testing it.")[1] is True
assert mod.natural_score("did:key:z6Mk123") == 0

state = {"contacts": {f"did:{i}": {"messages_seen": 1} for i in range(20)}}
mod.migrate_v21(state)
assert len(state["contacts"]) == 0
assert state["v21_pruned_contacts"] == 20

print("Love8 Social v2.1 self-tests: OK")
