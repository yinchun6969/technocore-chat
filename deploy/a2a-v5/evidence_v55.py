#!/usr/bin/env python3
"""Deterministic evidence and Saga primitives for A2A v5.5.

The module intentionally uses only the Python standard library so the three
existing VPS roles do not acquire a mutable package dependency.  It treats the
public-room envelope as data already authenticated by the deployed Technocore
runtime and then binds its canonical payload, signer and locator into a
domain-separated Merkle tree.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


SCHEMA = "technocore.a2a/evidence-bundle-v1"
EVIDENCE_SCHEMA = "technocore.a2a/evidence-v1"
SAGA_SCHEMA = "technocore.a2a/saga-v1"

LOVE8_DID = "did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p"
AIZONG_DID = "did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e"
AI2AI_DID = "did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje"

STAGE_ORDER = (
    "WORKFLOW_TASK",
    "BUILD_RESULT",
    "CHALLENGE",
    "REVISED_RESULT",
    "COMPLETE",
)
EXPECTED_SIGNERS = {
    "WORKFLOW_TASK": LOVE8_DID,
    "BUILD_RESULT": AIZONG_DID,
    "CHALLENGE": AI2AI_DID,
    "REVISED_RESULT": AIZONG_DID,
    "COMPLETE": LOVE8_DID,
}
SAGA_STATES = {
    "WORKFLOW_TASK": "TASK_SIGNED",
    "BUILD_RESULT": "BUILD_SIGNED",
    "CHALLENGE": "REVIEW_SIGNED",
    "REVISED_RESULT": "REVISION_SIGNED",
    "COMPLETE": "COMPLETE_SIGNED",
}


class EvidenceError(ValueError):
    """Raised when signed stage evidence fails a deterministic constraint."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_timestamp(value: object) -> int:
    """Normalize Unix seconds/milliseconds or ISO-8601 into epoch milliseconds."""
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
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0, int(parsed.timestamp() * 1000))
    if numeric <= 0:
        return 0
    return int(numeric if numeric >= 1_000_000_000_000 else numeric * 1000)


