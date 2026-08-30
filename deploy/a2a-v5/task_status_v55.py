#!/usr/bin/env python3
"""Read-only task status CLI for the installed A2A v5.5 control plane."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("TECHNOCORE_A2A_ROOT", "/opt/technocore-a2a"))
RND = ROOT / "rnd-v5"
STATE = ROOT / "rnd-v5-state"
ARTIFACTS = ROOT / "rnd-v5-artifacts"
CACHE = STATE / "curator-stage-cache.json"
CURATOR_STATE = STATE / "curator.json"
DIRECTOR_STATE = STATE / "director.json"
LOGS = (STATE / "director.log", STATE / "curator.log")


def load_evidence_module():
    path = RND / "evidence_v55.py"
    if not path.exists():
        path = Path(__file__).resolve().with_name("evidence_v55.py")
    spec = importlib.util.spec_from_file_location("evidence_v55_status", path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load evidence_v55.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence_v55 = load_evidence_module()


def read_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default
    return value


def workflows() -> dict[str, dict[str, Any]]:
    document = read_json(CACHE, {})
    value = document.get("workflows", {}) if isinstance(document, dict) else {}
    return value if isinstance(value, dict) else {}


def latest_task(values: dict[str, dict[str, Any]]) -> str:
    def rank(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        task_id, stages = item
        timestamps = []
        for stage in stages.values() if isinstance(stages, dict) else []:
            if isinstance(stage, dict):
                timestamps.append(evidence_v55.parse_timestamp(stage.get("message_ts")))
                timestamps.append(evidence_v55.parse_timestamp(stage.get("seen_at")))
        return max(timestamps or [0]), task_id
    return max(values.items(), key=rank)[0] if values else ""


def errors_for(task_id: str, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in LOGS:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-1000:]
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(row, dict):
                continue
            row_task = str(row.get("workflow_id") or row.get("task_id") or "")
            row_request = str(row.get("request_id") or "")
            if task_id not in {row_task, row_request}:
                continue
            if row.get("error") or any(token in str(row.get("event", "")).lower() for token in ("error", "fail", "reject", "timeout", "gap")):
                rows.append(row)
    return sorted(rows, key=lambda row: float(row.get("ts", 0) or 0))[-limit:]


def verify_artifact(task_id: str, stages: dict[str, Any]) -> tuple[bool, str, str]:
    md_path = ARTIFACTS / f"{task_id}.md"
    json_path = ARTIFACTS / f"{task_id}.json"
    if not md_path.is_file() or not json_path.is_file():
        return False, "verified artifact pair is incomplete", ""
    try:
        text = md_path.read_text(encoding="utf-8")
        receipt = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return False, f"artifact pair unreadable: {exc}", ""
    if not isinstance(receipt, dict) or receipt.get("workflow_id") != task_id:
        return False, "receipt workflow binding mismatch", ""
    if receipt.get("evidence_verified") is not True:
        return False, "receipt is not marked evidence_verified", ""
    bundle = receipt.get("evidence_bundle")
    try:
        evidence_v55.verify_bundle(bundle)
        current = evidence_v55.build_bundle(task_id, stages)
    except Exception as exc:
        return False, f"evidence bundle invalid: {exc}", ""
    if bundle != current:
        return False, "receipt evidence does not match current signed stages", ""
    root = current["merkle_root"]
    if receipt.get("evidence_merkle_root") != root:
        return False, "receipt Merkle root mismatch", ""
    if receipt.get("artifact_sha256") != hashlib.sha256(text.encode()).hexdigest():
        return False, "artifact SHA256 mismatch", ""
    saga = receipt.get("saga", {})
    if not isinstance(saga, dict) or saga.get("task_id") != task_id or saga.get("state") != "ARTIFACT_VERIFIED":
        return False, "receipt Saga binding invalid", ""
    return True, "", root


def snapshot(task_id: str) -> dict[str, Any]:
    values = workflows()
    stages = values.get(task_id)
    if not isinstance(stages, dict):
        return {
            "version": "5.5.1", "task_id": task_id, "found": False,
            "state": "NOT_OBSERVED", "resume_from": "WORKFLOW_TASK", "errors": errors_for(task_id),
        }
    verified, verification_error, verified_root = verify_artifact(task_id, stages)
    saga = evidence_v55.saga_checkpoint(task_id, stages, artifact_verified=verified)
    present = [stage for stage in evidence_v55.STAGE_ORDER if stage in stages]
    missing = [stage for stage in evidence_v55.STAGE_ORDER if stage not in stages]
    curator_state = read_json(CURATOR_STATE, {})
    retry_map = curator_state.get("artifact_retries", {}) if isinstance(curator_state, dict) else {}
    retry = retry_map.get(task_id, {}) if isinstance(retry_map, dict) else {}
    result: dict[str, Any] = {
        "version": "5.5.1",
        "task_id": task_id,
        "found": True,
        "state": saga["state"],
        "resume_from": saga["resume_from"],
        "present_stages": present,
        "missing_stages": missing,
        "artifact": str(ARTIFACTS / f"{task_id}.md") if verified else "",
        "unverified_artifact": str(ARTIFACTS / f"{task_id}.md") if not verified and (ARTIFACTS / f"{task_id}.md").exists() else "",
        "evidence_verified": verified,
        "evidence_merkle_root": verified_root,
        "verification_error": verification_error,
        "retry": retry if isinstance(retry, dict) else {},
        "errors": errors_for(task_id),
    }
    return result


def render(value: dict[str, Any]) -> str:
    lines = [
        "=== TECHNOCORE A2A TASK STATUS ===",
        f"task_id: {value['task_id']}",
        f"found: {str(value['found']).lower()}",
        f"state: {value['state']}",
        f"resume_from: {value['resume_from']}",
    ]
    if value.get("found"):
        lines.extend((
            "present_stages: " + ",".join(value.get("present_stages", [])),
            "missing_stages: " + (",".join(value.get("missing_stages", [])) or "none"),
            f"evidence_verified: {str(value.get('evidence_verified', False)).lower()}",
            f"evidence_merkle_root: {value.get('evidence_merkle_root') or 'pending'}",
            f"artifact: {value.get('artifact') or 'pending'}",
        ))
        if value.get("verification_error"):
            lines.append(f"verification_error: {value['verification_error']}")
        retry = value.get("retry", {})
        if isinstance(retry, dict) and retry:
            lines.append(
                "retry: attempts={attempts} error_type={error_type} next_retry_at={next_retry_at}".format(
                    attempts=retry.get("attempts", 0), error_type=retry.get("error_type", "unknown"),
                    next_retry_at=retry.get("next_retry_at", 0),
                )
            )
    errors = value.get("errors", [])
    lines.append(f"structured_errors: {len(errors)}")
    for row in errors:
        lines.append(
            "- " + json.dumps({
                key: row.get(key) for key in ("ts", "event", "stage", "signer_did", "evidence_hash", "error")
                if row.get(key) not in (None, "")
            }, ensure_ascii=False, separators=(",", ":"))
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="technocore")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="show a workflow's verified stage/Saga status")
    status.add_argument("--task-id", default="", help="wf-...; defaults to latest observed workflow")
    status.add_argument("--json", action="store_true", help="emit canonical JSON")
    args = parser.parse_args()
    values = workflows()
    task_id = args.task_id or latest_task(values)
    if not task_id:
        raise SystemExit("no observed workflow; pass --task-id wf-...")
    if not task_id.startswith("wf-") and not task_id.startswith("sched-"):
        raise SystemExit("task id must start with wf- or sched-")
    value = snapshot(task_id)
    print(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) if args.json else render(value))
    return 0 if value["found"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
