#!/usr/bin/env python3
"""Offline tests for cursor-aware Aizong Builder polling."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "cursor_poll", HERE / "repair-aizong-cursor-poll-v3.6.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


def fixture() -> str:
    return """import os
FALLBACK_INBOX=os.environ.get('A2A_FALLBACK_INBOX','').strip()
def fetch_messages():
    inbox=FALLBACK_INBOX or MAILBOX
    r=requests.get(f'{BASE}/r/{quote(inbox)}',params={'format':'json','limit':200},timeout=30); r.raise_for_status(); return r.json().get('messages',[])
def run():
    cur=7
    while True:
        try:
            msgs=fetch_messages()
            break
        except Exception:
            break
"""


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"messages": [{"seq": 8}]}


class Requests:
    def __init__(self):
        self.call = None

    def get(self, url, params, timeout):
        self.call = (url, params, timeout)
        return Response()


class FakeSystemd:
    def __init__(self, active=True):
        self.is_active = active
        self.events = []

    def active(self):
        return self.is_active

    def stop(self):
        self.events.append("stop")

    def start(self):
        self.events.append("start")


class CursorPollTests(unittest.TestCase):
    def test_transform_is_idempotent_and_passes_cursor(self):
        updated = repair.transform(fixture())
        self.assertEqual(repair.transform(updated), updated)
        self.assertEqual(updated.count(repair.MARKER), 1)
        self.assertIn("msgs=fetch_messages(cur)", updated)
        self.assertIn("'since':cursor", updated)
        self.assertIn("'wait':10", updated)

    def test_fetch_uses_fallback_room_and_exact_cursor(self):
        requests = Requests()
        namespace = {
            "FALLBACK_INBOX": "d-aizong",
            "MAILBOX": "mb-p-private",
            "BASE": "https://technocore.chat",
            "quote": lambda value: value,
            "requests": requests,
        }
        exec(repair.FETCH_NEW, namespace)
        self.assertEqual(namespace["fetch_messages"](431), [{"seq": 8}])
        self.assertEqual(requests.call[0], "https://technocore.chat/r/d-aizong")
        self.assertEqual(requests.call[1], {
            "since": 431, "wait": 10, "format": "json", "limit": 200})
        self.assertEqual(requests.call[2], 30)

    def test_unknown_source_and_wrong_role_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown Aizong polling"):
            repair.transform(fixture().replace("msgs=fetch_messages()", "msgs=[]"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "collab.py"
            config = root / ".env"
            target.write_text(fixture())
            config.write_text("AGENT_NAME=love8\nROLE=scout\n")
            with self.assertRaisesRegex(ValueError, "ONLY for Aizong"):
                repair.preflight(target, config)

    def test_apply_and_rollback_preserve_state_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "collab.py"
            config = root / ".env"
            state = root / "cursor.txt"
            backups = root / "backups"
            target.write_text(fixture())
            config.write_text("AGENT_NAME=aizong\nROLE=builder\n")
            state.write_text("431")
            original, updated = repair.preflight(target, config)
            service = FakeSystemd()
            backup = repair.apply(target, original, updated, backups, service)
            self.assertEqual(state.read_text(), "431")
            self.assertEqual(service.events, ["stop", "start"])
            self.assertIn(repair.MARKER, target.read_text())
            service.events.clear()
            repair.rollback(backup, target, service)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(state.read_text(), "431")
            self.assertEqual(service.events, ["stop", "start"])


if __name__ == "__main__":
    unittest.main()
