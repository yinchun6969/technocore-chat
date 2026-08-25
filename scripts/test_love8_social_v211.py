#!/usr/bin/env python3
"""Regression checks for Love8 Social v2.1.1 human-signal and template-cluster rules."""
from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).with_name("love8_social.py")
spec = importlib.util.spec_from_file_location("love8_social", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

q1 = "What do you think are the biggest advantages of on-chain trading?"
q2 = "What do you think are the biggest challenges facing DAOs today?"
personal = "I've been testing a validator on my server for two days and it keeps dropping peers."
human = "I'm a human testing this network."

assert mod.human_signal(q1) == (False, False)
assert mod.human_signal(q2) == (False, False)
assert mod.human_signal(personal) == (False, True)
assert mod.human_signal(human)[0] is True

cluster = mod.template_cluster_messages(
    [
        {"from": "did:key:a", "seq": 5, "text": q1},
        {"from": "did:key:b", "seq": 8, "text": q2},
    ]
)
assert ("did:key:a", 5) in cluster
assert ("did:key:b", 8) in cluster
assert mod.human_signal(personal, probable_bot_cluster=True) == (False, False)

print("LOVE8 SOCIAL v2.1.1 REGRESSION TESTS OK")
