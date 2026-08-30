#!/usr/bin/env python3
"""Failure-path regression coverage for v5.5.1 artifact recovery."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent

FAKE_AGENT = r'''
import json
AGENT = "ai2ai"
BASE = "https://example.invalid"
class Requests:
    def get(self, *args, **kwargs): raise RuntimeError("503 Service Unavailable")
requests = Requests()
def peers(): return {}
def parse(text): return json.loads(text)
def ledger(*args, **kwargs): return None
def payload(*args, **kwargs): return "receipt"
def signed_post(*args, **kwargs): return None
def ai_call(prompt): raise RuntimeError("test must replace ai_call")
'''


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V551RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "a2a"
        (self.root / "bin").mkdir(parents=True)
        (self.root / "bin/agent.py").write_text(FAKE_AGENT, encoding="utf-8")
        self.old_root = os.environ.get("TECHNOCORE_A2A_ROOT")
        self.old_publish = os.environ.get("RND_V5_PUBLISH_RECEIPTS")
        os.environ["TECHNOCORE_A2A_ROOT"] = str(self.root)
        os.environ["RND_V5_PUBLISH_RECEIPTS"] = "0"
        self.curator = load(HERE / "autonomous-curator-v5.py", "curator_v551_recovery")

    def tearDown(self):
        if self.old_root is None:
            os.environ.pop("TECHNOCORE_A2A_ROOT", None)
        else:
            os.environ["TECHNOCORE_A2A_ROOT"] = self.old_root
        if self.old_publish is None:
            os.environ.pop("RND_V5_PUBLISH_RECEIPTS", None)
        else:
            os.environ["RND_V5_PUBLISH_RECEIPTS"] = self.old_publish
        self.temp.cleanup()

    def stages(self, task_id: str = "wf-v551-recovery"):
        fields = {
            "WORKFLOW_TASK": {"goal": "cross evidence test"},
            "BUILD_RESULT": {"build_result": "independent source analysis"},
            "CHALLENGE": {"challenge": "counter evidence verification"},
            "REVISED_RESULT": {"revised_result": "test revision confidence"},
            "COMPLETE": {"final_summary": "verified provenance"},
        }
        return {
            stage: {
                "seq": index, "from": self.curator.evidence_v55.EXPECTED_SIGNERS[stage],
                "room": f"room-{index}", "message_ts": 1788058800000 + index,
                "seen_at": 1788058800 + index,
                "obj": {"type": stage, "task_id": task_id, **fields[stage]},
            }
            for index, stage in enumerate(self.curator.evidence_v55.STAGE_ORDER, 1)
        }

    def valid_text(self, task_id: str, root: str) -> str:
        body = "verified evidence independent source cross validation test challenge confidence " * 5
        sections = [
            "# Title", "## Objective\nWORKFLOW: " + task_id + "\nEVIDENCE_MERKLE_ROOT: " + root,
            "## Verified Evidence", "## Cross-Validation", "## Findings", "## Design Proposal",
            "## Minimal Test Matrix", "## Open Questions", "## Provenance",
        ]
        return ("\n" + body + "\n").join(sections) + "\n" + body

    def test_complete_cached_workflow_survives_room_503(self):
        values = self.stages()
        self.curator.save_cache({"wf-v551-recovery": values}, {"room-x": 10})
        self.curator.rooms = lambda: ["room-x"]
        self.curator.room_messages = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("503 Service Unavailable"))
        scanned = self.curator.scan()
        self.assertTrue(self.curator.complete(scanned["wf-v551-recovery"]))
        rows = [json.loads(line) for line in self.curator.LOG_FILE.read_text().splitlines()]
        self.assertEqual(rows[0]["error_type"], "room_503")
        self.assertEqual(rows[-1]["decision"], "artifact_generation_may_continue")

    def test_malformed_first_draft_is_repaired_and_bound(self):
        stages = self.stages()
        bundle = self.curator.evidence_v55.build_bundle("wf-v551-recovery", stages)
        replies = iter(["too short", self.valid_text("wf-v551-recovery", bundle["merkle_root"])])
        self.curator.agent.ai_call = lambda prompt: next(replies)
        value = self.curator.create("wf-v551-recovery", stages)
        self.assertTrue(value["evidence_verified"])
        self.assertEqual(value["version"], "5.5.1")
        self.assertTrue(self.curator.read_verified_receipt("wf-v551-recovery", stages))

    def test_provider_timeout_sets_persistent_exponential_retry(self):
        stages = self.stages()
        self.curator.scan = lambda: {"wf-v551-recovery": stages}
        self.curator.agent.ai_call = lambda prompt: (_ for _ in ()).throw(RuntimeError("Read timed out (read timeout=90)"))
        self.curator.tick()
        state = json.loads(self.curator.STATE_FILE.read_text())
        retry = state["artifact_retries"]["wf-v551-recovery"]
        self.assertEqual(retry["attempts"], 1)
        self.assertEqual(retry["error_type"], "provider_timeout")
        self.assertEqual(retry["next_retry_at"] - retry["last_attempt_at"], 120)

    def test_receipt_rejects_current_stage_tamper(self):
        stages = self.stages()
        bundle = self.curator.evidence_v55.build_bundle("wf-v551-recovery", stages)
        self.curator.agent.ai_call = lambda prompt: self.valid_text("wf-v551-recovery", bundle["merkle_root"])
        self.curator.create("wf-v551-recovery", stages)
        changed = self.stages()
        changed["COMPLETE"]["obj"]["final_summary"] = "tampered"
        with self.assertRaisesRegex(self.curator.ReceiptVerificationError, "current signed stages"):
            self.curator.read_verified_receipt("wf-v551-recovery", changed)

    def test_verified_brief_patch_rejects_markdown_only_layout(self):
        patcher = load(HERE / "patch-verified-brief-v5.5.1.py", "verified_brief_patch_test")
        source = (HERE / "telegram-control-v1.py").read_text(encoding="utf-8")
        source = source.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\n# RESEARCH_CONTEXT_V32\n",
            1,
        )
        patched = patcher.patch(source)
        self.assertIn('ARTIFACTS.glob("*.json")', patched)
        self.assertIn("最新已验证研究简报", patched)
        self.assertNotIn('files = sorted(ARTIFACTS.glob("*.md")', patched)


if __name__ == "__main__":
    unittest.main()
