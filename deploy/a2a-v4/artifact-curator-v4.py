#!/usr/bin/env python3
"""Technocore autonomous R&D artifact curator v4.0.

Runs only on the existing ai2ai Reviewer VPS. It watches the already-existing
signed three-agent workflow, creates one evidence-backed local artifact for
completed workflows, and optionally publishes a compact signed hash receipt to
the existing d-ai2ai room.

It never creates a DID, room, mailbox, GitHub PR, social post, or upstream write.
"""

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
STATE = ROOT / "state"
ARTIFACTS = ROOT / "artifacts"
RUNTIME = ROOT / "bin" / "agent.py"
STATE_FILE = STATE / "artifact_curator_v4.json"
LOCK_FILE = STATE / "artifact_curator_v4.lock"
LOG_FILE = STATE / "artifact_curator_v4.log"

spec = importlib.util.spec_from_file_location("a2a_runtime", RUNTIME)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load existing ai2ai runtime")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

if getattr(agent, "AGENT", "") != "ai2ai":
    raise SystemExit("artifact curator must run on ai2ai")

requests = agent.requests
LOVE8_DID = "did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p"
AIZONG_DID = "did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e"
AI2AI_DID = "did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje"
RECEIPT_ROOM = "d-ai2ai"
POLL_SECONDS = int(os.environ.get("CURATOR_POLL_SECONDS", "120"))
PUBLISH_RECEIPTS = os.environ.get("CURATOR_PUBLISH_RECEIPTS", "1") == "1"

EXPECTED = {
    "WORKFLOW_TASK": LOVE8_DID,
    "BUILD_RESULT": AIZONG_DID,
    "CHALLENGE": AI2AI_DID,
    "REVISED_RESULT": AIZONG_DID,
    "COMPLETE": LOVE8_DID,
}


def log(message):
    STATE.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as handle:
        handle.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {message}\n")


def ledger(event, **fields):
    try:
        agent.ledger(event, **fields)
    except Exception as exc:
        log("ledger_error=" + str(exc)[:180])


def clean(value, limit):
    return " ".join(str(value or "").split())[:limit]


def load_state():
    default = {"version": "4.0", "artifacts": {}, "last_error": ""}
    try:
        value = json.loads(STATE_FILE.read_text())
        if isinstance(value, dict):
            default.update(value)
    except Exception:
        pass
    return default


def save_state(value):
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n")
    tmp.replace(STATE_FILE)


