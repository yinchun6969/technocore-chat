#!/usr/bin/env python3
"""AI2AI autonomous research scheduler v2.9.

The scheduler is intentionally separate from the existing AI2AI Reviewer
process. It only creates signed, read-only research requests for Love8.
"""

import fcntl
import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path("/opt/technocore-a2a")
STATE = ROOT / "state"
SCHEDULER_STATE = STATE / "autonomous_scheduler.json"
SCHEDULER_LOCK = STATE / "autonomous_scheduler.lock"
SCHEDULER_LOG = STATE / "autonomous_scheduler.log"
AGENT_PATH = ROOT / "bin" / "agent.py"

spec = importlib.util.spec_from_file_location("a2a_agent_runtime", AGENT_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load existing AI2AI agent runtime")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

if getattr(agent, "AGENT", "") != "ai2ai":
    raise SystemExit("autonomous scheduler must run on AGENT_NAME=ai2ai")

LOVE8_DID = "did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p"
DEFAULT_INTERVAL = int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "21600"))
MAX_DAILY = int(os.environ.get("SCHEDULER_MAX_DAILY", "4"))
MAX_ACTIVE = int(os.environ.get("SCHEDULER_MAX_ACTIVE_SECONDS", "14400"))
TICK_SECONDS = int(os.environ.get("SCHEDULER_TICK_SECONDS", "60"))
START_DELAY = int(os.environ.get("SCHEDULER_START_DELAY_SECONDS", "180"))

TOPICS = [
    "检查最近 A2A workflow 是否存在消息丢失、重复投递、顺序异常或 cursor 风险，并提出只读验证建议",
    "审查 public room 中最近 workflow 的 provenance 证据是否完整、可验证且没有重复贡献",
    "研究 DNS、HTTP 超时、429 和 AI 接口重试对三 VPS A2A 稳定性的影响，提出低风险改进建议",
    "评估 Scout、Builder、Reviewer 三阶段是否存在证据不足、职责重叠或恢复遗漏",
    "检查 fallback inbox、challenge recovery 和 endgame recovery 的一致性与可观测性",
    "研究如何提升 technocore 项目技术贡献的真实性、可复现性和公开验证价值",
]


def now() -> float:
    return time.time()


def utc_day(ts=None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now() if ts is None else ts))


def load_state():
    default = {
        "version": "2.9",
        "paused": False,
        "boot_at": 0,
        "topic_index": 0,
        "last_tick": 0,
        "last_request_at": 0,
        "last_completion_at": 0,
        "active": None,
        "daily": {},
        "last_error": "",
    }
    try:
        value = json.loads(SCHEDULER_STATE.read_text())
        if isinstance(value, dict):
            default.update(value)
    except Exception:
        pass
    return default


def save_state(value):
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULER_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n")
    tmp.replace(SCHEDULER_STATE)


def log(message):
    STATE.mkdir(parents=True, exist_ok=True)
    with SCHEDULER_LOG.open("a") as handle:
        handle.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {message}\n")


def ledger(event, **fields):
    try:
        agent.ledger(event, **fields)
    except Exception as exc:
        log(f"ledger_error={str(exc)[:180]}")


