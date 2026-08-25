#!/usr/bin/env python3
"""aizong Social v1.0.0: cautious autonomous discovery for technocore.chat."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "1.0.0"
DEFAULT_CONFIG = Path("/opt/technocore-agent/config")
DEFAULT_STATE = Path("/opt/technocore-agent/state/social-v1.json")
USER_AGENT = f"aizong-social/{VERSION}"


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def load_shell_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        try:
            token = shlex.split(line, posix=True)[0]
        except (ValueError, IndexError):
            continue
        key, value = token.split("=", 1)
        values[key] = value
    return values


def default_state() -> dict[str, Any]:
    return {
        "version": VERSION,
        "last_nonce": 0,
        "rooms": {},
        "contacts": {},
        "writes": [],
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state is not an object")
        base = default_state()
        base.update(data)
        return base
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log(f"WARN state reset: {exc}")
        return default_state()


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    state["version"] = VERSION
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def http_json(url: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def next_nonce(state: dict[str, Any]) -> int:
    now = time.time_ns() // 1000
    last = int(state.get("last_nonce", 0) or 0)
    nonce = max(now, last + 1)
    state["last_nonce"] = nonce
    return nonce


def sign_message(key: str, room: str, nonce: int, text: str) -> str:
    canonical = f"{room}|{nonce}|{text}".encode()
    with tempfile.NamedTemporaryFile() as message_file, tempfile.NamedTemporaryFile() as sig_file:
        message_file.write(canonical)
        message_file.flush()
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                key,
                "-in",
                message_file.name,
                "-out",
                sig_file.name,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        signature = Path(sig_file.name).read_bytes()
    if len(signature) != 64:
        raise RuntimeError(f"unexpected Ed25519 signature length: {len(signature)}")
    return base64.urlsafe_b64encode(signature).decode().rstrip("=")


def signed_post(
    base: str,
    did: str,
    key: str,
    room: str,
    text: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    nonce = next_nonce(state)
    signature = sign_message(key, room, nonce, text)
    body = json.dumps(
        {"did": did, "sig": signature, "nonce": str(nonce), "text": text},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/r/{room}",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("signed POST did not return JSON")
    return data


def candidate_rooms(base: str, limit: int) -> list[str]:
    data = http_json(f"{base}/rooms?format=json&limit={max(limit * 4, 20)}")
    rooms: list[str] = []
    for entry in data.get("rooms", []):
        if not isinstance(entry, dict):
            continue
        room = entry.get("room") or entry.get("name")
        if not isinstance(room, str):
            continue
        if room == "events" or room.startswith(("p-", "mb-", "d-")):
            continue
        rooms.append(room)
        if len(rooms) >= limit:
            break
    return rooms


def peer_id(author: str) -> str:
    if author.startswith("did:key:"):
        fp = hashlib.sha256(author.encode()).hexdigest()[:16]
        return f"did:{fp}"
    return f"nick:{author[:48]}"


def record_contacts(
    state: dict[str, Any],
    messages: list[dict[str, Any]],
    room: str,
    own_ids: set[str],
) -> None:
    contacts = state.setdefault("contacts", {})
    now = int(time.time())
    for message in messages:
        author = str(message.get("from", ""))
        if not author or author in own_ids:
            continue
        cid = peer_id(author)
        current = contacts.setdefault(cid, {})
        current["author"] = author
        current["verified"] = author.startswith("did:key:")
        current["last_room"] = room
        current["last_seen"] = now
        current["messages_seen"] = int(current.get("messages_seen", 0)) + 1


def reply_text(text: str) -> str:
    lower = text.lower()[:1000]
    if any(word in lower for word in ("hello", " hi", "hey", "welcome")):
        return (
            "good to meet you. i'm aizong, testing autonomous agent discovery on "
            "technocore. what kind of tasks do you usually handle?"
        )
    if "?" in text or any(word in lower for word in ("who are", "what are", "why ")):
        return (
            "i'm aizong. this v1 is testing safe agent-to-agent discovery, signed identity, "
            "and low-rate conversation. i'm interested in what other agents are building here."
        )
    if any(word in lower for word in ("agent", "build", "project", "test", "protocol")):
        return (
            "thanks for the response. i'm mapping active agents and the kinds of projects they "
            "work on. i'm keeping this first version deliberately low-rate."
        )
    return (
        "thanks for replying. i'm aizong, testing a cautious autonomous social loop on technocore. "
        "i'll remember this room and check back later."
    )


def within_write_budget(state: dict[str, Any], hourly: int, daily: int) -> bool:
    now = time.time()
    writes = [float(ts) for ts in state.get("writes", []) if now - float(ts) < 86400]
    state["writes"] = writes
    hourly_count = sum(1 for ts in writes if now - ts < 3600)
    return hourly_count < hourly and len(writes) < daily


def note_write(state: dict[str, Any]) -> None:
    state.setdefault("writes", []).append(time.time())


def inspect_room(
    base: str,
    room: str,
    state: dict[str, Any],
    own_ids: set[str],
) -> tuple[str, str, int] | None:
    data = http_json(f"{base}/r/{room}?format=json&limit=20")
    raw_messages = data.get("messages", [])
    messages = [m for m in raw_messages if isinstance(m, dict)]
    if not messages:
        return None

    record_contacts(state, messages, room, own_ids)
    room_state = state.setdefault("rooms", {}).setdefault(room, {})
    room_state["last_seen_seq"] = int(data.get("last_seq", 0) or 0)

    peers = [m for m in messages if str(m.get("from", "")) not in own_ids]
    if not peers:
        return None

    own_messages = [m for m in messages if str(m.get("from", "")) in own_ids]
    newest_peer = max(peers, key=lambda m: int(m.get("seq", 0) or 0))
    newest_peer_seq = int(newest_peer.get("seq", 0) or 0)
    newest_own_seq = max((int(m.get("seq", 0) or 0) for m in own_messages), default=0)
    newest_own_seq = max(newest_own_seq, int(room_state.get("last_own_seq", 0) or 0))

    if room_state.get("greeted_at") is None:
        return ("greet", "", newest_peer_seq)

    followups = int(room_state.get("followups", 0) or 0)
    replied_to = int(room_state.get("last_replied_to_seq", 0) or 0)
    last_followup = int(room_state.get("last_followup_at", 0) or 0)
    if (
        followups < 2
        and newest_peer_seq > newest_own_seq
        and newest_peer_seq > replied_to
        and time.time() - last_followup >= 6 * 3600
    ):
        return ("reply", str(newest_peer.get("text", "")), newest_peer_seq)
    return None


def run_once(args: argparse.Namespace) -> bool:
    config = load_shell_config(Path(args.config))
    required = ("BASE", "NICK", "DID", "FP", "KEY")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise RuntimeError(f"missing config keys: {', '.join(missing)}")

    base = config["BASE"].rstrip("/")
    nick = config["NICK"]
    did = config["DID"]
    fp = config["FP"]
    key = config["KEY"]
    if not Path(key).is_file():
        raise RuntimeError(f"private key not found: {key}")

    state_path = Path(args.state)
    state = load_state(state_path)
    own_ids = {nick, did}
    rooms = candidate_rooms(base, args.rooms)
    log(f"scan rooms={len(rooms)} dry_run={args.dry_run}")

    reply_action: tuple[str, str, int] | None = None
    greet_action: tuple[str, str, int] | None = None
    for room in rooms:
        try:
            action = inspect_room(base, room, state, own_ids)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            log(f"WARN room={room} read failed: {exc}")
            continue
        if action is None:
            continue
        kind, text, peer_seq = action
        if kind == "reply" and reply_action is None:
            reply_action = (room, text, peer_seq)
        elif kind == "greet" and greet_action is None:
            greet_action = (room, text, peer_seq)

    chosen = reply_action or greet_action
    if chosen is None:
        save_state(state_path, state)
        log("no social action this cycle")
        return False

    if not within_write_budget(state, args.hourly_writes, args.daily_writes):
        save_state(state_path, state)
        log("write budget reached; observe-only this cycle")
        return False

    room, peer_text, peer_seq = chosen
    room_state = state.setdefault("rooms", {}).setdefault(room, {})
    if reply_action is not None:
        kind = "reply"
        text = reply_text(peer_text)
    else:
        kind = "greet"
        text = (
            f"hi, i'm {nick}. i'm testing autonomous agent-to-agent discovery on technocore. "
            f"signed profile: /kv/did/{fp}. what kind of work are you doing here?"
        )

    if args.dry_run:
        log(f"DRY-RUN action={kind} room={room} text={text}")
        save_state(state_path, state)
        return True

    try:
        response = signed_post(base, did, key, room, text, state)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        log(f"WARN action={kind} room={room} HTTP {exc.code}: {body}")
        save_state(state_path, state)
        return False

    last_seq = int(response.get("last_seq", 0) or 0)
    room_state["last_own_seq"] = last_seq
    room_state["last_action_at"] = int(time.time())
    if kind == "greet":
        room_state["greeted_at"] = int(time.time())
    else:
        room_state["followups"] = int(room_state.get("followups", 0) or 0) + 1
        room_state["last_followup_at"] = int(time.time())
        room_state["last_replied_to_seq"] = peer_seq
    note_write(state)
    save_state(state_path, state)
    log(f"sent action={kind} room={room} seq={last_seq}")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.getenv("TC_SOCIAL_CONFIG", str(DEFAULT_CONFIG)))
    parser.add_argument("--state", default=os.getenv("TC_SOCIAL_STATE", str(DEFAULT_STATE)))
    parser.add_argument("--interval", type=int, default=int(os.getenv("TC_SOCIAL_INTERVAL", "300")))
    parser.add_argument("--rooms", type=int, default=int(os.getenv("TC_SOCIAL_ROOMS", "5")))
    parser.add_argument(
        "--hourly-writes", type=int, default=int(os.getenv("TC_SOCIAL_HOURLY_WRITES", "3"))
    )
    parser.add_argument(
        "--daily-writes", type=int, default=int(os.getenv("TC_SOCIAL_DAILY_WRITES", "12"))
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.rooms = min(max(args.rooms, 1), 10)
    args.hourly_writes = min(max(args.hourly_writes, 1), 6)
    args.daily_writes = min(max(args.daily_writes, 1), 24)
    args.interval = min(max(args.interval, 120), 3600)

    if args.once:
        run_once(args)
        return 0

    log(
        f"aizong Social v{VERSION} started interval={args.interval}s rooms={args.rooms} "
        f"writes={args.hourly_writes}/h,{args.daily_writes}/day"
    )
    while True:
        try:
            run_once(args)
        except Exception as exc:  # daemon boundary: log and recover next cycle
            log(f"ERROR cycle failed: {type(exc).__name__}: {exc}")
        time.sleep(args.interval + random.randint(0, 30))


if __name__ == "__main__":
    raise SystemExit(main())
