#!/usr/bin/env python3
"""Offline tests for cursor-aware Love8 Scout polling."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "love8_inbound", HERE / "repair-love8-inbound-cursor-v3.8.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


def fixture(fallback=True) -> str:
    fallback_line = "FALLBACK_INBOX=os.environ.get('A2A_FALLBACK_INBOX','').strip()\n" if fallback else ""
    fetch = repair.FETCH_OLD_FALLBACK if fallback else repair.FETCH_OLD_MAILBOX
    return f"""import os
{fallback_line}{repair.PREREQUISITE}
{fetch}
def run():
    cur=431
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
        return {"messages": [{"seq": 432}]}


class Requests:
    def __init__(self):
        self.call = None

    def get(self, url, params, timeout):
        self.call = (url, params, timeout)
        return Response()


class FakeRuntime:
    def __init__(self, active=True):
        self.is_active = active
        self.mode = "process-runner"
        self.events = []

    def active(self):
        return self.is_active

    def stop(self):
        self.events.append("stop")

    def start(self):
        self.events.append("start")


class Love8InboundTests(unittest.TestCase):
    def test_transform_is_idempotent_and_passes_cursor(self):
        updated = repair.transform(fixture())
        self.assertEqual(repair.transform(updated), updated)
        self.assertEqual(updated.count(repair.MARKER), 1)
        self.assertIn("msgs=fetch_messages(cur)", updated)
        self.assertIn("'since':cursor", updated)
        self.assertIn("'wait':10", updated)

    def test_transform_supports_direct_mailbox_variant(self):
        updated = repair.transform(fixture(fallback=False))
        self.assertIn(repair.FETCH_NEW_MAILBOX, updated)
        self.assertIn("msgs=fetch_messages(cur)", updated)

    def test_fetch_uses_fallback_room_and_exact_cursor(self):
        requests = Requests()
        namespace = {
            "FALLBACK_INBOX": "d-love8",
            "MAILBOX": "mb-p-private",
            "BASE": "https://technocore.chat",
            "quote": lambda value: value,
            "requests": requests,
        }
        exec(repair.FETCH_NEW_FALLBACK, namespace)
        self.assertEqual(namespace["fetch_messages"](431), [{"seq": 432}])
        self.assertEqual(requests.call[0], "https://technocore.chat/r/d-love8")
        self.assertEqual(requests.call[1], {
            "since": 431, "wait": 10, "format": "json", "limit": 200})
        self.assertEqual(requests.call[2], 30)

    def test_unknown_source_prerequisite_and_wrong_role_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "prerequisite absent"):
            repair.transform(fixture().replace(repair.PREREQUISITE, ""))
        with self.assertRaisesRegex(ValueError, "unknown Love8 polling"):
            repair.transform(fixture().replace("msgs=fetch_messages()", "msgs=[]"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "collab.py"
            config = root / ".env"
            target.write_text(fixture())
            config.write_text("AGENT_NAME=aizong\nROLE=builder\n")
            with self.assertRaisesRegex(ValueError, "ONLY for Love8"):
                repair.preflight(target, config)

    def test_runtime_falls_back_to_process_runner(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            if argv == ["systemctl", "show", "-p", "LoadState", "--value",
                        repair.SERVICE]:
                return subprocess.CompletedProcess(argv, 1, "", "not found")
            if argv == ["tc-collab-process-status"]:
                return subprocess.CompletedProcess(argv, 0, "runner: ACTIVE pid=42\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        runtime = repair.Runtime(runner=runner, which=lambda _: "/bin/fake", sleeper=lambda _: None)
        self.assertTrue(runtime.active())
        self.assertEqual(runtime.mode, "process-runner")
        runtime.stop()
        runtime.start()
        self.assertIn(["tc-collab-stop"], calls)
        self.assertIn(["tc-collab-start"], calls)

    def test_apply_and_rollback_preserve_cursor_and_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "collab.py"
            config = root / ".env"
            state = root / "cursor.txt"
            backups = root / "backups"
            target.write_text(fixture())
            config.write_text("AGENT_NAME=love8\nROLE=scout\n")
            state.write_text("431")
            original, updated = repair.preflight(target, config)
            runtime = FakeRuntime()
            backup = repair.apply(target, original, updated, backups, runtime)
            self.assertEqual(state.read_text(), "431")
            self.assertEqual(runtime.events, ["stop", "start"])
            self.assertIn(repair.MARKER, target.read_text())
            runtime.events.clear()
            repair.rollback(backup, target, runtime)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(state.read_text(), "431")
            self.assertEqual(runtime.events, ["stop", "start"])


if __name__ == "__main__":
    unittest.main()
