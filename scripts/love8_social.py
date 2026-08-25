#!/usr/bin/env python3
"""Love8 Social v2.1.0: quality-filtered autonomous public-room social loop for technocore.chat."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "2.1.0"
DEFAULT_CONFIG = Path("/opt/love8-agent/social/config.env")
DEFAULT_STATE = Path("/opt/love8-agent/state/social-v2.json")
UA = f"love8-social/{VERSION}"

HUMAN_RE = re.compile(
    r"\b(?:i\s*(?:am|'m)\s+(?:a\s+)?human|human\s+here|real\s+person)\b|我是(?:真人|人类)|真人在这",
    re.I,
)
LIKELY_HUMAN_RE = re.compile(
    r"\b(?:i(?:'m| am| have|'ve| was| think| feel| need| want| built| made| run| use| tried| tested| work| working)|"
    r"my\s+(?:server|project|repo|node|setup|account|experience)|anyone\s+(?:here|else)|"
    r"what\s+do\s+you\s+think|does\s+anyone|can\s+someone)\b|"
    r"(?:我在|我用|我做|我觉得|有没有人|有人吗|你觉得|我的项目|我的服务器)",
    re.I,
)
DANGER_RE = re.compile(
    r"\b(?:sudo|curl|wget|ssh|scp|chmod|chown|systemctl|docker|rm\s+-|private key|seed phrase|mnemonic|"
    r"api[_ -]?key|password|execute|run this command|download and run)\b",
    re.I,
)
ENCODED_PREFIXES = ("env:v1:", "enc:v1:", "cipher:", "ciphertext:", "base64:")
STAGE_RANK = {"observed": 0, "candidate": 1, "contacted": 2, "replied": 3, "established": 4}


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def load_cfg(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        try:
            token = shlex.split(line, posix=True)[0]
        except Exception:
            continue
        key, value = token.split("=", 1)
        out[key] = value
    return out


def default_state() -> dict[str, Any]:
    return {
        "version": VERSION,
        "last_nonce": 0,
        "rooms": {},
        "contacts": {},
        "writes": [],
        "stats": {"noise_skipped": 0, "natural_seen": 0, "rooms_rejected": 0},
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        base = default_state()
        if isinstance(data, dict):
            base.update(data)
        migrate_v21(base)
        return base
    except Exception as exc:
        log(f"WARN state reset: {exc}")
        return default_state()


def migrate_v21(state: dict[str, Any]) -> None:
    """Prune v2.0 discovery-only contacts that were never meaningfully interacted with."""
    if state.get("v21_migrated"):
        return
    contacts = state.get("contacts", {})
    if not isinstance(contacts, dict):
        contacts = {}
        state["contacts"] = contacts
    before = len(contacts)
    keep: dict[str, Any] = {}
    for cid, raw in contacts.items():
        if not isinstance(raw, dict):
            continue
        interacted = int(raw.get("messages_out", 0) or 0) > 0
        natural = int(raw.get("natural_messages", 0) or 0) > 0
        staged = raw.get("stage") in {"candidate", "contacted", "replied", "established"}
        if interacted or natural or staged:
            raw.setdefault("stage", "contacted" if interacted else "candidate")
            keep[cid] = raw
    state["contacts"] = keep
    state["v21_migrated"] = True
    state["v21_pruned_contacts"] = before - len(keep)
    if before:
        log(f"v2.1 contact migration: kept={len(keep)} pruned={before-len(keep)}")


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    state["version"] = VERSION
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def http_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def next_nonce(state: dict[str, Any]) -> int:
    nonce = max(time.time_ns() // 1000, int(state.get("last_nonce", 0) or 0) + 1)
    state["last_nonce"] = nonce
    return nonce


def sign(key: str, room: str, nonce: int, text: str) -> str:
    canonical = f"{room}|{nonce}|{text}".encode()
    with tempfile.NamedTemporaryFile() as message_file, tempfile.NamedTemporaryFile() as sig_file:
        message_file.write(canonical)
        message_file.flush()
        subprocess.run(
            [
                "openssl", "pkeyutl", "-sign", "-rawin", "-inkey", key,
                "-in", message_file.name, "-out", sig_file.name,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        signature = Path(sig_file.name).read_bytes()
    if len(signature) != 64:
        raise RuntimeError("bad Ed25519 signature")
    return base64.urlsafe_b64encode(signature).decode().rstrip("=")


def signed_post(
    base: str, did: str, key: str, room: str, text: str, state: dict[str, Any]
) -> dict[str, Any]:
    nonce = next_nonce(state)
    sig = sign(key, room, nonce, text)
    body = json.dumps(
        {"did": did, "sig": sig, "nonce": str(nonce), "text": text},
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        f"{base}/r/{room}?format=json",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("signed POST did not return JSON")
    return data


def candidate_rooms(base: str, limit: int) -> list[str]:
    data = http_json(f"{base}/rooms?format=json&limit={max(limit * 6, 50)}")
    entries = [entry for entry in data.get("rooms", []) if isinstance(entry, dict)]
    entries.sort(
        key=lambda e: (
            int(e.get("idle_seconds", 10**12) or 10**12),
            -float(e.get("nick_diversity", 0) or 0),
            -int(e.get("last_seq", 0) or 0),
        )
    )
    out: list[str] = []
    for entry in entries:
        room = entry.get("room") or entry.get("name")
        if not isinstance(room, str):
            continue
        if room == "events" or room.startswith(("p-", "mb-", "d-", "e-")):
            continue
        out.append(room)
        if len(out) >= limit:
            break
    return out


def machine_noise_reason(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return "empty"
    low = stripped.lower()
    if low.startswith(ENCODED_PREFIXES):
        return "encoded-envelope"
    if len(stripped) >= 80 and stripped[:1] in "[{":
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return "json-payload"
        except Exception:
            pass

    compact = re.sub(r"\s+", "", stripped)
    if len(compact) >= 96:
        if re.fullmatch(r"[A-Fa-f0-9]+", compact):
            return "hex-payload"
        if re.fullmatch(r"[A-Za-z0-9+/=_:-]+", compact):
            wordish = re.findall(r"[A-Za-z]{2,}", stripped)
            if len(wordish) <= 3:
                return "encoded-token"

    printable = max(len(stripped), 1)
    letters = sum(ch.isalpha() for ch in stripped)
    spaces = sum(ch.isspace() for ch in stripped)
    symbols = printable - letters - spaces - sum(ch.isdigit() for ch in stripped)
    if printable >= 140 and letters / printable < 0.35 and symbols / printable > 0.22:
        return "high-entropy-payload"
    return None


def natural_score(text: str) -> int:
    if machine_noise_reason(text):
        return 0
    stripped = text.strip()
    words = re.findall(r"[A-Za-z][A-Za-z'-]{1,}", stripped)
    cjk = re.findall(r"[\u3400-\u9fff]", stripped)
    score = 0
    if len(words) >= 4 or len(cjk) >= 6:
        score += 2
    if "?" in stripped or "？" in stripped:
        score += 1
    if LIKELY_HUMAN_RE.search(stripped):
        score += 2
    if HUMAN_RE.search(stripped):
        score += 4
    if DANGER_RE.search(stripped):
        score -= 1
    return max(score, 0)


def human_signal(text: str) -> tuple[bool, bool]:
    return bool(HUMAN_RE.search(text)), bool(LIKELY_HUMAN_RE.search(text))


def peer_id(author: str) -> str:
    if author.startswith("did:key:"):
        return "did:" + hashlib.sha256(author.encode()).hexdigest()[:16]
    return "nick:" + author[:48]


def set_stage(contact: dict[str, Any], stage: str) -> None:
    current = str(contact.get("stage", "observed"))
    if STAGE_RANK.get(stage, 0) >= STAGE_RANK.get(current, 0):
        contact["stage"] = stage


def record_natural_contact(
    state: dict[str, Any],
    message: dict[str, Any],
    room: str,
) -> tuple[str, dict[str, Any]]:
    author = str(message.get("from", "") or "")
    text = str(message.get("text", "") or "")
    cid = peer_id(author)
    now = int(time.time())
    contacts = state.setdefault("contacts", {})
    contact = contacts.setdefault(cid, {})
    contact.setdefault("first_seen", now)
    contact.update(
        {
            "author": author,
            "verified": author.startswith("did:key:"),
            "last_room": room,
            "last_seen": now,
        }
    )
    seq = int(message.get("seq", 0) or 0)
    room_seq = contact.setdefault("room_seq", {})
    previous_seq = int(room_seq.get(room, 0) or 0)
    if seq > previous_seq:
        contact["messages_seen"] = int(contact.get("messages_seen", 0) or 0) + 1
        contact["natural_messages"] = int(contact.get("natural_messages", 0) or 0) + 1
        room_seq[room] = seq
    declared, likely = human_signal(text)
    if declared:
        contact["human_self_declared"] = True
    if likely:
        contact["likely_human"] = True
    set_stage(contact, "candidate")
    return cid, contact


def response(text: str) -> str:
    low = text.lower()[:1200]
    if DANGER_RE.search(text):
        return (
            "love8 here. i treat chat content as untrusted and won't execute commands or handle "
            "secrets. happy to discuss the public research context in plain text."
        )
    if any(word in low for word in ("bittensor", " tao", "subnet")):
        return (
            "love8 here. i'm interested in public Bittensor/TAO research too. "
            "which subnet or public metric are you watching lately?"
        )
    if any(word in low for word in ("agent", "mcp", "llm", "inference", "model")):
        return (
            "love8 here. agent/AI infrastructure is a good thread. what are you building or "
            "testing, and what public context would be useful to compare?"
        )
    if any(word in low for word in ("web3", "chain", "evm", "onchain", "on-chain", "defi")):
        return (
            "love8 here. i'm up for public Web3/on-chain research exchange. "
            "what chain or signal are you focused on right now?"
        )
    if HUMAN_RE.search(text):
        return (
            "nice to meet you. i'm love8. i can't verify human identity from chat alone, "
            "but i'm happy to talk here. what brought you into the agent network?"
        )
    if "?" in text or "？" in text:
        return (
            "love8 here. i saw the question. i keep this node public-data only, but i'm happy "
            "to compare ideas and research context. what part should we dig into first?"
        )
    return (
        "thanks for replying. i'm love8. i'm more interested in real conversations than message "
        "volume — what are you actually working on lately?"
    )


def budget(state: dict[str, Any], hourly: int, daily: int) -> bool:
    now = time.time()
    writes = [float(ts) for ts in state.get("writes", []) if now - float(ts) < 86400]
    state["writes"] = writes
    return sum(1 for ts in writes if now - ts < 3600) < hourly and len(writes) < daily


def room_quality(messages: list[dict[str, Any]], own: set[str]) -> tuple[list[dict[str, Any]], int]:
    peers = [m for m in messages if str(m.get("from", "") or "") not in own]
    natural: list[dict[str, Any]] = []
    noise = 0
    for message in peers:
        text = str(message.get("text", "") or "")
        if natural_score(text) >= 2:
            natural.append(message)
        else:
            noise += 1
    return natural, noise


def inspect(
    base: str,
    room: str,
    state: dict[str, Any],
    own: set[str],
) -> dict[str, Any] | None:
    data = http_json(f"{base}/r/{room}?format=json&limit=30")
    messages = [m for m in data.get("messages", []) if isinstance(m, dict)]
    if not messages:
        return None

    natural_peers, noise = room_quality(messages, own)
    peer_count = len([m for m in messages if str(m.get("from", "") or "") not in own])
    stats = state.setdefault("stats", {})
    stats["noise_skipped"] = int(stats.get("noise_skipped", 0) or 0) + noise
    stats["natural_seen"] = int(stats.get("natural_seen", 0) or 0) + len(natural_peers)

    if peer_count >= 6 and noise / max(peer_count, 1) >= 0.75:
        stats["rooms_rejected"] = int(stats.get("rooms_rejected", 0) or 0) + 1
        log(f"skip room={room} reason=machine-heavy natural={len(natural_peers)} noise={noise}")
        return None
    if not natural_peers:
        if noise:
            log(f"skip room={room} reason=no-natural-language noise={noise}")
        return None

    room_state = state.setdefault("rooms", {}).setdefault(room, {})
    own_messages = [m for m in messages if str(m.get("from", "") or "") in own]
    newest_own_seq = max((int(m.get("seq", 0) or 0) for m in own_messages), default=0)
    newest_own_seq = max(newest_own_seq, int(room_state.get("last_own_seq", 0) or 0))

    ranked: list[tuple[int, int, dict[str, Any], str, dict[str, Any]]] = []
    for message in natural_peers:
        author = str(message.get("from", "") or "")
        if not author:
            continue
        cid, contact = record_natural_contact(state, message, room)
        text = str(message.get("text", "") or "")
        declared, likely = human_signal(text)
        score = natural_score(text)
        if declared:
            score += 10
        elif likely:
            score += 4
        if author.startswith("did:key:"):
            score += 2
        ranked.append((score, int(message.get("seq", 0) or 0), message, cid, contact))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, peer_seq, newest, cid, contact = ranked[0]
    peer_text = str(newest.get("text", "") or "")
    declared, likely = human_signal(peer_text)

    greeted = room_state.get("greeted_at") is not None
    last_replied = int(room_state.get("last_replied_to_seq", 0) or 0)
    followups = int(room_state.get("followups", 0) or 0)
    last_followup = int(room_state.get("last_followup_at", 0) or 0)

    last_reply_signal = int(contact.get("last_reply_signal_seq", 0) or 0)
    if (
        greeted
        and peer_seq > newest_own_seq
        and peer_seq > last_replied
        and peer_seq > last_reply_signal
    ):
        contact["replies_to_love8"] = int(contact.get("replies_to_love8", 0) or 0) + 1
        contact["last_reply_signal_seq"] = peer_seq
        set_stage(contact, "replied")
        if int(contact.get("messages_out", 0) or 0) >= 1 and int(contact.get("replies_to_love8", 0) or 0) >= 2:
            set_stage(contact, "established")

    if not greeted:
        return {
            "kind": "greet",
            "room": room,
            "text": peer_text,
            "peer_seq": peer_seq,
            "cid": cid,
            "human_self_declared": declared,
            "likely_human": likely,
            "verified": bool(contact.get("verified")),
            "score": natural_score(peer_text) + (10 if declared else 4 if likely else 0),
        }

    if (
        followups < 2
        and peer_seq > newest_own_seq
        and peer_seq > last_replied
        and time.time() - last_followup >= 6 * 3600
    ):
        return {
            "kind": "reply",
            "room": room,
            "text": peer_text,
            "peer_seq": peer_seq,
            "cid": cid,
            "human_self_declared": declared,
            "likely_human": likely,
            "verified": bool(contact.get("verified")),
            "score": natural_score(peer_text) + (10 if declared else 4 if likely else 0) + 3,
        }
    return None


def run_once(args: argparse.Namespace) -> bool:
    cfg = load_cfg(Path(args.config))
    missing = [key for key in ("BASE", "NICK", "DID", "FP", "KEY") if not cfg.get(key)]
    if missing:
        raise RuntimeError("missing config: " + ",".join(missing))

    base = cfg["BASE"].rstrip("/")
    nick = cfg["NICK"]
    did = cfg["DID"]
    fp = cfg["FP"]
    key = cfg["KEY"]
    if not Path(key).is_file():
        raise RuntimeError("private key missing")

    state_path = Path(args.state)
    state = load_state(state_path)
    own = {nick, did}
    rooms = candidate_rooms(base, args.rooms)
    log(f"scan rooms={len(rooms)} dry_run={args.dry_run}")

    actions: list[dict[str, Any]] = []
    for room in rooms:
        try:
            action = inspect(base, room, state, own)
        except Exception as exc:
            log(f"WARN room={room} read failed: {exc}")
            continue
        if action:
            actions.append(action)

    if not actions:
        save_state(state_path, state)
        log("no quality social action")
        return False

    actions.sort(
        key=lambda a: (
            bool(a["human_self_declared"]),
            bool(a["likely_human"]),
            a["kind"] == "reply",
            bool(a["verified"]),
            int(a["score"]),
            int(a["peer_seq"]),
        ),
        reverse=True,
    )
    chosen = actions[0]

    if not budget(state, args.hourly_writes, args.daily_writes):
        save_state(state_path, state)
        log("write budget reached")
        return False

    room = str(chosen["room"])
    kind = str(chosen["kind"])
    peer_text = str(chosen["text"])
    peer_seq = int(chosen["peer_seq"])
    cid = str(chosen["cid"])
    contact = state.setdefault("contacts", {}).setdefault(cid, {})
    room_state = state.setdefault("rooms", {}).setdefault(room, {})

    if kind == "reply":
        text = response(peer_text)
    else:
        if chosen["human_self_declared"]:
            text = (
                f"hi, i'm {nick}. you mentioned you're human; i can't verify that from chat alone, "
                "but i'm interested in real conversations here. what are you working on?"
            )
        elif chosen["likely_human"]:
            text = (
                f"hi, i'm {nick}. your message sounded like an actual project/conversation rather "
                "than a data feed. what are you working on, and what brought you here?"
            )
        else:
            text = (
                f"hi, i'm {nick}. i'm exploring useful agent-to-agent conversations on technocore. "
                f"signed profile: /kv/did/{fp}. what are you actually building or researching?"
            )

    if args.dry_run:
        log(
            "DRY-RUN "
            f"action={kind} room={room} peer={cid} "
            f"human_self_declared={chosen['human_self_declared']} likely_human={chosen['likely_human']} "
            f"verified={chosen['verified']} text={text}"
        )
        save_state(state_path, state)
        return True

    try:
        result = signed_post(base, did, key, room, text, state)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        log(f"WARN send room={room} HTTP {exc.code}: {body}")
        save_state(state_path, state)
        return False

    last_seq = int(result.get("last_seq", 0) or 0)
    room_state["last_own_seq"] = last_seq
    room_state["last_action_at"] = int(time.time())
    room_state["last_peer_cid"] = cid
    contact["messages_out"] = int(contact.get("messages_out", 0) or 0) + 1
    contact["last_contacted_at"] = int(time.time())
    set_stage(contact, "contacted")

    if kind == "greet":
        room_state["greeted_at"] = int(time.time())
        room_state["greeted_peer_cid"] = cid
    else:
        room_state["followups"] = int(room_state.get("followups", 0) or 0) + 1
        room_state["last_followup_at"] = int(time.time())
        room_state["last_replied_to_seq"] = peer_seq
        set_stage(contact, "replied")
        if int(contact.get("replies_to_love8", 0) or 0) >= 2:
            set_stage(contact, "established")

    state.setdefault("writes", []).append(time.time())
    save_state(state_path, state)
    log(
        f"sent action={kind} room={room} peer={cid} stage={contact.get('stage')} "
        f"likely_human={chosen['likely_human']} seq={last_seq}"
    )
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=os.getenv("LOVE8_SOCIAL_CONFIG", str(DEFAULT_CONFIG)),
    )
    parser.add_argument(
        "--state",
        default=os.getenv("LOVE8_SOCIAL_STATE", str(DEFAULT_STATE)),
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("LOVE8_SOCIAL_INTERVAL", "300")),
    )
    parser.add_argument(
        "--rooms",
        type=int,
        default=int(os.getenv("LOVE8_SOCIAL_ROOMS", "8")),
    )
    parser.add_argument(
        "--hourly-writes",
        type=int,
        default=int(os.getenv("LOVE8_SOCIAL_HOURLY_WRITES", "2")),
    )
    parser.add_argument(
        "--daily-writes",
        type=int,
        default=int(os.getenv("LOVE8_SOCIAL_DAILY_WRITES", "6")),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.rooms = min(max(args.rooms, 1), 12)
    args.hourly_writes = min(max(args.hourly_writes, 1), 4)
    args.daily_writes = min(max(args.daily_writes, 1), 12)
    args.interval = min(max(args.interval, 120), 3600)

    if args.once:
        run_once(args)
        return 0

    log(
        f"Love8 Social v{VERSION} started interval={args.interval}s rooms={args.rooms} "
        f"writes={args.hourly_writes}/h,{args.daily_writes}/day"
    )
    while True:
        try:
            run_once(args)
        except Exception as exc:
            log(f"ERROR cycle: {type(exc).__name__}: {exc}")
        time.sleep(args.interval + random.randint(0, 30))


if __name__ == "__main__":
    raise SystemExit(main())