def payload_hash(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise EvidenceError("payload must be an object")
    return sha256_hex(canonical_bytes(payload))


def _positive_int(value: object, name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f"{name} must be an integer") from exc
    if result <= 0:
        raise EvidenceError(f"{name} must be positive")
    return result


def evidence_from_stage(workflow_id: str, stage: str, item: dict[str, Any]) -> dict[str, Any]:
    if not workflow_id.startswith("wf-"):
        raise EvidenceError("invalid workflow_id")
    if stage not in EXPECTED_SIGNERS:
        raise EvidenceError(f"unsupported stage: {stage}")
    if not isinstance(item, dict):
        raise EvidenceError(f"{stage} stage record must be an object")
    payload = item.get("obj")
    if not isinstance(payload, dict):
        raise EvidenceError(f"{stage} payload must be an object")
    if payload.get("type") != stage:
        raise EvidenceError(f"{stage} payload type mismatch")
    if payload.get("task_id") != workflow_id:
        raise EvidenceError(f"{stage} workflow binding mismatch")
    signer = str(item.get("from") or "")
    if signer != EXPECTED_SIGNERS[stage]:
        raise EvidenceError(f"{stage} signer mismatch")
    room = str(item.get("room") or "").strip()
    if not room or len(room) > 128:
        raise EvidenceError(f"{stage} room locator missing")
    sequence = _positive_int(item.get("seq"), f"{stage} sequence")
    timestamp = parse_timestamp(item.get("message_ts")) or parse_timestamp(item.get("seen_at"))
    if timestamp <= 0:
        raise EvidenceError(f"{stage} timestamp missing")
    return {
        "schema": EVIDENCE_SCHEMA,
        "workflow_id": workflow_id,
        "stage": stage,
        "source_type": "signed_room_message",
        "payload_sha256": payload_hash(payload),
        "timestamp": timestamp,
        "signer_did": signer,
        "locator": {"room": room, "sequence": sequence},
    }


def evidence_leaf(evidence: dict[str, Any]) -> str:
    validate_evidence(evidence)
    return sha256_hex(b"\x00" + canonical_bytes(evidence))


def merkle_root(leaves: list[str]) -> str:
    if not leaves:
        raise EvidenceError("evidence set is empty")
    try:
        level = [bytes.fromhex(value) for value in leaves]
    except ValueError as exc:
        raise EvidenceError("invalid leaf hash") from exc
    if any(len(value) != 32 for value in level):
        raise EvidenceError("invalid leaf hash length")
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(b"\x01" + level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    return level[0].hex()


def validate_evidence(value: dict[str, Any]) -> None:
    required = {
        "schema", "workflow_id", "stage", "source_type", "payload_sha256",
        "timestamp", "signer_did", "locator",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise EvidenceError("evidence schema fields mismatch")
    if value["schema"] != EVIDENCE_SCHEMA or value["source_type"] != "signed_room_message":
        raise EvidenceError("unsupported evidence schema/source")
    workflow_id = value["workflow_id"]
    stage = value["stage"]
    if not isinstance(workflow_id, str) or not workflow_id.startswith("wf-"):
        raise EvidenceError("invalid evidence workflow_id")
    if stage not in EXPECTED_SIGNERS or value["signer_did"] != EXPECTED_SIGNERS[stage]:
        raise EvidenceError("invalid evidence signer/stage")
    digest = value["payload_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise EvidenceError("invalid payload hash")
    try:
        bytes.fromhex(digest)
    except ValueError as exc:
        raise EvidenceError("invalid payload hash encoding") from exc
    _positive_int(value["timestamp"], "timestamp")
    locator = value["locator"]
    if not isinstance(locator, dict) or set(locator) != {"room", "sequence"}:
        raise EvidenceError("invalid evidence locator")
    if not isinstance(locator["room"], str) or not locator["room"]:
        raise EvidenceError("invalid evidence room")
    _positive_int(locator["sequence"], "sequence")


def build_bundle(workflow_id: str, stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [stage for stage in STAGE_ORDER if stage not in stages]
    if missing:
        raise EvidenceError("missing stages: " + ",".join(missing))
    evidence = [evidence_from_stage(workflow_id, stage, stages[stage]) for stage in STAGE_ORDER]
    leaves = [evidence_leaf(value) for value in evidence]
    bundle = {
        "schema": SCHEMA,
        "workflow_id": workflow_id,
        "evidence": evidence,
        "leaf_hashes": leaves,
        "merkle_root": merkle_root(leaves),
        "evidence_count": len(evidence),
    }
    verify_bundle(bundle)
    return bundle


def verify_bundle(bundle: dict[str, Any]) -> bool:
    required = {"schema", "workflow_id", "evidence", "leaf_hashes", "merkle_root", "evidence_count"}
    if not isinstance(bundle, dict) or set(bundle) != required:
        raise EvidenceError("bundle schema fields mismatch")
    if bundle["schema"] != SCHEMA:
        raise EvidenceError("unsupported bundle schema")
    evidence = bundle["evidence"]
    if not isinstance(evidence, list) or len(evidence) != len(STAGE_ORDER):
        raise EvidenceError("bundle must contain exactly five stages")
    if [item.get("stage") for item in evidence if isinstance(item, dict)] != list(STAGE_ORDER):
        raise EvidenceError("bundle stage order mismatch")
    if any(item.get("workflow_id") != bundle["workflow_id"] for item in evidence):
        raise EvidenceError("bundle workflow binding mismatch")
    locators: set[tuple[str, str, int]] = set()
    for item in evidence:
        validate_evidence(item)
        key = (item["signer_did"], item["locator"]["room"], item["locator"]["sequence"])
        if key in locators:
            raise EvidenceError("replayed room locator")
        locators.add(key)
    leaves = [evidence_leaf(item) for item in evidence]
    if bundle["leaf_hashes"] != leaves:
        raise EvidenceError("leaf hash mismatch")
    if bundle["merkle_root"] != merkle_root(leaves):
        raise EvidenceError("Merkle root mismatch")
    if bundle["evidence_count"] != len(evidence):
        raise EvidenceError("evidence count mismatch")
    return True


def saga_checkpoint(
    workflow_id: str,
    stages: dict[str, dict[str, Any]],
    *,
    artifact_verified: bool = False,
) -> dict[str, Any]:
    transitions: list[dict[str, Any]] = []
    current = "CREATED"
    missing: list[str] = []
    for stage in STAGE_ORDER:
        if stage not in stages:
            missing.append(stage)
            continue
        if missing:
            # Never jump a failed/missing step. Later observations remain cached
            # evidence but are not promoted into the recoverable Saga state.
            continue
        evidence = evidence_from_stage(workflow_id, stage, stages[stage])
        target = SAGA_STATES[stage]
        transitions.append({
            "from": current,
            "to": target,
            "stage": stage,
            "task_id": workflow_id,
            "nonce": evidence["locator"]["sequence"],
            "timestamp": evidence["timestamp"],
            "evidence_hash": evidence_leaf(evidence),
        })
        current = target
    if artifact_verified and current == "COMPLETE_SIGNED":
        artifact_nonce = max((row["nonce"] for row in transitions), default=0) + 1
        artifact_timestamp = max((row["timestamp"] for row in transitions), default=0) + 1
        artifact_evidence_hash = sha256_hex(canonical_bytes({
            "task_id": workflow_id,
            "state": "ARTIFACT_VERIFIED",
            "prior_transition_hashes": [row["evidence_hash"] for row in transitions],
        }))
        transitions.append({
            "from": current,
            "to": "ARTIFACT_VERIFIED",
            "stage": "ARTIFACT_RECEIPT",
            "task_id": workflow_id,
            "nonce": artifact_nonce,
            "timestamp": artifact_timestamp,
            "evidence_hash": artifact_evidence_hash,
        })
        current = "ARTIFACT_VERIFIED"
    resume_from = missing[0] if missing else ("ARTIFACT_RECEIPT" if current == "COMPLETE_SIGNED" else "DONE")
    return {
        "schema": SAGA_SCHEMA,
        "task_id": workflow_id,
        "state": current,
        "resume_from": resume_from,
        "transitions": transitions,
    }
