#!/usr/bin/env python3
"""Public-only A2A v5.5.2 evidence compatibility primitives.

The canonicalization and domain separation intentionally match
``deploy/a2a-v5/evidence_v55.py``. Atlas projects only non-secret evidence
metadata into its loopback snapshot and never reads the A2A state directory.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

EVIDENCE_SCHEMA = "technocore.a2a/evidence-v1"
BUNDLE_SCHEMA = "technocore.a2a/evidence-bundle-v1"
SOURCE_TYPE = "signed_room_message"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def payload_hash(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    return sha256_hex(canonical_bytes(payload))


def timestamp_ms(value: object) -> int:
    """Normalize Unix seconds/milliseconds or ISO-8601 to epoch milliseconds."""

    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        text = str(value or "").strip()
        if not text:
            return 0
        try:
            numeric = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return 0
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0, int(parsed.timestamp() * 1000))
    if numeric <= 0:
        return 0
    return int(numeric if numeric >= 1_000_000_000_000 else numeric * 1000)


def evidence_record(
    *,
    workflow_id: str,
    stage: str,
    payload: dict[str, Any],
    timestamp: int,
    signer_did: str,
    room: str,
    sequence: int,
) -> dict[str, Any]:
    if not workflow_id.startswith("wf-") or payload.get("task_id") != workflow_id:
        raise ValueError("workflow binding mismatch")
    if payload.get("type") != stage:
        raise ValueError("stage binding mismatch")
    if timestamp <= 0 or sequence <= 0 or not room or not signer_did:
        raise ValueError("evidence locator metadata missing")
    return {
        "schema": EVIDENCE_SCHEMA,
        "workflow_id": workflow_id,
        "stage": stage,
        "source_type": SOURCE_TYPE,
        "payload_sha256": payload_hash(payload),
        "timestamp": timestamp,
        "signer_did": signer_did,
        "locator": {"room": room, "sequence": sequence},
    }


def evidence_leaf(value: dict[str, Any]) -> str:
    return sha256_hex(b"\x00" + canonical_bytes(value))


def merkle_root(leaves: tuple[str, ...]) -> str:
    if not leaves:
        return ""
    try:
        level = [bytes.fromhex(value) for value in leaves]
    except ValueError as exc:
        raise ValueError("invalid leaf hash") from exc
    if any(len(value) != 32 for value in level):
        raise ValueError("invalid leaf hash length")
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(b"\x01" + level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    return level[0].hex()
