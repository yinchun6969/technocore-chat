from __future__ import annotations

import json
from pathlib import Path

from tools.technocore_atlas import (
    _a2a_metadata,
    _load_local_events,
    collect_snapshot,
    render_svg,
    snapshot_from_dict,
)


def test_a2a_metadata_is_allow_listed_and_bounded() -> None:
    kind, task_id = _a2a_metadata('A2A1 {"type":"RESULT","task_id":"wf-123"}')
    assert (kind, task_id) == ("RESULT", "wf-123")
    assert _a2a_metadata('A2A1 {"type":"SHELL","task_id":"wf-123"}') == ("A2A1_OTHER", "wf-123")
    assert _a2a_metadata("A2A1 not-json") == ("A2A1_INVALID", None)
    assert _a2a_metadata("ordinary message") == ("MESSAGE", None)


def test_collect_skips_private_rooms_and_does_not_keep_message_body() -> None:
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
    assert len(calls) == 2


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
