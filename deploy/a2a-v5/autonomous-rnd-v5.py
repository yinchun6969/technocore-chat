#!/usr/bin/env python3
"""Autonomous, evidence-first R&D director for the existing AI2AI node.

This process is deliberately an orchestration layer.  It never changes source
code, opens a PR, changes a VPS, creates an identity, or creates a room.  It
only reads public evidence and sends a signed, read-only request to Love8.
"""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path("/opt/technocore-a2a")
RUNTIME = ROOT / "bin" / "agent.py"
STATE = ROOT / "rnd-v5-state"
STATE_FILE = STATE / "director.json"
LOG_FILE = STATE / "director.log"
LOCK_FILE = STATE / "director.lock"

spec = importlib.util.spec_from_file_location("existing_a2a_agent", RUNTIME)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load existing AI2AI runtime")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

if getattr(agent, "AGENT", "") != "ai2ai":
    raise SystemExit("autonomous R&D director must run on AGENT_NAME=ai2ai")

requests = agent.requests
BASE = getattr(agent, "BASE", "https://technocore.chat")
LOVE8_DID = "did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p"
AIZONG_DID = "did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e"
AI2AI_DID = "did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje"
AIZONG_ROOM = "d-aizong"

DEFAULTS = {
    "RND_V5_TICK_SECONDS": "90",
    "RND_V5_START_DELAY_SECONDS": "180",
    "RND_V5_MIN_GAP_SECONDS": "21600",
    "RND_V5_MAX_DAILY": "4",
    "RND_V5_MAX_ACTIVE_SECONDS": "21600",
    "RND_V5_SOURCE_REPO": "yinchun6969/technocore-chat",
    "RND_V5_UPSTREAM_REPO": "flop-labs/technocore-chat",
    "RND_V5_SOURCE_LOOKBACK": "8",
}

BLOCKED = (
    "rm -rf", "sudo ", "ssh ", "private key", "api key", "password",
    "credential", "systemctl", "deploy", "push", "pull request", "pr ",
    "modify server", "change server", "write to github", "execute command",
)


def setting(name: str) -> str:
    return os.environ.get(name, DEFAULTS.get(name, ""))


def number(name: str, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(setting(name))))
    except (TypeError, ValueError):
        return int(DEFAULTS[name])


def now() -> float:
    return time.time()


def utc_day(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now() if ts is None else ts))


def clean(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def log(event: str, **fields: object) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    row = {"ts": now(), "event": event, **fields}
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")


def ledger(event: str, **fields: object) -> None:
    try:
        agent.ledger(event, **fields)
    except Exception as exc:  # the local director log remains authoritative
        log("ledger_error", error=clean(exc, 220), source_event=event)


def load_state() -> dict:
    default = {
        "version": "5.0",
        "boot_at": now(),
        "paused": False,
        "last_tick": 0,
        "last_request_at": 0,
        "last_error": "",
        "history": [],
        "daily": {},
        "active_request": None,
    }
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            default.update(value)
    except (OSError, ValueError, TypeError):
        pass
    return default


def save_state(value: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE_FILE)


def parse_message(message: dict) -> dict | None:
    text = message.get("text")
    if not isinstance(text, str):
        return None
    try:
        parsed = agent.parse(text)
    except Exception:
        try:
            parsed = json.loads(text[5:]) if text.startswith("A2A1 ") else None
        except (ValueError, TypeError):
            parsed = None
    return parsed if isinstance(parsed, dict) else None


def read_room(room: str, limit: int = 200) -> list[dict]:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.get(
                f"{BASE}/r/{quote(room)}",
                params={"format": "json", "limit": limit},
                timeout=20,
                headers={"User-Agent": "technocore-a2a-rnd-v5/1.0"},
            )
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(8, 2**attempt))
                continue
            response.raise_for_status()
            body = response.json()
            return body.get("messages", []) if isinstance(body, dict) else []
        except Exception as exc:  # noqa: BLE001 - network boundary
            last_error = exc
            time.sleep(min(8, 2**attempt))
    raise RuntimeError(f"room read failed {room}: {clean(last_error, 180)}")


def rooms() -> list[str]:
    values = [AIZONG_ROOM]
    try:
        values.extend(str(value) for value in agent.peers().values())
    except Exception as exc:
        log("peer_map_read_error", error=clean(exc, 180))
    return list(dict.fromkeys(value for value in values if value))


