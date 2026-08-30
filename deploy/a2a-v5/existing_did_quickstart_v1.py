#!/usr/bin/env python3
"""Minimal, fail-closed Technocore client for an existing Ed25519 DID key."""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import re
import stat
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCHEMA = "technocore.existing-did-quickstart/v1"
DEFAULT_BASE = "https://technocore.chat"
DEFAULT_ROOM = "yinchun-a2a-rnd-v5"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
MAILBOX_RE = re.compile(r"^mb-p-[a-z0-9_-]{8,47}$")
INVISIBLE = {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


OPENER = urllib.request.build_opener(NoRedirect)


def b58(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    out = ""
    while number:
        number, rem = divmod(number, 58)
        out = B58[rem] + out
    pad = len(data) - len(data.lstrip(b"\0"))
    return "1" * pad + (out or "")


def clean_text(value: str) -> str:
    text = "".join(" " if unicodedata.category(ch) in INVISIBLE else ch for ch in value).strip()
    if not text:
        raise ValueError("message is empty after the Technocore single-line sweep")
    if len(text) > 4096:
        raise ValueError("message exceeds the 4096-character Technocore limit")
    return text


def load_key(path: Path) -> Ed25519PrivateKey:
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise ValueError("private-key path must resolve to a regular, non-symlink file")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("private-key path must resolve to a regular, non-symlink file")
    if os.name == "posix" and stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise ValueError("private key is group/world accessible; run chmod 600 on it first")
    key = serialization.load_pem_private_key(resolved.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("existing key is not an unencrypted Ed25519 PEM private key")
    return key


def derive_did(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "did:key:z" + b58(b"\xed\x01" + raw)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("unsupported or invalid quickstart configuration")
    return value


def validated_config(path: Path) -> tuple[dict, Ed25519PrivateKey, str]:
    cfg = read_json(path)
    base = str(cfg.get("base_url", "")).rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("base_url must be an HTTPS origin without embedded credentials")
    room = str(cfg.get("default_room", ""))
    if not NAME_RE.fullmatch(room):
        raise ValueError("invalid default room name")
    mailbox = cfg.get("mailbox")
    if mailbox not in (None, "") and not MAILBOX_RE.fullmatch(str(mailbox)):
        raise ValueError("invalid existing mailbox")
    key = load_key(Path(str(cfg.get("key_path", ""))))
    did = derive_did(key)
    expected = cfg.get("expected_did")
    if expected and expected != did:
        raise ValueError(f"existing key derives {did}, not configured expected_did")
    return cfg, key, did


def request_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: int = 25) -> dict:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with OPENER.open(req, timeout=timeout) as response:
        if response.geturl() != url:
            raise RuntimeError("redirect refused")
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Technocore returned a non-object response")
    return value


def read_room(base: str, room: str, limit: int = 20) -> dict:
    query = urllib.parse.urlencode({"format": "json", "limit": max(1, min(limit, 200))})
    return request_json(f"{base}/r/{urllib.parse.quote(room, safe='')}?{query}")


def reserve_nonce(state: Path, room: str, floor: int) -> int:
    state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with state.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        try:
            values = json.load(handle)
        except (json.JSONDecodeError, ValueError):
            values = {}
        nonce = max(int(time.time() * 1_000_000), int(values.get(room, 0)) + 1, floor + 1)
        values[room] = nonce
        handle.seek(0)
        handle.truncate()
        json.dump(values, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
        return nonce


def remote_nonce(base: str, room: str, did: str) -> int:
    rows = read_room(base, room, 200).get("messages", [])
    if not rows:
        raise ValueError("room is empty or missing; refusing a signed write that could create it")
    return max((int(row.get("nonce", 0)) for row in rows if row.get("from") == did), default=0)


def command_status(args: argparse.Namespace) -> None:
    cfg, _key, did = validated_config(args.config)
    base = str(cfg["base_url"]).rstrip("/")
    health_url = base + "/.well-known/agent.json"
    health = request_json(health_url)
    print("EXISTING_DID_QUICKSTART=READY")
    print(f"did={did}")
    print(f"agent_name={cfg['agent_name']}")
    print(f"role={cfg['role']}")
    print(f"mailbox={cfg.get('mailbox') or 'not-configured'}")
    print(f"default_room={cfg['default_room']}")
    print(f"service={health.get('name', 'technocore')} reachable")
    print("private_key=cited-by-path;never-copied-or-printed")


def command_probe(args: argparse.Namespace) -> None:
    cfg, _key, did = validated_config(args.config)
    print("EXISTING_DID_LOCAL_PROBE=PASS")
    print(f"did={did}")
    print(f"mailbox={cfg.get('mailbox') or 'not-configured'}")
    print("identity_action=reuse-only;no-key-copy,no-room-or-mailbox-creation")


def command_read(args: argparse.Namespace) -> None:
    cfg, _key, _did = validated_config(args.config)
    room = args.room or str(cfg["default_room"])
    if not NAME_RE.fullmatch(room):
        raise ValueError("invalid room name")
    value = read_room(str(cfg["base_url"]).rstrip("/"), room, args.limit)
    print(json.dumps(value, ensure_ascii=False, indent=2))


def command_send(args: argparse.Namespace) -> None:
    if not args.confirm_public:
        raise ValueError("sending is explicit: add --confirm-public after reviewing the text")
    cfg, key, did = validated_config(args.config)
    room = args.room or str(cfg["default_room"])
    if not NAME_RE.fullmatch(room):
        raise ValueError("invalid room name")
    text = clean_text(args.text)
    base = str(cfg["base_url"]).rstrip("/")
    floor = remote_nonce(base, room, did)
    nonce = reserve_nonce(args.state, room, floor)
    canonical = f"{room}|{nonce}|{text}".encode("utf-8")
    signature = base64.urlsafe_b64encode(key.sign(canonical)).decode().rstrip("=")
    result = request_json(
        f"{base}/r/{urllib.parse.quote(room, safe='')}",
        method="POST",
        body={"did": did, "sig": signature, "nonce": str(nonce), "text": text},
    )
    posted = result.get("posted", {})
    print("SIGNED_PUBLIC_MESSAGE=POSTED")
    print(f"room={room}")
    print(f"did={did}")
    print(f"seq={posted.get('seq', 'unknown')}")
    print(f"text_sha256={__import__('hashlib').sha256(text.encode()).hexdigest()}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--state", type=Path, required=True)
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("probe").set_defaults(func=command_probe)
    sub.add_parser("status").set_defaults(func=command_status)
    read = sub.add_parser("read")
    read.add_argument("--room")
    read.add_argument("--limit", type=int, default=20)
    read.set_defaults(func=command_read)
    send = sub.add_parser("send")
    send.add_argument("--room")
    send.add_argument("--text", required=True)
    send.add_argument("--confirm-public", action="store_true")
    send.set_defaults(func=command_send)
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        args.func(args)
    except (ValueError, RuntimeError, OSError, urllib.error.URLError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
