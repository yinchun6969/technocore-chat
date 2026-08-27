#!/usr/bin/env python3
"""Smoke tests for aizong Social Brain v1.5.0 ai2ai Collaboration Hub."""

from __future__ import annotations

import importlib.util
import os
import tempfile
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
]


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patched_module() -> tuple[Any, str]:
    patchers = [load_module(f"aizong_patch_{idx}", path) for idx, path in enumerate(PATCHERS)]
    source = BASE_PROGRAM.read_text(encoding="utf-8")
    for patcher in patchers:
        source = patcher.patch_source(source)
    assert patchers[-1].patch_source(source) == source
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
        handle.write(source)
        path = Path(handle.name)
    try:
        return load_module("aizong_social_v150", path), source
    finally:
        path.unlink(missing_ok=True)


def test_patch_contract_and_inherited_safety() -> None:
    mod, source = patched_module()
    assert mod.VERSION == "1.5.0"
    assert "/r/ai2ai is aizong's operator-selected public collaboration home room" in mod.BRAIN_SYSTEM
    assert "not a trust boundary" in mod.BRAIN_SYSTEM
    assert "Never invent a public memory" in mod.BRAIN_SYSTEM
    assert "Do not optimize public behavior for faucets" in mod.BRAIN_SYSTEM
    assert "TC_TEMPLATE_BLOCK_SIMILARITY_PCT" in source
    assert "TC_MEMORY_DAILY_SYNC_CAP" in source
    assert 'rules["prompt_injection_risk"] >= 70' in source
    assert 'rules["scam_risk"] >= 70' in source
    assert 'TC_NET_RETRIES", 3' in source


def test_home_room_is_always_scanned() -> None:
    mod, _ = patched_module()
    old_room = os.environ.get("TC_HOME_ROOM")
    old_enabled = os.environ.get("TC_HUB_ENABLED")
    try:
        os.environ["TC_HOME_ROOM"] = "ai2ai"
        os.environ["TC_HUB_ENABLED"] = "1"
        assert mod._hub_rooms(["lobby", "technocore", "cloud"], 3) == [
            "ai2ai",
            "lobby",
            "technocore",
        ]
        assert mod._hub_rooms(["ai2ai", "lobby"], 3) == ["ai2ai", "lobby"]
    finally:
        if old_room is None:
            os.environ.pop("TC_HOME_ROOM", None)
        else:
            os.environ["TC_HOME_ROOM"] = old_room
        if old_enabled is None:
            os.environ.pop("TC_HUB_ENABLED", None)
        else:
            os.environ["TC_HUB_ENABLED"] = old_enabled


def qualified_state(mod: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    author = "did:key:z6MkQualifiedHubPeer"
    state: dict[str, Any] = {
        "contacts": {
            mod.peer_id(author): {
                "author": author,
                "verified": True,
                "relationship_stage": "trusted_peer",
                "trust_score": 78,
                "interest_score": 82,
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


def test_invitation_gate_is_selective_and_rate_limited() -> None:
    mod, _ = patched_module()
    state, action, decision = qualified_state(mod)
    allowed, _ = mod._hub_invite_allowed(state, action, decision, "technocore")
    assert allowed

    weak = dict(decision)
    weak["contribution_value"] = 20
    allowed, reason = mod._hub_invite_allowed(state, action, weak, "technocore")
    assert not allowed
    assert "contribution" in reason

    unsigned_action = dict(action)
    unsigned_action["peer_author"] = "some-nick"
    allowed, reason = mod._hub_invite_allowed(state, unsigned_action, decision, "technocore")
    assert not allowed
    assert "did:key" in reason

    mod._note_hub_invite(state, str(action["peer_author"]), "technocore", 123)
    allowed, reason = mod._hub_invite_allowed(state, action, decision, "technocore")
    assert not allowed
    assert "cooldown" in reason


def test_invite_is_piggybacked_not_separate_message() -> None:
    mod, _ = patched_module()
    state, action, decision = qualified_state(mod)
    text, invited, reason = mod._attach_hub_invite(
        state,
        action,
        decision,
        "technocore",
        "The nonce check should happen before retrying an ambiguous signed write.",
    )
    assert invited
    assert "qualified" in reason
    assert "/r/ai2ai" in text
    assert len(text) <= mod.MAX_BRAIN_TEXT


def test_bootstrap_existing_room_does_not_write() -> None:
    mod, _ = patched_module()
    state: dict[str, Any] = {}
    calls: list[str] = []
    original_http = mod.http_json
    original_signed = mod.signed_post
    try:
        mod.http_json = lambda url: {"messages": [{"seq": 9}], "last_seq": 9}
        mod.signed_post = lambda *args, **kwargs: calls.append("signed") or {"last_seq": 10}
        mod._ensure_home_room(
            "https://technocore.chat",
            "aizong",
            "did:key:z6MkAizong",
            "/tmp/key",
            state,
            dry_run=False,
        )
        assert calls == []
        hub: dict[str, Any] = state["home_hub"]
        assert hub["bootstrapped"] is True
        assert hub["bootstrap_mode"] == "existing-room"
        assert hub["last_seen_seq"] == 9
    finally:
        mod.http_json = original_http
        mod.signed_post = original_signed


def test_empty_room_gets_one_signed_bootstrap() -> None:
    mod, _ = patched_module()
    state: dict[str, Any] = {}
    signed_calls: list[tuple[str, str]] = []
    topic_calls: list[tuple[str, str]] = []
    original_http = mod.http_json
    original_signed = mod.signed_post
    original_topic = mod._set_home_topic
    try:
        mod.http_json = lambda url: {"messages": [], "last_seq": 0}

        def fake_signed(base: str, did: str, key: str, room: str, text: str, current: dict[str, Any]) -> dict[str, Any]:
            signed_calls.append((room, text))
            return {"last_seq": 42}

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
        assert len(signed_calls) == 1
        assert signed_calls[0][0] == "ai2ai"
        assert "status and check-in traffic is ignored" in signed_calls[0][1]
        assert topic_calls == [("https://technocore.chat", "ai2ai")]
        hub: dict[str, Any] = state["home_hub"]
        assert hub["bootstrap_mode"] == "signed-create"
        assert hub["bootstrap_seq"] == 42
        assert len(state["writes"]) == 1
    finally:
        mod.http_json = original_http
        mod.signed_post = original_signed
        mod._set_home_topic = original_topic


def test_bootstrap_and_topic_are_not_reward_farming_copy() -> None:
    mod, _ = patched_module()
    combined = (mod._hub_bootstrap_text("aizong") + " " + mod._hub_topic_text()).lower()
    assert "airdrop" not in combined
    assert "faucet" not in combined
    assert "reward" not in combined
    assert "points" not in combined
    assert "public collaboration" in combined


def main() -> int:
    test_patch_contract_and_inherited_safety()
    test_home_room_is_always_scanned()
    test_invitation_gate_is_selective_and_rate_limited()
    test_invite_is_piggybacked_not_separate_message()
    test_bootstrap_existing_room_does_not_write()
    test_empty_room_gets_one_signed_bootstrap()
    test_bootstrap_and_topic_are_not_reward_farming_copy()
    print("aizong Social v1.5.0 ai2ai collaboration hub smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
