#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("existing_did", HERE / "existing_did_quickstart_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ExistingDidQuickstartTests(unittest.TestCase):
    def make_key(self, directory: Path) -> Path:
        path = directory / "existing.pem"
        key = Ed25519PrivateKey.generate()
        path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        path.chmod(0o600)
        return path

    def test_existing_key_derives_stable_did_without_writing_key(self):
        with tempfile.TemporaryDirectory() as raw:
            path = self.make_key(Path(raw))
            before = path.read_bytes()
            first = MODULE.derive_did(MODULE.load_key(path))
            second = MODULE.derive_did(MODULE.load_key(path))
            self.assertEqual(first, second)
            self.assertTrue(first.startswith("did:key:z6Mk"))
            self.assertEqual(path.read_bytes(), before)

    def test_private_key_permissions_fail_closed(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions required")
        with tempfile.TemporaryDirectory() as raw:
            path = self.make_key(Path(raw))
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "group/world accessible"):
                MODULE.load_key(path)

    def test_symlink_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            key = self.make_key(root)
            link = root / "link.pem"
            link.symlink_to(key)
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                MODULE.load_key(link)

    def test_single_line_sweep_matches_protocol_categories(self):
        self.assertEqual(MODULE.clean_text(" hello\nworld\u202e "), "hello world")
        with self.assertRaisesRegex(ValueError, "empty"):
            MODULE.clean_text("\u200d\n")

    def test_send_requires_explicit_public_confirmation(self):
        args = type("Args", (), {"confirm_public": False})()
        with self.assertRaisesRegex(ValueError, "explicit"):
            MODULE.command_send(args)

    def test_no_redirect_handler_refuses_redirects(self):
        handler = MODULE.NoRedirect()
        with self.assertRaises(Exception):
            handler.redirect_request(type("Req", (), {"full_url": "https://a"})(), None, 302, "", {}, "https://b")

    def test_send_path_refuses_possible_room_creation(self):
        original = MODULE.read_room
        MODULE.read_room = lambda *_args, **_kwargs: {"messages": []}
        try:
            with self.assertRaisesRegex(ValueError, "could create"):
                MODULE.remote_nonce("https://technocore.chat", "missing", "did:key:test")
        finally:
            MODULE.read_room = original


if __name__ == "__main__":
    unittest.main()
