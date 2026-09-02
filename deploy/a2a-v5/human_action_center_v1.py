#!/usr/bin/env python3
"""Deterministic, local-only human-action inbox for verified A2A artifacts."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
from pathlib import Path


SCHEMA = "technocore.a2a/human-action-v1"
QUEUE_SCHEMA = "technocore.a2a/human-action-queue-v1"
DEFAULT_QUEUE = Path("/opt/technocore-a2a/rnd-v5-state/human-actions.json")
ACTIVE_STATES = {"pending", "acknowledged", "snoozed", "approved"}
FINAL_STATES = {"resolved", "rejected"}
ALL_STATES = ACTIVE_STATES | FINAL_STATES
TASK_RE = re.compile(r"^wf-[a-zA-Z0-9_-]{4,100}$")
SECRET_RE = re.compile(
    r"BEGIN [A-Z ]*PRIVATE KEY|(?:api[_-]?key|password|access[_-]?token|seed phrase)\s*[:=]",
    re.I,
)

HEADINGS = (
    "# Title", "## Objective", "## Verified Evidence", "## Cross-Validation",
    "## Findings", "## Design Proposal", "## Minimal Test Matrix",
    "## Open Questions", "## Provenance",
)

P0_MARKERS = (
    "private key leak", "credential leak", "signature bypass", "authentication bypass",
    "data loss", "rollback reports success", "silent corruption", "remote code execution",
    "私钥泄露", "凭据泄露", "签名绕过", "认证绕过", "数据丢失", "静默损坏",
    "回滚失败仍报告成功", "远程代码执行",
)
BUG_MARKERS = (
    " bug", "bug/", "vulnerability", "defect", "incorrect", "fails", "failure",
    "regression", "race condition", "rollback", "漏洞", "缺陷", "错误", "失败",
    "回归", "竞争条件", "回滚",
)
FIX_MARKERS = (
    "fix", "patch", "change", "guard", "validate", "reject", "preserve", "restore",
    "修复", "补丁", "修改", "校验", "拒绝", "保留", "恢复", "建议",
)
HUMAN_MARKERS = (
    "human decision", "manual decision", "manual approval", "requires approval",
    "operator decision", "needs confirmation", "人工决定", "人工确认", "需要确认",
    "需要批准", "等待批准", "需要人工", "方案取舍",
)


def _compact(value: object, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())[:limit]
    return "[sensitive summary hidden]" if SECRET_RE.search(text) else text


def _section(text: str, heading: str) -> str:
    try:
        start = text.index(heading) + len(heading)
    except ValueError:
        return ""
    ends = [text.find(item, start) for item in HEADINGS if text.find(item, start) >= 0]
    end = min(ends) if ends else len(text)
    return text[start:end].strip()


def _has(text: str, markers: tuple[str, ...]) -> bool:
    lowered = " " + text.lower()
    return any(marker in lowered for marker in markers)


def _title(text: str) -> str:
    value = _section(text, "# Title").splitlines()
    return _compact(value[0] if value else "Verified A2A research result", 180)


def classify(task_id: str, artifact: str, receipt: dict) -> dict | None:
    """Return a conservative action candidate, never an execution authorization."""
    if not TASK_RE.fullmatch(task_id):
        raise ValueError("invalid workflow ID")
    if not isinstance(receipt, dict) or receipt.get("evidence_verified") is not True:
        return None
    try:
        score = int(receipt.get("cross_validation_score", 0))
    except (TypeError, ValueError):
        return None
    evidence_root = str(receipt.get("evidence_merkle_root", ""))
    artifact_sha = str(receipt.get("artifact_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", evidence_root) or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha):
        return None

    title = _title(artifact)
    findings = _section(artifact, "## Findings")
    proposal = _section(artifact, "## Design Proposal")
    tests = _section(artifact, "## Minimal Test Matrix")
    questions = _section(artifact, "## Open Questions")
    finding_scope = title + " " + findings

    if _has(finding_scope, P0_MARKERS):
        kind, priority = "CRITICAL_CONFIRMATION", "P0"
    elif score >= 90 and _has(finding_scope, BUG_MARKERS) and _has(proposal, FIX_MARKERS) and len(tests) >= 40:
        kind, priority = "PR_CANDIDATE", "P1"
    elif _has(findings + " " + questions, HUMAN_MARKERS):
        kind, priority = "HUMAN_CONFIRMATION", "P2"
    else:
        return None

    action_id = "act-" + hashlib.sha256(
        f"{task_id}|{artifact_sha}|{kind}".encode()
    ).hexdigest()[:16]
    now = int(time.time())
    return {
        "schema": SCHEMA,
        "alert_id": action_id,
        "workflow_id": task_id,
        "kind": kind,
        "priority": priority,
        "status": "pending",
        "summary": title,
        "evidence_merkle_root": evidence_root,
        "artifact_sha256": artifact_sha,
        "cross_validation_score": score,
        "human_action_required": True,
        "decision_basis": "deterministic-markers+verified-artifact",
        "created_at": now,
        "updated_at": now,
        "snoozed_until": 0,
        "history": [],
        "policy": {
            "auto_pr": False,
            "auto_server_change": False,
            "auto_public_post": False,
        },
    }


def _load_unlocked(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        value = {}
    if not isinstance(value, dict) or value.get("schema") != QUEUE_SCHEMA:
        value = {"schema": QUEUE_SCHEMA, "actions": {}, "updated_at": 0}
    if not isinstance(value.get("actions"), dict):
        value["actions"] = {}
    return value


def load(path: Path = DEFAULT_QUEUE) -> dict:
    return _load_unlocked(path)


def _write_unlocked(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o640)


def _locked(path: Path):
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    handle = path.with_suffix(path.suffix + ".lock").open("a+")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def upsert(action: dict, path: Path = DEFAULT_QUEUE) -> tuple[bool, dict]:
    alert_id = str(action.get("alert_id", ""))
    if not re.fullmatch(r"act-[0-9a-f]{16}", alert_id):
        raise ValueError("invalid action ID")
    lock = _locked(path)
    try:
        value = _load_unlocked(path)
        existing = value["actions"].get(alert_id)
        if isinstance(existing, dict):
            return False, existing
        value["actions"][alert_id] = action
        value["updated_at"] = int(time.time())
        _write_unlocked(path, value)
        return True, action
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def update(alert_id: str, status: str, actor: str, *, snooze_seconds: int = 0,
           path: Path = DEFAULT_QUEUE) -> dict:
    if status not in ALL_STATES:
        raise ValueError("invalid action state")
    lock = _locked(path)
    try:
        value = _load_unlocked(path)
        action = value["actions"].get(alert_id)
        if not isinstance(action, dict):
            raise ValueError("action not found")
        now = int(time.time())
        if status == "snoozed":
            snooze_seconds = min(max(int(snooze_seconds), 300), 7 * 86400)
            action["snoozed_until"] = now + snooze_seconds
        else:
            action["snoozed_until"] = 0
        action["status"] = status
        action["updated_at"] = now
        history = action.setdefault("history", [])
        if not isinstance(history, list):
            history = []
            action["history"] = history
        history.append({"ts": now, "status": status, "actor": _compact(actor, 80)})
        action["history"] = history[-30:]
        value["updated_at"] = now
        _write_unlocked(path, value)
        return action
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def active(path: Path = DEFAULT_QUEUE, *, include_snoozed: bool = False) -> list[dict]:
    now = int(time.time())
    rows = []
    for action in load(path).get("actions", {}).values():
        if not isinstance(action, dict) or action.get("status") not in ACTIVE_STATES:
            continue
        if not include_snoozed and int(action.get("snoozed_until", 0) or 0) > now:
            continue
        rows.append(action)
    rank = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(rows, key=lambda item: (rank.get(str(item.get("priority")), 9), -int(item.get("created_at", 0))))


def counts(path: Path = DEFAULT_QUEUE) -> dict[str, int]:
    result = {"P0": 0, "P1": 0, "P2": 0, "total": 0}
    for action in active(path, include_snoozed=True):
        priority = str(action.get("priority", ""))
        if priority in result:
            result[priority] += 1
            result["total"] += 1
    return result


def public_projection(action: dict) -> dict:
    """Fields safe to place in a signed public receipt and Atlas snapshot."""
    return {
        key: action[key] for key in (
            "schema", "alert_id", "workflow_id", "kind", "priority",
            "human_action_required", "evidence_merkle_root", "artifact_sha256",
            "cross_validation_score",
        ) if key in action
    }
