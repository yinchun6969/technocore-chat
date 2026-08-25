#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
from pathlib import Path

P = Path(__file__).with_name('love8_persistent.py')
s = importlib.util.spec_from_file_location('p24', P)
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)


def test_relationships():
    weak = {"verified": True, "natural_messages": 1, "messages_out": 0, "replies_to_love8": 0,
            "brain": {"conversation_quality": 20, "trust_score": 45, "bot_probability": 80, "scam_risk": 0}}
    strong = {"verified": True, "natural_messages": 8, "messages_out": 4, "replies_to_love8": 3,
              "brain": {"conversation_quality": 82, "trust_score": 85, "bot_probability": 18, "scam_risk": 2}}
    assert m.relationship_score(strong) > m.relationship_score(weak)
    score = m.relationship_score(strong)
    assert m.relationship_stage(strong, score) in {"established", "trusted_peer"}


def test_topics():
    contacts = {
        "did:a": {"relationship_score": 80, "relationship_stage": "trusted_peer", "last_room": "ai",
                  "brain": {"topics": ["agent identity", "reputation"], "bot_probability": 10, "scam_risk": 0}},
        "did:b": {"relationship_score": 70, "relationship_stage": "established", "last_room": "builders",
                  "brain": {"topics": ["agent identity"], "bot_probability": 20, "scam_risk": 0}},
    }
    t = m.topic_momentum(contacts)
    assert t and t[0]["topic"] == "agent identity"
    assert t[0]["peer_count"] == 2


def test_contribution():
    good = {"sent": True, "action": "reply", "conversation_quality": 80, "bot_probability": 10,
            "scam_risk": 0, "human_likelihood": 55}
    bad = {"sent": False, "action": "reply", "conversation_quality": 100, "bot_probability": 0,
           "scam_risk": 0, "human_likelihood": 100}
    assert m.contribution_score(good) >= 60
    assert m.contribution_score(bad) == 0


def test_room_slug():
    value = m.room_slug("Agent Identity / Reputation", "2026-08-25")
    assert value.startswith("love8-agent-identity-reputation-")
    assert len(value) <= 58


if __name__ == '__main__':
    test_relationships(); test_topics(); test_contribution(); test_room_slug()
    print('LOVE8 PERSISTENT v2.4 TESTS OK')
