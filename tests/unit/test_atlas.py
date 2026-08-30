from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.technocore_atlas import (
    EVIDENCE_ALGORITHM,
    WORKFLOW_SIGNERS,
    _a2a_metadata,
    _load_local_events,
    collect_snapshot,
    evidence_merkle_root,
    render_svg,
    snapshot_from_dict,
)


def test_a2a_metadata_is_allow_listed_and_bounded() -> None:
    kind, task_id = _a2a_metadata('A2A1 {"type":"RESULT","task_id":"wf-123"}')
    assert (kind, task_id) == ("RESULT", "wf-123")
    assert _a2a_metadata('A2A1 {"type":"SHELL","task_id":"wf-123"}') == ("A2A1_OTHER", "wf-123")
    assert _a2a_metadata("A2A1 not-json") == ("A2A1_INVALID", None)
    assert _a2a_metadata("ordinary message") == ("MESSAGE", None)


def test_collect_skips_private_rooms_and_does_not_keep_raw_message_body() -> None:
    calls: list[str] = []

    def fake_fetch(url: str, timeout: float) -> dict:
        calls.append(url)
        if "/rooms?" in url:
            return {"rooms": [{"room": "lobby"}, {"room": "p-private"}, {"room": "mb-p-secret"}]}
        return {
            "last_seq": 4,
            "messages": [
                {
                    "seq": 4,
                    "ts": "2026-08-28T00:00:00Z",
                    "from": "did:key:z6MkExampleKey",
                    "nonce": "9",
                    "text": 'A2A1 {"type":"RESULT","task_id":"wf-1","result":"do not export"}',
                }
            ],
        }

    snapshot = collect_snapshot("https://example.test", room_limit=10, fetcher=fake_fetch)
    assert [room.name for room in snapshot.rooms] == ["lobby"]
    message = snapshot.rooms[0].messages[0]
    assert message.signed and message.kind == "RESULT"
    assert not hasattr(message, "text")
    assert message.content is None
    assert len(calls) == 2


def test_collects_verified_five_stage_workflow_with_allowlisted_content() -> None:
    contents = {
        "WORKFLOW_TASK": ("goal", "调查一个可靠性问题"),
        "BUILD_RESULT": ("build_result", "Builder 初步分析"),
        "CHALLENGE": ("challenge", "Reviewer 要求补充反例"),
        "REVISED_RESULT": ("revised_result", "Builder 已根据质疑修订"),
        "COMPLETE": ("final_summary", "Scout 总结并保留未解决风险"),
    }

    def row(index: int, kind: str) -> dict:
        field, content = contents[kind]
        payload = {
            "v": 1,
            "type": kind,
            "task_id": "wf-live-1",
            field: content,
            "unknown_private_field": "must not be exported",
        }
        return {
            "seq": index,
            "ts": f"2026-08-29T02:2{index}:00Z",
            "from": WORKFLOW_SIGNERS[kind],
            "nonce": str(index),
            "text": "A2A1 " + json.dumps(payload, ensure_ascii=False),
        }

    rows = [row(index, kind) for index, kind in enumerate(contents, 1)]

    def fetch(url: str, timeout: float) -> dict:
        if "/r/ai2ai?" in url:
            return {"last_seq": 0, "messages": []}
        return {"last_seq": 5, "messages": rows}

    snapshot = collect_snapshot(
        "https://example.test",
        selected_rooms=("ai2ai",),
        workflow_rooms=("d-aizong", "mb-p-" + "a" * 32),
        fetcher=fetch,
    )
    assert snapshot.schema == "technocore-atlas/v2"
    assert len(snapshot.workflows) == 1
    workflow = snapshot.workflows[0]
    assert workflow.status == "complete"
    assert [stage.kind for stage in workflow.stages] == list(contents)
    assert [stage.agent for stage in workflow.stages] == [
        "Love8",
        "Aizong",
        "AI2AI",
        "Aizong",
        "Love8",
    ]
    assert len(workflow.evidence) == 5
    assert workflow.evidence_algorithm == EVIDENCE_ALGORITHM
    assert len(workflow.evidence_root) == 64
    assert [item.stage for item in workflow.evidence] == list(contents)
    assert all(item.source_type == "technocore_signed_stage" for item in workflow.evidence)
    assert all(item.signer_did == WORKFLOW_SIGNERS[item.stage] for item in workflow.evidence)
    assert (
        snapshot_from_dict(snapshot.to_dict()).workflows[0].evidence_root == workflow.evidence_root
    )
    exported = json.dumps(snapshot.to_dict(), ensure_ascii=False)
    assert "Builder 初步分析" in exported
    assert "unknown_private_field" not in exported
    assert "must not be exported" not in exported
    assert "mb-p-" not in exported


