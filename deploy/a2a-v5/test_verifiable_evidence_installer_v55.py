#!/usr/bin/env python3
"""Static safety and pinning checks for the v5.5 targeted installer."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "install-verifiable-evidence-v5.5.sh"
V55_RELEASE_HASHES = {
    "autonomous-curator-v5.py": "de5a95850324f478ce32def3dd2f164ecab2fd129e4b373532a8587e46a96cd1",
    "evidence_v55.py": "64e361389ff7a247f897f6536de89c640096c5e01b3d236e96d43a5ea1664b9e",
    "task_status_v55.py": "d22504ec648ca2a791d0353a14e4c487ca4535a6c8f08ad3a820988be62faa84",
    "demo_v55.py": "a10e20e68095eeb0d035dfb5139bf00e71055332b148b9c9fd63e8b39b63171f",
}


class VerifiableEvidenceInstallerTests(unittest.TestCase):
    def setUp(self):
        self.text = INSTALLER.read_text(encoding="utf-8")

    def test_source_is_immutable_and_payload_hashes_match(self):
        match = re.search(r'^SOURCE_REF="([0-9a-f]{40})"$', self.text, re.M)
        self.assertIsNotNone(match)
        pairs = dict(re.findall(r'^  \[([^]]+)\]="([0-9a-f]{64})"$', self.text, re.M))
        self.assertEqual(pairs, V55_RELEASE_HASHES)

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
