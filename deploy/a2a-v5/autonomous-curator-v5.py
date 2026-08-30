#!/usr/bin/env python3
"""Evidence curator for completed, signed v5 research workflows."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(os.environ.get("TECHNOCORE_A2A_ROOT", "/opt/technocore-a2a"))
RUNTIME = ROOT / "bin" / "agent.py"
STATE = ROOT / "rnd-v5-state"
ARTIFACTS = ROOT / "rnd-v5-artifacts"
STATE_FILE = STATE / "curator.json"
CACHE_FILE = STATE / "curator-stage-cache.json"
LOG_FILE = STATE / "curator.log"
LOCK_FILE = STATE / "curator.lock"

spec = importlib.util.spec_from_file_location("existing_a2a_agent", RUNTIME)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load existing AI2AI runtime")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)
if getattr(agent, "AGENT", "") != "ai2ai":
    raise SystemExit("curator must run on AGENT_NAME=ai2ai")

evidence_spec = importlib.util.spec_from_file_location(
    "technocore_evidence_v55", Path(__file__).resolve().with_name("evidence_v55.py")
)
if evidence_spec is None or evidence_spec.loader is None:
    raise SystemExit("cannot load evidence_v55.py")
evidence_v55 = importlib.util.module_from_spec(evidence_spec)
evidence_spec.loader.exec_module(evidence_v55)

requests = agent.requests
BASE = getattr(agent, "BASE", "https://technocore.chat")
LOVE8_DID = "did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p"
AIZONG_DID = "did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e"
AI2AI_DID = "did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje"
RECEIPT_ROOM = "d-ai2ai"
POLL_SECONDS = max(30, int(os.environ.get("RND_V5_CURATOR_POLL_SECONDS", "120")))
ROOM_LIMIT = min(200, max(50, int(os.environ.get("RND_V5_CURATOR_ROOM_LIMIT", "200"))))
ROOM_RETRIES = min(5, max(1, int(os.environ.get("RND_V5_CURATOR_ROOM_RETRIES", "3"))))
CACHE_MAX_WORKFLOWS = max(20, int(os.environ.get("RND_V5_CURATOR_CACHE_WORKFLOWS", "120")))
PUBLISH = os.environ.get("RND_V5_PUBLISH_RECEIPTS", "1") == "1"
MAX_ARTIFACT_ATTEMPTS_PER_TICK = max(
    1, min(3, int(os.environ.get("RND_V5_ARTIFACT_ATTEMPTS_PER_TICK", "1")))
)
RETRY_DELAYS = (120, 300, 900, 1800, 3600)
EXPECTED = {
    "WORKFLOW_TASK": LOVE8_DID,
    "BUILD_RESULT": AIZONG_DID,
    "CHALLENGE": AI2AI_DID,
    "REVISED_RESULT": AIZONG_DID,
    "COMPLETE": LOVE8_DID,
}

REQUIRED_ARTIFACT_HEADINGS = (
    "# Title", "## Objective", "## Verified Evidence", "## Cross-Validation",
    "## Findings", "## Design Proposal", "## Minimal Test Matrix",
    "## Open Questions", "## Provenance",
)


class ArtifactGateError(RuntimeError):
    """A model response exists but is not a valid workflow-bound artifact."""


class ReceiptVerificationError(RuntimeError):
    """A persisted receipt or artifact failed deterministic verification."""


def clean(value: object, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit]


def log(event: str, **fields: object) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "event": event, **fields}
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")


def ledger(event: str, **fields: object) -> None:
    try:
        agent.ledger(event, **fields)
    except Exception as exc:
        log("ledger_error", error=clean(exc, 180), source_event=event)


def load_state() -> dict:
    value = {"version": "5.5", "artifacts": {}, "sagas": {}, "last_error": ""}
    try:
        loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            value.update(loaded)
    except (OSError, ValueError, TypeError):
        pass
    return value


def save_state(value: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE_FILE)


def load_cache_document() -> dict:
    try:
        loaded = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"workflows": {}, "room_cursors": {}}
    return loaded if isinstance(loaded, dict) else {"workflows": {}, "room_cursors": {}}


def load_cache() -> dict[str, dict]:
    loaded = load_cache_document()
    workflows = loaded.get("workflows", {}) if isinstance(loaded, dict) else {}
    if not isinstance(workflows, dict):
        return {}
    return {
        str(task_id): stages for task_id, stages in workflows.items()
        if str(task_id).startswith("wf-") and isinstance(stages, dict)
    }


def load_room_cursors() -> dict[str, int]:
    values = load_cache_document().get("room_cursors", {})
    if not isinstance(values, dict):
        return {}
    result: dict[str, int] = {}
    for room, value in values.items():
        try:
            cursor = int(value)
        except (TypeError, ValueError):
            continue
        if room and cursor >= 0:
            result[str(room)] = cursor
    return result


def save_cache(workflows: dict[str, dict], room_cursors: dict[str, int] | None = None) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    ranked = sorted(
        workflows.items(),
        key=lambda item: max(
            (float(stage.get("seen_at", 0) or 0) for stage in item[1].values() if isinstance(stage, dict)),
            default=0,
        ),
        reverse=True,
    )[:CACHE_MAX_WORKFLOWS]
    value = {
        "version": "5.5",
        "workflows": dict(ranked),
        "room_cursors": room_cursors if room_cursors is not None else load_room_cursors(),
        "updated_at": int(time.time()),
    }
    temporary = CACHE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, CACHE_FILE)


def parse(message: dict) -> dict | None:
    text = message.get("text")
    if not isinstance(text, str):
        return None
    try:
        value = agent.parse(text)
    except Exception:
        try:
            value = json.loads(text[5:]) if text.startswith("A2A1 ") else None
        except (ValueError, TypeError):
            value = None
    return value if isinstance(value, dict) else None


def room_messages(room: str, since: int | None = None) -> dict:
    last_error: Exception | None = None
    for attempt in range(ROOM_RETRIES):
        try:
            params: dict[str, object] = {"format": "json", "limit": ROOM_LIMIT}
            if since is not None:
                params["since"] = since
            response = requests.get(
                f"{BASE}/r/{quote(room)}", params=params,
                timeout=25, headers={"User-Agent": "technocore-a2a-rnd-v5-curator/1.1"},
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("messages", []), list):
                raise ValueError("invalid room JSON")
            return body
        except Exception as exc:
            last_error = exc
            if attempt + 1 < ROOM_RETRIES:
                time.sleep(min(4, 2 ** attempt))
    assert last_error is not None
    raise last_error


def sequence_gap(body: dict, since: int | None) -> tuple[int, int] | None:
    """Return the missing inclusive sequence range without advancing a cursor."""
    if since is None:
        return None
    messages = body.get("messages", [])
    sequences = sorted({
        int(row.get("seq", 0) or 0) for row in messages
        if isinstance(row, dict) and str(row.get("seq", "")).isdigit()
    })
    try:
        last_seq = int(body.get("last_seq", since) or since)
    except (TypeError, ValueError):
        last_seq = since
    if last_seq <= since:
        return None
    if not sequences:
        return since + 1, last_seq
    expected = since + 1
    for sequence in sequences:
        if sequence < expected:
            continue
        if sequence > expected:
            return expected, sequence - 1
        expected += 1
    if expected <= last_seq:
        return expected, last_seq
    return None


def rooms() -> list[str]:
    values = [RECEIPT_ROOM, "d-aizong"]
    try:
        values.extend(str(value) for value in agent.peers().values())
    except Exception:
        pass
    return list(dict.fromkeys(value for value in values if value))


def scan() -> dict[str, dict]:
    # A workflow spans several public rooms.  Preserve successfully observed,
    # sender-checked stages across polling rounds so intermittent 503s in one
    # room cannot erase evidence collected from another room in a prior round.
    workflows: dict[str, dict] = load_cache()
    room_cursors = load_room_cursors()
    observed_at = time.time()
    failed_rooms: list[str] = []
    for room in rooms():
        try:
            body = room_messages(room, room_cursors.get(room))
        except Exception as exc:
            error = clean(exc, 180)
            failed_rooms.append(room)
            log(
                "room_read_error", room=room, error_type=classify_error(exc),
                error=error, decision="cached_stages_preserved",
            )
            continue
        messages = body.get("messages", [])
        for message in messages:
            obj = parse(message)
            if not obj or obj.get("type") not in EXPECTED:
                continue
            if message.get("from") != EXPECTED[obj["type"]]:
                continue
            task_id = clean(obj.get("task_id"), 100)
            if not task_id.startswith("wf-"):
                continue
            seq = int(message.get("seq", 0) or 0)
            message_ts = evidence_v55.parse_timestamp(message.get("ts")) or evidence_v55.parse_timestamp(observed_at)
            old = workflows.setdefault(task_id, {}).get(obj["type"])
            old_key = (
                float(old.get("message_ts", 0) or 0), str(old.get("room", "")),
                int(old.get("seq", 0) or 0),
            ) if isinstance(old, dict) else (-1.0, "", -1)
            new_key = (message_ts, room, seq)
            if old is None or new_key > old_key:
                workflows[task_id][obj["type"]] = {
                    "seq": seq, "from": message.get("from"), "room": room,
                    "obj": obj, "message_ts": message_ts, "seen_at": observed_at,
                }
        gap = sequence_gap(body, room_cursors.get(room))
        if gap:
            log(
                "room_sequence_gap", room=room, cursor=room_cursors.get(room, 0),
                missing_from=gap[0], missing_to=gap[1], decision="cursor_not_advanced",
            )
            continue
        try:
            last_seq = int(body.get("last_seq", room_cursors.get(room, 0)) or 0)
        except (TypeError, ValueError):
            last_seq = room_cursors.get(room, 0)
        room_cursors[room] = max(room_cursors.get(room, 0), last_seq)
    # Workflow stages and room cursors share one atomic checkpoint. A failed
    # room is never advanced, so its unseen messages remain eligible next poll.
    save_cache(workflows, room_cursors)
    cached_complete = sum(1 for stages in workflows.values() if complete(stages))
    if failed_rooms and cached_complete:
        log(
            "cached_complete_workflows_available", failed_rooms=failed_rooms,
            workflow_count=cached_complete, decision="artifact_generation_may_continue",
        )
    return workflows


def field(stages: dict, kind: str, name: str, limit: int = 1800) -> str:
    return clean(stages.get(kind, {}).get("obj", {}).get(name, ""), limit)


def complete(stages: dict) -> bool:
    return all(kind in stages for kind in EXPECTED)


def cross_validation_score(stages: dict) -> int:
    if not complete(stages):
        return 0
    text = " ".join(field(stages, kind, name, 2500) for kind, name in (
        ("WORKFLOW_TASK", "goal"), ("BUILD_RESULT", "build_result"), ("CHALLENGE", "challenge"),
        ("REVISED_RESULT", "revised_result"), ("COMPLETE", "final_summary"),
    )).lower()
    score = 50
    if any(token in text for token in ("cross", "交叉", "独立来源", "independent source")):
        score += 15
    if any(token in text for token in ("evidence", "证据", "provenance", "source")):
        score += 10
    if any(token in text for token in ("test", "verify", "复现", "验证", "反例")):
        score += 10
    if any(token in text for token in ("counter", "challenge", "质疑", "否定")):
        score += 10
    if any(token in text for token in ("confidence", "置信度", "uncertain", "不确定")):
        score += 5
    return min(100, score)


def artifact_prompt(task_id: str, stages: dict, bundle: dict) -> str:
    return (
        "你是证据审计员。根据以下五个已验签阶段生成一份工程研究档案。绝不编造测试、"
        "执行结果或观察；把建议和已验证事实分开。必须明确列出至少两个独立来源的交叉对比，"
        "若证据不足要标记为未验证。严格使用这些 Markdown 标题：# Title, ## Objective, "
        "## Verified Evidence, ## Cross-Validation, ## Findings, ## Design Proposal, "
        "## Minimal Test Matrix, ## Open Questions, ## Provenance。不得包含凭据，不要求自动改动。\n\n"
        f"WORKFLOW: {task_id}\nEVIDENCE_SCHEMA: {bundle['schema']}\n"
        f"EVIDENCE_MERKLE_ROOT: {bundle['merkle_root']}\n"
        f"EVIDENCE_COUNT: {bundle['evidence_count']}\nTASK:\n{field(stages, 'WORKFLOW_TASK', 'goal')}\n\n"
        f"BUILDER:\n{field(stages, 'BUILD_RESULT', 'build_result')}\n\n"
        f"REVIEWER:\n{field(stages, 'CHALLENGE', 'challenge')}\n\n"
        f"REVISION:\n{field(stages, 'REVISED_RESULT', 'revised_result')}\n\n"
        f"SCOUT FINAL:\n{field(stages, 'COMPLETE', 'final_summary')}"
    )[:11000]


def artifact_repair_prompt(task_id: str, bundle: dict, rejected: str) -> str:
    return (
        "Repair the draft below without adding facts. Return only Markdown between 1200 and 8000 characters. "
        "The output must contain each exact heading once and in this order: "
        + ", ".join(REQUIRED_ARTIFACT_HEADINGS)
        + ". It must literally include the workflow ID and evidence Merkle root shown below. "
        "Clearly label unverified claims and never claim commands, writes, deployments, or tests that were not observed.\n\n"
        f"WORKFLOW: {task_id}\nEVIDENCE_MERKLE_ROOT: {bundle['merkle_root']}\n\n"
        "REJECTED_DRAFT:\n" + rejected[:8000]
    )[:11000]


def artifact_text_error(text: str, task_id: str, merkle_root: str) -> str:
    if len(text) < 1200:
        return f"artifact too short length={len(text)}"
    if len(text) > 8000:
        return f"artifact too long length={len(text)}"
    missing = [heading for heading in REQUIRED_ARTIFACT_HEADINGS if heading not in text]
    if missing:
        return "artifact headings missing=" + ",".join(missing)
    positions = [text.index(heading) for heading in REQUIRED_ARTIFACT_HEADINGS]
    if positions != sorted(positions):
        return "artifact headings out of order"
    if task_id not in text:
        return "artifact workflow binding missing"
    if merkle_root not in text:
        return "artifact Merkle binding missing"
    return ""


def generate_artifact_text(task_id: str, stages: dict, bundle: dict) -> str:
    first = str(agent.ai_call(artifact_prompt(task_id, stages, bundle))).strip()
    first_error = artifact_text_error(first, task_id, bundle["merkle_root"])
    if not first_error:
        return first.rstrip() + "\n"
    log(
        "artifact_repair_requested", workflow_id=task_id, error_type="format_gate",
        error=first_error, evidence_hash=bundle["merkle_root"],
    )
    repaired = str(agent.ai_call(artifact_repair_prompt(task_id, bundle, first))).strip()
    repaired_error = artifact_text_error(repaired, task_id, bundle["merkle_root"])
    if repaired_error:
        raise ArtifactGateError(repaired_error)
    return repaired.rstrip() + "\n"


def classify_error(exc: object) -> str:
    message = clean(exc, 500).lower()
    if "503" in message or "service unavailable" in message:
        return "room_503"
    if "timed out" in message or "timeout" in message:
        return "provider_timeout"
    if isinstance(exc, ArtifactGateError) or ("artifact " in message and "gate" in message):
        return "format_gate"
    if isinstance(exc, ReceiptVerificationError):
        return "receipt_verification"
    if isinstance(exc, getattr(evidence_v55, "EvidenceError", ())):
        return "evidence_gate"
    return "runtime_error"


def retry_delay(attempts: int, error_type: str) -> int:
    base = RETRY_DELAYS[min(max(attempts, 1) - 1, len(RETRY_DELAYS) - 1)]
    return min(base, 900) if error_type == "format_gate" else base


def payload_hash(obj: dict) -> str:
    return evidence_v55.payload_hash(obj)


def receipt(task_id: str, text: str, score: int, stages: dict, bundle: dict) -> dict:
    stage_meta = {
        kind: {"from": item["from"], "room": item["room"], "seq": item["seq"], "payload_sha256": payload_hash(item["obj"])}
        for kind, item in stages.items()
    }
    return {
        "version": "5.5.1", "workflow_id": task_id,
        "artifact_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "cross_validation_score": score, "stage_count": len(stage_meta), "stages": stage_meta,
        "evidence_verified": True,
        "evidence_merkle_root": bundle["merkle_root"],
        "evidence_bundle": bundle,
        "saga": evidence_v55.saga_checkpoint(task_id, stages, artifact_verified=True),
        "created_at": int(time.time()),
        "policy": {"read_only": True, "auto_pr": False, "auto_server_change": False, "auto_social_post": False},
    }


def verify_receipt(task_id: str, stages: dict, value: dict, text: str) -> bool:
    if not isinstance(value, dict):
        raise ReceiptVerificationError("receipt is not an object")
    if value.get("workflow_id") != task_id:
        raise ReceiptVerificationError("receipt workflow binding mismatch")
    if value.get("evidence_verified") is not True:
        raise ReceiptVerificationError("receipt is not marked evidence_verified")
    bundle = value.get("evidence_bundle")
    try:
        evidence_v55.verify_bundle(bundle)
        current = evidence_v55.build_bundle(task_id, stages)
    except Exception as exc:
        raise ReceiptVerificationError(f"evidence bundle invalid: {clean(exc, 220)}") from exc
    if bundle != current:
        raise ReceiptVerificationError("receipt evidence does not match current signed stages")
    if value.get("evidence_merkle_root") != current["merkle_root"]:
        raise ReceiptVerificationError("receipt Merkle root mismatch")
    if value.get("artifact_sha256") != hashlib.sha256(text.encode()).hexdigest():
        raise ReceiptVerificationError("artifact SHA256 mismatch")
    if artifact_text_error(text, task_id, current["merkle_root"]):
        raise ReceiptVerificationError("persisted artifact format or binding invalid")
    saga = value.get("saga", {})
    if not isinstance(saga, dict) or saga.get("task_id") != task_id or saga.get("state") != "ARTIFACT_VERIFIED":
        raise ReceiptVerificationError("receipt Saga binding invalid")
    return True


def read_verified_receipt(task_id: str, stages: dict) -> dict:
    md_path = ARTIFACTS / f"{task_id}.md"
    json_path = ARTIFACTS / f"{task_id}.json"
    if not md_path.is_file() or not json_path.is_file():
        raise ReceiptVerificationError("verified artifact pair is incomplete")
    try:
        text = md_path.read_text(encoding="utf-8")
        value = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ReceiptVerificationError(f"artifact pair unreadable: {clean(exc, 180)}") from exc
    verify_receipt(task_id, stages, value, text)
    return value


def preserve_replaced_artifacts(task_id: str, stamp: int) -> None:
    for suffix in ("md", "json"):
        path = ARTIFACTS / f"{task_id}.{suffix}"
        if path.exists():
            archive = ARTIFACTS / f"{task_id}.unverified-{stamp}.{suffix}"
            if not archive.exists():
                shutil.copy2(path, archive)


def atomic_write(path: Path, text: str, mode: int = 0o640) -> None:
    temporary = path.with_name(path.name + ".v551-new")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def publish(task_id: str, value: dict) -> None:
    if not PUBLISH:
        return
    message = agent.payload(
        "ARTIFACT_RECEIPT", task_id,
        artifact_sha256=value["artifact_sha256"], quality_score=value["cross_validation_score"],
        stage_count=value["stage_count"], origin="ai2ai-rnd-v5", promotion="manual-review-required",
        evidence_merkle_root=value["evidence_merkle_root"], evidence_schema=evidence_v55.SCHEMA,
    )
    peers = agent.peers()
    room = peers.get(AI2AI_DID) or RECEIPT_ROOM
    agent.signed_post(room, message)
    ledger("rnd_artifact_receipt_published", workflow_id=task_id, artifact_sha256=value["artifact_sha256"])


def create(task_id: str, stages: dict) -> dict:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    md_path = ARTIFACTS / f"{task_id}.md"
    json_path = ARTIFACTS / f"{task_id}.json"
    if md_path.exists() and json_path.exists():
        try:
            return read_verified_receipt(task_id, stages)
        except ReceiptVerificationError as exc:
            log(
                "artifact_pair_unverified", workflow_id=task_id,
                error_type="receipt_verification", error=clean(exc, 500),
                decision="preserve_then_replace_only_after_new_artifact_verifies",
            )
    bundle = evidence_v55.build_bundle(task_id, stages)
    evidence_v55.verify_bundle(bundle)
    score = cross_validation_score(stages)
    if score < 80:
        raise RuntimeError(f"cross-validation evidence gate failed score={score}")
    text = generate_artifact_text(task_id, stages, bundle)
    value = receipt(task_id, text, score, stages, bundle)
    verify_receipt(task_id, stages, value, text)
    preserve_replaced_artifacts(task_id, int(time.time()))
    atomic_write(md_path, text)
    atomic_write(json_path, json.dumps(value, ensure_ascii=True, indent=2) + "\n")
    ledger(
        "rnd_artifact_created", workflow_id=task_id,
        artifact_sha256=value["artifact_sha256"], score=score,
        evidence_hash=value["evidence_merkle_root"], evidence_verified=True,
    )
    try:
        publish(task_id, value)
    except Exception as exc:
        log("receipt_publish_error", error=clean(exc, 220))
    return value


def tick() -> None:
    state = load_state()
    workflows = scan()
    sagas = state.setdefault("sagas", {})
    if not isinstance(sagas, dict):
        sagas = {}
        state["sagas"] = sagas
    retries = state.setdefault("artifact_retries", {})
    if not isinstance(retries, dict):
        retries = {}
        state["artifact_retries"] = retries
    now = time.time()
    attempted = 0
    ranked = sorted(
        workflows.items(),
        key=lambda item: max(
            (evidence_v55.parse_timestamp(stage.get("message_ts")) for stage in item[1].values() if isinstance(stage, dict)),
            default=0,
        ),
        reverse=True,
    )
    for task_id, stages in ranked:
        sagas[task_id] = evidence_v55.saga_checkpoint(
            task_id, stages, artifact_verified=False,
        )
        if not complete(stages):
            continue
        if task_id in state.setdefault("artifacts", {}):
            try:
                read_verified_receipt(task_id, stages)
                sagas[task_id] = evidence_v55.saga_checkpoint(task_id, stages, artifact_verified=True)
                retries.pop(task_id, None)
                continue
            except Exception as exc:
                state["artifacts"].pop(task_id, None)
                log(
                    "artifact_receipt_invalid", workflow_id=task_id,
                    error_type=classify_error(exc), error=clean(exc, 500),
                    decision="removed_from_verified_index;artifact_files_preserved",
                )
        retry = retries.get(task_id, {}) if isinstance(retries.get(task_id, {}), dict) else {}
        if float(retry.get("next_retry_at", 0) or 0) > now:
            continue
        if attempted >= MAX_ARTIFACT_ATTEMPTS_PER_TICK:
            continue
        attempted += 1
        try:
            value = create(task_id, stages)
            state["artifacts"][task_id] = {"sha256": value["artifact_sha256"], "score": value["cross_validation_score"], "created_at": value["created_at"]}
            sagas[task_id] = value["saga"]
            retries.pop(task_id, None)
            state["last_error"] = ""
            save_state(state)
            log("artifact_ready", workflow_id=task_id, score=value["cross_validation_score"])
        except Exception as exc:
            state["last_error"] = clean(exc, 500)
            error_type = classify_error(exc)
            attempts = int(retry.get("attempts", 0) or 0) + 1
            delay = retry_delay(attempts, error_type)
            retries[task_id] = {
                "attempts": attempts, "error_type": error_type,
                "last_error": state["last_error"], "last_attempt_at": int(now),
                "next_retry_at": int(now + delay),
            }
            evidence_hash = ""
            try:
                evidence_hash = evidence_v55.build_bundle(task_id, stages)["merkle_root"]
            except Exception:
                pass
            ledger(
                "rnd_artifact_rejected", workflow_id=task_id,
                stage=sagas.get(task_id, {}).get("resume_from", "UNKNOWN"),
                signer_did="", evidence_hash=evidence_hash, error_type=error_type,
                retry_attempt=attempts, retry_after_seconds=delay, error=state["last_error"],
            )
            log(
                "artifact_rejected", workflow_id=task_id,
                stage=sagas.get(task_id, {}).get("resume_from", "UNKNOWN"),
                signer_did="", evidence_hash=evidence_hash, error_type=error_type,
                retry_attempt=attempts, retry_after_seconds=delay, error=state["last_error"],
            )
    save_state(state)


def status() -> None:
    state = load_state()
    print("curator: autonomous-rnd-v5")
    print("artifacts:", len(state.get("artifacts", {})))
    print("last_error:", clean(state.get("last_error"), 500))
    print("publish_receipts:", PUBLISH)
    print("policy: cross-validation evidence gate, read-only, manual promotion")


def daemon() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        log("curator_started")
        while True:
            try:
                tick()
            except Exception as exc:
                state = load_state()
                state["last_error"] = clean(exc, 500)
                save_state(state)
                ledger("rnd_curator_error", error=state["last_error"])
                log("curator_error", error=state["last_error"])
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "run":
        daemon()
    elif command == "tick":
        tick()
    elif command == "status":
        status()
    else:
        raise SystemExit("usage: autonomous-curator-v5.py run|tick|status")