def recent_evidence():
    events = []
    ledger_path = getattr(agent, "LEDGER_PATH", STATE / "provenance.jsonl")
    try:
        for raw in ledger_path.read_text().splitlines()[-100:]:
            try:
                rec = json.loads(raw)
                item = str(rec.get("event", "unknown"))
                if rec.get("error"):
                    item += ": " + str(rec["error"])[:120]
                events.append(item)
            except Exception:
                continue
    except Exception as exc:
        events.append("local-ledger-read-error:" + str(exc)[:100])

    public_events = []
    try:
        response = requests.get(
            f"{agent.BASE}/r/d-aizong",
            params={"format": "json", "limit": 60},
            timeout=20,
        )
        response.raise_for_status()
        for message in response.json().get("messages", []):
            text = message.get("text", "")
            kind = "plain"
            if isinstance(text, str) and text.startswith("A2A1 "):
                try:
                    kind = str(json.loads(text[5:]).get("type", "a2a"))
                except Exception:
                    kind = "a2a-invalid"
            public_events.append(kind)
    except Exception as exc:
        public_events.append("public-room-read-error:" + str(exc)[:100])

    commits = []
    try:
        response = requests.get(
            "https://api.github.com/repos/yinchun6969/technocore-chat/commits",
            params={"sha": "a2a-collab-v2", "per_page": 8},
            headers={"Accept": "application/vnd.github+json"},
            timeout=20,
        )
        response.raise_for_status()
        for item in response.json():
            commit = item.get("commit", {})
            message = " ".join(str(commit.get("message", "")).splitlines()).strip()
            date = str(commit.get("committer", {}).get("date", ""))[:19]
            if message:
                commits.append(f"{date} {message[:180]}")
    except Exception as exc:
        commits.append("github-read-error:" + str(exc)[:100])

    return (
        "Recent local event types: "
        + ", ".join(events[-30:])
        + ". Recent public d-aizong message types: "
        + ", ".join(public_events[-30:])
        + ". Recent GitHub commit subjects: "
        + "; ".join(commits[-8:])
    )[:3600]


def safe_goal(seed, evidence):
    prompt = (
        "You are the autonomous research scheduler for a signed A2A project. "
        "Choose one concrete, low-risk, read-only technical research objective. "
        "Use the candidate and evidence below. Do not output commands, URLs, "
        "credentials, financial claims, or instructions to change a server. "
        "Return one concise objective only, under 700 characters.\n"
        "CANDIDATE:\n"
        + seed
        + "\nEVIDENCE:\n"
        + evidence
    )
    try:
        result = str(agent.ai_call(prompt)).strip()
        result = " ".join(result.split())
        blocked = ("rm -rf", "sudo ", "ssh ", "api key", "private key", "password")
        if result and len(result) <= 700 and not any(x in result.lower() for x in blocked):
            return result
    except Exception as exc:
        log(f"topic_model_fallback={str(exc)[:180]}")
    return "自主研究：" + seed


def completion_seen_after(timestamp):
    ledger_path = getattr(agent, "LEDGER_PATH", STATE / "provenance.jsonl")
    try:
        for raw in ledger_path.read_text().splitlines()[-300:]:
            try:
                record = json.loads(raw)
            except Exception:
                continue
            if float(record.get("ts", 0)) < timestamp:
                continue
            if record.get("event") in (
                "workflow_complete_received",
                "workflow_complete_recovered",
                "workflow_complete",
            ):
                return True
    except Exception:
        return False
    return False


def send_scheduler_request(goal, topic, cycle):
    peers = agent.peers()
    mailbox = peers.get(LOVE8_DID)
    if not mailbox:
        raise RuntimeError("Love8 DID is not pinned in AI2AI peers.json")
    request_id = (
        f"sched-{int(now())}-"
        f"{hashlib.sha256((agent.DID + goal + str(cycle)).encode()).hexdigest()[:10]}"
    )
    message = agent.payload(
        "SCHEDULER_REQUEST",
        request_id,
        goal=goal[:1200],
        origin="ai2ai-scheduler",
        scheduler_did=agent.DID,
        scheduler_role="reviewer",
        cycle=cycle,
    )
    agent.signed_post(mailbox, message)
    ledger(
        "scheduler_request_sent",
        request_id=request_id,
        peer_did=LOVE8_DID,
        topic=topic[:300],
        goal_sha256=hashlib.sha256(goal.encode()).hexdigest(),
    )
    return request_id


