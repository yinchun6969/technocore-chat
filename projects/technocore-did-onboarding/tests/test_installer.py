from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "install.sh").read_text(encoding="utf-8")


class InstallerTests(unittest.TestCase):
    def test_helper_and_dependency_are_pinned(self):
        self.assertIsNotNone(re.search(r'^SOURCE_REF="[0-9a-f]{40}"$', TEXT, re.M))
        self.assertIsNotNone(re.search(r'^WIZARD_SHA256="[0-9a-f]{64}"$', TEXT, re.M))
        self.assertIn('"cryptography==46.0.3"', TEXT)

    def test_check_only_exits_before_venv_and_backup(self):
        check = TEXT.index('if [[ "$MODE" == check ]]')
        exit_at = TEXT.index("exit 0", check)
        self.assertGreater(TEXT.index("python3 -m venv", exit_at), exit_at)
        self.assertGreater(TEXT.index('backup_one "$INSTALL_ROOT/venv"', exit_at), exit_at)

    def test_identity_and_state_are_never_managed_targets(self):
        self.assertNotIn('backup_one "$INSTALL_ROOT/identity"', TEXT)
        self.assertNotIn('restore_one "$INSTALL_ROOT/identity"', TEXT)
        self.assertNotIn('backup_one "$INSTALL_ROOT/state"', TEXT)
        self.assertNotIn('restore_one "$INSTALL_ROOT/state"', TEXT)
        self.assertNotIn("openssl genpkey", TEXT)

    def test_post_backup_failure_is_transactional_and_truthful(self):
        trap_on = TEXT.index("trap 'rollback_transaction $?' ERR")
        first_write = TEXT.index('rm -rf -- "$INSTALL_ROOT/venv"')
        trap_off = TEXT.index("trap - ERR", first_write)
        self.assertLess(trap_on, first_write)
        self.assertLess(first_write, trap_off)
        self.assertIn("TRANSACTION_ROLLBACK=INCOMPLETE", TEXT)

    def test_wizard_requires_tty_or_explicit_no_wizard(self):
        self.assertIn("interactive wizard requires a terminal", TEXT)
        self.assertIn("--no-wizard", TEXT)


if __name__ == "__main__":
    unittest.main()