def workflow_snapshot() -> tuple[dict[str, dict], bool]:
    """Return signed stages and whether a workflow is currently in flight."""
    expected = {
        "WORKFLOW_TASK": LOVE8_DID,
        "BUILD_RESULT": AIZONG_DID,
        "CHALLENGE": AI2AI_DID,
        "REVISED_RESULT": AIZONG_DID,
        "COMPLETE": LOVE8_DID,
    }
    workflows: dict[str, dict] = {}
    read_ok = False
    for room in rooms():
        try:
            messages = read_room(room)
            read_ok = True
        except Exception as exc:
            log("evidence_room_error", room=room, error=clean(exc, 180))
            continue
        for message in messages:
            obj = parse_message(message)
            if not obj or obj.get("type") not in expected:
                continue
            task_id = clean(obj.get("task_id"), 120)
            if not task_id.startswith("wf-") or message.get("from") != expected[obj["type"]]:
                continue
            bucket = workflows.setdefault(task_id, {})
            seq = int(message.get("seq", 0) or 0)
            old = bucket.get(obj["type"])
            if old is None or seq > old["seq"]:
                bucket[obj["type"]] = {"seq": seq, "from": message.get("from"), "obj": obj, "room": room}
    active = []
    for task_id, stages in workflows.items():
        if "WORKFLOW_TASK" in stages and "COMPLETE" not in stages:
            active.append((stages["WORKFLOW_TASK"]["seq"], task_id))
    active.sort(reverse=True)
    return workflows, bool(active) if read_ok else True


def local_evidence() -> list[str]:
    values: list[str] = []
    path = getattr(agent, "LEDGER_PATH", ROOT / "state" / "provenance.jsonl")
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]
    except OSError:
        return values
    interesting = ("error", "fail", "timeout", "reject", "recovery", "invalid", "stalled")
    for line in lines:
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        event = clean(row.get("event"), 120)
        if any(token in event.lower() for token in interesting) or row.get("error"):
            values.append(clean(f"{event} workflow={row.get('workflow_id', '')} error={row.get('error', '')}", 260))
    return values[-40:]


def github_json(path: str, params: dict[str, object]) -> object:
    response = requests.get(
        f"https://api.github.com{path}",
        params=params,
        timeout=25,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "technocore-a2a-rnd-v5/1.0"},
    )
    response.raise_for_status()
    return response.json()


def source_evidence() -> list[str]:
    """Collect independent, read-only GitHub signals; failures are evidence too."""
    result: list[str] = []
    lookback = number("RND_V5_SOURCE_LOOKBACK", 3, 12)
    repositories = [setting("RND_V5_SOURCE_REPO")]
    upstream = setting("RND_V5_UPSTREAM_REPO")
    if upstream and upstream not in repositories:
        repositories.append(upstream)
    for repository in repositories:
        try:
            issues = github_json(f"/repos/{repository}/issues", {
                "state": "open", "sort": "updated", "direction": "desc", "per_page": lookback,
            })
            for item in issues if isinstance(issues, list) else []:
                if "pull_request" in item:
                    continue
                labels = ",".join(clean(label.get("name"), 35) for label in item.get("labels", [])[:4])
                result.append(clean(f"ISSUE {repository} #{item.get('number')} labels={labels} title={item.get('title')}", 320))
            commits = github_json(f"/repos/{repository}/commits", {"per_page": lookback})
            for item in commits if isinstance(commits, list) else []:
                message = item.get("commit", {}).get("message", "").splitlines()[0]
                result.append(clean(f"COMMIT {repository} {item.get('sha', '')[:12]} {message}", 320))
            pulls = github_json(f"/repos/{repository}/pulls", {
                "state": "open", "sort": "updated", "direction": "desc", "per_page": lookback,
            })
            for item in pulls if isinstance(pulls, list) else []:
                result.append(clean(f"OPEN_PR {repository} #{item.get('number')} {item.get('title')}", 320))
            runs = github_json(f"/repos/{repository}/actions/runs", {"status": "failure", "per_page": lookback})
            for item in (runs.get("workflow_runs", []) if isinstance(runs, dict) else []):
                result.append(clean(f"CI_FAILURE {repository} {item.get('name')} branch={item.get('head_branch')} sha={str(item.get('head_sha', ''))[:12]}", 320))
        except Exception as exc:  # noqa: BLE001 - each source is independent
            result.append(clean(f"GITHUB_READ_ERROR {repository} {exc}", 280))
    return result[-80:]


