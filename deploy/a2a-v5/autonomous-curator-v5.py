#!/usr/bin/env python3
"""Evidence curator for completed, signed v5 research workflows."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path("/opt/technocore-a2a")
RUNTIME = ROOT / "bin" / "agent.py"
STATE = ROOT / "rnd-v5-state"
ARTIFACTS = ROOT / "rnd-v5-artifacts"
STATE_FILE = STATE / "curator.json"
LOG_FILE = STATE / "curator.log"
LOCK_FILE = STATE / "curator.lock"

spec = importlib.util.spec_from_file_location("existing_a2a_agent", RUNTIME)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load existing AI2AI runtime")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)
if getattr(agent, "AGENT", "") != "ai2ai":
    raise SystemExit("curator must run on AGENT_NAME=ai2ai")

requests = agent.requests
BASE = getattr(agent, "BASE", "https://technocore.chat")
LOVE8_DID = "did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p"
AIZONG_DID = "did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e"
AI2AI_DID = "did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje"
RECEIPT_ROOM = "d-ai2ai"
POLL_SECONDS = max(30, int(os.environ.get("RND_V5_CURATOR_POLL_SECONDS", "120")))
PUBLISH = os.environ.get("RND_V5_PUBLISH_RECEIPTS", "1") == "1"
EXPECTED = {
    "WORKFLOW_TASK": LOVE8_DID,
    "BUILD_RESULT": AIZONG_DID,
    "CHALLENGE": AI2AI_DID,
    "REVISED_RESULT": AIZONG_DID,
    "COMPLETE": LOVE8_DID,
}


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
    value = {"version": "5.0", "artifacts": {}, "last_error": ""}
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


def room_messages(room: str) -> list[dict]:
    response = requests.get(
        f"{BASE}/r/{quote(room)}", params={"format": "json", "limit": 250},
        timeout=25, headers={"User-Agent": "technocore-a2a-rnd-v5-curator/1.0"},
    )
    response.raise_for_status()
    body = response.json()
    return body.get("messages", []) if isinstance(body, dict) else []


def rooms() -> list[str]:
    values = [RECEIPT_ROOM, "d-aizong"]
    try:
        values.extend(str(value) for value in agent.peers().values())
    except Exception:
        pass
    return list(dict.fromkeys(value for value in values if value))


def scan() -> dict[str, dict]:
    workflows: dict[str, dict] = {}
    for room in rooms():
        try:
            messages = room_messages(room)
        except Exception as exc:
            log("room_read_error", room=room, error=clean(exc, 180))
            continue
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
            old = workflows.setdefault(task_id, {}).get(obj["type"])
            if old is None or seq > old["seq"]:
                workflows[task_id][obj["type"]] = {"seq": seq, "from": message.get("from"), "room": room, "obj": obj}
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


def artifact_prompt(task_id: str, stages: dict) -> str:
    return (
        "你是证据审计员。根据以下五个已验签阶段生成一份工程研究档案。绝不编造测试、"
        "执行结果或观察；把建议和已验证事实分开。必须明确列出至少两个独立来源的交叉对比，"
        "若证据不足要标记为未验证。严格使用这些 Markdown 标题：# Title, ## Objective, "
        "## Verified Evidence, ## Cross-Validation, ## Findings, ## Design Proposal, "
        "## Minimal Test Matrix, ## Open Questions, ## Provenance。不得包含凭据，不要求自动改动。\n\n"
        f"WORKFLOW: {task_id}\nTASK:\n{field(stages, 'WORKFLOW_TASK', 'goal')}\n\n"
        f"BUILDER:\n{field(stages, 'BUILD_RESULT', 'build_result')}\n\n"
        f"REVIEWER:\n{field(stages, 'CHALLENGE', 'challenge')}\n\n"
        f"REVISION:\n{field(stages, 'REVISED_RESULT', 'revised_result')}\n\n"
        f"SCOUT FINAL:\n{field(stages, 'COMPLETE', 'final_summary')}"
    )[:11000]


def payload_hash(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def receipt(task_id: str, text: str, score: int, stages: dict) -> dict:
    stage_meta = {
        kind: {"from": item["from"], "room": item["room"], "seq": item["seq"], "payload_sha256": payload_hash(item["obj"])}
        for kind, item in stages.items()
    }
    return {
        "version": "5.0", "workflow_id": task_id,
        "artifact_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "cross_validation_score": score, "stage_count": len(stage_meta), "stages": stage_meta,
        "created_at": int(time.time()),
        "policy": {"read_only": True, "auto_pr": False, "auto_server_change": False, "auto_social_post": False},
    }


def publish(task_id: str, value: dict) -> None:
    if not PUBLISH:
        return
    message = agent.payload(
        "ARTIFACT_RECEIPT", task_id,
        artifact_sha256=value["artifact_sha256"], quality_score=value["cross_validation_score"],
        stage_count=value["stage_count"], origin="ai2ai-rnd-v5", promotion="manual-review-required",
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
        return json.loads(json_path.read_text(encoding="utf-8"))
    score = cross_validation_score(stages)
    if score < 80:
        raise RuntimeError(f"cross-validation evidence gate failed score={score}")
    text = str(agent.ai_call(artifact_prompt(task_id, stages))).strip()
    required = ("Verified Evidence", "Cross-Validation", "Minimal Test Matrix", "Open Questions", "Provenance")
    if len(text) < 1200 or len(text) > 8000 or not all(item in text for item in required):
        raise RuntimeError("artifact format/length gate failed")
    value = receipt(task_id, text, score, stages)
    md_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.chmod(md_path, 0o640)
    os.chmod(json_path, 0o640)
    ledger("rnd_artifact_created", workflow_id=task_id, artifact_sha256=value["artifact_sha256"], score=score)
    try:
        publish(task_id, value)
    except Exception as exc:
        log("receipt_publish_error", error=clean(exc, 220))
    return value


def tick() -> None:
    state = load_state()
    for task_id, stages in sorted(scan().items()):
        if task_id in state.setdefault("artifacts", {}) or not complete(stages):
            continue
        try:
            value = create(task_id, stages)
            state["artifacts"][task_id] = {"sha256": value["artifact_sha256"], "score": value["cross_validation_score"], "created_at": value["created_at"]}
            state["last_error"] = ""
            save_state(state)
            log("artifact_ready", workflow_id=task_id, score=value["cross_validation_score"])
        except Exception as exc:
            state["last_error"] = clean(exc, 500)
            ledger("rnd_artifact_rejected", workflow_id=task_id, error=state["last_error"])
            log("artifact_rejected", workflow_id=task_id, error=state["last_error"])
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
