#!/usr/bin/env python3
"""Love8 Persistent v2.5.1 capacity-aware identity-room wrapper."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Any

VERSION = "2.5.1"
ROOT = Path("/opt/love8-agent")
SOCIAL = ROOT / "social"
CORE = SOCIAL / "love8_persistent_v250_core.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capacity_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "room limit reached" in text or "20480 is the cap" in text:
        return True
    code = int(getattr(exc, "code", 0) or 0)
    if code != 400:
        return False
    try:
        body = exc.read().decode("utf-8", "replace").lower()
    except Exception:
        body = ""
    return "room limit reached" in body or "20480 is the cap" in body


def fallback_room(cfg: dict[str, str]) -> str:
    return str(cfg.get("MAILBOX", "") or "").strip().lower()


def fallback_cycle(
    v250,
    guard,
    cfg: dict[str, str],
    social_state: dict[str, Any],
    persist_state: dict[str, Any],
    *,
    dry_run: bool,
    reason: str,
) -> dict[str, Any] | None:
    room = fallback_room(cfg)
    if not room or not v250.valid_room(room.replace("mb-p-", "x-", 1)):
        # valid_room intentionally rejects mailbox namespaces; enforce only the raw name grammar here.
        import re

        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", room) or room == "events":
            print("capacity fallback unavailable: configured mailbox is invalid")
            return None

    state = v250.load_json(v250.IDENTITY_STATE)
    now = int(time.time())
    retry = int(cfg.get("PERSIST_CAPACITY_RETRY", "21600"))
    state["version"] = VERSION
    state["base_room"] = v250.room_base(cfg)
    state["desired_room"] = v250.room_base(cfg)
    state["room"] = room
    state["owner_did"] = str(cfg.get("DID", ""))
    state["bootstrap_mode"] = "capacity-fallback-mailbox"
    state["capacity_blocked_at"] = now
    state["capacity_wait_until"] = now + retry
    state["last_capacity_error"] = reason[:240]

    if not dry_run and not state.get("fallback_announced_at"):
        text = (
            f"[{cfg.get('NICK','love8')}-deep] Technocore room capacity is full, so this existing signed "
            "mailbox temporarily also carries long-lived collaboration threads. When capacity returns, "
            f"the hub will migrate to /r/{v250.room_base(cfg)}. No secrets or status loops."
        )[:420]
        try:
            result = guard.signed_post(
                cfg["BASE"].rstrip("/"), cfg["DID"], cfg["KEY"], room, text, social_state
            )
            social_state.setdefault("writes", []).append(time.time())
            state["fallback_announced_at"] = now
            state["bootstrap_seq"] = int(result.get("last_seq", 0) or 0)
            state["bootstrapped"] = True
        except Exception as exc:
            print(f"capacity fallback mailbox write failed: {type(exc).__name__}: {exc}")
            return None
    elif dry_run:
        state["bootstrapped"] = True

    peers = v250.mature_peers(social_state, cfg, now=now)
    invited = v250.send_invites(cfg, state, peers, room, dry_run=dry_run)
    state["mature_peer_count"] = len(peers)
    state["last_cycle_at"] = now
    if not dry_run:
        v250.save_json(v250.IDENTITY_STATE, state)

    persist_state["identity_room"] = {
        "room": room,
        "base_room": v250.room_base(cfg),
        "desired_room": v250.room_base(cfg),
        "capacity_fallback": True,
        "mature_peer_count": len(peers),
        "last_cycle_at": now,
    }
    return {
        "date": time.strftime("%Y-%m-%d", time.gmtime(now)),
        "ts": now,
        "topic": "identity-deep-collaboration-capacity-fallback",
        "room": room,
        "peer_ids": [cid for cid, _ in peers],
        "invited_peer_ids": invited,
        "dry_run": dry_run,
        "capacity_fallback": True,
    }


def install_hooks(v250) -> None:
    original = v250.identity_room_cycle

    def identity_room_cycle(
        guard,
        cfg: dict[str, str],
        social_state: dict[str, Any],
        persist_state: dict[str, Any],
        topics: list[dict[str, Any]],
        dry_run: bool,
    ) -> dict[str, Any] | None:
        state = v250.load_json(v250.IDENTITY_STATE)
        now = int(time.time())
        wait_until = int(state.get("capacity_wait_until", 0) or 0)
        if wait_until > now and str(state.get("bootstrap_mode", "")).startswith("capacity-fallback"):
            return fallback_cycle(
                v250,
                guard,
                cfg,
                social_state,
                persist_state,
                dry_run=dry_run,
                reason=str(state.get("last_capacity_error", "capacity backoff")),
            )
        try:
            result = original(guard, cfg, social_state, persist_state, topics, dry_run)
        except Exception as exc:
            if not capacity_error(exc):
                raise
            return fallback_cycle(
                v250,
                guard,
                cfg,
                social_state,
                persist_state,
                dry_run=dry_run,
                reason=f"{type(exc).__name__}: {exc}",
            )
        if result is not None and not dry_run:
            current = v250.load_json(v250.IDENTITY_STATE)
            current["version"] = VERSION
            if not str(current.get("bootstrap_mode", "")).startswith("capacity-fallback"):
                for key in (
                    "capacity_wait_until",
                    "capacity_blocked_at",
                    "last_capacity_error",
                    "desired_room",
                ):
                    current.pop(key, None)
                v250.save_json(v250.IDENTITY_STATE, current)
        return result

    v250.identity_room_cycle = identity_room_cycle
    v250.VERSION = VERSION


def main() -> int:
    v250 = load("love8_persistent_v250_core", CORE)
    install_hooks(v250)
    return int(v250.main())


if __name__ == "__main__":
    raise SystemExit(main())
