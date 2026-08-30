#!/usr/bin/env python3
"""Integration and offline E2E coverage for the v5.5 evidence release."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


FAKE_AGENT = r'''
import json
import re
AGENT = "ai2ai"
BASE = "https://example.invalid"
class Requests:
    def get(self, *args, **kwargs): raise RuntimeError("network disabled in integration test")
requests = Requests()
def peers(): return {}
def parse(text): return json.loads(text)
def ledger(*args, **kwargs): return None
def payload(*args, **kwargs): return "receipt"
def signed_post(*args, **kwargs): return None
def ai_call(prompt):
    workflow = re.search(r"WORKFLOW:\s*(wf-[^\s]+)", prompt).group(1)
    merkle = re.search(r"EVIDENCE_MERKLE_ROOT:\s*([0-9a-f]{64})", prompt).group(1)
    body = "verified evidence and independent source cross validation test challenge confidence " * 5
    return "# Title\n## Objective\nWORKFLOW: " + workflow + "\nEVIDENCE_MERKLE_ROOT: " + merkle + "\n" + body + "\n## Verified Evidence\n" + body + "\n## Cross-Validation\n" + body + "\n## Findings\n" + body + "\n## Design Proposal\n" + body + "\n## Minimal Test Matrix\n" + body + "\n## Open Questions\n" + body + "\n## Provenance\n" + body
'''


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V55IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "a2a"
        (self.root / "bin").mkdir(parents=True)
        (self.root / "bin/agent.py").write_text(FAKE_AGENT, encoding="utf-8")
        self.old_root = os.environ.get("TECHNOCORE_A2A_ROOT")
        self.old_publish = os.environ.get("RND_V5_PUBLISH_RECEIPTS")
        os.environ["TECHNOCORE_A2A_ROOT"] = str(self.root)
        os.environ["RND_V5_PUBLISH_RECEIPTS"] = "0"

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

    def stages(self, evidence):
        values = {}
        fields = {
            "WORKFLOW_TASK": {"goal": "cross evidence test"},
            "BUILD_RESULT": {"build_result": "independent source analysis"},
            "CHALLENGE": {"challenge": "counter evidence verification"},
            "REVISED_RESULT": {"revised_result": "test revision confidence"},
            "COMPLETE": {"final_summary": "verified provenance"},
        }
        for index, stage in enumerate(evidence.STAGE_ORDER, 1):
            values[stage] = {
                "seq": index, "from": evidence.EXPECTED_SIGNERS[stage], "room": f"room-{index}",
                "message_ts": 1788058800000 + index,
                "obj": {"type": stage, "task_id": "wf-v55-integration", **fields[stage]},
            }
        return values

    def test_curator_creates_verified_receipt_and_cli_reports_it(self):
        curator = load_module(HERE / "autonomous-curator-v5.py", "curator_v55_integration")
        value = curator.create("wf-v55-integration", self.stages(curator.evidence_v55))
        self.assertTrue(value["evidence_verified"])
        self.assertEqual(value["saga"]["state"], "ARTIFACT_VERIFIED")
        self.assertRegex(value["evidence_merkle_root"], r"^[0-9a-f]{64}$")

        curator.save_cache({"wf-v55-integration": self.stages(curator.evidence_v55)}, {})
        status = load_module(HERE / "task_status_v55.py", "task_status_v55_integration")
        snapshot = status.snapshot("wf-v55-integration")
        self.assertEqual(snapshot["state"], "ARTIFACT_VERIFIED")
        self.assertTrue(snapshot["evidence_verified"])

        artifact = self.root / "rnd-v5-artifacts/wf-v55-integration.md"
        artifact.write_text(artifact.read_text() + "tampered\n", encoding="utf-8")
        tampered = status.snapshot("wf-v55-integration")
        self.assertEqual(tampered["state"], "COMPLETE_SIGNED")
        self.assertFalse(tampered["evidence_verified"])
        self.assertEqual(tampered["verification_error"], "artifact SHA256 mismatch")

    def test_offline_e2e_generates_verifiable_files(self):
        output = Path(self.temp.name) / "demo"
        result = subprocess.run(
            ["python3", str(HERE / "demo_v55.py"), "--output", str(output)],
            text=True, capture_output=True, check=True, timeout=20,
        )
        self.assertIn("A2A_V55_OFFLINE_DEMO=PASS", result.stdout)
        bundle = json.loads((output / "evidence-bundle.json").read_text())
        evidence = load_module(HERE / "evidence_v55.py", "evidence_v55_e2e")
        self.assertTrue(evidence.verify_bundle(bundle))
        self.assertTrue((output / "artifact.md").exists())
        self.assertEqual(len((output / "run.jsonl").read_text().splitlines()), 6)


if __name__ == "__main__":
    unittest.main()
