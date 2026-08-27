#!/usr/bin/env python3
"""Smoke tests for Love8 Persistent v2.5.0 identity-named deep room."""

from __future__ import annotations

import importlib.util
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "love8_persistent_v250_wrapper.py"


def load_module():
    spec = importlib.util.spec_from_file_location("love8_v250", WRAPPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeGuard:
    def __init__(self, rooms: dict[str, dict[str, Any]]):
        self.rooms = rooms
        self.posts: list[tuple[str, str]] = []

    def http_json(self, url: str) -> dict[str, Any]:
        room = url.split("/r/", 1)[1].split("?", 1)[0]
        return self.rooms.get(room, {"messages": [], "last_seq": 0})

    def budget(self, state: dict[str, Any], hourly: int, daily: int) -> bool:
        del state, hourly, daily
        return True

    def signed_post(
        self,
        base: str,
        did: str,
        key: str,
        room: str,
        text: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        del base, did, key, state
        self.posts.append((room, text))
        return {"last_seq": 42}


def cfg(nick: str = "love8") -> dict[str, str]:
    return {
        "BASE": "https://technocore.chat",
        "NICK": nick,
        "DID": f"did:key:z6Mk{nick}",
        "KEY": "/tmp/fake-key",
        "PERSIST_DEEP_MIN_SCORE": "78",
        "PERSIST_DEEP_MIN_INBOUND": "3",
        "PERSIST_DEEP_MIN_OUTBOUND": "3",
        "PERSIST_DEEP_MIN_AGE": "21600",
        "PERSIST_DEEP_MIN_TRUST": "55",
        "PERSIST_DEEP_MAX_RISK": "25",
        "PERSIST_DEEP_MAX_BOT": "60",
        "PERSIST_DEEP_INVITES_PER_DAY": "3",
        "PERSIST_DEEP_PEER_COOLDOWN": "604800",
        "BRAIN_PUBLIC_HOURLY_WRITES": "6",
        "BRAIN_PUBLIC_DAILY_WRITES": "20",
        "PERSIST_ROOM_CREATE_ENABLED": "yes",
    }


def mature_contact(now: int) -> dict[str, Any]:
    return {
        "verified": True,
        "relationship_stage": "trusted_peer",
        "relationship_score": 88,
        "messages_out": 4,
        "replies_to_love8": 5,
        "first_seen": now - 8 * 3600,
        "brain": {
            "trust_score": 80,
            "scam_risk": 0,
            "bot_probability": 20,
            "topics": ["DID retry semantics"],
        },
    }


def test_room_names_match_agent_identity() -> None:
    mod = load_module()
    for nick in ("aizong", "love8", "ai2ai"):
        conf = cfg(nick)
        assert mod.room_base(conf) == nick
        assert mod.room_candidate(nick, None) == nick
        assert mod.room_candidate(nick, 0) == nick + "00"
        assert mod.room_candidate(nick, 1) == nick + "01"
        assert mod.room_candidate(nick, 99) == nick + "99"


def test_collision_moves_to_zero_padded_room() -> None:
    mod = load_module()
    conf = cfg("love8")
    guard = FakeGuard(
        {
            "love8": {
                "messages": [{"seq": 8, "from": "did:key:z6MkOther", "text": "occupied"}],
                "last_seq": 8,
            },
            "love800": {"messages": [], "last_seq": 0},
        }
    )
    state: dict[str, Any] = {}
    room, status, seq = mod.select_room(guard, conf, state)
    assert room == "love800"
    assert status == "empty"
    assert seq == 0
    assert state["collisions"] == ["love8"]
    assert state["room"] == "love800"


def test_same_did_room_is_reused() -> None:
    mod = load_module()
    conf = cfg("love8")
    guard = FakeGuard(
        {
            "love8": {
                "messages": [{"seq": 12, "from": conf["DID"], "text": "home"}],
                "last_seq": 12,
            }
        }
    )
    room, status, seq = mod.select_room(guard, conf, {})
    assert room == "love8"
    assert status == "owned"
    assert seq == 12


def test_mature_peer_gate_requires_history_depth_and_low_risk() -> None:
    mod = load_module()
    now = int(time.time())
    conf = cfg()
    contact = mature_contact(now)
    assert mod.mature_peer(contact, conf, now=now)

    weak = dict(contact)
    weak["relationship_stage"] = "established"
    assert not mod.mature_peer(weak, conf, now=now)

    shallow = dict(contact)
    shallow["replies_to_love8"] = 1
    assert not mod.mature_peer(shallow, conf, now=now)

    fresh = dict(contact)
    fresh["first_seen"] = now - 60
    assert not mod.mature_peer(fresh, conf, now=now)

    risky = dict(contact)
    risky["brain"] = dict(contact["brain"], scam_risk=70)
    assert not mod.mature_peer(risky, conf, now=now)


def test_invite_cooldown_and_daily_cap() -> None:
    mod = load_module()
    conf = cfg()
    now = 2_000_000_000.0
    state: dict[str, Any] = {}
    assert mod.invite_allowed(state, "did:1111111111111111", conf, now=now)
    mod.note_invite(state, "did:1111111111111111", "love8", now=now)
    assert not mod.invite_allowed(state, "did:1111111111111111", conf, now=now + 10)
    mod.note_invite(state, "did:2222222222222222", "love8", now=now + 20)
    mod.note_invite(state, "did:3333333333333333", "love8", now=now + 30)
    assert not mod.invite_allowed(state, "did:4444444444444444", conf, now=now + 40)


def test_identity_cycle_bootstraps_once_and_selects_mature_peers() -> None:
    mod = load_module()
    now = int(time.time())
    conf = cfg("love8")
    guard = FakeGuard({"love8": {"messages": [], "last_seq": 0}})
    social_state: dict[str, Any] = {
        "contacts": {
            "did:1111111111111111": mature_contact(now),
            "did:2222222222222222": {
                **mature_contact(now),
                "relationship_stage": "established",
            },
        },
        "writes": [],
    }
    persist_state: dict[str, Any] = {}

    with tempfile.TemporaryDirectory() as td:
        old_state = mod.IDENTITY_STATE
        mod.IDENTITY_STATE = Path(td) / "identity.json"
        try:
            record = mod.identity_room_cycle(
                guard,
                conf,
                social_state,
                persist_state,
                [],
                dry_run=False,
            )
            assert record is not None
            assert guard.posts and guard.posts[0][0] == "love8"
            assert "/r/love8" in guard.posts[0][1]
            assert record["peer_ids"] == ["did:1111111111111111"]
            saved = mod.load_json(mod.IDENTITY_STATE)
            assert saved["room"] == "love8"
            assert saved["bootstrap_seq"] == 42
        finally:
            mod.IDENTITY_STATE = old_state


def main() -> int:
    test_room_names_match_agent_identity()
    test_collision_moves_to_zero_padded_room()
    test_same_did_room_is_reused()
    test_mature_peer_gate_requires_history_depth_and_low_risk()
    test_invite_cooldown_and_daily_cap()
    test_identity_cycle_bootstraps_once_and_selects_mature_peers()
    print("Love8 Persistent v2.5.0 identity-room smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
