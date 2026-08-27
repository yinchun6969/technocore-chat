#!/usr/bin/env python3
"""Smoke tests for Social v1.5.2 capacity-aware identity rooms."""

from __future__ import annotations

import importlib.util
import io
import os
import tempfile
import time
import urllib.error
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
    ROOT / "scripts" / "patch_aizong_social_v152.py",
]


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patched_module() -> Any:
    source = BASE_PROGRAM.read_text(encoding="utf-8")
    for idx, path in enumerate(PATCHERS):
        patcher = load_module(f"patch_{idx}", path)
        source = patcher.patch_source(source)
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
        handle.write(source)
        tmp = Path(handle.name)
    try:
        return load_module("social_v152", tmp)
    finally:
        tmp.unlink(missing_ok=True)


def capacity_error() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://technocore.chat/r/aizong",
        400,
        "Bad Request",
        {},
        io.BytesIO(b"400 room limit reached (20480 is the cap, and this would be a new one)"),
    )


def test_capacity_error_detection() -> None:
    mod = patched_module()
    assert mod.VERSION == "1.5.2"
    assert mod._room_capacity_error(capacity_error())
    assert not mod._room_capacity_error(RuntimeError("other failure"))


def test_capacity_uses_verified_existing_owned_room() -> None:
    mod = patched_module()
    state: dict[str, Any] = {}
    original_select = mod._select_identity_room
    original_signed = mod.signed_post
    original_http = mod.http_json
    original_topic = mod._set_home_topic
    old = {key: os.environ.get(key) for key in ("TC_AGENT_NICK", "TC_HUB_CAPACITY_FALLBACK")}
    try:
        os.environ["TC_AGENT_NICK"] = "aizong"
        os.environ["TC_HUB_CAPACITY_FALLBACK"] = "d-aizong"
        mod._select_identity_room = lambda base, did, current: ("aizong", "empty", 0)
        mod.signed_post = lambda *args, **kwargs: (_ for _ in ()).throw(capacity_error())
        mod.http_json = lambda url, timeout=20: {
            "messages": [{"seq": 8, "from": "did:key:z6MkAizong", "text": "legacy owned"}],
            "last_seq": 8,
        }
        mod._set_home_topic = lambda *args, **kwargs: None
        mod._ensure_home_room(
            "https://technocore.chat",
            "aizong",
            "did:key:z6MkAizong",
            "/tmp/key",
            state,
            dry_run=False,
        )
        hub = state["home_hub"]
        assert hub["room"] == "d-aizong"
        assert hub["desired_room"] == "aizong"
        assert hub["bootstrap_mode"] == "capacity-fallback-existing"
        assert hub["bootstrapped"] is True
        assert int(hub["capacity_wait_until"]) > int(time.time())
        assert os.environ["TC_HOME_ROOM_RESOLVED"] == "d-aizong"
        assert mod._home_room_name() == "d-aizong"
    finally:
        mod._select_identity_room = original_select
        mod.signed_post = original_signed
        mod.http_json = original_http
        mod._set_home_topic = original_topic
        os.environ.pop("TC_HOME_ROOM_RESOLVED", None)
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_capacity_without_verified_fallback_enters_wait() -> None:
    mod = patched_module()
    state: dict[str, Any] = {}
    original_select = mod._select_identity_room
    original_signed = mod.signed_post
    original_http = mod.http_json
    old = os.environ.get("TC_AGENT_NICK")
    try:
        os.environ["TC_AGENT_NICK"] = "aizong"
        mod._select_identity_room = lambda base, did, current: ("aizong", "empty", 0)
        mod.signed_post = lambda *args, **kwargs: (_ for _ in ()).throw(capacity_error())
        mod.http_json = lambda url, timeout=20: {"messages": [], "last_seq": 0}
        mod._ensure_home_room(
            "https://technocore.chat",
            "aizong",
            "did:key:z6MkAizong",
            "/tmp/key",
            state,
            dry_run=False,
        )
        hub = state["home_hub"]
        assert hub["bootstrap_mode"] == "capacity-wait"
        assert hub["bootstrapped"] is False
        assert int(hub["capacity_wait_until"]) > int(time.time())
    finally:
        mod._select_identity_room = original_select
        mod.signed_post = original_signed
        mod.http_json = original_http
        if old is None:
            os.environ.pop("TC_AGENT_NICK", None)
        else:
            os.environ["TC_AGENT_NICK"] = old


def main() -> int:
    test_capacity_error_detection()
    test_capacity_uses_verified_existing_owned_room()
    test_capacity_without_verified_fallback_enters_wait()
    print("Social v1.5.2 capacity-aware identity-room smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