def evidence_pack() -> tuple[str, str]:
    workflows, room_read_safe = workflow_snapshot()
    local = local_evidence()
    source = source_evidence()
    stage_lines: list[str] = []
    for task_id, stages in sorted(workflows.items(), key=lambda item: item[0], reverse=True)[:12]:
        stage_lines.append(f"WORKFLOW {task_id} stages={','.join(sorted(stages))}")
    if not room_read_safe:
        stage_lines.append("WORKFLOW_READ_UNAVAILABLE fail-closed")
    lines = ["A2A STAGE EVIDENCE:", *(stage_lines or ["none"]), "LOCAL PROVENANCE SIGNALS:", *(local or ["none"]), "GITHUB SIGNALS:", *(source or ["none"])]
    text = "\n".join(lines)[:9000]
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def history_goals(state: dict) -> list[str]:
    return [clean(row.get("goal"), 500) for row in state.get("history", [])[-30:] if isinstance(row, dict)]


def deterministic_goal(evidence: list[str]) -> str:
    candidates = [line for line in evidence if line.startswith(("ISSUE ", "CI_FAILURE ", "WORKFLOW "))]
    focus = candidates[0] if candidates else "最近 A2A workflow 的证据链和恢复路径"
    return (
        f"围绕以下证据候选开展只读技术研究：{focus}。判断问题是否可复现，" 
        "并交叉比较至少两个独立来源（源码/Issue/CI/provenance/实际协议响应中的任意两类）；"
        "给出最小验证矩阵、证据差异、结论置信度和不改变服务器的修复建议。"
    )[:1700]


def model_goal(evidence_text: str, prior: list[str]) -> str:
    prompt = (
        "你是 Technocore 三 Agent 系统的 Research Director。请从证据中选择一个新的、具体、可验证的"
        "只读研究目标，优先 Bug、可靠性、协议一致性、性能或测试缺口。必须要求至少两个独立来源"
        "交叉验证，并写出可判定的验收标准。不得要求执行命令、改服务器、改 GitHub、发帖、开 PR、"
        "接触凭据或奖励活动。不得重复历史目标。只输出严格 JSON："
        '{"goal":"...","reason":"...","quality":0}。goal 不超过 1200 字。\n'
        "EVIDENCE:\n" + evidence_text + "\nHISTORY:\n" + "\n".join(prior[-20:])
    )
    try:
        raw = str(agent.ai_call(prompt)).strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
        obj = json.loads(raw)
        goal = clean(obj.get("goal"), 1200)
        quality = int(obj.get("quality", 0))
        if goal and quality >= 70:
            return goal
    except Exception as exc:  # deterministic fallback keeps the service useful during AI outage
        log("goal_model_fallback", error=clean(exc, 220))
    return deterministic_goal(evidence_text.splitlines())


def safe_goal(goal: str) -> bool:
    lowered = goal.lower()
    return bool(goal) and len(goal) <= 1700 and not any(token in lowered for token in BLOCKED)


def daily_count(state: dict, day: str) -> int:
    daily = state.setdefault("daily", {})
    return int(daily.get(day, 0) or 0)


def active_request(state: dict, workflows: dict[str, dict], room_read_safe: bool) -> str | None:
    if not room_read_safe:
        return "room-read-failed"
    for task_id, stages in workflows.items():
        if "WORKFLOW_TASK" in stages and "COMPLETE" not in stages:
            return task_id
    active = state.get("active_request")
    if isinstance(active, dict):
        started = float(active.get("sent_at", 0) or 0)
        if started and now() - started < number("RND_V5_MAX_ACTIVE_SECONDS", 900, 86400):
            return clean(active.get("request_id"), 120) or "request-pending"
    return None


def send_request(goal: str, evidence_sha256: str, cycle: int) -> dict:
    peers = agent.peers()
    mailbox = peers.get(LOVE8_DID)
    if not mailbox:
        raise RuntimeError("Love8 DID is not pinned in AI2AI peers.json")
    request_id = f"sched-{int(now())}-{hashlib.sha256((AI2AI_DID + goal).encode()).hexdigest()[:12]}"
    plan = "源码/Issue/CI/provenance 中至少选两类独立证据；记录复现条件、反例、最小测试矩阵；不执行写入或部署。"
    payload = agent.payload(
        "SCHEDULER_REQUEST",
        request_id,
        goal=(
            "研究模式：bug-analysis-cross-validation。\n"
            f"目标：{goal}\n"
            f"验证计划：{plan}\n"
            f"证据包哈希：{evidence_sha256}\n"
            "输出要求：Builder 给出独立分析与证据；Reviewer 必须逐项质疑并寻找反例；"
            "最终只形成研究档案，不自动修改任何上游或服务器。"
        )[:1900],
        origin="ai2ai-rnd-v5",
        scheduler_did=AI2AI_DID,
        scheduler_role="reviewer-research-director",
        research_mode="bug-analysis-cross-validation",
        evidence_sha256=evidence_sha256,
        cycle=cycle,
        policy="read_only=true;auto_pr=false;auto_server_change=false;auto_social_post=false",
    )
    agent.signed_post(mailbox, payload)
    return {"request_id": request_id, "sent_at": now(), "goal": goal, "evidence_sha256": evidence_sha256}


