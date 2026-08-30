#!/usr/bin/env python3
"""Static safety, pinning, and rollback checks for v5.5.1."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "install-verifiable-evidence-v5.5.1.sh"
V551_RELEASE_HASHES = {
    "autonomous-curator-v5.py": "10b6db42538c754ba4a9fde906321d4ca437ced5470767a7347941bc6f49a48d",
    "evidence_v55.py": "64e361389ff7a247f897f6536de89c640096c5e01b3d236e96d43a5ea1664b9e",
    "task_status_v55.py": "38819807b98da67e01c4841a2939c1898294d4e92e2f541fa7a4e66c0b4a48be",
    "demo_v55.py": "a10e20e68095eeb0d035dfb5139bf00e71055332b148b9c9fd63e8b39b63171f",
    "patch-verified-brief-v5.5.1.py": "8b98157d353707b900dfc7dfceb7c42d0efe0e89edc0a9a399b0f79df8e10b2a",
}


class VerifiableEvidenceV551InstallerTests(unittest.TestCase):
    def setUp(self):
        self.text = INSTALLER.read_text(encoding="utf-8")

    def test_source_is_immutable_and_all_payload_hashes_match(self):
        self.assertIsNotNone(re.search(r'^SOURCE_REF="[0-9a-f]{40}"$', self.text, re.M))
        pairs = dict(re.findall(r'^  \[([^]]+)\]="([0-9a-f]{64})"$', self.text, re.M))
        self.assertEqual(pairs, V551_RELEASE_HASHES)

    def test_check_only_exits_before_lock_backup_install_or_service_restart(self):
        check_exit = self.text.index('[[ "$MODE" == apply ]]')
        for marker in ("exec 9>", 'backup_one "$CURATOR"', 'install -o root', 'systemctl restart "$CURATOR_SERVICE"'):
            self.assertGreater(self.text.index(marker), check_exit)

    def test_ai2ai_only_and_live_state_never_rewound(self):
        self.assertIn('[[ "${AGENT_NAME:-}" == ai2ai ]]', self.text)
        self.assertIn("never-rewind-live-state-or-artifacts", self.text)
        self.assertIn("retry-state,stage-cache,artifacts", self.text)
        self.assertNotIn('rm -rf "$ROOT/rnd-v5-state"', self.text)
        self.assertNotIn('rm -rf "$ROOT/rnd-v5-artifacts"', self.text)

    def test_telegram_is_preflighted_backed_up_patched_and_rollback_guarded(self):
        self.assertIn('backup_one "$TELEGRAM" telegram', self.text)
        self.assertIn('"$TELEGRAM" --apply', self.text)
        self.assertIn('installed Telegram changed; refusing rollback', self.text)
        self.assertIn('restore_one "\\$TELEGRAM" telegram', self.text)
        self.assertIn('systemctl restart "\\$CURATOR_SERVICE" "\\$TELEGRAM_SERVICE"', self.text)


if __name__ == "__main__":
    unittest.main()