def test_evidence_merkle_root_is_deterministic_ordered_and_tamper_evident() -> None:
    leaves = tuple(hashlib.sha256(value).hexdigest() for value in (b"one", b"two", b"three"))
    root = evidence_merkle_root(leaves)
    assert len(root) == 64
    assert evidence_merkle_root(leaves) == root
    assert evidence_merkle_root(tuple(reversed(leaves))) != root
    changed = (*leaves[:2], hashlib.sha256(b"changed").hexdigest())
    assert evidence_merkle_root(changed) != root
    assert evidence_merkle_root(()) == ""


def test_workflow_rejects_wrong_signer_and_redacts_credentials() -> None:
    messages = [
        {
            "seq": 1,
            "ts": "2026-08-29T02:20:00Z",
            "from": WORKFLOW_SIGNERS["WORKFLOW_TASK"],
            "nonce": "1",
            "text": 'A2A1 {"type":"WORKFLOW_TASK","task_id":"wf-safe","goal":"token=super-secret-value"}',
        },
        {
            "seq": 2,
            "ts": "2026-08-29T02:21:00Z",
            "from": WORKFLOW_SIGNERS["WORKFLOW_TASK"],
            "nonce": "2",
            "text": 'A2A1 {"type":"CHALLENGE","task_id":"wf-safe","challenge":"forged"}',
        },
    ]

    def fetch(url: str, timeout: float) -> dict:
        return {"last_seq": 2, "messages": [] if "/r/ai2ai?" in url else messages}

    snapshot = collect_snapshot(
        "https://example.test",
        selected_rooms=("ai2ai",),
        workflow_rooms=("d-aizong",),
        fetcher=fetch,
    )
    workflow = snapshot.workflows[0]
    assert len(workflow.stages) == 1
    assert workflow.stages[0].content == "[敏感内容已隐藏]"
    assert "super-secret-value" not in json.dumps(snapshot.to_dict())


def test_render_escapes_untrusted_dynamic_labels() -> None:
    raw = {
        "schema": "technocore-atlas/v1",
        "observed_at": "now",
        "base_url": "https://example.test",
        "summary": {
            "rooms_observed": 1,
            "messages_observed": 1,
            "signed_messages": 0,
            "did_writers": 0,
            "a2a_messages": 0,
            "workflow_tasks": 0,
        },
        "rooms": [
            {
                "name": "safe-room",
                "message_count": 1,
                "last_seq": 1,
                "messages": [
                    {
                        "seq": 1,
                        "ts": "now",
                        "author_id": "abc",
                        "author": "<script>alert(1)</script>",
                        "did_writer": False,
                        "signed": False,
                        "nonce": None,
                        "kind": "MESSAGE",
                        "task_id": None,
                        "text_sha256": "0" * 64,
                    }
                ],
            }
        ],
    }
    svg = render_svg(snapshot_from_dict(raw))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in svg
    assert "<script>alert(1)</script>" not in svg


def test_render_connects_observed_author_to_their_room() -> None:
    snapshot = snapshot_from_dict(
        {
            "schema": "technocore-atlas/v1",
            "observed_at": "now",
            "base_url": "https://example.test",
            "summary": {
                "rooms_observed": 1,
                "messages_observed": 1,
                "signed_messages": 1,
                "did_writers": 1,
                "a2a_messages": 1,
                "workflow_tasks": 1,
            },
            "rooms": [
                {
                    "name": "lobby",
                    "message_count": 1,
                    "last_seq": 1,
                    "messages": [
                        {
                            "seq": 1,
                            "ts": "now",
                            "author_id": "agent-1",
                            "author": "did:key:z6MkAgentOne",
                            "did_writer": True,
                            "signed": True,
                            "nonce": "1",
                            "kind": "TASK",
                            "task_id": "task-1",
                            "text_sha256": "0" * 64,
                        }
                    ],
                }
            ],
        }
    )
    svg = render_svg(snapshot)
    assert 'd="M494 174H570"' in svg


def test_ledger_count_does_not_export_secret_rows(tmp_path: Path) -> None:
    ledger = tmp_path / "provenance.jsonl"
    ledger.write_text(
        json.dumps({"event": "task", "task_id": "a"})
        + "\n"
        + json.dumps({"event": "bad", "api_key": "hidden"})
        + "\ninvalid\n",
        encoding="utf-8",
    )
    events = _load_local_events(str(ledger))
    assert len(events) == 1
    assert not hasattr(events[0], "api_key")