def tick() -> None:
    state = load_state()
    state["last_tick"] = now()
    if not state.get("boot_at"):
        state["boot_at"] = now()
    if state.get("paused"):
        save_state(state)
        return
    if now() - float(state["boot_at"]) < number("RND_V5_START_DELAY_SECONDS", 30, 3600):
        save_state(state)
        return
    day = utc_day()
    state["daily"] = {key: value for key, value in state.get("daily", {}).items() if key >= day}
    if daily_count(state, day) >= number("RND_V5_MAX_DAILY", 1, 8):
        save_state(state)
        return
    last_sent = float(state.get("last_request_at", 0) or 0)
    if last_sent and now() - last_sent < number("RND_V5_MIN_GAP_SECONDS", 1800, 86400):
        save_state(state)
        return
    evidence_text, evidence_sha256 = evidence_pack()
    workflows, room_read_safe = workflow_snapshot()
    active = active_request(state, workflows, room_read_safe)
    if active:
        log("director_wait", active=active)
        save_state(state)
        return
    goal = model_goal(evidence_text, history_goals(state))
    if not safe_goal(goal):
        state["last_error"] = "candidate rejected by read-only safety policy"
        ledger("rnd_candidate_rejected", reason=state["last_error"], goal_sha256=hashlib.sha256(goal.encode()).hexdigest())
        save_state(state)
        return
    cycle = daily_count(state, day) + 1
    sent = send_request(goal, evidence_sha256, cycle)
    state["last_request_at"] = sent["sent_at"]
    state["active_request"] = sent
    state["daily"][day] = cycle
    history = state.setdefault("history", [])
    history.append({**sent, "cycle": cycle, "day": day})
    state["history"] = history[-200:]
    state["last_error"] = ""
    ledger("rnd_objective_selected", request_id=sent["request_id"], goal=goal[:500], evidence_sha256=evidence_sha256, cycle=cycle)
    ledger("scheduler_request_sent", request_id=sent["request_id"], peer_did=LOVE8_DID, mode="bug-analysis-cross-validation")
    log("scheduler_request_sent", request_id=sent["request_id"], cycle=cycle)
    save_state(state)


def status() -> None:
    state = load_state()
    print("director: autonomous-rnd-v5")
    print("agent:", getattr(agent, "AGENT", ""))
    print("did:", getattr(agent, "DID", ""))
    print("paused:", bool(state.get("paused")))
    print("daily:", json.dumps(state.get("daily", {}), sort_keys=True))
    print("last_request_at:", state.get("last_request_at", 0))
    print("active_request:", json.dumps(state.get("active_request"), ensure_ascii=True))
    print("last_error:", clean(state.get("last_error"), 500))
    print("policy: read-only, cross-validation>=2 sources, no-auto-PR, no-auto-server-change")


def change_pause(paused: bool) -> None:
    state = load_state()
    state["paused"] = paused
    save_state(state)
    print("paused:", paused)


def reset_active() -> None:
    state = load_state()
    state["active_request"] = None
    state["last_error"] = ""
    save_state(state)
    print("active request marker reset; existing mailbox/provenance was preserved")


def daemon() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = load_state()
        if not state.get("boot_at"):
            state["boot_at"] = now()
        save_state(state)
        log("director_started")
        while True:
            try:
                tick()
            except Exception as exc:  # noqa: BLE001 - daemon must stay online
                state = load_state()
                state["last_error"] = clean(exc, 500)
                save_state(state)
                ledger("rnd_director_error", error=clean(exc, 500))
                log("director_error", error=clean(exc, 500))
            time.sleep(number("RND_V5_TICK_SECONDS", 30, 900))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "run":
        daemon()
    elif command == "tick":
        tick()
    elif command == "status":
        status()
    elif command == "pause":
        change_pause(True)
    elif command == "resume":
        change_pause(False)
    elif command == "reset-active":
        reset_active()
    else:
        raise SystemExit("usage: autonomous-rnd-v5.py run|tick|status|pause|resume|reset-active")
