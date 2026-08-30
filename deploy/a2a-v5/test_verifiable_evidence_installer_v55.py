#!/usr/bin/env python3
"""Static safety and pinning checks for the v5.5 targeted installer."""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "install-verifiable-evidence-v5.5.sh"


class VerifiableEvidenceInstallerTests(unittest.TestCase):
    def setUp(self):
        self.text = INSTALLER.read_text(encoding="utf-8")

    def test_source_is_immutable_and_payload_hashes_match(self):
        match = re.search(r'^SOURCE_REF="([0-9a-f]{40})"$', self.text, re.M)
        self.assertIsNotNone(match)
        pairs = dict(re.findall(r'^  \[([^]]+)\]="([0-9a-f]{64})"$', self.text, re.M))
        for name in ("autonomous-curator-v5.py", "evidence_v55.py", "task_status_v55.py", "demo_v55.py"):
            digest = hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            self.assertEqual(pairs.get(name), digest)

    def test_live_state_is_never_restored_or_deleted(self):
        self.assertIn("never-rewind-live-state", self.text)
        self.assertIn("stage-cache,artifacts", self.text)
        self.assertNotIn('rm -rf "$ROOT/rnd-v5-state"', self.text)
        self.assertNotIn('rm -rf "$ROOT/rnd-v5-artifacts"', self.text)
        self.assertNotRegex(self.text, r'tar .*rnd-v5-state')

    def test_unknown_short_cli_is_preserved(self):
        self.assertIn("existing unrelated /usr/local/bin/technocore preserved", self.text)
        self.assertIn("grep -q 'TECHNOCORE_A2A_V55_CLI'", self.text)

    def test_preflight_is_offline_verified_before_apply(self):
        check_position = self.text.index("A2A_V55_OFFLINE_DEMO=PASS")
        apply_position = self.text.index('[[ "$MODE" == apply ]]')
        self.assertLess(check_position, apply_position)


if __name__ == "__main__":
    unittest.main()
