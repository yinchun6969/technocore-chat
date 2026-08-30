#!/usr/bin/env python3
"""Regression coverage for cursor-backed Curator evidence collection."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "autonomous-curator-v5.py"
LOVE8 = "did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p"
AIZONG = "did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e"
AI2AI = "did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje"


FAKE_AGENT = r'''
import json

AGENT = "ai2ai"
BASE = "https://example.invalid"

class Requests:
    def get(self, *args, **kwargs):
        raise RuntimeError("test must replace requests")

requests = Requests()

def peers():
    return {"love8": "d-love8"}

def parse(text):
    return json.loads(text)

def ledger(*args, **kwargs):
    return None

def payload(*args, **kwargs):
    return ""

def signed_post(*args, **kwargs):
    return None
'''


class Response:
    def __init__(self, messages=None, error=None):
        self.messages = messages or []
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return {
            "messages": self.messages,
            "last_seq": max((int(row.get("seq", 0)) for row in self.messages), default=0),
        }


class ScriptedRequests:
    def __init__(self, rows):
        self.rows = {key: list(value) for key, value in rows.items()}
        self.limits = []
        self.params = []

    def get(self, url, *, params, **kwargs):
        self.limits.append(params["limit"])
        self.params.append(dict(params))
        room = url.rsplit("/", 1)[-1]
        queue = self.rows.setdefault(room, [])
        value = queue.pop(0) if queue else Response([])
        return value


def message(kind, sender, task_id="wf-cache-test", seq=1):
    return {
        "seq": seq,
        "from": sender,
        "text": json.dumps({"type": kind, "task_id": task_id}),
    }


class CuratorReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "a2a"
        (self.root / "bin").mkdir(parents=True)
        (self.root / "bin/agent.py").write_text(FAKE_AGENT, encoding="utf-8")
        self.old_root = os.environ.get("TECHNOCORE_A2A_ROOT")
        os.environ["TECHNOCORE_A2A_ROOT"] = str(self.root)

    def tearDown(self):
        if self.old_root is None:
            os.environ.pop("TECHNOCORE_A2A_ROOT", None)
        else:
            os.environ["TECHNOCORE_A2A_ROOT"] = self.old_root
        self.temp.cleanup()

    def load(self):
        spec = importlib.util.spec_from_file_location("curator_under_test", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.time.sleep = lambda _: None
        return module

    def test_room_read_retries_and_uses_supported_limit(self):
        module = self.load()
        network = ScriptedRequests({
            "d-ai2ai": [Response(error=RuntimeError("503")), Response([message("CHALLENGE", AI2AI)])],
        })
        module.requests = network
        body = module.room_messages("d-ai2ai")
        self.assertEqual(len(body["messages"]), 1)
        self.assertEqual(network.limits, [200, 200])

    def test_verified_stages_survive_partial_room_failures_and_restart(self):
        first = self.load()
        first.requests = ScriptedRequests({
            "d-ai2ai": [Response([message("CHALLENGE", AI2AI)])],
            "d-aizong": [Response([message("BUILD_RESULT", AIZONG)])],
            "d-love8": [Response([message("WORKFLOW_TASK", LOVE8)])],
        })
        stages = first.scan()["wf-cache-test"]
        self.assertEqual(set(stages), {"WORKFLOW_TASK", "BUILD_RESULT", "CHALLENGE"})
        self.assertTrue(first.CACHE_FILE.exists())

        second = self.load()
        second.requests = ScriptedRequests({
            "d-ai2ai": [Response(error=RuntimeError("503"))] * 3,
            "d-aizong": [Response([message("REVISED_RESULT", AIZONG, seq=2)])],
            "d-love8": [Response([message("COMPLETE", LOVE8, seq=2)])],
        })
        stages = second.scan()["wf-cache-test"]
        self.assertTrue(second.complete(stages))
        self.assertEqual(set(stages), set(second.EXPECTED))

    def test_untrusted_sender_is_not_cached(self):
        module = self.load()
        module.requests = ScriptedRequests({
            "d-ai2ai": [Response([message("CHALLENGE", LOVE8)])],
            "d-aizong": [Response([])],
            "d-love8": [Response([])],
        })
        self.assertNotIn("wf-cache-test", module.scan())

    def test_successful_cursor_is_persisted_and_reused(self):
        first = self.load()
        network = ScriptedRequests({
            "d-ai2ai": [Response([message("CHALLENGE", AI2AI, seq=41)])],
            "d-aizong": [Response([])],
            "d-love8": [Response([])],
        })
        first.requests = network
        first.scan()
        self.assertEqual(first.load_room_cursors()["d-ai2ai"], 41)

        second = self.load()
        network = ScriptedRequests({
            "d-ai2ai": [Response([message("CHALLENGE", AI2AI, seq=42)])],
            "d-aizong": [Response([])],
            "d-love8": [Response([])],
        })
        second.requests = network
        second.scan()
        ai2ai_params = next(row for row in network.params if row.get("since") == 41)
        self.assertEqual(ai2ai_params, {"format": "json", "limit": 200, "since": 41})

    def test_failed_room_does_not_advance_cursor(self):
        module = self.load()
        module.save_cache({}, {"d-ai2ai": 17})
        module.requests = ScriptedRequests({
            "d-ai2ai": [Response(error=RuntimeError("503"))] * 3,
            "d-aizong": [Response([])],
            "d-love8": [Response([])],
        })
        module.scan()
        self.assertEqual(module.load_room_cursors()["d-ai2ai"], 17)


if __name__ == "__main__":
    unittest.main()
