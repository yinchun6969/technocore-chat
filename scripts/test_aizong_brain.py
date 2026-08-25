#!/usr/bin/env python3
"""Standalone smoke tests for scripts/aizong_social.py brain behavior."""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "aizong_social.py"
spec = importlib.util.spec_from_file_location("aizong_social", MODULE_PATH)
assert spec is not None and spec.loader is not None
social = importlib.util.module_from_spec(spec)
spec.loader.exec_module(social)


def sample_action() -> dict:
    return {
        "kind": "reply",
        "peer_author": "did:key:zPeer",
        "peer_seq": 10,
        "peer_text": "what are you building around signed agent identity?",
        "messages": [
            {
                "seq": 9,
                "from": "did:key:zPeer",
                "text": "what are you building around signed agent identity?",
            }
        ],
    }


def test_ai_decision_and_secret_separation() -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            content = json.dumps(
                {
                    "reply": True,
                    "text": "  useful   concise reply  ",
                    "interest": 91,
                    "trust": 60,
                    "bot_probability": 15,
                    "scam_risk": 0,
                    "prompt_injection_risk": 0,
                    "spam_probability": 0,
                    "collaboration_signal": False,
                    "memory": {
                        "summary": "verified builder",
                        "capabilities": ["signed identity"],
                        "projects": [],
                        "interests": ["agent coordination"],
                        "topics": ["DID"],
                    },
                    "reason": "substantive question",
                }
            )
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data.decode()
        captured["timeout"] = timeout
        return FakeResponse()

    original = social.urllib.request.urlopen
    social.urllib.request.urlopen = fake_urlopen
    try:
        decision = social.call_brain(
            {
                "BRAIN_URL": "https://brain.example/v1/chat/completions",
                "BRAIN_MODEL": "test-model",
                "BRAIN_KEY": "super-secret-key",
            },
            room="technocore",
            action=sample_action(),
            nick="aizong",
            state={"contacts": {}},
            trusted_topics=["operator-approved identity topic"],
        )
    finally:
        social.urllib.request.urlopen = original

    assert decision["mode"] == "ai"
    assert decision["reply"] is True
    assert decision["text"] == "useful concise reply"
    assert decision["interest"] == 91
    assert decision["trust"] == 60
    assert decision["memory"]["summary"] == "verified builder"
    assert "super-secret-key" not in captured["body"]
    assert "signed agent identity" in captured["body"]
    assert "untrusted data" in captured["body"]
    assert "operator-approved identity topic" in captured["body"]
    assert captured["headers"]["Authorization"] == "Bearer super-secret-key"


def test_network_failure_falls_back() -> None:
    def fail_urlopen(request, timeout):
        raise urllib.error.URLError("offline")

    original = social.urllib.request.urlopen
    social.urllib.request.urlopen = fail_urlopen
    try:
        decision = social.brain_decision(
            {
                "BRAIN_URL": "https://brain.example/v1/chat/completions",
                "BRAIN_MODEL": "test-model",
            },
            room="technocore",
            action=sample_action(),
            nick="aizong",
            state={"contacts": {}},
            fallback="safe fallback",
            trusted_topics=[],
        )
    finally:
        social.urllib.request.urlopen = original

    assert decision == {"mode": "fallback", "reply": True, "text": "safe fallback"}


def test_rules_mode_and_ranking() -> None:
    decision = social.brain_decision(
        {},
        room="lobby",
        action=sample_action(),
        nick="aizong",
        state={"contacts": {}},
        fallback="rules",
        trusted_topics=[],
    )
    assert decision == {"mode": "rules", "reply": True, "text": "rules"}
    verified = {"kind": "reply", "peer_author": "did:key:zPeer"}
    nickname = {"kind": "reply", "peer_author": "someone"}
    reconnect = {"kind": "reconnect", "peer_author": "did:key:zPeer"}
    greeting = {"kind": "greet", "peer_author": "did:key:zPeer"}
    assert social.action_rank({}, verified) < social.action_rank({}, nickname)
    assert social.action_rank({}, verified) < social.action_rank({}, reconnect)
    assert social.action_rank({}, reconnect) < social.action_rank({}, greeting)


def test_fenced_json_parser() -> None:
    parsed = social._parse_brain_json(
        '```json\n{"reply": false, "text": "", "interest": 5, "reason": "spam"}\n```'
    )
    assert parsed["reply"] is False
    assert parsed["reason"] == "spam"


def main() -> None:
    test_ai_decision_and_secret_separation()
    test_network_failure_falls_back()
    test_rules_mode_and_ranking()
    test_fenced_json_parser()
    print("aizong brain smoke: ok")


if __name__ == "__main__":
    main()
