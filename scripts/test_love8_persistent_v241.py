#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


memory = load("love8_memory_v241_test", HERE / "love8_memory_v241.py")
upstream = load("love8_upstream_v241_test", HERE / "love8_upstream_scout_v241.py")

assert memory.VERSION == "2.4.1"
assert memory.canonical({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
assert memory.event_id("x", "y", {"z": 1}) == memory.event_id("x", "y", {"z": 1})
assert memory.event_id("x", "y", {"z": 1}) != memory.event_id("x", "y", {"z": 2})
ns, key, path = memory.sharded_profile_path("913b3d032992b96b")
assert ns == "did-91"
assert key == "3b3d032992b96b"
assert path == "/kv/did-91/3b3d032992b96b"

score, reasons = upstream.score_issue({
    "title": "race regression with reproducible failure",
    "body": "## Reproduction\n```python\nassert False\n```\npytest fails 11/60 runs. Suggested fix and benchmark 3.9ms -> 2.2ms.",
    "comments": 1,
    "labels": [],
})
assert score >= 70, (score, reasons)
score2, _ = upstream.score_issue({"title": "idea", "body": "maybe add feature", "comments": 20, "labels": []})
assert score2 < score

print("LOVE8 PERSISTENT v2.4.1 TESTS OK")
