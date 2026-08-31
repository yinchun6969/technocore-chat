#!/usr/bin/env python3
"""Generate a deterministic, offline Atlas five-stage evidence artifact."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.technocore_atlas import WORKFLOW_SIGNERS, collect_snapshot  # noqa: E402

TASK_ID = "wf-atlas-demo-v39"
STAGES = (
    ("WORKFLOW_TASK", "goal", "Reproduce the Atlas evidence path offline."),
    ("BUILD_RESULT", "build_result", "Built a bounded deterministic fixture."),
    ("CHALLENGE", "challenge", "Check signer, nonce, ordering and digest tampering."),
    ("REVISED_RESULT", "revised_result", "Added deterministic Merkle assertions."),
    ("COMPLETE", "final_summary", "Fixture passed without network access or secrets."),
)


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, (kind, field, content) in enumerate(STAGES, 1):
        payload = {"v": 1, "type": kind, "task_id": TASK_ID, field: content}
        rows.append(
            {
                "seq": index,
                "ts": f"2026-01-01T00:0{index}:00Z",
                "from": WORKFLOW_SIGNERS[kind],
                "nonce": str(index),
                "text": "A2A1 " + json.dumps(payload, separators=(",", ":"), sort_keys=True),
            }
        )
    return rows


def build_artifacts(output_dir: Path) -> dict[str, object]:
    rows = _rows()
    receipt_rows: list[dict[str, object]] = []

    def fetch(url: str, timeout: float) -> dict[str, object]:
        del timeout
        if "/r/demo-public?" in url:
            messages: list[dict[str, object]] = []
        elif "/r/d-ai2ai?" in url:
            messages = receipt_rows
        else:
            messages = rows
        return {"last_seq": len(messages), "messages": messages}

    snapshot = collect_snapshot(
        "https://example.test",
        selected_rooms=("demo-public",),
        workflow_rooms=("d-aizong", "d-ai2ai"),
        fetcher=fetch,
    )
    workflow = snapshot.workflows[0]
    if workflow.status != "complete" or len(workflow.evidence) != len(STAGES):
        raise RuntimeError("offline workflow did not complete")
    receipt_payload = {
        "v": 1,
        "type": "ARTIFACT_RECEIPT",
        "task_id": TASK_ID,
        "artifact_sha256": "a" * 64,
        "evidence_merkle_root": workflow.evidence_root,
        "evidence_schema": "technocore.a2a/evidence-bundle-v1",
    }
    receipt_rows.append(
        {
            "seq": 6,
            "ts": "2026-01-01T00:06:00Z",
            "from": WORKFLOW_SIGNERS["CHALLENGE"],
            "nonce": "6",
            "text": "A2A1 " + json.dumps(receipt_payload, separators=(",", ":"), sort_keys=True),
        }
    )
    snapshot = collect_snapshot(
        "https://example.test",
        selected_rooms=("demo-public",),
        workflow_rooms=("d-aizong", "d-ai2ai"),
        fetcher=fetch,
    )
    workflow = snapshot.workflows[0]
    if workflow.receipt_status != "matched":
        raise RuntimeError("offline receipt did not match independently derived root")

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_data = snapshot.to_dict()
    bundle = {
        "schema": "technocore.a2a/evidence-bundle-v1",
        "task_id": workflow.task_id,
        "algorithm": workflow.evidence_algorithm,
        "root": workflow.evidence_root,
        "leaf_count": len(workflow.evidence),
        "evidence": [item.__dict__ for item in workflow.evidence],
        "receipt_status": workflow.receipt_status,
        "receipt": workflow.receipt.__dict__ if workflow.receipt else None,
        "claim": (
            "public-stage root independently derived and matched to the signed receipt; "
            "local artifact bytes not read or verified by Atlas"
        ),
    }
    observer_state = {
        "snapshot": snapshot_data,
        "last_attempt": snapshot.observed_at,
        "last_success": snapshot.observed_at,
        "last_success_epoch": time.time(),
        "last_attempt_ok": True,
        "error_code": None,
        "consecutive_failures": 0,
    }
    (output_dir / "snapshot.json").write_text(
        json.dumps(snapshot_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "evidence.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "observer-state.json").write_text(
        json.dumps(observer_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "demo.log").write_text(
        "\n".join(
            [
                f"task_id={workflow.task_id}",
                f"status={workflow.status}",
                f"stages={len(workflow.stages)}",
                f"evidence_algorithm={workflow.evidence_algorithm}",
                f"evidence_root={workflow.evidence_root}",
                f"receipt_status={workflow.receipt_status}",
                "artifact_bytes_verified=false",
                "network_writes=0",
                "private_keys_read=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/technocore-atlas-demo"))
    args = parser.parse_args()
    bundle = build_artifacts(args.output_dir)
    print(f"ATLAS_DEMO_OK task={bundle['task_id']} root={bundle['root']}")
    print(f"artifacts={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
