#!/usr/bin/env python3
"""Smoke tests for Love8 Persistent v2.5.1 capacity fallback."""

from __future__ import annotations

import importlib.util
import io
import tempfile
import urllib.error
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "love8_persistent_v251_wrapper.py"


def load_module():
    spec = importlib.util.spec_from_file_location("love8_v251", WRAPPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capacity_error() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://technocore.chat/r/love8",
        400,
        "Bad Request",
        {},
        io.BytesIO(b"room limit reached (20480 is the cap, and this would be a new one)"),
    )


class FakeV250:
    VERSION = "2.5.0"

    def __init__(self, state_path: Path):
        self.IDENTITY_STATE = state_path
        self.identity_room_cycle = self.original_cycle
        self.invites: list[str] = []

    def original_cycle(self, guard, cfg, social, persist, topics, dry_run):
        del guard, cfg, social, persist, topics, dry_run
        raise capacity_error()

    @staticmethod
    def room_base(cfg):
        return cfg["NICK"]

    @staticmethod
    def valid_room(room):
        return bool(room)

    @staticmethod
    def load_json(path):
        import json

        try:
            value = json.loads(path.read_text())
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def save_json(path, value):
        import json

        path.write_text(json.dumps(value))

    @staticmethod
    def mature_peers(social, cfg, now=None):
        del social, cfg, now
        return [("did:1111111111111111", {"verified": True})]

    def send_invites(self, cfg, state, peers, room, dry_run=False):
        del cfg, state, peers, dry_run
        self.invites.append(room)
        return ["did:1111111111111111"]


class FakeGuard:
    def __init__(self):
        self.posts: list[str] = []

    def signed_post(self, base, did, key, room, text, social):
        del base, did, key, text, social
        self.posts.append(room)
        return {"last_seq": 77}


def cfg() -> dict[str, str]:
    return {
        "BASE": "https://technocore.chat",
        "NICK": "love8",
        "DID": "did:key:z6MkLove8",
        "KEY": "/tmp/key",
        "MAILBOX": "mb-p-0123456789abcdef0123456789abcdef",
        "PERSIST_CAPACITY_RETRY": "21600",
    }


def test_detector() -> None:
    mod = load_module()
    assert mod.VERSION == "2.5.1"
    assert mod.capacity_error(capacity_error())
    assert not mod.capacity_error(RuntimeError("not capacity"))


def test_original_capacity_failure_switches_to_mailbox() -> None:
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        core = FakeV250(Path(td) / "identity.json")
        mod.install_hooks(core)
        guard = FakeGuard()
        social: dict[str, Any] = {"writes": []}
        persist: dict[str, Any] = {}
        result = core.identity_room_cycle(guard, cfg(), social, persist, [], False)
        assert result is not None
        assert result["capacity_fallback"] is True
        assert result["room"].startswith("mb-p-")
        assert guard.posts == [cfg()["MAILBOX"]]
        state = core.load_json(core.IDENTITY_STATE)
        assert state["base_room"] == "love8"
        assert state["desired_room"] == "love8"
        assert state["room"] == cfg()["MAILBOX"]
        assert state["bootstrap_mode"] == "capacity-fallback-mailbox"
        assert state["bootstrap_seq"] == 77
        assert state["capacity_wait_until"] > state["capacity_blocked_at"]
        assert core.invites == [cfg()["MAILBOX"]]


def main() -> int:
    test_detector()
    test_original_capacity_failure_switches_to_mailbox()
    print("Love8 Persistent v2.5.1 capacity-aware identity-room smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
