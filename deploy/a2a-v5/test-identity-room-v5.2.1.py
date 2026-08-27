#!/usr/bin/env python3
"""Smoke tests for AI2AI Identity Room v5.2.1 capacity handling."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WRAPPER = ROOT / "identity-room-v5.2.1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("a2a_identity_v521", WRAPPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Agent:
    ROOM = "d-ai2ai"


class FakeCore:
    AGENT = "ai2ai"
    DID = "did:key:z6MkAI2AI"
    BASE = "https://technocore.chat"
    NAME_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
    agent = Agent()

    def __init__(self, state_path: Path):
        self.STATE_FILE = state_path
        self.invited: list[str] = []

    def load_state(self):
        try:
            return json.loads(self.STATE_FILE.read_text())
        except Exception:
            return {"version": "5.2.0", "invites": [], "collisions": []}

    def save_state(self, state):
        self.STATE_FILE.write_text(json.dumps(state))

    @staticmethod
    def base_room():
        return "ai2ai"

    @staticmethod
    def probe(room):
        assert room == "d-ai2ai"
        return "owned", 77

    def resolve(self, state):
        state.update({"room": "ai2ai", "base_room": "ai2ai"})
        self.save_state(state)
        return "ai2ai", "empty", 0

    @staticmethod
    def bootstrap(state, room, status):
        del state, room, status
        raise RuntimeError(
            "signed write failed: 400 400 room limit reached (20480 is the cap, and this would be a new one)"
        )

    def invite(self, state, room):
        del state
        self.invited.append(room)
        return 1

    @staticmethod
    def mature_peers():
        return []

    @staticmethod
    def prune_invites(state, now):
        del now
        return state.get("invites", [])


def test_capacity_detector() -> None:
    mod = load_module()
    assert mod.VERSION == "5.2.1"
    assert mod.capacity_error(RuntimeError("400 room limit reached 20480 is the cap"))
    assert not mod.capacity_error(RuntimeError("429 rate limited"))


def test_sync_falls_back_to_existing_owned_room() -> None:
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        core = FakeCore(Path(td) / "state.json")
        old_room_file = mod.ROOM_FILE
        mod.ROOM_FILE = Path(td) / "room-name"
        try:
            result = mod.sync(core)
            assert result["room"] == "d-ai2ai"
            assert result["status"] == "capacity-fallback"
            state = core.load_state()
            assert state["desired_room"] == "ai2ai"
            assert state["room"] == "d-ai2ai"
            assert state["bootstrap_mode"] == "capacity-fallback-existing"
            assert state["capacity_wait_until"] > int(time.time())
            assert mod.ROOM_FILE.read_text().strip() == "d-ai2ai"
            assert core.invited == ["d-ai2ai"]
        finally:
            mod.ROOM_FILE = old_room_file


def test_backoff_reuses_fallback_without_new_room_attempt() -> None:
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        core = FakeCore(Path(td) / "state.json")
        now = int(time.time())
        core.save_state(
            {
                "room": "d-ai2ai",
                "base_room": "ai2ai",
                "desired_room": "ai2ai",
                "bootstrap_mode": "capacity-fallback-existing",
                "capacity_wait_until": now + 3600,
                "last_seen_seq": 77,
                "invites": [],
            }
        )
        old_room_file = mod.ROOM_FILE
        mod.ROOM_FILE = Path(td) / "room-name"
        core.resolve = lambda state: (_ for _ in ()).throw(AssertionError("must not resolve during backoff"))
        try:
            result = mod.sync(core)
            assert result["room"] == "d-ai2ai"
            assert result["status"] == "capacity-fallback"
        finally:
            mod.ROOM_FILE = old_room_file


def main() -> int:
    test_capacity_detector()
    test_sync_falls_back_to_existing_owned_room()
    test_backoff_reuses_fallback_without_new_room_attempt()
    print("AI2AI Identity Room v5.2.1 capacity-aware smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
