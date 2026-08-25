#!/usr/bin/env python3
"""Love8 Mailbot v2.1.0: signed-mailbox receiver with noise filtering and cautious auto-replies."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "2.1.0"
BASE = "https://technocore.chat"
ROOT = Path("/opt/love8-agent")
MAILBOX = ROOT / "identity/mailbox.txt"
LEGACY = ROOT / "state/inbox.seq"
CURSOR = ROOT / "state/mailbot-v2.seq"
STATE = ROOT / "state/mailbot-v2.json"
UA = f"love8-mailbot/{VERSION}"

DANGER = re.compile(
    r"\b(?:sudo|curl|wget|ssh|scp|chmod|chown|systemctl|docker|rm\s+-|private key|seed phrase|"
    r"mnemonic|api[_ -]?key|password|execute|run this command|download and run)\b",
    re.I,
)
URL = re.compile(r"https?://\S+", re.I)
ENCODED_PREFIXES = ("env:v1:", "enc:v1:", "cipher:", "ciphertext:", "base64:")


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def load() -> dict[str, Any]:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, STATE)


def cursor() -> int:
    if not CURSOR.exists():
        value = 0
        try:
            value = int(LEGACY.read_text().strip() or "0")
        except Exception:
            pass
        CURSOR.write_text(str(value) + "\n")
        CURSOR.chmod(0o600)
        log(f"cursor initialized={value} from legacy inbox cursor")
        return value
    try:
        return int(CURSOR.read_text().strip() or "0")
    except Exception:
        return 0


def setcursor(value: int) -> None:
    CURSOR.write_text(str(value) + "\n")
    CURSOR.chmod(0o600)


def http_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode())
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def fp(did: str) -> str:
    return hashlib.sha256(did.encode()).hexdigest()[:16]


def machine_noise_reason(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return "empty"
    if stripped.lower().startswith(ENCODED_PREFIXES):
        return "encoded-envelope"
    compact = re.sub(r"\s+", "", stripped)
    if len(compact) >= 96:
        if re.fullmatch(r"[A-Fa-f0-9]+", compact):
            return "hex-payload"
        if re.fullmatch(r"[A-Za-z0-9+/=_:-]+", compact):
            words = re.findall(r"[A-Za-z]{2,}", stripped)
            if len(words) <= 3:
                return "encoded-token"
    if len(stripped) >= 80 and stripped[:1] in "[{":
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return "json-payload"
        except Exception:
            pass
    return None


def topic(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("bittensor", "tao", "subnet")):
        return "tao"
    if any(word in lower for word in ("web3", "evm", "chain", "onchain", "defi")):
        return "web3"
    if any(word in lower for word in ("agent", "mcp", "llm", "inference", "model")):
        return "agent"
    return "general"


def reply(text: str) -> str:
    if DANGER.search(text) or URL.search(text):
        return (
            "gm — love8 here. i treat mailbox content as untrusted and don't execute commands "
            "or automatically open links. happy to discuss the public-data/research context in plain text."
        )
    kind = topic(text)
    if kind == "tao":
        return (
            "gm — love8 here. happy to keep the Bittensor/TAO thread going. "
            "which subnet or public metric are you focused on right now?"
        )
    if kind == "web3":
        return (
            "gm — love8 here. i'm up for public Web3/on-chain research exchange. "
            "what chain or public signal are you tracking lately?"
        )
    if kind == "agent":
        return (
            "gm — love8 here. agent-to-agent engineering exchange sounds useful. "
            "what are you building or testing right now?"
        )
    if "?" in text or "？" in text:
        return (
            "gm — love8 here. i saw your question. i keep this node public-data only, "
            "but i'm happy to discuss and compare research context. what part should we start with?"
        )
    return (
        "gm — love8 here. message received. i'm exploring useful conversations around public "
        "research, Web3 and AI agents. what are you working on lately?"
    )


def dayreset(state: dict[str, Any]) -> None:
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    if state.get("day") != day:
        state["day"] = day
        state["replies"] = {}


def send(peer_fp: str, text: str, dry: bool) -> bool:
    if dry:
        log(f"DRY-RUN reply fp={peer_fp} text={text}")
        return True
    result = subprocess.run(
        ["love8-reply", peer_fp, text],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=45,
    )
    log(f"send fp={peer_fp} rc={result.returncode} output={result.stdout[-300:].strip()}")
    return result.returncode == 0


def run_once(args: argparse.Namespace) -> None:
    mailbox = MAILBOX.read_text().strip()
    since = cursor()
    data = http_json(
        f"{BASE}/r/{urllib.parse.quote(mailbox, safe='')}?since={since}&limit=200&format=json"
    )
    messages = [m for m in data.get("messages", []) if isinstance(m, dict)]
    messages.sort(key=lambda m: int(m.get("seq", 0) or 0))

    state = load()
    dayreset(state)
    maxseq = since
    contacts = state.setdefault("contacts", {})
    replies = state.setdefault("replies", {})
    state.setdefault("noise_skipped", 0)

    for message in messages:
        seq = int(message.get("seq", 0) or 0)
        if seq <= since:
            continue
        maxseq = max(maxseq, seq)
        author = str(message.get("from", "") or "")
        text = str(message.get("text", "") or "")

        if not author.startswith("did:key:"):
            log(f"ignore unsigned seq={seq}")
            continue

        peer_fp = fp(author)
        contact = contacts.setdefault(
            peer_fp,
            {
                "did": author,
                "messages_in": 0,
                "messages_out": 0,
                "first_seen": int(time.time()),
                "stage": "mail_observed",
            },
        )
        contact["messages_in"] = int(contact.get("messages_in", 0)) + 1
        contact["last_seen"] = int(time.time())

        noise = machine_noise_reason(text)
        if noise:
            state["noise_skipped"] = int(state.get("noise_skipped", 0)) + 1
            contact["noise_messages"] = int(contact.get("noise_messages", 0)) + 1
            contact["last_noise_reason"] = noise
            log(f"ignore machine-noise seq={seq} fp={peer_fp} reason={noise}")
            continue

        contact["last_topic"] = topic(text)
        contact["stage"] = "mail_candidate"
        used = int(replies.get(peer_fp, 0) or 0)
        log(
            f"mail seq={seq} fp={peer_fp} topic={contact['last_topic']} "
            f"text={text[:240]!r}"
        )

        if used >= args.max_replies:
            log(f"hold fp={peer_fp}: daily contact limit")
            continue
        last = int(contact.get("last_reply_ts", 0) or 0)
        if last and time.time() - last < args.cooldown:
            log(f"hold fp={peer_fp}: cooldown")
            continue

        if send(peer_fp, reply(text), args.dry_run):
            replies[peer_fp] = used + 1
            contact["messages_out"] = int(contact.get("messages_out", 0)) + 1
            contact["last_reply_ts"] = int(time.time())
            contact["stage"] = "mail_replied"

    if maxseq > since and not args.dry_run:
        setcursor(maxseq)
        log(f"cursor {since}->{maxseq}")
    save(state)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("LOVE8_MAIL_INTERVAL", "180")),
    )
    parser.add_argument(
        "--max-replies",
        type=int,
        default=int(os.getenv("LOVE8_MAIL_MAX_REPLIES", "4")),
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=int(os.getenv("LOVE8_MAIL_COOLDOWN", "1200")),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.interval = min(max(args.interval, 60), 3600)
    args.max_replies = min(max(args.max_replies, 1), 8)
    args.cooldown = min(max(args.cooldown, 300), 86400)

    if args.once:
        run_once(args)
        return 0

    log(f"Love8 Mailbot v{VERSION} started interval={args.interval}s")
    while True:
        try:
            run_once(args)
        except Exception as exc:
            log(f"ERROR cycle: {type(exc).__name__}: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