def room_messages(room):
    response = requests.get(
        f"{agent.BASE}/r/{quote(room)}",
        params={"format": "json", "limit": 200},
        timeout=25,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("messages", []) if isinstance(body, dict) else []


def parse_message(message):
    text = message.get("text")
    if not isinstance(text, str):
        return None
    try:
        return agent.parse(text)
    except Exception:
        return None


def rooms():
    values = [RECEIPT_ROOM, "d-aizong", getattr(agent, "MAILBOX", "")]
    try:
        values.extend(agent.peers().values())
    except Exception:
        pass
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def scan():
    workflows = {}
    malformed = {}
    for room in rooms():
        try:
            messages = room_messages(room)
        except Exception as exc:
            log(f"room_read_error room={room} error={str(exc)[:160]}")
            continue
        for message in messages:
            sender = message.get("from", "")
            text = message.get("text", "")
            obj = parse_message(message)
            if obj and obj.get("type") in EXPECTED:
                tid = clean(obj.get("task_id", ""), 128)
                typ = obj.get("type")
                if not tid.startswith("wf-") or sender != EXPECTED[typ]:
                    continue
                seq = int(message.get("seq", 0) or 0)
                current = workflows.setdefault(tid, {}).get(typ)
                if current is None or seq > current["seq"]:
                    workflows[tid][typ] = {
                        "room": room,
                        "seq": seq,
                        "from": sender,
                        "obj": obj,
                    }
            elif isinstance(text, str) and text.startswith("A2A1 ") and "wf-" in text:
                for token in text.replace('"', ' ').replace(',', ' ').split():
                    if token.startswith("wf-"):
                        malformed.setdefault(token[:128], []).append(
                            {"room": room, "seq": int(message.get("seq", 0) or 0)}
                        )
                        break
    return workflows, malformed


def complete(stages):
    return all(kind in stages for kind in EXPECTED)


def field(stages, kind, name, limit):
    return clean(stages.get(kind, {}).get("obj", {}).get(name, ""), limit)


def prompt(tid, stages):
    return (
        "Create a concise engineering research artifact from a completed signed "
        "three-agent Technocore workflow. Do not invent observations, tests, or execution. "
        "Separate verified evidence from design recommendations. Include these exact "
        "Markdown sections: # Title, ## Objective, ## Verified Evidence, ## Findings, "
        "## Design Proposal, ## Minimal Test Matrix, ## Open Questions, ## Provenance. "
        "Mention the workflow id. The artifact must be useful without any airdrop/reward "
        "context. Target 1400-5000 characters.\n\n"
        f"WORKFLOW: {tid}\n\n"
        "TASK:\n" + field(stages, "WORKFLOW_TASK", "goal", 1000) + "\n\n"
        "BUILD:\n" + field(stages, "BUILD_RESULT", "build_result", 1500) + "\n\n"
        "REVIEW CHALLENGE:\n" + field(stages, "CHALLENGE", "challenge", 1300) + "\n\n"
        "REVISED RESULT:\n" + field(stages, "REVISED_RESULT", "revised_result", 1600) + "\n\n"
        "FINAL SUMMARY:\n" + field(stages, "COMPLETE", "final_summary", 1100)
    )[:9000]


def quality(text, stages):
    score = 50 if complete(stages) else 0
    if field(stages, "CHALLENGE", "challenge", 220):
        score += 10
    if field(stages, "REVISED_RESULT", "revised_result", 220):
        score += 10
    if 1200 <= len(text) <= 7000:
        score += 10
    if all(section in text for section in ("Verified Evidence", "Minimal Test Matrix", "Open Questions")):
        score += 20
    return min(100, score)


def payload_hash(obj):
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def receipt_for(tid, text, score, stages, malformed):
    stage_meta = {}
    for kind, item in stages.items():
        stage_meta[kind] = {
            "from": item["from"],
            "room": item["room"],
            "seq": item["seq"],
            "payload_sha256": payload_hash(item["obj"]),
        }
    return {
        "version": "4.0",
        "workflow_id": tid,
        "artifact_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "quality_score": score,
        "stage_count": len(stage_meta),
        "stages": stage_meta,
        "malformed_envelopes_observed": malformed[-20:],
        "created_at": int(time.time()),
        "policy": {
            "auto_pr": False,
            "auto_social_post": False,
            "auto_server_change": False,
            "public_hash_receipt": PUBLISH_RECEIPTS,
        },
    }


def receipt_seen(tid, sha256):
    try:
        for message in room_messages(RECEIPT_ROOM):
            obj = parse_message(message)
            if (
                obj
                and message.get("from") == AI2AI_DID
                and obj.get("type") == "ARTIFACT_RECEIPT"
                and obj.get("task_id") == tid
                and obj.get("artifact_sha256") == sha256
            ):
                return True
    except Exception:
        pass
    return False


def publish_receipt(tid, receipt):
    sha256 = receipt["artifact_sha256"]
    if not PUBLISH_RECEIPTS or receipt_seen(tid, sha256):
        return
    message = agent.payload(
        "ARTIFACT_RECEIPT",
        tid,
        artifact_sha256=sha256,
        quality_score=receipt["quality_score"],
        stage_count=receipt["stage_count"],
        origin="ai2ai-autonomous-rnd-v4",
        promotion="manual-review-required",
    )
    agent.signed_post(RECEIPT_ROOM, message)
    ledger("artifact_receipt_published", workflow_id=tid, artifact_sha256=sha256)


def create_artifact(tid, stages, malformed):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    md_path = ARTIFACTS / f"{tid}.md"
    json_path = ARTIFACTS / f"{tid}.json"
    if md_path.exists() and json_path.exists():
        return json.loads(json_path.read_text())

    text = str(agent.ai_call(prompt(tid, stages))).strip()
    if len(text) > 7000:
        text = text[:7000]
    score = quality(text, stages)
    if len(text) < 1000 or score < 80:
        raise RuntimeError(f"artifact quality gate failed score={score} length={len(text)}")

    receipt = receipt_for(tid, text, score, stages, malformed)
    md_path.write_text(text.rstrip() + "\n")
    json_path.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n")
    os.chmod(md_path, 0o640)
    os.chmod(json_path, 0o640)
    ledger(
        "artifact_created",
        workflow_id=tid,
        artifact_sha256=receipt["artifact_sha256"],
        quality_score=score,
        path=str(md_path),
    )
    try:
        publish_receipt(tid, receipt)
    except Exception as exc:
        log("receipt_publish_error=" + str(exc)[:240])
    return receipt


def tick():
    state = load_state()
    workflows, malformed = scan()
    created = state.setdefault("artifacts", {})
    for tid in sorted(workflows):
        if tid in created or not complete(workflows[tid]):
            continue
        receipt = create_artifact(tid, workflows[tid], malformed.get(tid, []))
        created[tid] = {
            "artifact_sha256": receipt["artifact_sha256"],
            "quality_score": receipt["quality_score"],
            "created_at": receipt["created_at"],
        }
        state["last_error"] = ""
        save_state(state)
        log(f"artifact_ready workflow={tid} score={receipt['quality_score']}")
    save_state(state)


def daemon():
    STATE.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        log("artifact_curator_v4_started")
        while True:
            try:
                tick()
            except Exception as exc:
                state = load_state()
                state["last_error"] = str(exc)[:500]
                save_state(state)
                ledger("artifact_curator_error", error=str(exc)[:500])
                log("error=" + str(exc)[:500])
            time.sleep(max(30, POLL_SECONDS))


def status():
    state = load_state()
    print("artifact_curator: v4.0")
    print("agent:", agent.AGENT)
    print("did:", agent.DID)
    print("artifact_dir:", ARTIFACTS)
    print("artifacts:", len(state.get("artifacts", {})))
    print("publish_receipts:", PUBLISH_RECEIPTS)
    print("poll_seconds:", POLL_SECONDS)
    print("last_error:", state.get("last_error", ""))
    print("policy: no-auto-PR, no-auto-social, no-auto-server-change")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "run":
        daemon()
    elif command == "tick":
        tick()
    elif command == "status":
        status()
    else:
        raise SystemExit("usage: artifact-curator-v4.py run|tick|status")