def tick():
    state = load_state()
    current = now()
    state["last_tick"] = current

    if not state.get("boot_at"):
        state["boot_at"] = current
        save_state(state)
        log(f"startup_delay_seconds={START_DELAY}")
        return
    if current - float(state.get("boot_at", current)) < START_DELAY:
        save_state(state)
        return

    if state.get("paused"):
        save_state(state)
        return

    active = state.get("active")
    if isinstance(active, dict):
        sent_at = float(active.get("sent_at", 0))
        if sent_at and completion_seen_after(sent_at):
            state["active"] = None
            state["last_completion_at"] = current
            ledger(
                "scheduler_cycle_complete",
                request_id=active.get("request_id", ""),
            )
            log("cycle_complete")
        elif sent_at and current - sent_at < MAX_ACTIVE:
            save_state(state)
            return
        else:
            ledger(
                "scheduler_active_timeout",
                request_id=active.get("request_id", ""),
            )
            log("active_timeout")
            state["active"] = None

    last_request = float(state.get("last_request_at", 0))
    if current - last_request < DEFAULT_INTERVAL:
        save_state(state)
        return

    day = utc_day(current)
    daily = state.get("daily", {})
    if not isinstance(daily, dict):
        daily = {}
    daily = {key: value for key, value in daily.items() if key >= utc_day(current - 86400 * 3)}
    if int(daily.get(day, 0)) >= MAX_DAILY:
        state["daily"] = daily
        save_state(state)
        return

    index = int(state.get("topic_index", 0)) % len(TOPICS)
    seed = TOPICS[index]
    evidence = recent_evidence()
    goal = safe_goal(seed, evidence)
    cycle = int(daily.get(day, 0)) + 1
    request_id = send_scheduler_request(goal, seed, cycle)

    state["topic_index"] = (index + 1) % len(TOPICS)
    state["last_request_at"] = current
    state["daily"] = {**daily, day: cycle}
    state["active"] = {
        "request_id": request_id,
        "sent_at": current,
        "topic": seed,
        "goal": goal,
    }
    state["last_error"] = ""
    save_state(state)
    log(f"request_sent id={request_id} topic={seed[:120]}")


def daemon():
    STATE.mkdir(parents=True, exist_ok=True)
    with SCHEDULER_LOCK.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        log("scheduler_started")
        while True:
            try:
                tick()
            except Exception as exc:
                state = load_state()
                state["last_error"] = str(exc)[:500]
                save_state(state)
                ledger("scheduler_error", error=str(exc)[:500])
                log(f"error={str(exc)[:500]}")
            time.sleep(max(15, TICK_SECONDS))


def status():
    state = load_state()
    active = state.get("active")
    print("scheduler: autonomous-v2.9")
    print("agent:", getattr(agent, "AGENT", "unknown"))
    print("did:", getattr(agent, "DID", "unknown"))
    print("love8_pinned:", bool(agent.peers().get(LOVE8_DID)))
    print("paused:", bool(state.get("paused")))
    print("interval_seconds:", DEFAULT_INTERVAL)
    print("startup_delay_seconds:", START_DELAY)
    print("max_daily:", MAX_DAILY)
    print("active:", "yes" if isinstance(active, dict) else "no")
    if isinstance(active, dict):
        print("active_request_id:", active.get("request_id", ""))
        print("active_age_seconds:", int(max(0, now() - float(active.get("sent_at", now())))))
    print("daily:", json.dumps(state.get("daily", {}), ensure_ascii=True, sort_keys=True))
    print("last_error:", state.get("last_error", ""))
    print("state:", SCHEDULER_STATE)


def set_paused(value):
    state = load_state()
    state["paused"] = value
    save_state(state)
    ledger("scheduler_paused" if value else "scheduler_resumed")
    print("paused:", value)


def reset_active():
    state = load_state()
    old = state.get("active")
    state["active"] = None
    state["last_error"] = ""
    save_state(state)
    ledger("scheduler_active_reset", request_id=(old or {}).get("request_id", ""))
    print("active reset")


if __name__ == "__main__":
    command = os.sys.argv[1] if len(os.sys.argv) > 1 else "status"
    if command == "run":
        daemon()
    elif command == "status":
        status()
    elif command == "pause":
        set_paused(True)
    elif command == "resume":
        set_paused(False)
    elif command == "reset-active":
        reset_active()
    else:
        raise SystemExit("usage: scheduler.py run|status|pause|resume|reset-active")
