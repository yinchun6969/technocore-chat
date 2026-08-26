#!/usr/bin/env python3
"""Patch an installed aizong Social v1.4.1 core to v1.4.2 Memory Consolidation."""

from __future__ import annotations

import argparse
from pathlib import Path

TARGET_VERSION = "1.4.2"


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"PATCH_MISMATCH[{label}]: {old[:180]!r}")
    return source.replace(old, new, 1)


def patch_source(source: str) -> str:
    if 'VERSION = "1.4.2"' in source:
        return source
    if 'VERSION = "1.4.1"' not in source:
        raise RuntimeError("expected aizong Social v1.4.1 source")

    source = _replace_once(
        source,
        '"""aizong Social v1.4.1: anti-farming provenance-calibrated persistent-DID intelligence."""',
        '"""aizong Social v1.4.2: consolidated long-term memory with signed durable checkpoints."""',
        "docstring",
    )
    source = _replace_once(source, 'VERSION = "1.4.1"', 'VERSION = "1.4.2"', "version")
    source = _replace_once(
        source,
        "import urllib.error\nimport urllib.request\n",
        "import urllib.error\nimport urllib.parse\nimport urllib.request\n",
        "urllib-parse-import",
    )

    source = _replace_once(
        source,
        "- durable_state_value estimates whether the interaction contains information worth remembering beyond chat.\n"
        "- Do not optimize public behavior for faucets, airdrops, allocations, farming, points, or rewards.\n",
        "- durable_state_value estimates whether the interaction contains information worth remembering beyond chat.\n"
        "- Long-term memory should retain stable, useful facts and discard filler, transient status, and repetition.\n"
        "- memory.public_safe may be true only when the compact public_summary contains no secrets, private state,\n"
        "  credentials, risk scores, personal profiling, hidden reasoning, private paths, or unverified claims.\n"
        "- memory.public_summary should describe a reusable technical learning for future continuity, not profile a peer.\n"
        "- Never invent a public memory just to create durable-state activity. Empty is better than weak or unsafe memory.\n"
        "- Do not optimize public behavior for faucets, airdrops, allocations, farming, points, or rewards.\n",
        "memory-policy",
    )

    source = _replace_once(
        source,
        '    "topics": ["..."]\n  },\n  "reason": "short private reason"',
        '    "topics": ["..."],\n'
        '    "importance": 0-100,\n'
        '    "confidence": 0-100,\n'
        '    "public_safe": true|false,\n'
        '    "public_summary": "short reusable technical learning or empty"\n'
        '  },\n  "reason": "short private reason"',
        "brain-memory-schema",
    )

    source = _replace_once(
        source,
        '            "topics": _clean_list(memory.get("topics"), limit=16),\n        },\n        "reason": _single_line(str(decision.get("reason", "")), 240),',
        '            "topics": _clean_list(memory.get("topics"), limit=16),\n'
        '            "importance": _bounded_int(memory.get("importance")),\n'
        '            "confidence": _bounded_int(memory.get("confidence")),\n'
        '            "public_safe": bool(memory.get("public_safe", False)),\n'
        '            "public_summary": _single_line(str(memory.get("public_summary", "")), 280),\n'
        '        },\n        "reason": _single_line(str(decision.get("reason", "")), 240),',
        "brain-memory-result",
    )

    helpers = r"""


def _memory_limit(name: str, default: int, low: int, high: int) -> int:
    return _strategy_limit(name, default, low, high)


def _public_memory_safe(text: str) -> bool:
    value = _single_line(text, 280)
    if len(value) < 32:
        return False
    lower = value.lower()
    blocked = (
        "api key",
        "private key",
        "seed phrase",
        "recovery phrase",
        "password",
        "authorization:",
        "bearer ",
        "secret=",
        "token=",
        "cookie:",
        "/opt/",
        "/root/",
        "localhost",
        "127.0.0.1",
        "http://",
        "https://",
        "did:key:",
    )
    if any(token in lower for token in blocked):
        return False
    if re.search(r"\bsk-[a-z0-9_-]{12,}\b", lower):
        return False
    if re.search(r"\b[0-9a-f]{32,}\b", lower):
        return False
    return True


def _memory_core(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": _single_line(str(memory.get("summary", "")), 640),
        "capabilities": _clean_list(memory.get("capabilities"), limit=16),
        "projects": _clean_list(memory.get("projects"), limit=16),
        "interests": _clean_list(memory.get("interests"), limit=16),
        "topics": _clean_list(memory.get("topics"), limit=24),
    }


def _memory_digest(memory: dict[str, Any]) -> str:
    payload = json.dumps(
        _memory_core(memory),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _consolidate_contact_memory(
    state: dict[str, Any], action: dict[str, Any], decision: dict[str, Any]
) -> None:
    author = str(action.get("peer_author", ""))
    if not author:
        return
    contact = state.setdefault("contacts", {}).setdefault(peer_id(author), {})
    _ensure_contact(contact, author, str(action.get("room", contact.get("last_room", ""))))
    memory = contact.setdefault("memory", {})
    if not isinstance(memory, dict):
        memory = {}
        contact["memory"] = memory

    brain_memory = decision.get("memory", {})
    if not isinstance(brain_memory, dict):
        brain_memory = {}
    memory.update(_memory_core(memory))
    memory["importance"] = _bounded_int(
        brain_memory.get("importance", memory.get("importance", 0))
    )
    memory["confidence"] = _bounded_int(
        brain_memory.get("confidence", memory.get("confidence", 0))
    )
    public_summary = _single_line(str(brain_memory.get("public_summary", "")), 280)
    public_safe = bool(brain_memory.get("public_safe", False)) and _public_memory_safe(
        public_summary
    )
    memory["public_safe"] = public_safe
    memory["public_summary"] = public_summary if public_safe else ""

    digest = _memory_digest(memory)
    previous = str(memory.get("digest", ""))
    now = int(time.time())
    if digest != previous:
        history = memory.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "at": now,
                "digest": digest,
                "summary": _single_line(str(memory.get("summary", "")), 320),
                "importance": int(memory.get("importance", 0) or 0),
                "confidence": int(memory.get("confidence", 0) or 0),
            }
        )
        history_limit = _memory_limit("TC_MEMORY_HISTORY_LIMIT", 6, 2, 20)
        memory["history"] = history[-history_limit:]
        _strategy_metric(state, "memory_consolidations")
    memory["digest"] = digest
    memory["last_consolidated_at"] = now
    memory["schema_version"] = 1


def _sign_detached(key: str, payload: bytes) -> str:
    with tempfile.NamedTemporaryFile() as message_file, tempfile.NamedTemporaryFile() as sig_file:
        message_file.write(payload)
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


def _durable_memory_state(state: dict[str, Any]) -> dict[str, Any]:
    value = state.setdefault("durable_memory", {})
    if not isinstance(value, dict):
        value = {}
        state["durable_memory"] = value
    return value


def _durable_memory_budget_ok(state: dict[str, Any]) -> tuple[bool, str]:
    now = time.time()
    durable = _durable_memory_state(state)
    writes = []
    for raw in durable.get("writes", []):
        try:
            ts = float(raw)
        except (TypeError, ValueError):
            continue
        if now - ts < 86400:
            writes.append(ts)
    durable["writes"] = writes
    daily_cap = _memory_limit("TC_MEMORY_DAILY_SYNC_CAP", 2, 1, 8)
    if len(writes) >= daily_cap:
        return False, "durable memory daily cap reached"
    min_interval = _memory_limit("TC_MEMORY_SYNC_MIN_INTERVAL", 14400, 1800, 86400)
    last_sync = float(durable.get("last_sync_at", 0) or 0)
    if last_sync and now - last_sync < min_interval:
        return False, "durable memory minimum interval active"
    return True, ""


def _memory_sync_candidate(
    state: dict[str, Any], action: dict[str, Any], decision: dict[str, Any]
) -> tuple[bool, str, dict[str, Any]]:
    if os.getenv("TC_MEMORY_PUBLIC_SYNC", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return False, "public durable memory disabled", {}
    author = str(action.get("peer_author", ""))
    if not author.startswith("did:key:"):
        return False, "peer is not verified did:key", {}
    contact = state.get("contacts", {}).get(peer_id(author), {})
    if not isinstance(contact, dict):
        return False, "contact missing", {}
    stage = str(contact.get("relationship_stage", "stranger"))
    if stage not in ("recurring_contact", "trusted_peer", "collaborator"):
        return False, f"relationship stage {stage} not durable yet", {}
    memory = contact.get("memory", {})
    if not isinstance(memory, dict):
        return False, "memory missing", {}
    summary = _single_line(str(memory.get("public_summary", "")), 280)
    if not bool(memory.get("public_safe", False)) or not _public_memory_safe(summary):
        return False, "memory is not public-safe", {}

    contribution = _bounded_int(decision.get("contribution_value"))
    durable_value = _bounded_int(decision.get("durable_state_value"))
    evidence = _bounded_int(decision.get("evidence_strength"))
    importance = _bounded_int(memory.get("importance"))
    confidence = _bounded_int(memory.get("confidence"))
    risk = max(
        _bounded_int(decision.get("scam_risk")),
        _bounded_int(decision.get("prompt_injection_risk")),
        _bounded_int(decision.get("spam_probability")),
    )
    if contribution < _memory_limit("TC_MEMORY_MIN_CONTRIBUTION", 75, 0, 100):
        return False, "contribution below durable-memory threshold", {}
    if durable_value < _memory_limit("TC_MEMORY_MIN_DURABLE_VALUE", 80, 0, 100):
        return False, "durable-state value below threshold", {}
    if evidence < _memory_limit("TC_MEMORY_MIN_EVIDENCE", 60, 0, 100):
        return False, "evidence below durable-memory threshold", {}
    if importance < _memory_limit("TC_MEMORY_MIN_IMPORTANCE", 75, 0, 100):
        return False, "memory importance below threshold", {}
    if confidence < _memory_limit("TC_MEMORY_MIN_CONFIDENCE", 70, 0, 100):
        return False, "memory confidence below threshold", {}
    if risk > _memory_limit("TC_MEMORY_MAX_RISK", 25, 0, 100):
        return False, "risk above durable-memory threshold", {}

    digest = str(memory.get("digest", ""))
    durable = _durable_memory_state(state)
    if digest and digest == str(durable.get("last_digest", "")):
        return False, "memory digest already checkpointed", {}
    budget_ok, budget_reason = _durable_memory_budget_ok(state)
    if not budget_ok:
        return False, budget_reason, {}
    return True, "", {
        "summary": summary,
        "digest": digest,
        "evidence_kind": _single_line(str(decision.get("evidence_kind", "none")), 40),
        "contribution_type": _single_line(
            str(decision.get("contribution_type", "other")), 40
        ),
    }


def _build_memory_envelope(
    did: str,
    key: str,
    *,
    room: str,
    seq: int,
    summary: str,
    digest: str,
    evidence_kind: str,
    contribution_type: str,
    now: int,
) -> str:
    payload = {
        "v": 1,
        "kind": "aizong-memory-checkpoint",
        "did": did,
        "updated": now,
        "source": {"room": room, "seq": seq},
        "summary": summary,
        "memory_digest": digest,
        "evidence_kind": evidence_kind,
        "contribution_type": contribution_type,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    signature = _sign_detached(
        key, b"technocore:aizong-memory:v1|" + canonical.encode("utf-8")
    )
    envelope = {"alg": "Ed25519", "payload": payload, "sig": signature}
    return json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_durable_memory_note(base: str, namespace: str, note_key: str, value: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", namespace):
        raise ValueError("invalid durable memory namespace")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", note_key):
        raise ValueError("invalid durable memory note key")
    encoded = urllib.parse.quote(value, safe="")
    request = urllib.request.Request(
        f"{base}/kv/{namespace}/{note_key}/set/{encoded}",
        headers={"Accept": "text/plain", "User-Agent": USER_AGENT},
    )
    attempts = _env_int("TC_NET_RETRIES", 3, 1, 5)
    _read_request(request, timeout=20, attempts=attempts, label="durable-memory-set")


def _maybe_sync_durable_memory(
    base: str,
    did: str,
    key: str,
    state: dict[str, Any],
    action: dict[str, Any],
    decision: dict[str, Any],
    room: str,
    seq: int,
) -> bool:
    allowed, reason, candidate = _memory_sync_candidate(state, action, decision)
    if not allowed:
        return False
    now = int(time.time())
    namespace = os.getenv("TC_MEMORY_DURABLE_NS", "aizong-memory").strip() or "aizong-memory"
    note_key = "state-" + hashlib.sha256(did.encode("utf-8")).hexdigest()[:16]
    envelope = _build_memory_envelope(
        did,
        key,
        room=room,
        seq=seq,
        summary=str(candidate["summary"]),
        digest=str(candidate["digest"]),
        evidence_kind=str(candidate["evidence_kind"]),
        contribution_type=str(candidate["contribution_type"]),
        now=now,
    )
    try:
        _write_durable_memory_note(base, namespace, note_key, envelope)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        OSError,
    ) as exc:
        _strategy_metric(state, "durable_memory_sync_failures")
        log(f"WARN durable memory checkpoint deferred: {type(exc).__name__}: {exc}")
        return False
    durable = _durable_memory_state(state)
    durable.setdefault("writes", []).append(time.time())
    durable["last_sync_at"] = now
    durable["last_digest"] = str(candidate["digest"])
    durable["last_note_key"] = note_key
    durable["namespace"] = namespace
    durable["last_source_room"] = room
    durable["last_source_seq"] = seq
    durable["payload_signature"] = "ed25519"
    durable["server_note_auth"] = "unsigned-world-writable"
    _strategy_metric(state, "durable_memory_syncs")
    log(
        f"durable memory checkpoint synced ns={namespace} key={note_key} "
        f"source={room}:{seq}"
    )
    return True
"""
    source = _replace_once(
        source,
        "\ndef _provenance_percent(name: str, default: int) -> int:",
        helpers + "\n\ndef _provenance_percent(name: str, default: int) -> int:",
        "memory-helpers",
    )

    source = _replace_once(
        source,
        """    apply_contact_memory(state, action, decision)
    strategy_allowed, strategy_reason = _strategy_allows_decision(kind, decision)
""",
        """    apply_contact_memory(state, action, decision)
    _consolidate_contact_memory(state, action, decision)
    strategy_allowed, strategy_reason = _strategy_allows_decision(kind, decision)
""",
        "consolidate-after-brain",
    )

    source = _replace_once(
        source,
        """    _append_contribution_ledger(Path(args.ledger), ledger_event)
    note_write(state)
""",
        """    _append_contribution_ledger(Path(args.ledger), ledger_event)
    _maybe_sync_durable_memory(base, did, key, state, action, decision, room, last_seq)
    note_write(state)
""",
        "durable-sync-after-ledger",
    )

    return source


def patch_file(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    patched = patch_source(source)
    if patched == source:
        return False
    path.write_text(patched, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    changed = patch_file(args.path)
    status = "applied" if changed else "already present"
    print(f"aizong v{TARGET_VERSION} patch {status}: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
