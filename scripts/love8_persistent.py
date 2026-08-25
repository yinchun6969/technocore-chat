#!/usr/bin/env python3
"""Love8 Persistent Agent v2.4.0.

Builds durable relationship state, topic momentum, contribution scoring,
conditional social-circle rooms, and a DID-signed local provenance ledger on
top of Love8 Social/Brain. It never executes instructions received from chat.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "2.4.0"
ROOT = Path("/opt/love8-agent")
SOCIAL_DIR = ROOT / "social"
STATE_DIR = ROOT / "state"
GUARD_PATH = SOCIAL_DIR / "love8_social.py"
SOCIAL_CONFIG = SOCIAL_DIR / "config.env"
BRAIN_CONFIG = SOCIAL_DIR / "brain.env"
PERSIST_CONFIG = SOCIAL_DIR / "persistent.env"
SOCIAL_STATE = STATE_DIR / "social-v2.json"
BRAIN_STATE = STATE_DIR / "brain-v22.json"
PERSIST_STATE = STATE_DIR / "persistent-v24.json"
LEDGER_DIR = ROOT / "provenance"
LOG_PATH = Path("/var/log/love8-persistent-v24.log")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        try:
            token = shlex.split(line, posix=True)[0]
            key, value = token.split("=", 1)
            out[key] = value
        except Exception:
            continue
    return out


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def save_json(path: Path, data: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(mode)
    os.replace(tmp, path)


def load_guard():
    spec = importlib.util.spec_from_file_location("love8_guard_v24", GUARD_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Love8 guard")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(min(max(round(value), lo), hi))


def relationship_score(contact: dict[str, Any]) -> int:
    brain = contact.get("brain", {}) if isinstance(contact.get("brain"), dict) else {}
    verified = 1 if contact.get("verified") else 0
    natural = min(int(contact.get("natural_messages", 0) or 0), 12)
    out = min(int(contact.get("messages_out", 0) or 0), 6)
    replies = min(int(contact.get("replies_to_love8", 0) or 0), 6)
    quality = int(brain.get("conversation_quality", 0) or 0)
    trust = int(brain.get("trust_score", 50) or 50)
    bot = int(brain.get("bot_probability", 50) or 50)
    risk = int(brain.get("scam_risk", 0) or 0)

    score = (
        verified * 12
        + natural * 1.8
        + out * 4.5
        + replies * 8.0
        + quality * 0.22
        + trust * 0.18
        - bot * 0.22
        - risk * 0.38
    )
    if contact.get("human_self_declared"):
        score += 3  # self-declaration is only a weak signal, never verification
    if contact.get("probable_bot_cluster") or contact.get("brain_probable_bot"):
        score -= 25
    if contact.get("suspected_scam"):
        score -= 45
    return clamp(score)


def relationship_stage(contact: dict[str, Any], score: int) -> str:
    brain = contact.get("brain", {}) if isinstance(contact.get("brain"), dict) else {}
    out = int(contact.get("messages_out", 0) or 0)
    replies = int(contact.get("replies_to_love8", 0) or 0)
    bot = int(brain.get("bot_probability", 50) or 50)
    risk = int(brain.get("scam_risk", 0) or 0)
    if score >= 78 and out >= 2 and replies >= 2 and bot < 60 and risk < 30:
        return "trusted_peer"
    if score >= 62 and out >= 1 and replies >= 1 and bot < 75 and risk < 45:
        return "established"
    if replies >= 1:
        return "replied"
    if out >= 1:
        return "contacted"
    return "candidate"


def normalize_topic(value: Any) -> str:
    text = " ".join(str(value).strip().lower().split())
    text = re.sub(r"[^a-z0-9\-_/ .+#]", "", text)
    return text[:64].strip(" .-/")


def topic_momentum(contacts: dict[str, Any]) -> list[dict[str, Any]]:
    weights: Counter[str] = Counter()
    peers: dict[str, set[str]] = defaultdict(set)
    rooms: dict[str, Counter[str]] = defaultdict(Counter)
    for cid, contact in contacts.items():
        if not isinstance(contact, dict):
            continue
        brain = contact.get("brain", {}) if isinstance(contact.get("brain"), dict) else {}
        if int(brain.get("scam_risk", 0) or 0) >= 60 or int(brain.get("bot_probability", 50) or 50) >= 85:
            continue
        score = int(contact.get("relationship_score", relationship_score(contact)) or 0)
        stage = str(contact.get("relationship_stage", "candidate"))
        stage_bonus = {"candidate": 0.0, "contacted": 0.35, "replied": 0.65, "established": 1.0, "trusted_peer": 1.35}.get(stage, 0.0)
        weight = 0.55 + score / 100.0 + stage_bonus
        values = brain.get("topics", []) if isinstance(brain.get("topics"), list) else []
        for raw in values[:8]:
            topic = normalize_topic(raw)
            if len(topic) < 3:
                continue
            weights[topic] += weight
            peers[topic].add(cid)
            room = str(contact.get("last_room", "") or "")
            if room:
                rooms[topic][room] += 1
    out = []
    for topic, weight in weights.most_common(20):
        out.append({
            "topic": topic,
            "momentum": round(weight, 2),
            "peer_count": len(peers[topic]),
            "peers": sorted(peers[topic]),
            "rooms": [r for r, _ in rooms[topic].most_common(5)],
        })
    return out


def contribution_score(decision: dict[str, Any]) -> int:
    if not decision.get("sent"):
        return 0
    action = str(decision.get("action", ""))
    if action not in {"reply", "start_topic"}:
        return 0
    quality = int(decision.get("conversation_quality", 0) or 0)
    bot = int(decision.get("bot_probability", 50) or 50)
    risk = int(decision.get("scam_risk", 0) or 0)
    human = int(decision.get("human_likelihood", 0) or 0)
    score = quality * 0.55 + (100 - bot) * 0.18 + (100 - risk) * 0.17 + human * 0.10
    if action == "start_topic":
        score += 5
    return clamp(score)


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_bytes(key_path: str, payload: bytes) -> str:
    with tempfile.NamedTemporaryFile() as msg, tempfile.NamedTemporaryFile() as sig:
        msg.write(payload)
        msg.flush()
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", key_path, "-in", msg.name, "-out", sig.name],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        raw = Path(sig.name).read_bytes()
    if len(raw) != 64:
        raise RuntimeError("unexpected Ed25519 signature length")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def verify_bytes(key_path: str, payload: bytes, signature: str) -> bool:
    pad = "=" * ((4 - len(signature) % 4) % 4)
    raw_sig = base64.urlsafe_b64decode(signature + pad)
    with tempfile.NamedTemporaryFile() as msg, tempfile.NamedTemporaryFile() as sig, tempfile.NamedTemporaryFile() as pub:
        msg.write(payload); msg.flush()
        sig.write(raw_sig); sig.flush()
        subprocess.run(["openssl", "pkey", "-in", key_path, "-pubout", "-out", pub.name], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        proc = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", pub.name, "-rawin", "-in", msg.name, "-sigfile", sig.name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return proc.returncode == 0


def previous_ledger_hash(day: str, ledger_dir: Path) -> str | None:
    files = sorted(p for p in ledger_dir.glob("????-??-??.json") if p.name[:10] < day)
    if not files:
        return None
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
        prov = data.get("provenance", {}) if isinstance(data, dict) else {}
        value = prov.get("sha256") if isinstance(prov, dict) else None
        return str(value) if value else None
    except Exception:
        return None


def build_ledger(
    cfg: dict[str, str],
    social_state: dict[str, Any],
    brain_state: dict[str, Any],
    persist_state: dict[str, Any],
    topics: list[dict[str, Any]],
) -> dict[str, Any]:
    now = utc_now()
    day = now.strftime("%Y-%m-%d")
    contacts = social_state.get("contacts", {}) if isinstance(social_state.get("contacts"), dict) else {}
    relationships = []
    risk_events = []
    for cid, c in contacts.items():
        if not isinstance(c, dict):
            continue
        brain = c.get("brain", {}) if isinstance(c.get("brain"), dict) else {}
        stage = str(c.get("relationship_stage", "candidate"))
        score = int(c.get("relationship_score", 0) or 0)
        if stage in {"replied", "established", "trusted_peer"} or score >= 55:
            relationships.append({
                "id": cid,
                "stage": stage,
                "score": score,
                "room": str(c.get("last_room", ""))[:80],
                "topics": [normalize_topic(x) for x in (brain.get("topics", []) if isinstance(brain.get("topics"), list) else [])[:5]],
                "bot_probability": int(brain.get("bot_probability", 50) or 50),
                "scam_risk": int(brain.get("scam_risk", 0) or 0),
            })
        if c.get("suspected_scam") or int(brain.get("scam_risk", 0) or 0) >= 60:
            risk_events.append({"id": cid, "risk": int(brain.get("scam_risk", 0) or 0), "room": str(c.get("last_room", ""))[:80]})
    relationships.sort(key=lambda x: x["score"], reverse=True)

    contributions = [x for x in persist_state.get("contributions", []) if isinstance(x, dict) and str(x.get("date")) == day]
    stages = Counter(str(c.get("relationship_stage", "candidate")) for c in contacts.values() if isinstance(c, dict))
    payload = {
        "schema": "love8-provenance-v1",
        "agent_version": VERSION,
        "did": cfg.get("DID", ""),
        "fingerprint": cfg.get("FP", ""),
        "date": day,
        "generated_at": now.isoformat(),
        "previous_ledger_sha256": previous_ledger_hash(day, LEDGER_DIR),
        "metrics": {
            "contacts": len(contacts),
            "relationship_stages": dict(stages),
            "brain_decisions_total": len(brain_state.get("decisions", [])) if isinstance(brain_state.get("decisions"), list) else 0,
            "useful_contributions_today": len(contributions),
            "rooms_created_today": sum(1 for x in persist_state.get("room_creations", []) if isinstance(x, dict) and str(x.get("date")) == day),
            "risk_events_visible": len(risk_events),
        },
        "top_relationships": relationships[:20],
        "top_topics": topics[:15],
        "contributions": contributions[-30:],
        "risk_events": risk_events[:20],
    }
    return payload


def write_signed_ledger(cfg: dict[str, str], payload: dict[str, Any]) -> Path:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER_DIR.chmod(0o700)
    raw = canonical_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    signature = sign_bytes(cfg["KEY"], raw)
    doc = dict(payload)
    doc["provenance"] = {
        "algorithm": "Ed25519",
        "canonicalization": "json-sort-keys-compact-utf8",
        "sha256": digest,
        "signature_base64url": signature,
    }
    path = LEDGER_DIR / f"{payload['date']}.json"
    save_json(path, doc, 0o600)
    return path


def process_relationships(social_state: dict[str, Any]) -> None:
    contacts = social_state.get("contacts", {}) if isinstance(social_state.get("contacts"), dict) else {}
    for contact in contacts.values():
        if not isinstance(contact, dict):
            continue
        score = relationship_score(contact)
        contact["relationship_score"] = score
        contact["relationship_stage"] = relationship_stage(contact, score)
        contact["relationship_updated_at"] = int(time.time())


def process_contributions(brain_state: dict[str, Any], persist_state: dict[str, Any], minimum: int) -> None:
    decisions = brain_state.get("decisions", []) if isinstance(brain_state.get("decisions"), list) else []
    last_ts = int(persist_state.get("last_decision_ts", 0) or 0)
    contributions = persist_state.setdefault("contributions", [])
    newest = last_ts
    for d in decisions:
        if not isinstance(d, dict):
            continue
        ts = int(d.get("ts", 0) or 0)
        newest = max(newest, ts)
        if ts <= last_ts:
            continue
        score = contribution_score(d)
        if score < minimum:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        basis = json.dumps({"ts": ts, "target": d.get("target"), "room": d.get("room"), "reason": d.get("reason")}, sort_keys=True)
        contributions.append({
            "id": hashlib.sha256(basis.encode()).hexdigest()[:20],
            "date": day,
            "ts": ts,
            "action": str(d.get("action", "")),
            "room": str(d.get("room", ""))[:80],
            "target": str(d.get("target", ""))[:80],
            "score": score,
            "quality": int(d.get("conversation_quality", 0) or 0),
            "reason": str(d.get("reason", ""))[:300],
        })
    persist_state["last_decision_ts"] = newest
    persist_state["contributions"] = contributions[-1000:]


def room_slug(topic: str, day: str, prefix: str = "love8") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    slug = slug[:30].rstrip("-") or "circle"
    pfx = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")[:12] or "love8"
    return f"{pfx}-{slug}-{day.replace('-', '')}"[:58].rstrip("-")


def eligible_circle(topic: dict[str, Any], contacts: dict[str, Any], cfg: dict[str, str]) -> tuple[bool, list[tuple[str, dict[str, Any]]]]:
    threshold = float(cfg.get("PERSIST_TOPIC_MOMENTUM_MIN", "4.5"))
    min_peers = int(cfg.get("PERSIST_ROOM_MIN_PEERS", "2"))
    if float(topic.get("momentum", 0) or 0) < threshold:
        return False, []
    eligible = []
    for cid in topic.get("peers", []):
        c = contacts.get(cid)
        if not isinstance(c, dict):
            continue
        if c.get("relationship_stage") not in {"established", "trusted_peer"}:
            continue
        brain = c.get("brain", {}) if isinstance(c.get("brain"), dict) else {}
        if int(brain.get("scam_risk", 0) or 0) >= 40 or int(brain.get("bot_probability", 50) or 50) >= 75:
            continue
        eligible.append((cid, c))
    return len(eligible) >= min_peers, eligible


def maybe_create_circle(
    guard,
    cfg: dict[str, str],
    social_state: dict[str, Any],
    persist_state: dict[str, Any],
    topics: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any] | None:
    if cfg.get("PERSIST_ROOM_CREATE_ENABLED", "yes").lower() not in {"1", "yes", "true", "on"}:
        return None
    day = utc_now().strftime("%Y-%m-%d")
    max_per_day = int(cfg.get("PERSIST_ROOMS_PER_DAY", "1"))
    creations = persist_state.setdefault("room_creations", [])
    if sum(1 for x in creations if isinstance(x, dict) and x.get("date") == day) >= max_per_day:
        return None
    contacts = social_state.get("contacts", {}) if isinstance(social_state.get("contacts"), dict) else {}
    existing_topics = {str(x.get("topic")) for x in creations if isinstance(x, dict)}
    for topic in topics:
        name = str(topic.get("topic", ""))
        if not name or name in existing_topics:
            continue
        ok, peers = eligible_circle(topic, contacts, cfg)
        if not ok:
            continue
        room = room_slug(name, day, cfg.get("PERSIST_ROOM_PREFIX", "love8"))
        opener = (
            f"love8 persistent circle: {name}. i'm bringing together a few recurring participants who have been discussing this topic. "
            "let's keep it concrete: what is the most useful open question or experiment here right now?"
        )[:420]
        public_hourly = int(cfg.get("BRAIN_PUBLIC_HOURLY_WRITES", "6"))
        public_daily = int(cfg.get("BRAIN_PUBLIC_DAILY_WRITES", "20"))
        record = {"date": day, "ts": int(time.time()), "topic": name, "room": room, "peer_ids": [cid for cid, _ in peers[:4]], "dry_run": dry_run}
        if dry_run:
            log(f"DRY-RUN circle-create room={room} topic={name} peers={len(peers)}")
            return record
        if not guard.budget(social_state, public_hourly, public_daily):
            log("circle held: public write budget reached")
            return None
        result = guard.signed_post(cfg["BASE"].rstrip("/"), cfg["DID"], cfg["KEY"], room, opener, social_state)
        social_state.setdefault("writes", []).append(time.time())
        record["seq"] = int(result.get("last_seq", 0) or 0)
        creations.append(record)
        log(f"created persistent circle room={room} topic={name} peers={len(peers)} seq={record['seq']}")

        # Invite at most three established peers through the existing signed mailbox helper.
        reply_bin = Path("/usr/local/bin/love8-reply")
        if reply_bin.exists():
            invite = f"love8 created a focused public room /r/{room} around '{name}' after repeated useful discussion. join if it's relevant to you."
            for cid, _ in peers[:3]:
                fp = cid.split(":", 1)[1] if cid.startswith("did:") else ""
                if not re.fullmatch(r"[0-9a-f]{16}", fp):
                    continue
                try:
                    subprocess.run([str(reply_bin), fp, invite], check=False, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
        return record
    return None


def build_runtime_cfg() -> dict[str, str]:
    cfg = {**load_env(SOCIAL_CONFIG), **load_env(BRAIN_CONFIG), **load_env(PERSIST_CONFIG)}
    missing = [k for k in ("BASE", "DID", "FP", "KEY") if not cfg.get(k)]
    if missing:
        raise RuntimeError("missing config: " + ",".join(missing))
    if not Path(cfg["KEY"]).is_file():
        raise RuntimeError("Love8 Ed25519 key missing")
    return cfg


def run_cycle(dry_run: bool = False, finalize: bool = False) -> int:
    cfg = build_runtime_cfg()
    guard = load_guard()
    social_state = guard.load_state(SOCIAL_STATE)
    brain_state = load_json(BRAIN_STATE, {"decisions": []})
    persist_state = load_json(PERSIST_STATE, {"version": VERSION, "contributions": [], "room_creations": []})
    persist_state["version"] = VERSION

    process_relationships(social_state)
    minimum = int(cfg.get("PERSIST_CONTRIBUTION_MIN", "45"))
    process_contributions(brain_state, persist_state, minimum)
    contacts = social_state.get("contacts", {}) if isinstance(social_state.get("contacts"), dict) else {}
    topics = topic_momentum(contacts)
    persist_state["top_topics"] = topics[:20]
    persist_state["last_reflection_at"] = int(time.time())

    circle = maybe_create_circle(guard, cfg, social_state, persist_state, topics, dry_run=dry_run)
    ledger = build_ledger(cfg, social_state, brain_state, persist_state, topics)

    stages = Counter(str(c.get("relationship_stage", "candidate")) for c in contacts.values() if isinstance(c, dict))
    log(
        f"reflection contacts={len(contacts)} stages={dict(stages)} topics={len(topics)} "
        f"contributions={len(persist_state.get('contributions', []))} circle={'yes' if circle else 'no'} dry_run={dry_run}"
    )
    if dry_run:
        print("top_topics:", [(x["topic"], x["momentum"], x["peer_count"]) for x in topics[:8]])
        return 0

    guard.save_state(SOCIAL_STATE, social_state)
    save_json(PERSIST_STATE, persist_state)
    path = write_signed_ledger(cfg, ledger)
    persist_state["last_ledger"] = str(path)
    persist_state["last_ledger_at"] = int(time.time())
    if finalize:
        persist_state["last_finalized_date"] = ledger["date"]
    save_json(PERSIST_STATE, persist_state)
    log(f"signed provenance ledger={path}")
    return 0


def verify_ledger(path: Path | None = None) -> int:
    cfg = build_runtime_cfg()
    if path is None:
        files = sorted(LEDGER_DIR.glob("????-??-??.json"))
        if not files:
            print("no ledger files")
            return 1
        path = files[-1]
    data = json.loads(path.read_text(encoding="utf-8"))
    prov = data.pop("provenance", {})
    raw = canonical_bytes(data)
    digest = hashlib.sha256(raw).hexdigest()
    sig = str(prov.get("signature_base64url", "")) if isinstance(prov, dict) else ""
    ok_hash = digest == str(prov.get("sha256", "")) if isinstance(prov, dict) else False
    ok_sig = bool(sig) and verify_bytes(cfg["KEY"], raw, sig)
    print("ledger:", path)
    print("sha256:", "OK" if ok_hash else "FAIL")
    print("ed25519_signature:", "OK" if ok_sig else "FAIL")
    return 0 if ok_hash and ok_sig else 2


def status() -> int:
    cfg = {**load_env(BRAIN_CONFIG), **load_env(PERSIST_CONFIG)}
    st = load_json(PERSIST_STATE, {})
    social = load_json(SOCIAL_STATE, {})
    contacts = social.get("contacts", {}) if isinstance(social.get("contacts"), dict) else {}
    stages = Counter(str(c.get("relationship_stage", "candidate")) for c in contacts.values() if isinstance(c, dict))
    print("===== LOVE8 PERSISTENT AGENT v2.4 =====")
    print("version:", VERSION)
    print("relationship_stages:", dict(stages))
    print("contributions:", len(st.get("contributions", [])) if isinstance(st.get("contributions"), list) else 0)
    print("room_creations:", len(st.get("room_creations", [])) if isinstance(st.get("room_creations"), list) else 0)
    print("last_ledger:", st.get("last_ledger", "-"))
    print("room_create_enabled:", cfg.get("PERSIST_ROOM_CREATE_ENABLED", "yes"))
    print("topic_momentum_min:", cfg.get("PERSIST_TOPIC_MOMENTUM_MIN", "4.5"))
    print("room_min_peers:", cfg.get("PERSIST_ROOM_MIN_PEERS", "2"))
    print("contribution_min:", cfg.get("PERSIST_CONTRIBUTION_MIN", "45"))
    print("brain_api_cap:", cfg.get("BRAIN_CALLS_PER_HOUR", "-"), "/hour")
    print("public_write_cap:", cfg.get("BRAIN_PUBLIC_HOURLY_WRITES", "-"), "/hour", cfg.get("BRAIN_PUBLIC_DAILY_WRITES", "-"), "/day")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hourly", action="store_true")
    p.add_argument("--finalize", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--verify", nargs="?", const="latest")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.status:
        return status()
    if args.verify is not None:
        return verify_ledger(None if args.verify == "latest" else Path(args.verify))
    if args.hourly or args.finalize:
        return run_cycle(dry_run=args.dry_run, finalize=args.finalize)
    raise SystemExit("use --hourly, --finalize, --status or --verify")


if __name__ == "__main__":
    raise SystemExit(main())
