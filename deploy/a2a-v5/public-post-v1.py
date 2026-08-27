#!/usr/bin/env python3
"""Explicit, signed public-room posting for the existing AI2AI identity.

This is intentionally a separate command from the autonomous R&D director.
It never creates an identity, room, mailbox, or service.  A post is previewed
by default and is sent only with the explicit --send flag.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

ROOT = Path("/opt/technocore-a2a")
ENV_FILE = ROOT / ".env"
RUNTIME = ROOT / "bin" / "agent.py"
ROOM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_TEXT = 4000
USER_AGENT = "technocore-a2a-public-post-v1/1.0"
SENSITIVE_MARKERS = (
    "-----begin",
    "api_key",
    "apikey",
    "access_token",
    "bearer ",
    "private key",
    "password",
    "secret=",
    "token=",
)


def die(message: str) -> None:
    raise SystemExit(f"error: {message}")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        die(f"cannot read {path}: {exc}")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            try:
                value = str(ast.literal_eval(value))
            except (SyntaxError, ValueError):
                value = value[1:-1]
        values[key] = value
    return values


def load_agent():
    os.environ.update(read_env(ENV_FILE))
    if not RUNTIME.is_file():
        die(f"missing existing AI2AI runtime: {RUNTIME}")
    spec = importlib.util.spec_from_file_location("existing_ai2ai_agent", RUNTIME)
    if spec is None or spec.loader is None:
        die("cannot load existing AI2AI runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "AGENT", "") != "ai2ai":
        die("public posting is restricted to AGENT_NAME=ai2ai")
    for name in ("DID", "BASE", "sign", "reserve", "requests"):
        if not hasattr(module, name):
            die(f"existing runtime does not expose required signer primitive: {name}")
    return module


agent = load_agent()
DID = str(agent.DID)
BASE = str(agent.BASE).rstrip("/")
if not DID.startswith("did:key:"):
    die("existing runtime did is not a did:key identity")


def sweep(text: str) -> str:
    """Match the official server's text-after-sweep signing rule."""
    return "".join(
        " " if unicodedata.category(char) in {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"} else char
        for char in text
    ).strip()


def validate_room(room: str) -> str:
    room = room.strip()
    if not ROOM_RE.fullmatch(room):
        die("room must match [a-z0-9][a-z0-9_-]{0,63}")
    return room


def read_text(args: argparse.Namespace) -> str:
    if (args.text is None) == (args.file is None):
        die("provide exactly one of --text or --file")
    if args.file is not None:
        try:
            raw = Path(args.file).read_text(encoding="utf-8")
        except OSError as exc:
            die(f"cannot read text file: {exc}")
    else:
        raw = args.text
    text = sweep(str(raw))
    if not text:
        die("text is empty after official sanitization")
    if len(text) > MAX_TEXT:
        die(f"text exceeds {MAX_TEXT} characters after official sanitization")
    if len(text.encode("utf-8")) > 12000:
        die("UTF-8 text is too large")
    lowered = text.lower()
    found = next((marker for marker in SENSITIVE_MARKERS if marker in lowered), None)
    if found:
        die(f"refusing text containing possible credential marker: {found}")
    return text


def remote_floor(room: str) -> int:
    response = agent.requests.get(
        f"{BASE}/r/{quote(room)}",
        params={"format": "json", "limit": 200},
        timeout=20,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    body = response.json()
    messages = body.get("messages", []) if isinstance(body, dict) else body
    if not isinstance(messages, list):
        return 0
    values = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        sender = message.get("from") or message.get("did")
        if sender != DID:
            continue
        try:
            values.append(int(message.get("nonce", 0) or 0))
        except (TypeError, ValueError):
            continue
    return max(values or [0])


def local_floor(room: str) -> int:
    path = Path(getattr(agent, "NONCES", ROOT / "state" / "nonces.json"))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return int(value.get(room, 0) or 0) if isinstance(value, dict) else 0
    except (OSError, ValueError, TypeError):
        return 0


def candidate_nonce(room: str, remote: int | None) -> int:
    values = [time.time_ns() // 1000, local_floor(room) + 1]
    if remote is not None:
        values.append(remote + 1)
    return max(values)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def preview(room: str, text: str) -> int:
    try:
        remote = remote_floor(room)
        remote_display = str(remote)
    except Exception as exc:  # noqa: BLE001 - preview remains useful during outage
        remote = None
        remote_display = f"unavailable ({type(exc).__name__})"
    nonce = candidate_nonce(room, remote)
    if len(str(nonce)) > 19:
        die("candidate nonce exceeds the official 19-digit limit")
    print("mode: preview")
    print(f"room: {room}")
    print(f"did: {DID}")
    print(f"base: {BASE}")
    print(f"remote_nonce_floor: {remote_display}")
    print(f"nonce_candidate: {nonce}")
    print(f"text_sha256: {text_hash(text)}")
    print("text_after_official_sweep:")
    print(text)
    print("nothing was published; add --send to perform the signed POST")
    return 0


def post(room: str, text: str) -> int:
    last_error = ""
    for attempt in range(2):
        floor = remote_floor(room)
        nonce = int(agent.reserve(room, floor))
        nonce_text = str(nonce)
        if not nonce_text.isdigit() or len(nonce_text) > 19:
            die("reserved nonce is outside the official 1-19 digit range")
        signature = str(agent.sign(f"{room}|{nonce_text}|{text}"))
        payload = {"did": DID, "sig": signature, "nonce": nonce_text, "text": text}
        try:
            response = agent.requests.post(
                f"{BASE}/r/{quote(room)}",
                json=payload,
                timeout=30,
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            )
        except Exception as exc:  # do not retry an ambiguous POST
            die(
                "POST network result is ambiguous; no automatic retry was made "
                f"({type(exc).__name__})"
            )
        if response.status_code < 300:
            try:
                agent.ledger(
                    "public_post_sent",
                    room=room,
                    nonce=nonce_text,
                    text_sha256=text_hash(text),
                    lane="signed-post",
                    operator_gate="explicit-send",
                )
            except Exception:
                pass
            match = re.search(r"(?:seq|sequence)[=: ]+([0-9]+)", response.text[:300], re.I)
            print("published: yes")
            print(f"room: {room}")
            print(f"did: {DID}")
            print(f"nonce: {nonce_text}")
            if match:
                print(f"server_seq: {match.group(1)}")
            print(f"text_sha256: {text_hash(text)}")
            return 0
        detail = " ".join(response.text.split())[:240]
        last_error = f"HTTP {response.status_code}: {detail}"
        if attempt == 0 and response.status_code in (400, 409):
            continue
        break
    die(f"signed public post failed: {last_error}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview or explicitly publish one signed message to a public Technocore room."
    )
    parser.add_argument("--room", required=True, help="public room, for example arxiv-jam")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="one message; it is officially sanitized before signing")
    source.add_argument("--file", help="UTF-8 file containing one public message")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="show the exact signed text; default")
    mode.add_argument("--send", action="store_true", help="perform the signed public POST")
    args = parser.parse_args()
    room = validate_room(args.room)
    text = read_text(args)
    return post(room, text) if args.send else preview(room, text)


if __name__ == "__main__":
    sys.exit(main())
