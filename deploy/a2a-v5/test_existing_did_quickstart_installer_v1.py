#!/usr/bin/env python3
from __future__ import annotations

import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "install-existing-did-quickstart-v1.sh"


class ExistingDidInstallerTests(unittest.TestCase):
    def setUp(self):
        self.text = INSTALLER.read_text(encoding="utf-8")

    def test_source_and_dependency_are_immutable(self):
        self.assertIsNotNone(re.search(r'^SOURCE_REF="[0-9a-f]{40}"$', self.text, re.M))
        self.assertNotIn('SOURCE_REF="0000000000000000000000000000000000000000"', self.text)
        self.assertIsNotNone(re.search(r'^CLIENT_SHA256="[0-9a-f]{64}"$', self.text, re.M))
        self.assertIn('"cryptography==46.0.3"', self.text)

    def test_check_only_exits_before_venv_or_install(self):
        check = self.text.index('if [[ "$MODE" == check ]]')
        exit_at = self.text.index("exit 0", check)
        self.assertGreater(self.text.index('python3 -m venv', exit_at), exit_at)
        self.assertGreater(self.text.index('backup_one "$INSTALL_ROOT/venv"', exit_at), exit_at)

    def test_identity_is_referenced_never_managed(self):
        self.assertIn("private-key-never-copied-or-printed", self.text)
        self.assertNotRegex(self.text, r'(cp|mv|install|rm).*\$KEY_PATH')
        self.assertNotIn("openssl genpkey", self.text)
        self.assertNotIn("mb-p-$(", self.text)

    def test_explicit_send_and_transaction_rollback(self):
        self.assertIn("public-send-requires---confirm-public", self.text)
        trap_on = self.text.index("trap 'rollback_transaction $?' ERR")
        install_at = self.text.index('rm -rf -- "$INSTALL_ROOT/venv"')
        trap_off = self.text.index("trap - ERR", install_at)
        self.assertLess(trap_on, install_at)
        self.assertLess(install_at, trap_off)

    def test_live_nonce_state_is_not_backed_up_or_removed(self):
        self.assertIn('install -d -m 0700 "$INSTALL_ROOT/state"', self.text)
        self.assertNotIn('backup_one "$INSTALL_ROOT/state"', self.text)
        self.assertNotIn('restore_one "$INSTALL_ROOT/state"', self.text)

    def test_manual_rollback_restores_its_previous_entrypoint(self):
        generated = self.text[self.text.index('cat >"$ROLLBACK_PATH"') :]
        self.assertIn('restore_one "$ROLLBACK_PATH" rollback', generated)


if __name__ == "__main__":
    unittest.main()
