#!/usr/bin/env python3
"""Offline tests for Love8 transient outbound duplicate-check recovery."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "love8_outbound", HERE / "repair-love8-outbound-dedupe-v3.7.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


def fixture() -> str:
    return """import time
def transient_error(e):
    return isinstance(e,requests.RequestException)
def outbound_seen(mailbox,tid,kind):
    r=requests.get(f'{BASE}/r/{quote(mailbox)}',params={'format':'json','limit':200},timeout=25); r.raise_for_status()
    for m in r.json().get('messages',[]):
        if m.get('from')!=DID: continue
        x=parse(m.get('text'))
        if x and x.get('task_id')==tid and x.get('type')==kind: return True
    return False
"""


class RequestException(Exception):
    pass


class Response:
    def __init__(self, messages=None, error=None):
        self.messages = messages or []
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return {"messages": self.messages}


class Requests:
    RequestException = RequestException

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def outbound(requests, sleeps):
    namespace = {
        "requests": requests,
        "time": type("Clock", (), {"sleep": staticmethod(sleeps.append)}),
        "BASE": "https://technocore.chat",
        "quote": lambda value: value,
        "DID": "did:key:love8",
        "parse": lambda value: value,
        "transient_error": lambda error: isinstance(error, RequestException),
    }
    exec(repair.NEW, namespace)
    return namespace["outbound_seen"]


class Love8OutboundTests(unittest.TestCase):
    def test_transient_503_shape_retries_then_succeeds(self):
        requests = Requests([Response(error=RequestException("503")), Response([])])
        sleeps = []
        self.assertFalse(outbound(requests, sleeps)("d-aizong", "wf-1", "WORKFLOW_TASK"))
        self.assertEqual(requests.calls, 2)
        self.assertEqual(sleeps, [1])

    def test_existing_stage_is_detected_after_retry(self):
        message = {"from": "did:key:love8", "text": {"task_id": "wf-1", "type": "WORKFLOW_TASK"}}
        requests = Requests([Response(error=RequestException("503")), Response([message])])
        self.assertTrue(outbound(requests, [])("d-aizong", "wf-1", "WORKFLOW_TASK"))

    def test_five_failures_stop_without_claiming_send(self):
        requests = Requests([Response(error=RequestException("503")) for _ in range(5)])
        sleeps = []
        with self.assertRaisesRegex(RuntimeError, "no stage sent"):
            outbound(requests, sleeps)("d-aizong", "wf-1", "WORKFLOW_TASK")
        self.assertEqual(requests.calls, 5)
        self.assertEqual(sleeps, [1, 2, 4, 8])

    def test_transform_role_apply_and_rollback(self):
        updated = repair.transform(fixture())
        self.assertEqual(repair.transform(updated), updated)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, config = root / "collab.py", root / ".env"
            state, backups = root / "cursor.txt", root / "backups"
            target.write_text(fixture())
            config.write_text("AGENT_NAME=love8\nROLE=scout\n")
            state.write_text("97")
            original, changed = repair.preflight(target, config)

            class Service:
                def __init__(self): self.events = []
                def active(self): return True
                def stop(self): self.events.append("stop")
                def start(self): self.events.append("start")

            service = Service()
            backup = repair.apply(target, original, changed, backups, service)
            self.assertEqual(state.read_text(), "97")
            self.assertIn(repair.MARKER, target.read_text())
            repair.rollback(backup, target, service)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(state.read_text(), "97")

    def test_runtime_falls_back_to_active_process_runner(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if argv[:2] == ["systemctl", "show"]:
                return subprocess.CompletedProcess(argv, 1, "", "not found")
            if argv == ["tc-collab-process-status"]:
                return subprocess.CompletedProcess(argv, 0, "runner: ACTIVE pid=42\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        runtime = repair.Runtime(run, lambda command: "/usr/local/bin/" + command,
                                 lambda seconds: None)
        self.assertTrue(runtime.active())
        self.assertEqual(runtime.mode, "runner")
        runtime.stop()
        runtime.start()
        self.assertIn(["tc-collab-stop"], calls)
        self.assertIn(["tc-collab-start"], calls)


if __name__ == "__main__":
    unittest.main()
