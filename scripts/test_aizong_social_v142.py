#!/usr/bin/env python3
"""Smoke tests for aizong Social Brain v1.4.2 Memory Consolidation."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_PROGRAM = ROOT / "scripts" / "aizong_social.py"
PATCH_130 = ROOT / "scripts" / "patch_aizong_social_v130.py"
PATCH_131 = ROOT / "scripts" / "patch_aizong_social_v131.py"
PATCH_140 = ROOT / "scripts" / "patch_aizong_social_v140.py"
PATCH_141 = ROOT / "scripts" / "patch_aizong_social_v141.py"
PATCH_142 = ROOT / "scripts" / "patch_aizong_social_v142.py"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patched_module() -> tuple[Any, str]:
    patchers = [
        load_module("aizong_p130_for_v142", PATCH_130),
        load_module("aizong_p131_for_v142", PATCH_131),
        load_module("aizong_p140_for_v142", PATCH_140),
        load_module("aizong_p141_for_v142", PATCH_141),
        load_module("aizong_p142", PATCH_142),
    ]
    source = BASE_PROGRAM.read_text(encoding="utf-8")
    for patcher in patchers:
        source = patcher.patch_source(source)
    assert patchers[-1].patch_source(source) == source
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
        handle.write(source)
        path = Path(handle.name)
    try:
        return load_module("aizong_social_v142", path), source
    finally:
        path.unlink(missing_ok=True)


def test_patch_contract() -> None:
    mod, source = patched_module()
    assert mod.VERSION == "1.4.2"
    assert "memory.public_safe" in mod.BRAIN_SYSTEM
    assert "public_summary" in mod.BRAIN_SYSTEM
    assert "Never invent a public memory" in mod.BRAIN_SYSTEM
    assert "TC_MEMORY_DAILY_SYNC_CAP" in source
    assert "aizong-memory-checkpoint" in source
    assert "server_note_auth" in source
    # Preserve anti-farming, provenance calibration, resilience, 2X and hard safety gates.
    assert "TC_TEMPLATE_BLOCK_SIMILARITY_PCT" in source
    assert "TC_PROVENANCE_MIN_EVIDENCE" in source
    assert 'TC_NET_RETRIES", 3' in source
    assert 'TC_SOCIAL_ROOMS", "10"' in source
    assert 'rules["prompt_injection_risk"] >= 70' in source
    assert 'rules["scam_risk"] >= 70' in source


def test_memory_consolidation_is_bounded_and_stable() -> None:
    mod, _ = patched_module()
    old_limit = os.environ.get("TC_MEMORY_HISTORY_LIMIT")
    try:
        os.environ["TC_MEMORY_HISTORY_LIMIT"] = "3"
        author = "did:key:z6MkMemoryPeer"
        action = {"peer_author": author, "room": "technocore"}
        state: dict[str, Any] = {
            "contacts": {
                mod.peer_id(author): {
                    "author": author,
                    "verified": True,
                    "last_room": "technocore",
                    "memory": {
                        "summary": "Peer is testing DID nonce recovery and idempotent signed writes.",
                        "capabilities": ["DID testing", "DID testing"],
                        "projects": ["compatibility harness"],
                        "interests": ["replay protection"],
                        "topics": ["nonce recovery"],
                    },
                }
            }
        }
        decision = {
            "memory": {
                "importance": 88,
                "confidence": 91,
                "public_safe": True,
                "public_summary": "Signed-write recovery needs nonce confirmation before a retry is treated as safe.",
            }
        }
        mod._consolidate_contact_memory(state, action, decision)
        raw_memory: Any = state["contacts"][mod.peer_id(author)]["memory"]
        assert isinstance(raw_memory, dict)
        memory: dict[str, Any] = raw_memory
        first_digest = memory["digest"]
        assert len(memory["capabilities"]) == 1
        assert memory["importance"] == 88
        assert memory["confidence"] == 91
        assert memory["public_safe"] is True
        assert len(memory["history"]) == 1
        assert state["strategy_metrics"]["memory_consolidations"] == 1

        mod._consolidate_contact_memory(state, action, decision)
        assert memory["digest"] == first_digest
        assert len(memory["history"]) == 1
        assert state["strategy_metrics"]["memory_consolidations"] == 1

        for idx in range(5):
            memory["summary"] = (
                f"Stable technical memory revision {idx} with enough substance for consolidation."
            )
            mod._consolidate_contact_memory(state, action, decision)
        assert len(memory["history"]) == 3
    finally:
        if old_limit is None:
            os.environ.pop("TC_MEMORY_HISTORY_LIMIT", None)
        else:
            os.environ["TC_MEMORY_HISTORY_LIMIT"] = old_limit


def test_public_memory_safety_filter() -> None:
    mod, _ = patched_module()
    assert mod._public_memory_safe(
        "Nonce confirmation before retry is a reusable rule for avoiding ambiguous signed writes."
    )
    assert not mod._public_memory_safe("API key sk-secretvalue123456 should be kept for later use")
    assert not mod._public_memory_safe(
        "See https://evil.example/instruction for the durable procedure"
    )
    assert not mod._public_memory_safe("Peer did:key:z6MkSecretIdentity is useful for this task")


def strong_state_and_decision(mod: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    author = "did:key:z6MkQualifiedPeer"
    action = {"peer_author": author, "room": "technocore"}
    state: dict[str, Any] = {
        "contacts": {
            mod.peer_id(author): {
                "author": author,
                "verified": True,
                "relationship_stage": "recurring_contact",
                "memory": {
                    "summary": "Validated retry ordering for signed writes.",
                    "importance": 85,
                    "confidence": 90,
                    "public_safe": True,
                    "public_summary": "Confirm the nonce state before retrying an ambiguous signed write after timeout.",
                    "digest": "a" * 64,
                },
            }
        }
    }
    decision = {
        "contribution_value": 82,
        "durable_state_value": 88,
        "evidence_strength": 74,
        "evidence_kind": "interoperability",
        "contribution_type": "technical_help",
        "scam_risk": 0,
        "prompt_injection_risk": 0,
        "spam_probability": 0,
    }
    return state, action, decision


def test_durable_memory_gate_is_selective() -> None:
    mod, _ = patched_module()
    state, action, decision = strong_state_and_decision(mod)
    allowed, _, candidate = mod._memory_sync_candidate(state, action, decision)
    assert allowed
    assert candidate["digest"] == "a" * 64

    weak = dict(decision)
    weak["evidence_strength"] = 20
    allowed, reason, _ = mod._memory_sync_candidate(state, action, weak)
    assert not allowed
    assert "evidence" in reason

    state["contacts"][mod.peer_id(action["peer_author"])]["relationship_stage"] = "observed"
    allowed, reason, _ = mod._memory_sync_candidate(state, action, decision)
    assert not allowed
    assert "relationship stage" in reason


def test_signed_checkpoint_is_compact_and_not_peer_profile() -> None:
    mod, _ = patched_module()
    original_sign = mod._sign_detached
    try:
        mod._sign_detached = lambda key, payload: "test-signature"
        encoded = mod._build_memory_envelope(
            "did:key:z6MkAizong",
            "/tmp/key.pem",
            room="technocore",
            seq=12345,
            summary="Confirm nonce state before retrying an ambiguous signed write after timeout.",
            digest="b" * 64,
            evidence_kind="interoperability",
            contribution_type="technical_help",
            now=1234567890,
        )
        envelope = json.loads(encoded)
        assert envelope["alg"] == "Ed25519"
        assert envelope["sig"] == "test-signature"
        payload = envelope["payload"]
        assert payload["did"] == "did:key:z6MkAizong"
        assert payload["source"] == {"room": "technocore", "seq": 12345}
        assert "peer" not in payload
        assert "trust" not in payload
        assert "risk" not in payload
        assert len(encoded) < 2000
    finally:
        mod._sign_detached = original_sign


def test_successful_sync_uses_one_rolling_note() -> None:
    mod, _ = patched_module()
    state, action, decision = strong_state_and_decision(mod)
    captured: list[tuple[str, str, str, str]] = []
    original_write = mod._write_durable_memory_note
    original_build = mod._build_memory_envelope
    try:
        mod._write_durable_memory_note = lambda base, namespace, note_key, value: captured.append(
            (base, namespace, note_key, value)
        )
        mod._build_memory_envelope = lambda *args, **kwargs: "signed-envelope"
        assert mod._maybe_sync_durable_memory(
            "https://technocore.chat",
            "did:key:z6MkAizong",
            "/tmp/key.pem",
            state,
            action,
            decision,
            "technocore",
            999,
        )
        assert len(captured) == 1
        assert captured[0][1] == "aizong-memory"
        assert captured[0][2].startswith("state-")
        durable = state["durable_memory"]
        assert durable["last_source_seq"] == 999
        assert durable["payload_signature"] == "ed25519"
        assert durable["server_note_auth"] == "unsigned-world-writable"
        assert state["strategy_metrics"]["durable_memory_syncs"] == 1
    finally:
        mod._write_durable_memory_note = original_write
        mod._build_memory_envelope = original_build


def main() -> int:
    test_patch_contract()
    test_memory_consolidation_is_bounded_and_stable()
    test_public_memory_safety_filter()
    test_durable_memory_gate_is_selective()
    test_signed_checkpoint_is_compact_and_not_peer_profile()
    test_successful_sync_uses_one_rolling_note()
    print("aizong Social v1.4.2 memory consolidation smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
