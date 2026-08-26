#!/usr/bin/env python3
"""Love8 v2.4.1 /r/events rendezvous scout.

Read-only. Tracks newly-created public rooms from the server-owned events room so
Love8 can notice useful conversations before they rise into /rooms activity.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "2.4.1"
ROOT = Path("/opt/love8-agent")
SOCIAL_CONFIG = ROOT / "social/config.env"
STATE = ROOT / "state/event-scout-v241.json"
ROOM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
CREATED_RE = re.compile(r"^created\s+([a-z0-9][a-z0-9_-]{0,47})$", re.I)


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for raw in SOCIAL_CONFIG.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("\"'")
    except Exception:
        pass
    return out


def load_state() -> dict[str, Any]:
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(d: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.parent.chmod(0o700)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, STATE)


def fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": f"love8-event-scout/{VERSION}"})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d if isinstance(d, dict) else {}


def run() -> int:
    config = load_env()
    base = config.get("BASE", "https://technocore.chat").rstrip("/")
    st = load_state()
    cursor = int(st.get("cursor", 0) or 0)
    data = fetch_json(f"{base}/r/events?since={cursor}&limit=200&format=json")
    messages = [m for m in data.get("messages", []) if isinstance(m, dict)]
    rooms = st.get("rooms", []) if isinstance(st.get("rooms"), list) else []
    known = {(int(x.get("event_seq", 0) or 0), str(x.get("room", ""))) for x in rooms if isinstance(x, dict)}
    added = 0
    max_seq = cursor
    for m in messages:
        seq = int(m.get("seq", 0) or 0)
        max_seq = max(max_seq, seq)
        text = str(m.get("text", "") or "").strip()
        match = CREATED_RE.match(text)
        if not match:
            continue
        room = match.group(1).lower()
        if not ROOM_RE.fullmatch(room):
            continue
        key = (seq, room)
        if key in known:
            continue
        rooms.append({"event_seq": seq, "room": room, "seen_at": int(time.time())})
        known.add(key)
        added += 1
    rooms = sorted((x for x in rooms if isinstance(x, dict)), key=lambda x: int(x.get("event_seq", 0) or 0))[-500:]
    st.update({"version": VERSION, "cursor": max_seq, "rooms": rooms, "last_run_at": int(time.time()), "last_added": added})
    save_state(st)
    print(f"event_scout cursor={max_seq} added={added} retained={len(rooms)}")
    return 0


def status() -> int:
    st = load_state()
    rooms = st.get("rooms", []) if isinstance(st.get("rooms"), list) else []
    print("===== LOVE8 EVENT SCOUT v2.4.1 =====")
    print("cursor:", st.get("cursor", 0))
    print("last_run_at:", st.get("last_run_at", "-"))
    print("retained_rooms:", len(rooms))
    for x in rooms[-20:]:
        if isinstance(x, dict):
            print(f"seq={x.get('event_seq')} room={x.get('room')} seen_at={x.get('seen_at')}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    a = p.parse_args()
    if a.status:
        return status()
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
