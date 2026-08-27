#!/usr/bin/env python3
"""Smoke tests for Social v1.5.1 identity-named deep collaboration rooms."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_PROGRAM = ROOT / "scripts" / "aizong_social.py"
PATCHERS = [
    ROOT / "scripts" / "patch_aizong_social_v130.py",
    ROOT / "scripts" / "patch_aizong_social_v131.py",
    ROOT / "scripts" / "patch_aizong_social_v140.py",
    ROOT / "scripts" / "patch_aizong_social_v141.py",
    ROOT / "scripts" / "patch_aizong_social_v142.py",
    ROOT / "scripts" / "patch_aizong_social_v150.py",
    ROOT / "scripts" / "patch_aizong_social_v151.py",
]


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patched_module() -> tuple[Any, str]:
    patchers = [load_module(f"identity_patch_{idx}", path) for idx, path in enumerate(PATCHERS)]
    source = BASE_PROGRAM.read_text(encoding="utf-8")
    for patcher in patchers:
        source = patcher.patch_source(source)
    assert patchers[-1].patch_source(source) == source
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
        handle.write(source)
        path = Path(handle.name)
    try:
        return load_module("social_v151", path), source
    finally:
        path.unlink(missing_ok=True)


def with_env(**updates: str):
    class Env:
        def __enter__(self):
            self.old = {key: os.environ.get(key) for key in updates}
            os.environ.update(updates)
            os.environ.pop("TC_HOME_ROOM_RESOLVED", None)
            return self

        def __exit__(self, exc_type, exc, tb):
            for key, value in self.old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            os.environ.pop("TC_HOME_ROOM_RESOLVED", None)

    return Env()


def test_patch_chain_and_generic_identity() -> None:
    mod, source = patched_module()
    assert mod.VERSION == "1.5.1"
    assert "identity-named public collaboration home room" in mod.BRAIN_SYSTEM
    assert "deep continuity" in mod.BRAIN_SYSTEM
    assert "Do not optimize public behavior for faucets" in mod.BRAIN_SYSTEM
    assert 'rules["prompt_injection_risk"] >= 70' in source
    assert 'rules["scam_risk"] >= 70' in source
    assert "TC_MEMORY_DAILY_SYNC_CAP" in source
    assert "TC_TEMPLATE_BLOCK_SIMILARITY_PCT" in source

    for nick in ("aizong", "love8", "ai2ai"):
        with with_env(TC_AGENT_NICK=nick, TC_HOME_ROOM="wrong-old-room"):
            assert mod._identity_room_base() == nick
            assert mod._home_room_name() == nick
            assert mod._hub_rooms(["lobby", "technocore"], 3)[0] == nick
            assert nick in mod.fallback_reply("hello", nick)


def test_collision_uses_zero_padded_suffix_and_bootstraps() -> None:
    mod, _ = patched_module()
    state: dict[str, Any] = {}
    signed_calls: list[tuple[str, str]] = []
    topic_calls: list[tuple[str, str]] = []
    original_http = mod.http_json
    original_signed = mod.signed_post
    original_topic = mod._set_home_topic
    try:
        with with_env(TC_AGENT_NICK="aizong", TC_HOME_ROOM="ai2ai"):
            def fake_http(url: str, timeout: int = 20) -> dict[str, Any]:
                if "/r/aizong?" in url:
                    return {
                        "messages": [{"seq": 9, "from": "did:key:z6MkOtherOwner", "text": "occupied"}],
                        "last_seq": 9,
                    }
                if "/r/aizong00?" in url:
                    return {"messages": [], "last_seq": 0}
                raise AssertionError(url)

            def fake_signed(
                base: str,
                did: str,
                key: str,
                room: str,
                text: str,
                current: dict[str, Any],
            ) -> dict[str, Any]:
                signed_calls.append((room, text))
                return {"last_seq": 42}

            mod.http_json = fake_http
            mod.signed_post = fake_signed
            mod._set_home_topic = lambda base, room: topic_calls.append((base, room))
            mod._ensure_home_room(
                "https://technocore.chat",
                "aizong",
                "did:key:z6MkAizong",
                "/tmp/key",
                state,
                dry_run=False,
            )
            assert signed_calls and signed_calls[0][0] == "aizong00"
            assert "/r/aizong00" in signed_calls[0][1]
            assert topic_calls == [("https://technocore.chat", "aizong00")]
            hub = state["home_hub"]
            assert hub["base_room"] == "aizong"
            assert hub["room"] == "aizong00"
            assert hub["owner_did"] == "did:key:z6MkAizong"
            assert hub["bootstrap_seq"] == 42
            assert mod._home_room_name() == "aizong00"
    finally:
        mod.http_json = original_http
        mod.signed_post = original_signed
        mod._set_home_topic = original_topic


def test_existing_same_did_room_is_reused_without_write() -> None:
    mod, _ = patched_module()
    state: dict[str, Any] = {}
    signed_calls: list[str] = []
    original_http = mod.http_json
    original_signed = mod.signed_post
    try:
        with with_env(TC_AGENT_NICK="ai2ai"):
            mod.http_json = lambda url, timeout=20: {
                "messages": [{"seq": 12, "from": "did:key:z6MkAi2Ai", "text": "home"}],
                "last_seq": 12,
            }
            mod.signed_post = lambda *args, **kwargs: signed_calls.append("write") or {"last_seq": 13}
            mod._ensure_home_room(
                "https://technocore.chat",
                "ai2ai",
                "did:key:z6MkAi2Ai",
                "/tmp/key",
                state,
                dry_run=False,
            )
            assert signed_calls == []
            assert state["home_hub"]["room"] == "ai2ai"
            assert state["home_hub"]["owner_did"] == "did:key:z6MkAi2Ai"
            assert state["home_hub"]["bootstrap_mode"] == "existing-self"
    finally:
        mod.http_json = original_http
        mod.signed_post = original_signed


def mature_contact(mod: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    author = "did:key:z6MkMaturePeer"
    state: dict[str, Any] = {
        "contacts": {
            mod.peer_id(author): {
                "author": author,
                "verified": True,
                "relationship_stage": "trusted_peer",
                "trust_score": 78,
                "interest_score": 82,
                "inbound_count": 5,
                "outbound_count": 4,
                "first_seen": int(time.time()) - 8 * 3600,
                "scam_risk": 0,
                "prompt_injection_risk": 0,
                "spam_probability": 0,
            }
        }
    }
    action: dict[str, Any] = {
        "kind": "reply",
        "peer_author": author,
        "room": "technocore",
    }
    decision: dict[str, Any] = {
        "mode": "ai",
        "reply": True,
        "contribution_value": 78,
        "interest": 82,
        "durable_state_value": 76,
        "collaboration_signal": True,
        "scam_risk": 0,
        "prompt_injection_risk": 0,
        "spam_probability": 0,
    }
    return state, action, decision


def test_only_mature_long_relationships_are_invited() -> None:
    mod, _ = patched_module()
    with with_env(TC_AGENT_NICK="aizong"):
        state, action, decision = mature_contact(mod)
        allowed, reason = mod._hub_invite_allowed(state, action, decision, "technocore")
        assert allowed, reason

        cid = mod.peer_id(str(action["peer_author"]))
        state["contacts"][cid]["relationship_stage"] = "recurring_contact"
        allowed, reason = mod._hub_invite_allowed(state, action, decision, "technocore")
        assert not allowed and "not mature enough" in reason

        state["contacts"][cid]["relationship_stage"] = "trusted_peer"
        state["contacts"][cid]["first_seen"] = int(time.time()) - 60
        allowed, reason = mod._hub_invite_allowed(state, action, decision, "technocore")
        assert not allowed and "too new" in reason

        state["contacts"][cid]["first_seen"] = int(time.time()) - 8 * 3600
        state["contacts"][cid]["inbound_count"] = 1
        allowed, reason = mod._hub_invite_allowed(state, action, decision, "technocore")
        assert not allowed and "relationship depth" in reason


def test_invite_targets_resolved_identity_room() -> None:
    mod, _ = patched_module()
    with with_env(TC_AGENT_NICK="aizong"):
        os.environ["TC_HOME_ROOM_RESOLVED"] = "aizong00"
        state, action, decision = mature_contact(mod)
        text, invited, _ = mod._attach_hub_invite(
            state,
            action,
            decision,
            "technocore",
            "The nonce and idempotency behavior is worth comparing in more detail.",
        )
        assert invited
        assert "/r/aizong00" in text
        assert len(text) <= mod.MAX_BRAIN_TEXT


def main() -> int:
    test_patch_chain_and_generic_identity()
    test_collision_uses_zero_padded_suffix_and_bootstraps()
    test_existing_same_did_room_is_reused_without_write()
    test_only_mature_long_relationships_are_invited()
    test_invite_targets_resolved_identity_room()
    print("Social v1.5.1 identity-named deep collaboration room smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
