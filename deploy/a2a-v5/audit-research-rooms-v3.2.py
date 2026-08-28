#!/usr/bin/env python3
"""Read-only Social/room/participant audit. No runtime import or public writes."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

ROOM = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
DID = re.compile(r"did:key:z[1-9A-HJ-NP-Za-km-z]{40,60}")


def read_json(path):
    try:
        if path.stat().st_size > 40_000_000:
            return {}
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def config(path):
    allowed = {"AGENT_NAME", "ROLE", "NICK", "TC_HOME_ROOM", "TC_HUB_ENABLED", "PERSIST_ROOM_CREATE_ENABLED", "PERSIST_ROOMS_PER_DAY", "OWNED_ROOM"}
    result = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in allowed:
                result[key] = value.strip("\"' ")[:100]
    except OSError:
        pass
    return result


def code_info(path):
    if not path.is_file():
        return {"path": str(path), "present": False}
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
        funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    except SyntaxError:
        return {"path": str(path), "present": True, "syntax": "invalid"}
    version = re.search(r"(?m)^VERSION\s*=\s*['\"]([^'\"]+)", source)
    return {"path": str(path), "present": True, "version": version.group(1) if version else "unknown",
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
            "read_hooks": sorted(funcs & {"inspect", "candidate_rooms", "read_room", "_hub_rooms", "_ensure_home_room", "room_cycle", "identity_room_cycle"}),
            "invite_hooks": sorted(f for f in funcs if "invite" in f.lower())[:15],
            "identity_priority_scan": "identity-room-scan" in source}


def screen(state, topic, now=None):
    """Shortlist with evidence, never an authorization or human/bot claim."""
    now = time.time() if now is None else now
    tokens = {x.lower() for x in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,5}", topic)}
    candidates = []
    contacts = state.get("contacts", {})
    records = contacts.values() if isinstance(contacts, dict) else contacts if isinstance(contacts, list) else []
    for c in records:
        if not isinstance(c, dict):
            continue
        did = str(c.get("author", ""))
        stage = str(c.get("relationship_stage") or c.get("stage") or "unknown")
        last_room = str(c.get("last_room", ""))
        if not DID.fullmatch(did) or not ROOM.fullmatch(last_room) or last_room.startswith(("mb-", "p-", "d-", "e-")):
            continue
        if stage not in {"trusted_peer", "collaborator", "recurring_contact", "replied", "established"}:
            continue
        try:
            seen = float(c.get("last_seen", 0) or 0)
            risk = float(c.get("risk_score", c.get("scam_risk", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if not 0 <= now - seen <= 30 * 86400 or risk > 25 or c.get("probable_bot_cluster"):
            continue
        content = str(c.get("last_text", "")).lower()
        matches = sorted(t for t in tokens if t in content)
        if not matches:
            continue
        # Scores from different Social versions are not comparable. Do not
        # invent a combined number or call a did:key prefix signature proof.
        candidates.append({"did": did, "last_room": last_room, "relationship": stage,
                           "last_seen": seen, "topic_matches": matches[:6],
                           "verification": "local record only; verify signed conversation and confirm recipient before inviting"})
    candidates.sort(key=lambda c: (len(c["topic_matches"]), c["last_seen"]), reverse=True)
    return candidates[:5]


def unit_state(unit):
    try:
        r = subprocess.run(["systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "User", "-p", "Group"],
                           capture_output=True, text=True, timeout=5, check=False)
        return r.stdout.strip() if r.returncode == 0 else "unavailable (may be no-systemd host)"
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable (may be no-systemd host)"


def public_room(room):
    if not ROOM.fullmatch(room):
        return {"room": room, "status": "invalid room name"}
    url = "https://technocore.chat/r/" + room + "?format=json&limit=10"
    # GET only. Empty JSON is not evidence of room ownership/creation.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "tc-room-audit/3.2"}), timeout=12) as response:
            data = json.loads(response.read(100_000).decode())
        messages = data.get("messages", [])
        return {"room": room, "url": "https://technocore.chat/r/" + room,
                "readable": True, "messages_returned": len(messages), "last_seq": data.get("last_seq"),
                "ownership": "not established by this check"}
    except Exception as exc:
        return {"room": room, "readable": False, "error_type": type(exc).__name__}


def audit(root=Path("/"), topic="Technocore protocol bug reproducible reliability", remote=False):
    def p(value):
        return root / value.lstrip("/")
    result = {"mode": "read-only; no posts, invites, runtime imports or state changes", "nodes": []}
    nodes = [
        ("love8", ["/opt/love8-agent/social/love8_social.py", "/opt/love8-agent/social/love8_persistent.py"],
         ["/opt/love8-agent/social/config.env", "/opt/love8-agent/social/persistent.env"],
         "/opt/love8-agent/state/social-v2.json", "/opt/love8-agent/state/identity-room-v250.json", "technocore-collab.service"),
        ("aizong", ["/opt/technocore-agent/aizong_social.py"],
         ["/opt/technocore-agent/config", "/opt/technocore-agent/brain.env"],
         "/opt/technocore-agent/state/social-v1.json", "", "technocore-aizong-social.service"),
    ]
    for name, scripts, configs, state_path, identity_path, service in nodes:
        if not any(p(s).is_file() for s in scripts):
            continue
        cfg = {}
        for f in configs:
            cfg.update(config(p(f)))
        state = read_json(p(state_path))
        identity = read_json(p(identity_path)) if identity_path else {}
        hub = state.get("home_hub", {})
        if not isinstance(hub, dict):
            hub = {}
        room = identity.get("room") or hub.get("room") or cfg.get("TC_HOME_ROOM") or ""
        # Show defaults as inferred, not as a claim that a room exists.
        inferred = "ai2ai" if name == "aizong" and any(code_info(p(s)).get("version") == "1.5.0" for s in scripts) else cfg.get("NICK", "")
        row = {"node": name, "code": [code_info(p(s)) for s in scripts], "safe_config": cfg,
               "resolved_room": room, "code_default_hint": inferred, "identity_state_present": bool(identity),
               "hub_bootstrapped": bool(hub.get("bootstrapped")), "service": unit_state(service) if root == Path("/") else "fixture",
               "candidates_for_review": screen(state, topic), "listener_runtime": "not proven by source hooks; compare last-seen sequence/logs"}
        if remote and room:
            row["public_room"] = public_room(room)
        result["nodes"].append(row)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="Technocore protocol bug reproducible reliability")
    parser.add_argument("--read-public-room", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit(topic=args.topic, remote=args.read_public_room), ensure_ascii=False, indent=2))
