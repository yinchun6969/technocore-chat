#!/usr/bin/env python3
"""Offline, reproducible A2A v5.5 evidence/Merkle/Saga demonstration."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import evidence_v55


def mock_stages(task_id: str) -> dict:
    content = {
        "WORKFLOW_TASK": {"goal": "Audit deterministic multi-agent evidence verification"},
        "BUILD_RESULT": {"build_result": "Builder analysis from source and runtime-log evidence"},
        "CHALLENGE": {"challenge": "Reviewer requests independent hash and replay checks"},
        "REVISED_RESULT": {"revised_result": "Builder adds canonical hashes and negative tests"},
        "COMPLETE": {"final_summary": "Scout closes after deterministic verification"},
    }
    result = {}
    for index, stage in enumerate(evidence_v55.STAGE_ORDER, 1):
        result[stage] = {
            "seq": index,
            "from": evidence_v55.EXPECTED_SIGNERS[stage],
            "room": f"demo-{stage.lower()}",
            "message_ts": 1788058800 + index,
            "seen_at": 1788058800 + index,
            "obj": {"type": stage, "task_id": task_id, **content[stage]},
        }
    return result


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".v55-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=True, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def run(output: Path, task_id: str) -> dict:
    stages = mock_stages(task_id)
    bundle = evidence_v55.build_bundle(task_id, stages)
    evidence_v55.verify_bundle(bundle)
    saga = evidence_v55.saga_checkpoint(task_id, stages, artifact_verified=True)
    receipt = {
        "version": "5.5.0",
        "workflow_id": task_id,
        "evidence_verified": True,
        "evidence_merkle_root": bundle["merkle_root"],
        "evidence_bundle": bundle,
        "saga": saga,
        "policy": {"read_only": True, "commands_executed": False, "automatic_writes": False},
    }
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "evidence-bundle.json", bundle)
    atomic_json(output / "receipt.json", receipt)
    (output / "artifact.md").write_text(
        "# A2A v5.5 Offline Verification\n\n"
        f"- workflow: `{task_id}`\n"
        f"- evidence Merkle root: `{bundle['merkle_root']}`\n"
        "- five signer-bound stages verified\n"
        "- Saga state: `ARTIFACT_VERIFIED`\n"
        "- no network, model, deployment, credential or server write was used\n",
        encoding="utf-8",
    )
    with (output / "run.jsonl").open("w", encoding="utf-8") as handle:
        for row in saga["transitions"]:
            handle.write(json.dumps({"event": "saga_transition", **row}, ensure_ascii=True, separators=(",", ":")) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/technocore-a2a-v55-demo"))
    parser.add_argument("--task-id", default="wf-v55-offline-demo")
    args = parser.parse_args()
    receipt = run(args.output, args.task_id)
    print("A2A_V55_OFFLINE_DEMO=PASS")
    print("workflow_id=" + receipt["workflow_id"])
    print("evidence_merkle_root=" + receipt["evidence_merkle_root"])
    print("artifact=" + str(args.output / "artifact.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
