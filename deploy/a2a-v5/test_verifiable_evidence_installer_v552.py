#!/usr/bin/env python3
"""Static transactional and immutable-release checks for v5.5.2."""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "install-verifiable-evidence-v5.5.2.sh"


class VerifiableEvidenceV552InstallerTests(unittest.TestCase):
    def setUp(self):
        self.text = INSTALLER.read_text(encoding="utf-8")

    def test_source_is_immutable_and_payload_hashes_match(self):
        self.assertIsNotNone(re.search(r'^SOURCE_REF="[0-9a-f]{40}"$', self.text, re.M))
        pairs = dict(re.findall(r'^  \[([^]]+)\]="([0-9a-f]{64})"$', self.text, re.M))
        expected = {
            name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in (
                "autonomous-curator-v5.py", "evidence_v55.py", "task_status_v55.py",
                "demo_v55.py", "patch-verified-brief-v5.5.1.py",
            )
        }
        self.assertEqual(pairs, expected)

    def test_check_only_is_before_backup_and_apply(self):
        check_exit = self.text.index('[[ "$MODE" == apply ]]')
        self.assertGreater(self.text.index('backup_one "$CURATOR"'), check_exit)
        self.assertGreater(self.text.index('install -o root'), check_exit)
        self.assertIn("CHECK_ONLY: no installed files, services or live state changed", self.text)

    def test_every_mutating_step_is_inside_transaction_trap(self):
        trap_on = self.text.index("trap 'rollback_transaction $?' ERR")
        first_install = self.text.index('install -o root -g tcagent -m 0750')
        patch_apply = self.text.index('"$TELEGRAM" --apply')
        service_restart = self.text.index('systemctl restart "$CURATOR_SERVICE" "$TELEGRAM_SERVICE"', patch_apply)
        trap_off = self.text.index("trap - ERR", service_restart)
        self.assertLess(trap_on, first_install)
        self.assertLess(first_install, patch_apply)
        self.assertLess(patch_apply, service_restart)
        self.assertLess(service_restart, trap_off)

    def test_transaction_restores_every_managed_file_and_services(self):
        body = self.text[self.text.index("rollback_transaction()") : self.text.index("trap 'rollback_transaction")]
        for marker in (
            'restore_one "$CURATOR" curator', 'restore_one "$EVIDENCE" evidence',
            'restore_one "$STATUS" status', 'restore_one "$TELEGRAM" telegram',
            'restore_one "$CLI" cli', 'restore_one "$ROLLBACK" rollback_cli',
            'systemctl restart "$CURATOR_SERVICE" "$TELEGRAM_SERVICE"',
        ):
            self.assertIn(marker, body)

    def test_identity_and_live_state_are_never_targets(self):
        self.assertIn('[[ "${AGENT_NAME:-}" == ai2ai ]]', self.text)
        self.assertIn("never-rewind-live-state-or-artifacts", self.text)
        self.assertNotRegex(self.text, r'(rm|cp|install).*rnd-v5-state')
        self.assertNotRegex(self.text, r'(rm|cp|install).*rnd-v5-artifacts')


if __name__ == "__main__":
    unittest.main()
