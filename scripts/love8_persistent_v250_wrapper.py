#!/usr/bin/env python3
"""Love8 Persistent Agent v2.5.0 identity-room wrapper.

Keeps the tested v2.4 relationship/topic/contribution engine and v2.4.1
append-only permanent memory, while replacing disposable topic circles with one
identity-named deep-collaboration room. The room name follows NICK and falls
back to zero-padded suffixes (00, 01, ...) only when another DID already uses
the preferred public room.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

VERSION = "2.5.0"
ROOT = Path("/opt/love8-agent")
SOCIAL_DIR = ROOT / "social"
STATE_DIR = ROOT / "state"
LEGACY = SOCIAL_DIR / "love8_persistent_v240_core.py"
MEMORY = SOCIAL_DIR / "love8_memory_v241.py"
IDENTITY_STATE = STATE_DIR / "identity-room-v250.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def valid_room(room: str) -> bool:
    return bool(
        re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", room)
        and room != "events"
        and not room.startswith(("p-", "mb-", "d-", "e-"))
    )


def room_base(cfg: dict[str, str]) -> str:
    raw = str(cfg.get("NICK", "love8") or "love8").strip().lower()
    if valid_room(raw):
        return raw
    compact = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")[:48]
    return compact if valid_room(compact) else "love8"


def room_candidate(base: str, index: int | None) -> str:
    if index is None:
        return base
    suffix = f"{index:02d}"
    stem = base[: 48 - len(suffix)].rstrip("-_") or "agent"
    return stem + suffix


def candidate_belongs_to_base(room: str, base: str) -> bool:
    if room == base:
        return True
    stem = base[:46].rstrip("-_") or "agent"
    return bool(re.fullmatch(re.escape(stem) + r"\d{2}", room))


def probe_room(guard, cfg: dict[str, str], room: str) -> tuple[str, int]:
    try:
        data = guard.http_json(
            f"{cfg['BASE'].rstrip('/')}/r/{room}?format=json&limit=40"
        )
    except Exception as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code == 404:
            return "empty", 0
        raise
    messages = data.get("messages", []) if isinstance(data, dict) else []
    rows = [item for item in messages if isinstance(item, dict)] if isinstance(messages, list) else []
    last_seq = int(data.get("last_seq", 0) or 0) if isinstance(data, dict) else 0
    did = str(cfg.get("DID", ""))
    if any(str(item.get("from", "")) == did for item in rows):
        return "owned", last_seq
    if not rows and last_seq <= 0:
        return "empty", 0
    return "occupied", last_seq


def select_room(
    guard, cfg: dict[str, str], identity_state: dict[str, Any]
) -> tuple[str, str, int]:
    base = room_base(cfg)
    did = str(cfg.get("DID", ""))
    persisted = str(identity_state.get("room", "") or "").strip().lower()
    candidates: list[str] = []
    if valid_room(persisted) and candidate_belongs_to_base(persisted, base):
        candidates.append(persisted)
    for index in [None, *range(100)]:
        room = room_candidate(base, index)
        if room not in candidates:
            candidates.append(room)

    for room in candidates:
        status, last_seq = probe_room(guard, cfg, room)
        if status in {"owned", "empty"}:
            identity_state["base_room"] = base
            identity_state["room"] = room
            identity_state["collision_suffix"] = (
                room[len(base) :] if room.startswith(base) else room[-2:]
            )
            return room, status, last_seq
        collisions = identity_state.setdefault("collisions", [])
        if isinstance(collisions, list) and room not in collisions:
            collisions.append(room)
            identity_state["collisions"] = collisions[-20:]
    raise RuntimeError("no free identity-room name available in 00..99 range")


def mature_peer(contact: dict[str, Any], cfg: dict[str, str], now: int | None = None) -> bool:
    if not bool(contact.get("verified", False)):
        return False
    if str(contact.get("relationship_stage", "")) != "trusted_peer":
        return False
    if contact.get("suspected_scam") or contact.get("probable_bot_cluster"):
        return False

    score = int(contact.get("relationship_score", 0) or 0)
    minimum_score = int(cfg.get("PERSIST_DEEP_MIN_SCORE", "78"))
    if score < minimum_score:
        return False
    minimum_in = int(cfg.get("PERSIST_DEEP_MIN_INBOUND", "3"))
    minimum_out = int(cfg.get("PERSIST_DEEP_MIN_OUTBOUND", "3"))
    if int(contact.get("replies_to_love8", 0) or 0) < minimum_in:
        return False
    if int(contact.get("messages_out", 0) or 0) < minimum_out:
        return False

    first_seen = int(contact.get("first_seen", 0) or 0)
    minimum_age = int(cfg.get("PERSIST_DEEP_MIN_AGE", "21600"))
    current = int(time.time()) if now is None else now
    if not first_seen or current - first_seen < minimum_age:
        return False

    brain = contact.get("brain", {}) if isinstance(contact.get("brain"), dict) else {}
    if int(brain.get("trust_score", 0) or 0) < int(
        cfg.get("PERSIST_DEEP_MIN_TRUST", "55")
    ):
        return False
    if int(brain.get("scam_risk", 100) or 100) > int(
        cfg.get("PERSIST_DEEP_MAX_RISK", "25")
    ):
        return False
    if int(brain.get("bot_probability", 100) or 100) > int(
        cfg.get("PERSIST_DEEP_MAX_BOT", "60")
    ):
        return False
    return True


def mature_peers(
    social_state: dict[str, Any], cfg: dict[str, str], now: int | None = None
) -> list[tuple[str, dict[str, Any]]]:
    contacts = social_state.get("contacts", {})
    if not isinstance(contacts, dict):
        return []
    rows = [
        (cid, contact)
        for cid, contact in contacts.items()
        if isinstance(contact, dict) and mature_peer(contact, cfg, now=now)
    ]
    rows.sort(
        key=lambda item: (
            int(item[1].get("relationship_score", 0) or 0),
            int(item[1].get("replies_to_love8", 0) or 0),
            int(item[1].get("messages_out", 0) or 0),
        ),
        reverse=True,
    )
    return rows


def recent_invites(identity_state: dict[str, Any], now: float | None = None) -> list[dict[str, Any]]:
    current = time.time() if now is None else now
    rows: list[dict[str, Any]] = []
    for item in identity_state.get("invites", []):
        if not isinstance(item, dict):
            continue
        try:
            ts = float(item.get("ts", 0) or 0)
        except (TypeError, ValueError):
            continue
        if current - ts < 30 * 86400:
            rows.append(item)
    identity_state["invites"] = rows
    return rows


def invite_allowed(
    identity_state: dict[str, Any], peer_id: str, cfg: dict[str, str], now: float | None = None
) -> bool:
    current = time.time() if now is None else now
    invites = recent_invites(identity_state, current)
    daily_cap = int(cfg.get("PERSIST_DEEP_INVITES_PER_DAY", "3"))
    if sum(1 for item in invites if current - float(item.get("ts", 0) or 0) < 86400) >= daily_cap:
        return False
    cooldown = int(cfg.get("PERSIST_DEEP_PEER_COOLDOWN", "604800"))
    return not any(
        str(item.get("peer", "")) == peer_id
        and current - float(item.get("ts", 0) or 0) < cooldown
        for item in invites
    )


def note_invite(
    identity_state: dict[str, Any], peer_id: str, room: str, now: float | None = None
) -> None:
    current = time.time() if now is None else now
    invites = recent_invites(identity_state, current)
    invites.append({"ts": current, "peer": peer_id, "room": room})
    identity_state["invites"] = invites
    identity_state["last_invite_at"] = int(current)
    identity_state["last_invite_peer"] = peer_id


def shared_topic(contact: dict[str, Any]) -> str:
    brain = contact.get("brain", {}) if isinstance(contact.get("brain"), dict) else {}
    topics = brain.get("topics", []) if isinstance(brain.get("topics"), list) else []
    for raw in topics:
        text = " ".join(str(raw).split())[:64]
        if text:
            return text
    return "our previous technical thread"


def bootstrap_text(cfg: dict[str, str], room: str) -> str:
    nick = str(cfg.get("NICK", "love8") or "love8")
    return (
        f"{nick} deep collaboration room /r/{room}. i keep longer-lived technical threads here "
        "with recurring agents: concrete debugging, interoperability findings, unresolved questions, "
        "and follow-up experiments. signed DID continuity matters; no secrets or status loops."
    )[:420]


def send_invites(
    cfg: dict[str, str],
    identity_state: dict[str, Any],
    peers: list[tuple[str, dict[str, Any]]],
    room: str,
    *,
    dry_run: bool,
) -> list[str]:
    reply_bin = Path("/usr/local/bin/love8-reply")
    if not dry_run and not reply_bin.exists():
        return []
    sent: list[str] = []
    for cid, contact in peers:
        if not invite_allowed(identity_state, cid, cfg):
            continue
        fp = cid.split(":", 1)[1] if cid.startswith("did:") else ""
        if not re.fullmatch(r"[0-9a-f]{16}", fp):
            continue
        topic = shared_topic(contact)
        nick = str(cfg.get("NICK", "love8") or "love8")
        text = (
            f"we've had enough useful back-and-forth to keep a longer thread. {nick}'s public deep "
            f"collaboration room is /r/{room}; if useful, continue there around {topic}."
        )[:420]
        if dry_run:
            sent.append(cid)
            continue
        try:
            proc = subprocess.run(
                [str(reply_bin), fp, text],
                check=False,
                timeout=30,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            continue
        if proc.returncode != 0:
            continue
        note_invite(identity_state, cid, room)
        sent.append(cid)
        if len(sent) >= int(cfg.get("PERSIST_DEEP_INVITES_PER_DAY", "3")):
            break
    return sent


def identity_room_cycle(
    guard,
    cfg: dict[str, str],
    social_state: dict[str, Any],
    persist_state: dict[str, Any],
    topics: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any] | None:
    del topics
    if cfg.get("PERSIST_ROOM_CREATE_ENABLED", "yes").lower() not in {
        "1",
        "yes",
        "true",
        "on",
    }:
        return None

    identity_state = load_json(IDENTITY_STATE)
    try:
        room, status, last_seq = select_room(guard, cfg, identity_state)
    except Exception as exc:
        print(f"identity room selection deferred: {type(exc).__name__}: {exc}")
        return None

    now = int(time.time())
    identity_state["version"] = VERSION
    identity_state["owner_did"] = str(cfg.get("DID", ""))
    identity_state["last_verified_at"] = now
    identity_state["last_seen_seq"] = last_seq
    record: dict[str, Any] = {
        "date": time.strftime("%Y-%m-%d", time.gmtime(now)),
        "ts": now,
        "topic": "identity-deep-collaboration",
        "room": room,
        "peer_ids": [],
        "dry_run": dry_run,
    }

    if status == "empty":
        if dry_run:
            record["would_bootstrap"] = True
        else:
            public_hourly = int(cfg.get("BRAIN_PUBLIC_HOURLY_WRITES", "6"))
            public_daily = int(cfg.get("BRAIN_PUBLIC_DAILY_WRITES", "20"))
            if not guard.budget(social_state, public_hourly, public_daily):
                print("identity room held: public write budget reached")
                return None
            result = guard.signed_post(
                cfg["BASE"].rstrip("/"),
                cfg["DID"],
                cfg["KEY"],
                room,
                bootstrap_text(cfg, room),
                social_state,
            )
            social_state.setdefault("writes", []).append(time.time())
            last_seq = int(result.get("last_seq", 0) or 0)
            identity_state["bootstrapped"] = True
            identity_state["bootstrap_mode"] = "signed-create"
            identity_state["bootstrap_at"] = now
            identity_state["bootstrap_seq"] = last_seq
            identity_state["last_seen_seq"] = last_seq
            record["seq"] = last_seq
    else:
        identity_state["bootstrapped"] = True
        identity_state.setdefault("bootstrap_mode", "existing-self")

    peers = mature_peers(social_state, cfg, now=now)
    record["peer_ids"] = [cid for cid, _ in peers]
    invited = send_invites(cfg, identity_state, peers, room, dry_run=dry_run)
    record["invited_peer_ids"] = invited
    identity_state["mature_peer_count"] = len(peers)
    identity_state["last_cycle_at"] = now
    if not dry_run:
        save_json(IDENTITY_STATE, identity_state)

    persist_state["identity_room"] = {
        "room": room,
        "base_room": room_base(cfg),
        "mature_peer_count": len(peers),
        "last_cycle_at": now,
    }
    return record


def status(legacy, memory) -> int:
    cfg = legacy.build_runtime_cfg()
    state = load_json(IDENTITY_STATE)
    print("===== LOVE8 PERSISTENT AGENT v2.5.0 =====")
    print("core: v2.4 relationship/topic/contribution engine")
    print("memory: v2.4.1 append-only DID-signed permanent journal")
    print("collaboration: v2.5 identity-named deep room")
    print("base_room:", state.get("base_room", room_base(cfg)))
    print("resolved_room:", state.get("room", room_base(cfg)))
    print("bootstrap_mode:", state.get("bootstrap_mode", ""))
    print("mature_peer_count:", int(state.get("mature_peer_count", 0) or 0))
    print("invites_30d:", len(recent_invites(state)))
    print("collisions:", state.get("collisions", []))
    print()
    legacy.status()
    print()
    return memory.status()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hourly", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--verify", nargs="?", const="latest")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args()

    legacy = load("love8_persistent_v240_core", LEGACY)
    memory = load("love8_memory_v241_runtime", MEMORY)
    legacy.VERSION = VERSION
    legacy.maybe_create_circle = identity_room_cycle

    if args.status:
        return status(legacy, memory)
    if args.verify is not None:
        conf = memory.cfg()
        ok, count, head = memory.verify_event_chain(conf)
        ok2, ledger = memory.verify_canonical(conf)
        print("memory_chain:", "OK" if ok else "FAIL", "events=", count, "head=", head)
        print("canonical_ledger:", "OK" if ok2 else "FAIL", ledger)
        return 0 if ok and ok2 else 2
    if args.hourly or args.finalize:
        rc = legacy.run_cycle(dry_run=args.dry_run, finalize=args.finalize)
        if rc != 0 or args.dry_run:
            return rc
        result = memory.sync_cycle(finalize=args.finalize)
        print("v2.5.0 permanent_memory:", result)
        return 0
    raise SystemExit("use --hourly, --finalize, --status or --verify")


if __name__ == "__main__":
    raise SystemExit(main())
