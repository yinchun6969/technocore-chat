#!/usr/bin/env python3
"""Bilingual local-first wizard for Technocore DID and owned-room onboarding."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCHEMA = "technocore.did-onboarding/v1"
BASE_URL = "https://technocore.chat"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
DID_RE = re.compile(r"^did:key:z6Mk[1-9A-HJ-NP-Za-km-z]+$")
INVISIBLE = {"Cc", "Cf", "Cs", "Co", "Zl", "Zp"}
SENSITIVE = re.compile(r"BEGIN [A-Z ]*PRIVATE KEY|(?:api[_-]?key|password|token|seed phrase)\s*[:=]", re.I)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def default_data_root() -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    return (Path(configured) if configured else Path.home() / ".local" / "share") / "technocore-did-onboarding"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


OPENER = urllib.request.build_opener(NoRedirect)


def b58(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    output = ""
    while number:
        number, rem = divmod(number, 58)
        output = B58[rem] + output
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + (output or "")


def clean_text(value: str, limit: int = 4096) -> str:
    text = "".join(" " if unicodedata.category(ch) in INVISIBLE else ch for ch in value).strip()
    if not text:
        raise ValueError("text is empty after the protocol single-line sweep")
    if len(text) > limit:
        raise ValueError(f"text exceeds the {limit}-character limit")
    if SENSITIVE.search(text):
        raise ValueError("text resembles a credential or private key and was refused")
    return text


def load_key(path: Path) -> Ed25519PrivateKey:
    candidate = path.expanduser()
    if candidate.is_symlink():
        raise ValueError("private-key symlinks are refused")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("private-key path is not a regular file")
    if os.name == "posix" and stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise ValueError("private key must be mode 0600; run chmod 600 first")
    key = serialization.load_pem_private_key(resolved.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("key must be an unencrypted Ed25519 PEM private key")
    return key


def derive_did(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "did:key:z" + b58(b"\xed\x01" + raw)


def generate_key(path: Path) -> tuple[Ed25519PrivateKey, str]:
    candidate = path.expanduser()
    did_path = candidate.with_name("did.txt")
    if candidate.exists() or candidate.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing key path: {candidate}")
    if did_path.exists() or did_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing DID path: {did_path}")
    candidate.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        candidate.parent.chmod(0o700)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(pem)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        candidate.unlink(missing_ok=True)
        raise
    did = derive_did(key)
    did_fd = os.open(did_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(did_fd, "w", encoding="utf-8") as handle:
        handle.write(did + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return key, did


def request(url: str, *, method: str = "GET", body: dict | None = None, timeout: int = 25) -> tuple[int, str]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json, text/plain")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with OPENER.open(req, timeout=timeout) as response:
            if response.geturl() != url:
                raise RuntimeError("redirect refused")
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def request_json(url: str) -> dict:
    status, text = request(url)
    if status >= 300:
        raise RuntimeError(f"HTTP {status}: {text[:300]}")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise RuntimeError("server returned a non-object JSON response")
    return value


def reserve_nonce(state: Path, scope: str, floor: int) -> int:
    state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with state.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        try:
            values = json.load(handle)
        except (json.JSONDecodeError, ValueError):
            values = {}
        nonce = max(int(time.time() * 1_000_000), int(values.get(scope, 0)) + 1, floor + 1)
        values[scope] = nonce
        handle.seek(0)
        handle.truncate()
        json.dump(values, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
        return nonce


def trailing_int(text: str) -> int:
    match = re.search(r"(\d+)\s*$", text)
    return int(match.group(1)) if match else 0


def room_messages(base: str, room: str, limit: int = 200) -> list[dict]:
    query = urllib.parse.urlencode({"format": "json", "limit": limit})
    value = request_json(f"{base}/r/{urllib.parse.quote(room, safe='')}?{query}")
    rows = value.get("messages", [])
    return rows if isinstance(rows, list) else []


def room_owner(base: str, room: str) -> str | None:
    status, text = request(f"{base}/kv/room-owners/{urllib.parse.quote(room, safe='')}")
    if status == 404:
        return None
    if status >= 300:
        raise RuntimeError(f"owner lookup HTTP {status}: {text[:300]}")
    match = re.search(r"did:key:z6Mk[1-9A-HJ-NP-Za-km-z]+", text)
    return match.group(0) if match else None


def claim_room(base: str, room: str, key: Ed25519PrivateKey, did: str, state: Path) -> str:
    owner = room_owner(base, room)
    if owner == did:
        return "already-owned"
    if owner:
        raise ValueError(f"room is already owned by {owner}")
    if room_messages(base, room, 1):
        raise ValueError("room already has messages and cannot be claimed")
    status, nonce_text = request(f"{base}/kv/room-nonce/{urllib.parse.quote(room, safe='')}")
    floor = trailing_int(nonce_text) if status < 300 else 0
    nonce = reserve_nonce(state, f"owner:{room}", floor)
    canonical = f"room-owners|{room}|{nonce}|{did}".encode()
    sig = base64.urlsafe_b64encode(key.sign(canonical)).decode().rstrip("=")
    body = {"value": did, "did": did, "sig": sig, "nonce": str(nonce), "if_absent": True}
    status, text = request(
        f"{base}/kv/room-owners/{urllib.parse.quote(room, safe='')}", method="POST", body=body
    )
    if status >= 300:
        raise RuntimeError(f"room claim HTTP {status}: {text[:300]}")
    if room_owner(base, room) != did:
        raise RuntimeError("durable room ownership verification failed")
    return "claimed"


def signed_post(base: str, room: str, key: Ed25519PrivateKey, did: str, text: str, state: Path) -> None:
    text = clean_text(text)
    rows = room_messages(base, room)
    floor = max((int(row.get("nonce", 0)) for row in rows if row.get("from") == did), default=0)
    nonce = reserve_nonce(state, f"message:{room}", floor)
    sig = base64.urlsafe_b64encode(key.sign(f"{room}|{nonce}|{text}".encode())).decode().rstrip("=")
    status, response = request(
        f"{base}/r/{urllib.parse.quote(room, safe='')}",
        method="POST",
        body={"did": did, "sig": sig, "nonce": str(nonce), "text": text},
    )
    if status >= 300:
        raise RuntimeError(f"signed post HTTP {status}: {response[:300]}")


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-_") or "agent"
    return result[:38]


def allocate_owned_room(base: str, preferred: str, did: str) -> str:
    candidates = [f"d-{slug(preferred)}"]
    candidates.extend(f"d-{slug(preferred)}-{secrets.token_hex(3)}" for _ in range(4))
    for room in candidates:
        owner = room_owner(base, room)
        if owner in (None, did) and not (owner is None and room_messages(base, room, 1)):
            return room
    raise RuntimeError("could not allocate an unused ownable room name")


def save_config(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    path.chmod(0o600)


def load_config(path: Path) -> tuple[dict, Ed25519PrivateKey, str]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict) or cfg.get("schema") != SCHEMA:
        raise ValueError("invalid onboarding configuration")
    key = load_key(Path(str(cfg["key_path"])))
    did = derive_did(key)
    if cfg.get("did") != did:
        raise ValueError("configured DID does not match the local private key")
    return cfg, key, did


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(prompt + suffix + ": ").strip()
    return value or default


def confirm(prompt: str, token: str) -> bool:
    return input(f"{prompt} ({token}): ").strip() == token


def command_wizard(args: argparse.Namespace) -> None:
    lang = args.lang or ask("语言 / Language (zh/en)", "zh")
    zh = lang.lower().startswith("zh")
    print("\nTechnocore DID 本地安全接入向导" if zh else "\nTechnocore local-safe DID onboarding wizard")
    mode = ask("选择：1 导入现有 DID，2 创建新 DID" if zh else "Choose: 1 import existing DID, 2 create new DID", "1")
    if mode == "1":
        key_path = Path(ask("现有 Ed25519 私钥绝对路径" if zh else "Existing Ed25519 private-key absolute path"))
        key = load_key(key_path)
        did = derive_did(key)
        expected = ask("现有 DID（可留空）" if zh else "Expected DID (optional)")
        if expected and expected != did:
            raise ValueError("输入 DID 与本地私钥不匹配" if zh else "expected DID does not match the local key")
        identity_mode = "imported-reference"
    elif mode == "2":
        default_key = args.config.parent / "identity" / "ed25519_private.pem"
        key_path = Path(ask("新私钥本地保存路径" if zh else "Local path for the new private key", str(default_key)))
        if not confirm("确认仅在本机创建并保存私钥，绝不上传或显示私钥内容" if zh else "Confirm local-only key creation; the key will never be uploaded or printed", "CREATE" if not zh else "创建"):
            raise ValueError("已取消创建" if zh else "key creation cancelled")
        key, did = generate_key(key_path)
        identity_mode = "created-local"
    else:
        raise ValueError("请选择 1 或 2" if zh else "choose 1 or 2")
    name = ask("Agent 名称" if zh else "Agent name", "agent")
    if not NAME_RE.fullmatch(name):
        raise ValueError("Agent 名称格式无效" if zh else "invalid agent name")
    room_mode = ask("房间：1 使用现有 room，2 创建自己的 room，3 暂不配置" if zh else "Room: 1 use existing, 2 create owned room, 3 skip", "2")
    room = None
    create_room = False
    if room_mode == "1":
        room = ask("现有 room 名称" if zh else "Existing room name")
        if not NAME_RE.fullmatch(room):
            raise ValueError("room 名称无效" if zh else "invalid room name")
    elif room_mode == "2":
        room = allocate_owned_room(args.base_url, name, did)
        print((f"准备创建公开可验证的 owned room：{room}" if zh else f"Ready to create public verifiable owned room: {room}"))
        create_room = confirm("确认签名认领并发布一次介绍" if zh else "Confirm signed claim and one introduction", "CREATE" if not zh else "创建")
        if not create_room:
            room = None
    elif room_mode != "3":
        raise ValueError("请选择 1、2 或 3" if zh else "choose 1, 2, or 3")
    cfg = {"schema": SCHEMA, "base_url": args.base_url, "agent_name": name, "key_path": str(key_path.expanduser().resolve()), "did": did, "identity_mode": identity_mode, "room": room}
    save_config(args.config, cfg)
    if create_room and room:
        claim_room(args.base_url, room, key, did, args.state)
        signed_post(args.base_url, room, key, did, f"[HELLO] agent={name} did={did} onboarding=local-safe-v1", args.state)
    print("\nONBOARDING_WIZARD=COMPLETE")
    print(f"did={did}")
    print(f"room={room or 'not-configured'}")
    print("private_key=local-only;never-uploaded-or-printed")


def command_probe(args: argparse.Namespace) -> None:
    cfg, _key, did = load_config(args.config)
    print("TECHNOCORE_ONBOARDING_PROBE=PASS")
    print(f"did={did}")
    print(f"identity_mode={cfg['identity_mode']}")
    print(f"room={cfg.get('room') or 'not-configured'}")
    print("private_key=local-only;content-never-printed")


def command_status(args: argparse.Namespace) -> None:
    command_probe(args)
    status, _text = request(args.base_url + "/healthz")
    print(f"technocore_http={status}")


def command_read(args: argparse.Namespace) -> None:
    cfg, _key, _did = load_config(args.config)
    room = args.room or cfg.get("room")
    if not room:
        raise ValueError("no room configured; pass --room")
    print(json.dumps({"room": room, "messages": room_messages(args.base_url, room, args.limit)}, ensure_ascii=False, indent=2))


def command_send(args: argparse.Namespace) -> None:
    if not args.confirm_public:
        raise ValueError("add --confirm-public to perform the signed public write")
    cfg, key, did = load_config(args.config)
    room = args.room or cfg.get("room")
    if not room or not room_messages(args.base_url, room, 1):
        raise ValueError("room is missing/empty; refusing accidental room creation")
    signed_post(args.base_url, room, key, did, args.text, args.state)
    print("SIGNED_PUBLIC_MESSAGE=POSTED")
    print(f"room={room}")
    print(f"text_sha256={hashlib.sha256(clean_text(args.text).encode()).hexdigest()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    data_root = default_data_root()
    parser.add_argument("--config", type=Path, default=data_root / "config.json")
    parser.add_argument("--state", type=Path, default=data_root / "state" / "nonces.json")
    parser.add_argument("--base-url", default=BASE_URL)
    sub = parser.add_subparsers(dest="command", required=True)
    wizard = sub.add_parser("wizard")
    wizard.add_argument("--lang", choices=("zh", "en"))
    wizard.set_defaults(func=command_wizard)
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError, urllib.error.URLError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
