#!/usr/bin/env python3
"""Offline tests for Aizong signed evidence mirroring."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("mirror", HERE / "repair-aizong-evidence-mirror-v3.5.py")
mirror = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mirror)


class TransformTests(unittest.TestCase):
    def fixture(self):
        return (HERE / "aizong-wire-v34/workflow_fixture.py").read_text()

    def test_transform_is_idempotent_and_mirrors_both_builder_stages(self):
        updated = mirror.transform(self.fixture())
        self.assertEqual(mirror.transform(updated), updated)
        self.assertEqual(updated.count(mirror.MARKER), 1)
        self.assertIn("wf_evidence_mirror_v35(LOVE8_DID,'BUILD_RESULT'", updated)
        self.assertIn("wf_evidence_mirror_v35(AI2AI_DID,'REVISED_RESULT'", updated)
        compile(updated, "collab.py", "exec")

    def test_unknown_runtime_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown workflow"):
            mirror.transform(self.fixture().replace("workflow_build_result", "changed_event"))

    def test_role_preflight_and_no_write_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "collab.py"
            config = root / ".env"
            target.write_text(self.fixture())
            config.write_text("AGENT_NAME=aizong\nROLE=builder\n")
            original, updated = mirror.preflight(target, config)
            self.assertNotEqual(original, updated)
            self.assertEqual(target.read_bytes(), original)
            config.write_text("AGENT_NAME=love8\nROLE=scout\n")
            with self.assertRaisesRegex(ValueError, "ONLY for Aizong"):
                mirror.preflight(target, config)


if __name__ == "__main__":
    unittest.main()
