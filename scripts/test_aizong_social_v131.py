#!/usr/bin/env python3
"""Smoke tests for aizong Social Brain v1.3.1 Network Resilience."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import urllib.error
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_PROGRAM = ROOT / "scripts" / "aizong_social.py"
PATCH_130 = ROOT / "scripts" / "patch_aizong_social_v130.py"
PATCH_131 = ROOT / "scripts" / "patch_aizong_social_v131.py"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patched_module() -> tuple[Any, str]:
    p130 = load_module("aizong_p130_for_v131", PATCH_130)
    p131 = load_module("aizong_p131", PATCH_131)
    source = BASE_PROGRAM.read_text(encoding="utf-8")
    source = p130.patch_source(source)
    patched = p131.patch_source(source)
    assert p131.patch_source(patched) == patched
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
        handle.write(patched)
        path = Path(handle.name)
    try:
        return load_module("aizong_social_v131", path), patched
    finally:
        path.unlink(missing_ok=True)


def test_patch_contract() -> None:
    mod, source = patched_module()
    assert mod.VERSION == "1.3.1"
    assert 'TC_NET_RETRIES", 3' in source
    assert 'TC_NET_COOLDOWN_SECONDS", 900' in source
    assert 'TC_BRAIN_COOLDOWN_SECONDS", 900' in source
    assert 'brain.get("BRAIN_TIMEOUT", "60")' in source
    assert 'brain.get("BRAIN_RETRIES", "3")' in source
    assert 'attempts=1, label="signed-post"' in source
    assert '"mode": "deferred"' in source
    assert "not retrying automatically to avoid duplicate public writes" in source
    # v1.3 2X capacity and security gates must remain present.
    assert 'TC_SOCIAL_ROOMS", "10"' in source
    assert 'TC_SOCIAL_ROOM_MESSAGE_LIMIT", "40"' in source
    assert 'rules["prompt_injection_risk"] >= 70' in source
    assert 'rules["scam_risk"] >= 70' in source


def test_transient_get_retries_then_succeeds() -> None:
    mod, _ = patched_module()
    calls = 0
    original_urlopen = mod.urllib.request.urlopen
    original_sleep = mod.time.sleep
    original_uniform = mod.random.uniform
    old_retries = os.environ.get("TC_NET_RETRIES")
    old_backoff = os.environ.get("TC_NET_BACKOFF_BASE_MS")

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            del exc_type, exc, tb
            return False

        def read(self) -> bytes:
            return b'{"rooms": []}'

    def fake_urlopen(request: Any, timeout: int) -> Response:
        nonlocal calls
        del request, timeout
        calls += 1
        if calls < 3:
            raise TimeoutError("temporary timeout")
        return Response()

    try:
        os.environ["TC_NET_RETRIES"] = "3"
        os.environ["TC_NET_BACKOFF_BASE_MS"] = "100"
        mod.urllib.request.urlopen = fake_urlopen
        mod.time.sleep = lambda _: None
        mod.random.uniform = lambda _a, _b: 0.0
        data = mod.http_json("https://example.invalid/rooms", timeout=5)
    finally:
        mod.urllib.request.urlopen = original_urlopen
        mod.time.sleep = original_sleep
        mod.random.uniform = original_uniform
        if old_retries is None:
            os.environ.pop("TC_NET_RETRIES", None)
        else:
            os.environ["TC_NET_RETRIES"] = old_retries
        if old_backoff is None:
            os.environ.pop("TC_NET_BACKOFF_BASE_MS", None)
        else:
            os.environ["TC_NET_BACKOFF_BASE_MS"] = old_backoff

    assert data == {"rooms": []}
    assert calls == 3


def test_non_transient_http_is_not_retried() -> None:
    mod, _ = patched_module()
    calls = 0
    original = mod.urllib.request.urlopen

    def fake_urlopen(request: Any, timeout: int) -> Any:
        nonlocal calls
        del request, timeout
        calls += 1
        raise urllib.error.HTTPError(
            "https://example.invalid", 400, "bad request", hdrs=None, fp=None
        )

    mod.urllib.request.urlopen = fake_urlopen
    try:
        try:
            mod.http_json("https://example.invalid/rooms", timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("expected HTTPError")
    finally:
        mod.urllib.request.urlopen = original
    assert calls == 1


def test_brain_retries_with_growing_timeout() -> None:
    mod, _ = patched_module()
    calls: list[int] = []
    original_urlopen = mod.urllib.request.urlopen
    original_sleep = mod.time.sleep
    original_uniform = mod.random.uniform

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            del exc_type, exc, tb
            return False

        def read(self) -> bytes:
            decision = {
                "reply": False,
                "text": "",
                "interest": 70,
                "trust": 55,
                "bot_probability": 10,
                "scam_risk": 0,
                "prompt_injection_risk": 0,
                "spam_probability": 0,
                "collaboration_signal": False,
                "memory": {
                    "summary": "builder",
                    "capabilities": ["agents"],
                    "projects": ["alpha"],
                    "interests": ["identity"],
                    "topics": ["signed messages"],
                },
                "reason": "observe",
            }
            body = {"choices": [{"message": {"content": json.dumps(decision)}}]}
            return json.dumps(body).encode()

    def fake_urlopen(request: Any, timeout: int) -> Response:
        del request
        calls.append(timeout)
        if len(calls) < 3:
            raise TimeoutError("slow reasoning endpoint")
        return Response()

    try:
        mod.urllib.request.urlopen = fake_urlopen
        mod.time.sleep = lambda _: None
        mod.random.uniform = lambda _a, _b: 0.0
        decision = mod.call_brain(
            {
                "BRAIN_URL": "https://brain.example/v1/chat/completions",
                "BRAIN_MODEL": "reasoning-model",
                "BRAIN_KEY": "secret",
                "BRAIN_TIMEOUT": "60",
                "BRAIN_RETRIES": "3",
                "BRAIN_MAX_TOKENS": "1536",
            },
            room="technocore",
            action={
                "kind": "reply",
                "peer_author": "did:key:zPeer",
                "messages": [{"seq": 1, "from": "did:key:zPeer", "text": "hello"}],
            },
            nick="aizong",
            state={"contacts": {}},
            trusted_topics=[],
        )
    finally:
        mod.urllib.request.urlopen = original_urlopen
        mod.time.sleep = original_sleep
        mod.random.uniform = original_uniform

    assert calls == [60, 75, 90]
    assert decision["mode"] == "ai"


def test_brain_transport_failure_defers_and_enters_cooldown() -> None:
    mod, _ = patched_module()
    original = mod.call_brain
    original_sleep = mod.time.sleep

    def fail_brain(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise TimeoutError("brain timeout")

    state: dict[str, Any] = {"contacts": {}}
    action = {
        "kind": "reply",
        "peer_author": "did:key:zPeer",
        "messages": [{"seq": 1, "from": "did:key:zPeer", "text": "substantive hello"}],
    }
    try:
        mod.call_brain = fail_brain
        mod.time.sleep = lambda _: None
        for expected in (1, 2, 3):
            decision = mod.brain_decision(
                {"BRAIN_URL": "https://brain.example", "BRAIN_MODEL": "model"},
                room="lobby",
                action=action,
                nick="aizong",
                state=state,
                fallback="fallback",
                trusted_topics=[],
            )
            assert decision["mode"] == "deferred"
            assert decision["reply"] is False
            assert state["network_health"]["brain_consecutive_failures"] == expected
        assert mod._cooldown_remaining(state, "brain") > 0
        before = state["network_health"]["brain_consecutive_failures"]
        decision = mod.brain_decision(
            {"BRAIN_URL": "https://brain.example", "BRAIN_MODEL": "model"},
            room="lobby",
            action=action,
            nick="aizong",
            state=state,
            fallback="fallback",
            trusted_topics=[],
        )
        assert decision["mode"] == "deferred"
        assert state["network_health"]["brain_consecutive_failures"] == before
    finally:
        mod.call_brain = original
        mod.time.sleep = original_sleep


def test_signed_post_transport_uses_one_attempt() -> None:
    mod, _ = patched_module()
    calls = 0
    original_urlopen = mod.urllib.request.urlopen
    original_sign = mod.sign_message

    def fake_urlopen(request: Any, timeout: int) -> Any:
        nonlocal calls
        del request, timeout
        calls += 1
        raise TimeoutError("response lost")

    try:
        mod.urllib.request.urlopen = fake_urlopen
        mod.sign_message = lambda key, room, nonce, text: "fake-signature"
        try:
            mod.signed_post(
                "https://technocore.chat",
                "did:key:zOwn",
                "/tmp/not-used",
                "lobby",
                "hello",
                {"last_nonce": 0},
            )
        except TimeoutError:
            pass
        else:
            raise AssertionError("expected TimeoutError")
    finally:
        mod.urllib.request.urlopen = original_urlopen
        mod.sign_message = original_sign
    assert calls == 1


def main() -> None:
    tests = [
        test_patch_contract,
        test_transient_get_retries_then_succeeds,
        test_non_transient_http_is_not_retried,
        test_brain_retries_with_growing_timeout,
        test_brain_transport_failure_defers_and_enters_cooldown,
        test_signed_post_transport_uses_one_attempt,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"aizong Social v1.3.1 resilience smoke: {len(tests)} tests passed")


if __name__ == "__main__":
    main()
