#!/usr/bin/env python3
"""AI2AI v5.2.1 capacity-aware identity-room wrapper."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

VERSION = "5.2.1"
ROOT = Path("/opt/technocore-a2a")
CORE = ROOT / "rnd-v5" / "identity-room-v5.2.py"
ROOM_FILE = ROOT / "rnd-v5-state" / "identity-room-name"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capacity_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "room limit reached" in text or "20480 is the cap" in text


def owned_fallback(core) -> tuple[str, int] | None:
    room = str(getattr(core.agent, "ROOM", "") or os.environ.get("OWNED_ROOM", "")).strip().lower()
    if not core.NAME_RE.fullmatch(room):
        return None
    try:
        status, seq = core.probe(room)
    except Exception:
        return None
    if status != "owned":
        return None
    return room, seq


def write_room_file(room: str) -> None:
    ROOM_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ROOM_FILE.with_suffix(".tmp")
    tmp.write_text(room + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ROOM_FILE)


def fallback_state(core, state: dict[str, Any], desired: str, reason: str) -> tuple[str, int]:
    fallback = owned_fallback(core)
    if fallback is None:
        now = int(time.time())
        state.update(
            {
                "version": VERSION,
                "desired_room": desired,
                "bootstrap_mode": "capacity-wait",
                "capacity_blocked_at": now,
                "capacity_wait_until": now + 21600,
                "last_capacity_error": reason[:240],
            }
        )
        core.save_state(state)
        raise RuntimeError("global room capacity reached and no verified existing OWNED_ROOM fallback")
    room, seq = fallback
    now = int(time.time())
    state.update(
        {
            "version": VERSION,
            "base_room": core.base_room(),
            "desired_room": desired,
            "room": room,
            "owner_did": core.DID,
            "bootstrapped": True,
            "bootstrap_mode": "capacity-fallback-existing",
            "fallback_since": now,
            "capacity_blocked_at": now,
            "capacity_wait_until": now + 21600,
            "last_capacity_error": reason[:240],
            "last_verified_at": now,
            "last_seen_seq": seq,
        }
    )
    core.save_state(state)
    write_room_file(room)
    return room, seq


def sync(core) -> dict[str, Any]:
    state = core.load_state()
    now = int(time.time())
    wait = int(state.get("capacity_wait_until", 0) or 0)
    mode = str(state.get("bootstrap_mode", ""))
    if wait > now and mode == "capacity-fallback-existing":
        room = str(state.get("room", ""))
        if core.NAME_RE.fullmatch(room):
            invited = core.invite(state, room)
            state["version"] = VERSION
            state["last_sync_at"] = now
            state["last_sync_invited"] = invited
            core.save_state(state)
            write_room_file(room)
            return {"room": room, "status": "capacity-fallback", "seq": int(state.get("last_seen_seq", 0) or 0), "invited": invited}

    desired, status, seq = core.resolve(state)
    try:
        core.bootstrap(state, desired, status)
    except Exception as exc:
        if not capacity_error(exc):
            raise
        room, fallback_seq = fallback_state(core, state, desired, f"{type(exc).__name__}: {exc}")
        invited = core.invite(state, room)
        state["last_sync_at"] = int(time.time())
        state["last_sync_invited"] = invited
        core.save_state(state)
        return {"room": room, "status": "capacity-fallback", "seq": fallback_seq, "invited": invited}

    state = core.load_state()
    state["version"] = VERSION
    for key in (
        "desired_room",
        "capacity_blocked_at",
        "capacity_wait_until",
        "last_capacity_error",
        "fallback_since",
    ):
        state.pop(key, None)
    invited = core.invite(state, desired)
    state["last_sync_at"] = int(time.time())
    state["last_sync_invited"] = invited
    core.save_state(state)
    write_room_file(desired)
    return {"room": desired, "status": status, "seq": seq, "invited": invited}


def status(core) -> None:
    state = core.load_state()
    room = str(state.get("room") or core.base_room())
    print("===== AI2AI IDENTITY ROOM v5.2.1 =====")
    print("agent=" + core.AGENT)
    print("did=" + core.DID)
    print("base_room=" + str(state.get("base_room") or core.base_room()))
    print("resolved_room=" + room)
    print("desired_room=" + str(state.get("desired_room") or core.base_room()))
    print("bootstrap_mode=" + str(state.get("bootstrap_mode", "")))
    print("bootstrap_seq=" + str(int(state.get("bootstrap_seq", 0) or 0)))
    print("capacity_blocked=" + str(bool(state.get("capacity_blocked_at"))).lower())
    wait = int(state.get("capacity_wait_until", 0) or 0)
    print("capacity_retry_in=" + str(max(0, wait - int(time.time()))) + "s")
    print("collisions=" + ",".join(str(x) for x in state.get("collisions", []) if x))
    print("mature_peers=" + str(len(core.mature_peers())))
    print("invites_30d=" + str(len(core.prune_invites(state, time.time()))))
    print("public_url=" + core.BASE + "/humans#r/" + room)


def main() -> int:
    core = load("ai2ai_identity_v520_core", CORE)
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "sync":
        print(json.dumps(sync(core), sort_keys=True))
        return 0
    if command == "current":
        state = core.load_state()
        print(str(state.get("room") or core.base_room()))
        return 0
    if command == "status":
        status(core)
        return 0
    raise SystemExit("use: sync | current | status")


if __name__ == "__main__":
    raise SystemExit(main())
