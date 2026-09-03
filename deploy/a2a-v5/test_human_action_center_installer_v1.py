#!/usr/bin/env python3
"""Static safety regression for the Human Action Center installer."""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INSTALLER = ROOT / "install-human-action-center-v1.sh"


class HumanActionCenterInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = INSTALLER.read_text(encoding="utf-8")

    def test_immutable_source_and_payload_hashes(self) -> None:
        ref = re.search(r'^SOURCE_REF="([0-9a-f]{40})"$', self.source, re.MULTILINE)
        self.assertIsNotNone(ref)

        hashes = dict(
            re.findall(r'^  \[([^]]+)\]="([0-9a-f]{64})"$', self.source, re.MULTILINE)
        )
        required = {
            "autonomous-curator-v5.py",
            "human_action_center_v1.py",
            "telegram-control-v1.py",
            "research_context_v32.py",
            "patch-research-context-v3.2.py",
            "patch-verified-brief-v5.5.1.py",
            "compose-human-action-telegram-v1.py",
            "test_human_action_center_v1.py",
            "test_telegram_notifications_v53.py",
        }
        self.assertEqual(required, set(hashes))
        for name, expected in hashes.items():
            actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            self.assertEqual(expected, actual, name)

    def test_check_mode_exits_before_lock_backup_or_install(self) -> None:
        check_exit = self.source.index('[[ "$MODE" == apply ]] ||')
        lock = self.source.index("exec 9>/run/lock/")
        backup = self.source.index('backup="$BACKUP_ROOT/$stamp"')
        first_install = self.source.index('install -o root -g tcagent -m 0750')
        self.assertLess(check_exit, lock)
        self.assertLess(check_exit, backup)
        self.assertLess(check_exit, first_install)
        self.assertIn("CHECK_ONLY: no installed files, services or live state changed", self.source)

    def test_live_identity_and_state_are_explicitly_preserved(self) -> None:
        self.assertIn(
            "preserved=did,private-key,mailbox,peers,cursors,nonces,provenance,"
            "stage-cache,retries,artifacts,human-action-queue,telegram-offsets,drafts",
            self.source,
        )
        self.assertIn("rollback_policy=code-only;never-rewind-or-delete-live-state", self.source)
        forbidden_mutations = (
            r"rm\s+-[^\n]*\s(?:\$ROOT|\$RND)(?:/rnd-v5-(?:state|artifacts))?\b",
            r"install\s+[^\n]*(?:\.env|private|mailbox|human-actions\.json)",
            r"cp\s+[^\n]*(?:\.env|private|mailbox|human-actions\.json)",
        )
        for pattern in forbidden_mutations:
            self.assertIsNone(re.search(pattern, self.source), pattern)

    def test_transaction_restores_every_managed_file_and_service_state(self) -> None:
        for name in ("curator", "action", "telegram", "context", "rollback_cli"):
            self.assertIn(f'restore_one "$ROLLBACK" {name}' if name == "rollback_cli" else name, self.source)
        transaction = self.source[self.source.index("rollback_transaction()") :]
        for exact in (
            'restore_one "$CURATOR" curator',
            'restore_one "$ACTION" action',
            'restore_one "$TELEGRAM" telegram',
            'restore_one "$CONTEXT" context',
            'restore_one "$ROLLBACK" rollback_cli',
            "restore_services",
        ):
            self.assertIn(exact, transaction)
        self.assertIn("curator_was=", self.source)
        self.assertIn("telegram_was=", self.source)
        self.assertIn("trap 'rollback_transaction $?' ERR", self.source)

    def test_preflight_composes_and_tests_the_final_telegram_source(self) -> None:
        compose = self.source.index("compose-human-action-telegram-v1.py")
        move_final = self.source.index('mv "$stage/telegram-final.py"')
        action_test = self.source.index('"$stage/test_human_action_center_v1.py"')
        telegram_test = self.source.index('"$stage/test_telegram_notifications_v53.py"')
        apply_gate = self.source.index('[[ "$MODE" == apply ]] ||')
        self.assertLess(compose, move_final)
        self.assertLess(move_final, action_test)
        self.assertLess(action_test, apply_gate)
        self.assertLess(telegram_test, apply_gate)

    def test_authority_boundary_is_fail_closed(self) -> None:
        for marker in (
            'grep -Fq \'auto_pr": False\'',
            "authority=record-human-intent-only",
            "auto-pr=false",
            "server-write=false",
            "public-post=false",
        ):
            self.assertIn(marker, self.source)

    def test_alert_policy_is_high_severity_only(self) -> None:
        self.assertIn("verified-high-severity-v2", self.source)
        self.assertIn(
            "alerts=P0/P1-high-severity-only;minor=ignored;legacy-P1-P2=hidden-preserved",
            self.source,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
