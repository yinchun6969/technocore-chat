#!/usr/bin/env python3
"""Love8 v2.4.1 permanent memory and canonical provenance layer.

The append-only signed event journal is the local source of truth. Technocore
rooms/notes and GitHub are witnesses/projections, never the canonical store.
Every memory event is chained to the previous event and signed by Love8's
persistent Ed25519 DID key.
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
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "2.4.1"
ROOT = Path("/opt/love8-agent")
SOCIAL = ROOT / "social"
STATE = ROOT / "state"
IDENTITY = ROOT / "identity"
MEMORY = ROOT / "memory"
EVENTS = MEMORY / "events"
CONTACTS = MEMORY / "contacts"
BACKUPS = MEMORY / "backups"
CANONICAL = MEMORY / "provenance"
INDEX = MEMORY / "index.json"
MEMORY_STATE = MEMORY / "state.json"
TOPICS = MEMORY / "topics.json"
GITHUB_PROOFS = MEMORY / "github-proofs.json"
SIGNED_WRITES = STATE / "signed-writes-v241.jsonl"
EVENT_SCOUT = STATE / "event-scout-v241.json"
UPSTREAM_SCOUT = STATE / "upstream-scout-v241.json"
SOCIAL_STATE = STATE / "social-v2.json"
BRAIN_STATE = STATE / "brain-v22.json"
PERSIST_STATE = STATE / "persistent-v24.json"
SOCIAL_CONFIG = SOCIAL / "config.env"
BRAIN_CONFIG = SOCIAL / "brain.env"
PERSIST_CONFIG = SOCIAL / "persistent.env"
GUARD_PATH = SOCIAL / "love8_social.py"
LEGACY_LEDGER = ROOT / "provenance"
LOG = Path("/var/log/love8-persistent-v24.log")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path, default: Any) -> Any:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return default


def save_json(path: Path, data: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(mode)
    os.replace(tmp, path)


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
            k, v = token.split("=", 1)
            out[k] = v
        except Exception:
            continue
    return out


def cfg() -> dict[str, str]:
    out = {**load_env(SOCIAL_CONFIG), **load_env(BRAIN_CONFIG), **load_env(PERSIST_CONFIG)}
    missing = [k for k in ("BASE", "DID", "FP", "KEY") if not out.get(k)]
    if missing:
        raise RuntimeError("missing config: " + ",".join(missing))
    expected = hashlib.sha256(out["DID"].encode()).hexdigest()[:16]
    if out["FP"].lower() != expected:
        raise RuntimeError(f"fingerprint mismatch: config={out['FP']} expected={expected}")
    if not Path(out["KEY"]).is_file():
        raise RuntimeError("Love8 Ed25519 key missing")
    return out


def ensure_dirs() -> None:
    for p in (MEMORY, EVENTS, CONTACTS, BACKUPS, CANONICAL):
        p.mkdir(parents=True, exist_ok=True)
        p.chmod(0o700)


def sign_bytes(key_path: str, payload: bytes) -> str:
    with tempfile.NamedTemporaryFile() as msg, tempfile.NamedTemporaryFile() as sig:
        msg.write(payload); msg.flush()
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", key_path, "-in", msg.name, "-out", sig.name],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        raw = Path(sig.name).read_bytes()
    if len(raw) != 64:
        raise RuntimeError("unexpected Ed25519 signature length")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def verify_bytes(key_path: str, payload: bytes, signature: str) -> bool:
    try:
        pad = "=" * ((4 - len(signature) % 4) % 4)
        raw_sig = base64.urlsafe_b64decode(signature + pad)
    except Exception:
        return False
    with tempfile.NamedTemporaryFile() as msg, tempfile.NamedTemporaryFile() as sig, tempfile.NamedTemporaryFile() as pub:
        msg.write(payload); msg.flush(); sig.write(raw_sig); sig.flush()
        subprocess.run(["openssl", "pkey", "-in", key_path, "-pubout", "-out", pub.name], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        p = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", pub.name, "-rawin", "-in", msg.name, "-sigfile", sig.name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    return p.returncode == 0


def event_id(kind: str, subject: str, data: Any) -> str:
    return sha256_bytes(canonical({"kind": kind, "subject": subject, "data": data}))[:32]


def append_event(conf: dict[str, str], kind: str, subject: str, data: Any) -> bool:
    ensure_dirs()
    idx = load_json(INDEX, {"schema": "love8-memory-index-v1", "count": 0, "head": None, "event_ids": {}})
    if not isinstance(idx, dict):
        idx = {"schema": "love8-memory-index-v1", "count": 0, "head": None, "event_ids": {}}
    ids = idx.setdefault("event_ids", {})
    eid = event_id(kind, subject, data)
    if eid in ids:
        return False
    base = {
        "schema": "love8-memory-event-v1",
        "event_id": eid,
        "ts": now_iso(),
        "kind": kind,
        "subject": subject,
        "data": data,
        "prev_event_sha256": idx.get("head"),
    }
    raw = canonical(base)
    digest = sha256_bytes(raw)
    rec = dict(base)
    rec["event_sha256"] = digest
    rec["signature_base64url"] = sign_bytes(conf["KEY"], raw)
    journal = EVENTS / datetime.now(timezone.utc).strftime("%Y-%m.jsonl")
    with journal.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
    journal.chmod(0o600)
    ids[eid] = digest
    idx["count"] = int(idx.get("count", 0) or 0) + 1
    idx["head"] = digest
    idx["updated_at"] = rec["ts"]
    save_json(INDEX, idx)
    return True


def safe_contact_file(cid: str) -> Path:
    return CONTACTS / (hashlib.sha256(cid.encode()).hexdigest()[:24] + ".json")


def _uniq(seq: list[Any], limit: int) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for item in seq:
        k = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
        if k in seen:
            continue
        seen.add(k); out.append(item)
    return out[-limit:]


def sync_contacts(conf: dict[str, str], social: dict[str, Any]) -> int:
    changed = 0
    contacts = social.get("contacts", {}) if isinstance(social.get("contacts"), dict) else {}
    for cid, c in contacts.items():
        if not isinstance(c, dict):
            continue
        brain = c.get("brain", {}) if isinstance(c.get("brain"), dict) else {}
        path = safe_contact_file(cid)
        old = load_json(path, {})
        if not isinstance(old, dict): old = {}
        summary = str(brain.get("summary", "") or "").strip()[:600]
        topics = [str(x)[:80] for x in (brain.get("topics", []) if isinstance(brain.get("topics"), list) else [])]
        room = str(c.get("last_room", "") or "")[:96]
        new = {
            "schema": "love8-contact-memory-v1",
            "contact_id": cid,
            "author": str(c.get("author", "") or "")[:180],
            "first_remembered_at": old.get("first_remembered_at") or now_iso(),
            "last_updated_at": now_iso(),
            "relationship_stage": str(c.get("relationship_stage", c.get("stage", "candidate"))),
            "relationship_score": int(c.get("relationship_score", 0) or 0),
            "verified_signed_did": bool(c.get("verified")),
            "human_self_declared": bool(c.get("human_self_declared")),
            "messages_in": int(c.get("messages_in", c.get("natural_messages", 0)) or 0),
            "messages_out": int(c.get("messages_out", 0) or 0),
            "replies_to_love8": int(c.get("replies_to_love8", 0) or 0),
            "bot_probability": int(brain.get("bot_probability", 50) or 50),
            "human_likelihood": int(brain.get("human_likelihood", c.get("brain_human_likelihood", 0)) or 0),
            "scam_risk": int(brain.get("scam_risk", 0) or 0),
            "conversation_quality": int(brain.get("conversation_quality", 0) or 0),
            "trust_score": int(brain.get("trust_score", 50) or 50),
            "topics": _uniq(list(old.get("topics", [])) + topics, 60),
            "rooms": _uniq(list(old.get("rooms", [])) + ([room] if room else []), 60),
            "summaries": _uniq(list(old.get("summaries", [])) + ([summary] if summary else []), 100),
        }
        compare_old = dict(old); compare_new = dict(new)
        compare_old.pop("last_updated_at", None); compare_new.pop("last_updated_at", None)
        if compare_old == compare_new:
            continue
        save_json(path, new)
        snapshot = {
            "stage": new["relationship_stage"], "score": new["relationship_score"],
            "room": room, "topics": topics[:8], "summary": summary,
            "bot_probability": new["bot_probability"], "scam_risk": new["scam_risk"],
            "messages_out": new["messages_out"], "replies_to_love8": new["replies_to_love8"],
        }
        if append_event(conf, "contact_memory", cid, snapshot): changed += 1
    return changed


def sync_topics(conf: dict[str, str], persistent: dict[str, Any]) -> int:
    store = load_json(TOPICS, {"schema": "love8-topic-memory-v1", "topics": {}})
    if not isinstance(store, dict): store = {"schema": "love8-topic-memory-v1", "topics": {}}
    table = store.setdefault("topics", {})
    changed = 0
    for item in persistent.get("top_topics", []) if isinstance(persistent.get("top_topics"), list) else []:
        if not isinstance(item, dict): continue
        name = str(item.get("topic", "") or "").strip()[:80]
        if not name: continue
        old = table.get(name, {}) if isinstance(table.get(name), dict) else {}
        momentum = float(item.get("momentum", 0) or 0)
        rec = {
            "first_seen": old.get("first_seen") or now_iso(),
            "last_seen": now_iso(),
            "observations": int(old.get("observations", 0) or 0) + 1,
            "max_momentum": max(float(old.get("max_momentum", 0) or 0), momentum),
            "last_momentum": momentum,
            "peer_count": int(item.get("peer_count", 0) or 0),
            "peers": _uniq(list(old.get("peers", [])) + list(item.get("peers", []) if isinstance(item.get("peers"), list) else []), 80),
            "rooms": _uniq(list(old.get("rooms", [])) + list(item.get("rooms", []) if isinstance(item.get("rooms"), list) else []), 80),
        }
        table[name] = rec
        marker = {"momentum": round(momentum, 2), "peer_count": rec["peer_count"], "rooms": rec["rooms"][-5:]}
        if append_event(conf, "topic_observation", name, marker): changed += 1
    store["updated_at"] = now_iso()
    save_json(TOPICS, store)
    return changed


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists(): return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
            if isinstance(obj, dict): out.append(obj)
        except Exception:
            continue
    return out


def sync_signed_writes(conf: dict[str, str]) -> int:
    changed = 0
    for rec in read_jsonl(SIGNED_WRITES)[-1000:]:
        proof = {
            "did": str(rec.get("did", ""))[:180],
            "room": str(rec.get("room", ""))[:80],
            "nonce": str(rec.get("nonce", ""))[:24],
            "signature": str(rec.get("signature", ""))[:100],
            "text": str(rec.get("text", ""))[:4096],
            "text_sha256": str(rec.get("text_sha256", ""))[:64],
            "observed_seq": int(rec.get("observed_seq", 0) or 0),
            "observed_at": str(rec.get("observed_at", ""))[:64],
        }
        subject = f"{proof['room']}:{proof['nonce']}"
        if append_event(conf, "technocore_signed_write", subject, proof): changed += 1
    return changed


def sync_legacy_contributions(conf: dict[str, str], persistent: dict[str, Any]) -> int:
    changed = 0
    for c in persistent.get("contributions", []) if isinstance(persistent.get("contributions"), list) else []:
        if not isinstance(c, dict): continue
        subject = str(c.get("id", "") or hashlib.sha256(canonical(c)).hexdigest()[:20])
        if append_event(conf, "useful_contribution", subject, c): changed += 1
    return changed


def sync_event_scout(conf: dict[str, str]) -> int:
    data = load_json(EVENT_SCOUT, {})
    changed = 0
    for item in data.get("rooms", []) if isinstance(data, dict) and isinstance(data.get("rooms"), list) else []:
        if not isinstance(item, dict): continue
        room = str(item.get("room", "") or "")[:80]
        seq = int(item.get("event_seq", 0) or 0)
        if room and append_event(conf, "technocore_room_discovered", f"{seq}:{room}", item): changed += 1
    return changed


def sync_upstream_scout(conf: dict[str, str]) -> int:
    data = load_json(UPSTREAM_SCOUT, {})
    changed = 0
    if not isinstance(data, dict): return 0
    latest = str(data.get("latest_commit_sha", "") or "")
    if latest:
        append_event(conf, "upstream_head_observed", latest, {"sha": latest, "commit_url": data.get("latest_commit_url"), "observed_at": data.get("updated_at")})
    for item in data.get("candidates", []) if isinstance(data.get("candidates"), list) else []:
        if not isinstance(item, dict): continue
        num = str(item.get("number", "") or "")
        if num and append_event(conf, "github_contribution_candidate", num, item): changed += 1
    return changed


def add_github_proof(conf: dict[str, str], level: int, reference: str, summary: str) -> None:
    if level < 1 or level > 5: raise ValueError("level must be 1..5")
    store = load_json(GITHUB_PROOFS, {"schema": "love8-github-proofs-v1", "proofs": []})
    if not isinstance(store, dict): store = {"schema": "love8-github-proofs-v1", "proofs": []}
    proof = {"level": level, "reference": reference[:500], "summary": summary[:1000], "recorded_at": now_iso()}
    pid = hashlib.sha256(canonical({"level": level, "reference": reference, "summary": summary})).hexdigest()[:24]
    proof["id"] = pid
    proofs = store.setdefault("proofs", [])
    if not any(isinstance(x, dict) and x.get("id") == pid for x in proofs):
        proofs.append(proof); store["proofs"] = proofs[-500:]; save_json(GITHUB_PROOFS, store)
        append_event(conf, "github_proof", pid, proof)


def legacy_ledger_hash() -> str | None:
    files = sorted(LEGACY_LEDGER.glob("????-??-??.json")) if LEGACY_LEDGER.exists() else []
    if not files: return None
    return sha256_bytes(files[-1].read_bytes())


def previous_canonical_hash(day: str) -> str | None:
    files = sorted(p for p in CANONICAL.glob("????-??-??.json") if p.name[:10] < day)
    if not files: return None
    doc = load_json(files[-1], {})
    p = doc.get("provenance", {}) if isinstance(doc, dict) else {}
    return str(p.get("sha256")) if isinstance(p, dict) and p.get("sha256") else None


def sharded_profile_path(fp: str) -> tuple[str, str, str]:
    fp = fp.lower()
    if not re.fullmatch(r"[0-9a-f]{16}", fp): raise ValueError("bad fingerprint")
    return f"did-{fp[:2]}", fp[2:], f"/kv/did-{fp[:2]}/{fp[2:]}"


def latest_signed_proofs(limit: int = 50) -> list[dict[str, Any]]:
    rows = read_jsonl(SIGNED_WRITES)
    return rows[-limit:]


def build_canonical_ledger(conf: dict[str, str]) -> dict[str, Any]:
    idx = load_json(INDEX, {})
    social = load_json(SOCIAL_STATE, {})
    persistent = load_json(PERSIST_STATE, {})
    upstream = load_json(UPSTREAM_SCOUT, {})
    topics = load_json(TOPICS, {})
    proofs = load_json(GITHUB_PROOFS, {"proofs": []})
    contacts = social.get("contacts", {}) if isinstance(social, dict) and isinstance(social.get("contacts"), dict) else {}
    stages: dict[str, int] = {}
    relationships: list[dict[str, Any]] = []
    for cid, c in contacts.items():
        if not isinstance(c, dict): continue
        stage = str(c.get("relationship_stage", c.get("stage", "candidate")))
        stages[stage] = stages.get(stage, 0) + 1
        score = int(c.get("relationship_score", 0) or 0)
        if stage in {"replied", "established", "trusted_peer"} or score >= 55:
            relationships.append({"id": cid, "stage": stage, "score": score, "room": str(c.get("last_room", ""))[:80]})
    relationships.sort(key=lambda x: x["score"], reverse=True)
    ns, key, profile_path = sharded_profile_path(conf["FP"])
    topic_table = topics.get("topics", {}) if isinstance(topics, dict) and isinstance(topics.get("topics"), dict) else {}
    top_topics = sorted(
        ({"topic": k, **v} for k, v in topic_table.items() if isinstance(v, dict)),
        key=lambda x: float(x.get("max_momentum", 0) or 0), reverse=True,
    )[:20]
    payload = {
        "schema": "love8-canonical-provenance-v2",
        "agent_version": VERSION,
        "date": today(),
        "generated_at": now_iso(),
        "identity": {"did": conf["DID"], "fingerprint": conf["FP"], "canonical_profile_path": profile_path, "legacy_profile_path": f"/kv/did/{conf['FP']}"},
        "memory": {"source_of_truth": "local_append_only_signed_journal", "event_count": int(idx.get("count", 0) or 0), "head_sha256": idx.get("head")},
        "previous_canonical_sha256": previous_canonical_hash(today()),
        "legacy_ledger_file_sha256": legacy_ledger_hash(),
        "relationship_stages": stages,
        "top_relationships": relationships[:25],
        "top_topics": top_topics,
        "technocore_signed_proofs": latest_signed_proofs(50),
        "github_proofs": proofs.get("proofs", [])[-50:] if isinstance(proofs, dict) and isinstance(proofs.get("proofs"), list) else [],
        "upstream_observation": {"latest_commit_sha": upstream.get("latest_commit_sha") if isinstance(upstream, dict) else None, "candidates": upstream.get("candidates", [])[:12] if isinstance(upstream, dict) and isinstance(upstream.get("candidates"), list) else []},
        "useful_contributions": persistent.get("contributions", [])[-50:] if isinstance(persistent, dict) and isinstance(persistent.get("contributions"), list) else [],
    }
    return payload


def write_canonical_ledger(conf: dict[str, str]) -> Path:
    ensure_dirs()
    payload = build_canonical_ledger(conf)
    raw = canonical(payload)
    prov = {"algorithm": "Ed25519", "canonicalization": "json-sort-keys-compact-utf8", "sha256": sha256_bytes(raw), "signature_base64url": sign_bytes(conf["KEY"], raw)}
    doc = dict(payload); doc["provenance"] = prov
    path = CANONICAL / f"{payload['date']}.json"
    save_json(path, doc)
    st = load_json(MEMORY_STATE, {})
    if not isinstance(st, dict): st = {}
    st.update({"version": VERSION, "last_canonical_ledger": str(path), "last_canonical_sha256": prov["sha256"], "last_canonical_at": now_iso()})
    save_json(MEMORY_STATE, st)
    return path


def read_identity_value(names: list[str]) -> str:
    for name in names:
        p = IDENTITY / name
        try:
            value = p.read_text(encoding="utf-8").strip()
            if value: return value[:2000]
        except Exception:
            continue
    return ""


def publish_profile(conf: dict[str, str], force: bool = False) -> tuple[bool, str]:
    st = load_json(MEMORY_STATE, {})
    if not isinstance(st, dict): st = {}
    interval = max(int(conf.get("PERSIST_PROFILE_PUBLISH_HOURS", "6")), 1) * 3600
    last = int(st.get("last_profile_publish_epoch", 0) or 0)
    if not force and time.time() - last < interval:
        ns, key, path = sharded_profile_path(conf["FP"]); return False, path
    idx = load_json(INDEX, {})
    ledger = load_json(CANONICAL / f"{today()}.json", {})
    prov = ledger.get("provenance", {}) if isinstance(ledger, dict) else {}
    mailbox = read_identity_value(["mailbox.txt"])
    x25519 = read_identity_value(["x25519.pub", "x25519_public.txt", "x25519.txt", "x25519_public.key"])
    body = {
        "schema": "love8-did-profile-v2",
        "did": conf["DID"], "nick": conf.get("NICK", "love8"), "mailbox": mailbox,
        "x25519": x25519, "memory_head_sha256": idx.get("head"),
        "canonical_ledger_sha256": prov.get("sha256") if isinstance(prov, dict) else None,
        "updated_at": now_iso(),
    }
    raw = canonical(body)
    value = dict(body)
    value["profile_payload_sha256"] = sha256_bytes(raw)
    value["profile_signature_base64url"] = sign_bytes(conf["KEY"], raw)
    compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    ns, key, path = sharded_profile_path(conf["FP"])
    url = conf["BASE"].rstrip("/") + f"/kv/{ns}/{key}"
    req = urllib.request.Request(url, data=json.dumps({"value": compact}, ensure_ascii=False).encode(), method="POST", headers={"Content-Type": "application/json", "User-Agent": f"love8-persistent/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except Exception as exc:
        return False, f"{path} publish failed: {type(exc).__name__}: {exc}"
    st.update({"last_profile_publish_epoch": int(time.time()), "last_profile_path": path, "last_profile_payload_sha256": value["profile_payload_sha256"]})
    save_json(MEMORY_STATE, st)
    return True, path


def load_guard():
    spec = importlib.util.spec_from_file_location("love8_guard_v241_memory", GUARD_PATH)
    if spec is None or spec.loader is None: raise RuntimeError("cannot load guard")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def maybe_anchor(conf: dict[str, str], force: bool = False) -> bool:
    if conf.get("PERSIST_ANCHOR_ENABLED", "yes").lower() not in {"1", "yes", "true", "on"}: return False
    st = load_json(MEMORY_STATE, {})
    if not isinstance(st, dict): st = {}
    if not force and st.get("last_anchor_date") == today(): return False
    ledger = load_json(CANONICAL / f"{today()}.json", {})
    prov = ledger.get("provenance", {}) if isinstance(ledger, dict) else {}
    idx = load_json(INDEX, {})
    ledger_hash = str(prov.get("sha256", "")) if isinstance(prov, dict) else ""
    if not ledger_hash: return False
    _, _, profile_path = sharded_profile_path(conf["FP"])
    room = conf.get("PERSIST_ANCHOR_ROOM", "d-love8")
    text = f"love8 provenance anchor v2.4.1 date={today()} ledger_sha256={ledger_hash} memory_head={idx.get('head')} profile={profile_path}"[:420]
    guard = load_guard(); social = guard.load_state(SOCIAL_STATE)
    try:
        result = guard.signed_post(conf["BASE"].rstrip("/"), conf["DID"], conf["KEY"], room, text, social)
        social.setdefault("writes", []).append(time.time()); guard.save_state(SOCIAL_STATE, social)
        st.update({"last_anchor_date": today(), "last_anchor_room": room, "last_anchor_seq": int(result.get("last_seq", 0) or 0)})
        save_json(MEMORY_STATE, st)
        return True
    except Exception as exc:
        st["last_anchor_error"] = f"{type(exc).__name__}: {exc}"[:300]; save_json(MEMORY_STATE, st); return False


def backup_snapshot(conf: dict[str, str]) -> Path:
    ensure_dirs()
    files: dict[str, str] = {}
    for p in sorted(MEMORY.rglob("*")):
        if p.is_file() and BACKUPS not in p.parents and p.suffix in {".json", ".jsonl"}:
            try: files[str(p.relative_to(MEMORY))] = sha256_bytes(p.read_bytes())
            except Exception: pass
    payload = {"schema": "love8-memory-backup-manifest-v1", "created_at": now_iso(), "memory_head": load_json(INDEX, {}).get("head"), "files": files}
    raw = canonical(payload); doc = dict(payload)
    doc["provenance"] = {"sha256": sha256_bytes(raw), "signature_base64url": sign_bytes(conf["KEY"], raw), "algorithm": "Ed25519"}
    path = BACKUPS / (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ") + ".manifest.json")
    save_json(path, doc)
    return path


def sync_cycle(finalize: bool = False) -> dict[str, Any]:
    conf = cfg(); ensure_dirs()
    social = load_json(SOCIAL_STATE, {})
    persistent = load_json(PERSIST_STATE, {})
    counts = {
        "contacts": sync_contacts(conf, social if isinstance(social, dict) else {}),
        "topics": sync_topics(conf, persistent if isinstance(persistent, dict) else {}),
        "signed_writes": sync_signed_writes(conf),
        "contributions": sync_legacy_contributions(conf, persistent if isinstance(persistent, dict) else {}),
        "event_rooms": sync_event_scout(conf),
        "upstream": sync_upstream_scout(conf),
    }
    ledger = write_canonical_ledger(conf)
    published, profile = publish_profile(conf, force=finalize)
    anchored = maybe_anchor(conf, force=finalize) if finalize else False
    backup = backup_snapshot(conf) if finalize else None
    st = load_json(MEMORY_STATE, {})
    if not isinstance(st, dict): st = {}
    st.update({"version": VERSION, "last_sync_at": now_iso(), "last_sync_counts": counts, "profile_publish_result": profile})
    save_json(MEMORY_STATE, st)
    return {"counts": counts, "ledger": str(ledger), "profile_published": published, "profile": profile, "anchored": anchored, "backup": str(backup) if backup else None}


def verify_event_chain(conf: dict[str, str]) -> tuple[bool, int, str | None]:
    prev: str | None = None; count = 0
    for journal in sorted(EVENTS.glob("????-??.jsonl")):
        for rec in read_jsonl(journal):
            base = {k: rec.get(k) for k in ("schema", "event_id", "ts", "kind", "subject", "data", "prev_event_sha256")}
            raw = canonical(base); digest = sha256_bytes(raw)
            if rec.get("prev_event_sha256") != prev: return False, count, f"chain break at {rec.get('event_id')}"
            if rec.get("event_sha256") != digest: return False, count, f"hash fail at {rec.get('event_id')}"
            if not verify_bytes(conf["KEY"], raw, str(rec.get("signature_base64url", ""))): return False, count, f"signature fail at {rec.get('event_id')}"
            prev = digest; count += 1
    idx = load_json(INDEX, {})
    if int(idx.get("count", 0) or 0) != count: return False, count, "index count mismatch"
    if idx.get("head") != prev: return False, count, "index head mismatch"
    return True, count, prev


def verify_canonical(conf: dict[str, str]) -> tuple[bool, str]:
    files = sorted(CANONICAL.glob("????-??-??.json"))
    if not files: return False, "no canonical ledger"
    doc = load_json(files[-1], {})
    if not isinstance(doc, dict): return False, "bad ledger"
    prov = doc.pop("provenance", {})
    raw = canonical(doc); digest = sha256_bytes(raw)
    ok = isinstance(prov, dict) and prov.get("sha256") == digest and verify_bytes(conf["KEY"], raw, str(prov.get("signature_base64url", "")))
    return ok, str(files[-1])


def status() -> int:
    ensure_dirs(); st = load_json(MEMORY_STATE, {}); idx = load_json(INDEX, {})
    contact_count = len(list(CONTACTS.glob("*.json")))
    topic_store = load_json(TOPICS, {"topics": {}}); topic_count = len(topic_store.get("topics", {})) if isinstance(topic_store, dict) and isinstance(topic_store.get("topics"), dict) else 0
    _, _, profile = sharded_profile_path(cfg()["FP"])
    print("===== LOVE8 v2.4.1 PERMANENT MEMORY =====")
    print("source_of_truth: local append-only DID-signed journal")
    print("events:", idx.get("count", 0)); print("memory_head:", idx.get("head", "-"))
    print("contacts_remembered:", contact_count); print("topics_remembered:", topic_count)
    print("canonical_ledger:", st.get("last_canonical_ledger", "-")); print("canonical_profile:", profile)
    print("last_sync:", st.get("last_sync_at", "-")); print("last_anchor_date:", st.get("last_anchor_date", "-"))
    print("auto_prune: disabled")
    return 0


def search_memory(term: str) -> int:
    q = term.lower(); hits = 0
    for p in sorted(CONTACTS.glob("*.json")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if q in text.lower(): print(f"CONTACT {p.name}: {text[:1500]}"); hits += 1
    t = TOPICS.read_text(encoding="utf-8", errors="replace") if TOPICS.exists() else ""
    if q in t.lower(): print("TOPICS:", t[:3000]); hits += 1
    g = GITHUB_PROOFS.read_text(encoding="utf-8", errors="replace") if GITHUB_PROOFS.exists() else ""
    if q in g.lower(): print("GITHUB_PROOFS:", g[:3000]); hits += 1
    print("hits:", hits); return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sync", action="store_true"); p.add_argument("--finalize", action="store_true")
    p.add_argument("--status", action="store_true"); p.add_argument("--verify", action="store_true")
    p.add_argument("--backup", action="store_true"); p.add_argument("--search")
    p.add_argument("--add-github-proof", nargs=3, metavar=("LEVEL", "REFERENCE", "SUMMARY"))
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    a = p.parse_args()
    conf = cfg()
    if a.status: return status()
    if a.verify:
        ok, count, head = verify_event_chain(conf); ok2, ledger = verify_canonical(conf)
        print("memory_chain:", "OK" if ok else "FAIL", "events=", count, "head=", head)
        print("canonical_ledger:", "OK" if ok2 else "FAIL", ledger)
        return 0 if ok and ok2 else 2
    if a.backup: print(backup_snapshot(conf)); return 0
    if a.search is not None: return search_memory(a.search)
    if a.add_github_proof:
        level, ref, summary = a.add_github_proof; add_github_proof(conf, int(level), ref, summary); print("github proof recorded"); return 0
    if a.sync or a.finalize:
        print(json.dumps(sync_cycle(finalize=a.finalize), ensure_ascii=False, indent=2)); return 0
    raise SystemExit("use --sync, --finalize, --status, --verify, --backup or --search")


if __name__ == "__main__":
    raise SystemExit(main())
