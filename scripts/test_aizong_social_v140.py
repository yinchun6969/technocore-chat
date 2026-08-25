#!/usr/bin/env python3
"""Smoke tests for aizong Social Brain v1.4.0 Contribution Strategy."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_PROGRAM = ROOT / "scripts" / "aizong_social.py"
PATCH_130 = ROOT / "scripts" / "patch_aizong_social_v130.py"
PATCH_131 = ROOT / "scripts" / "patch_aizong_social_v131.py"
PATCH_140 = ROOT / "scripts" / "patch_aizong_social_v140.py"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patched_module() -> tuple[Any, str]:
    p130 = load_module("aizong_p130_for_v140", PATCH_130)
    p131 = load_module("aizong_p131_for_v140", PATCH_131)
    p140 = load_module("aizong_p140", PATCH_140)
    source = BASE_PROGRAM.read_text(encoding="utf-8")
    source = p130.patch_source(source)
    source = p131.patch_source(source)
    patched = p140.patch_source(source)
    assert p140.patch_source(patched) == patched
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
        handle.write(patched)
        path = Path(handle.name)
    try:
        return load_module("aizong_social_v140", path), patched
    finally:
        path.unlink(missing_ok=True)


def test_patch_contract() -> None:
    mod, source = patched_module()
    assert mod.VERSION == "1.4.0"
    assert "contribution_value" in mod.BRAIN_SYSTEM
    assert "provenance_worthy" in mod.BRAIN_SYSTEM
    assert "Do not optimize public behavior for faucets, airdrops" in mod.BRAIN_SYSTEM
    assert "TC_STRATEGY_ROOM_DAILY_CAP" in source
    assert "TC_STRATEGY_PEER_DAILY_CAP" in source
    assert "contribution-ledger.jsonl" in source
    # v1.3 2X + v1.3.1 resilience + hard safety gates must remain.
    assert 'TC_SOCIAL_ROOMS", "10"' in source
    assert 'TC_SOCIAL_ROOM_MESSAGE_LIMIT", "40"' in source
    assert 'TC_NET_RETRIES", 3' in source
    assert 'brain.get("BRAIN_TIMEOUT", "60")' in source
    assert 'rules["prompt_injection_risk"] >= 70' in source
    assert 'rules["scam_risk"] >= 70' in source


def test_quality_gate() -> None:
    mod, _ = patched_module()
    old = {
        key: os.environ.get(key)
        for key in (
            "TC_STRATEGY_REPLY_MIN_VALUE",
            "TC_STRATEGY_GREET_MIN_VALUE",
            "TC_STRATEGY_RECONNECT_MIN_VALUE",
        )
    }
    try:
        os.environ["TC_STRATEGY_REPLY_MIN_VALUE"] = "50"
        os.environ["TC_STRATEGY_GREET_MIN_VALUE"] = "65"
        os.environ["TC_STRATEGY_RECONNECT_MIN_VALUE"] = "60"
        assert mod._strategy_allows_decision("reply", {"mode": "ai", "contribution_value": 50})[0]
        assert not mod._strategy_allows_decision("reply", {"mode": "ai", "contribution_value": 49})[
            0
        ]
        assert not mod._strategy_allows_decision("greet", {"mode": "ai", "contribution_value": 64})[
            0
        ]
        assert mod._strategy_allows_decision("reconnect", {"mode": "ai", "contribution_value": 80})[
            0
        ]
        assert not mod._strategy_allows_decision(
            "greet", {"mode": "rules", "contribution_value": 100}
        )[0]
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_daily_diversity_caps() -> None:
    mod, _ = patched_module()
    old_room = os.environ.get("TC_STRATEGY_ROOM_DAILY_CAP")
    old_peer = os.environ.get("TC_STRATEGY_PEER_DAILY_CAP")
    try:
        os.environ["TC_STRATEGY_ROOM_DAILY_CAP"] = "2"
        os.environ["TC_STRATEGY_PEER_DAILY_CAP"] = "2"
        state: dict[str, Any] = {}
        assert mod._strategy_capacity_ok(state, "lobby", "did:key:peer-a")
        mod._note_strategy_write(state, "lobby", "did:key:peer-a", "reply", 70)
        assert mod._strategy_capacity_ok(state, "lobby", "did:key:peer-a")
        mod._note_strategy_write(state, "lobby", "did:key:peer-a", "reply", 75)
        assert not mod._strategy_capacity_ok(state, "lobby", "did:key:peer-a")
        assert mod._strategy_capacity_ok(state, "other-room", "did:key:peer-b")
    finally:
        if old_room is None:
            os.environ.pop("TC_STRATEGY_ROOM_DAILY_CAP", None)
        else:
            os.environ["TC_STRATEGY_ROOM_DAILY_CAP"] = old_room
        if old_peer is None:
            os.environ.pop("TC_STRATEGY_PEER_DAILY_CAP", None)
        else:
            os.environ["TC_STRATEGY_PEER_DAILY_CAP"] = old_peer


def test_contribution_ledger_is_private_jsonl() -> None:
    mod, _ = patched_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "contribution-ledger.jsonl"
        event = {
            "timestamp": 1,
            "did": "did:key:aizong",
            "room": "technocore",
            "seq": 123,
            "contribution_value": 88,
            "provenance_worthy": True,
            "text_sha256": "abc",
        }
        mod._append_contribution_ledger(path, event)
        rows = path.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1
        assert json.loads(rows[0]) == event
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def main() -> int:
    test_patch_contract()
    test_quality_gate()
    test_daily_diversity_caps()
    test_contribution_ledger_is_private_jsonl()
    print("aizong Social v1.4 contribution strategy smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
