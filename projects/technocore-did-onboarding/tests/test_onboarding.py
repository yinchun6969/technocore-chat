from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("onboarding", HERE / "onboarding.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class OnboardingTests(unittest.TestCase):
    def test_new_key_is_local_private_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "identity" / "ed25519_private.pem"
            _key, did = MODULE.generate_key(path)
            self.assertTrue(did.startswith("did:key:z6Mk"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                MODULE.generate_key(path)
            self.assertEqual(path.read_bytes(), before)

    def test_existing_did_record_prevents_partial_key_creation(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw) / "identity"
            directory.mkdir()
            (directory / "did.txt").write_text("keep\n", encoding="utf-8")
            key_path = directory / "ed25519_private.pem"
            with self.assertRaises(FileExistsError):
                MODULE.generate_key(key_path)
            self.assertFalse(key_path.exists())

    def test_imported_key_is_only_read(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "existing.pem"
            MODULE.generate_key(path)
            before = path.read_bytes()
            did = MODULE.derive_did(MODULE.load_key(path))
            self.assertTrue(MODULE.DID_RE.fullmatch(did))
            self.assertEqual(path.read_bytes(), before)

    def test_sensitive_public_text_is_refused(self):
        for value in ("-----BEGIN PRIVATE KEY-----", "api_key=secret", "password: hello", "token=abc"):
            with self.assertRaisesRegex(ValueError, "credential"):
                MODULE.clean_text(value)

    def test_claim_uses_durable_owner_nonce_and_verifies_owner(self):
        with tempfile.TemporaryDirectory() as raw:
            key_path = Path(raw) / "key.pem"
            key, did = MODULE.generate_key(key_path)
            state = Path(raw) / "nonces.json"
            owners = iter([None, did])
            calls = []
            with patch.object(MODULE, "room_owner", side_effect=lambda *_: next(owners)), \
                 patch.object(MODULE, "room_messages", return_value=[]), \
                 patch.object(MODULE, "request", side_effect=lambda *a, **kw: calls.append((a, kw)) or ((404, "") if "room-nonce" in a[0] else (200, "ok"))):
                self.assertEqual(MODULE.claim_room(MODULE.BASE_URL, "d-alice", key, did, state), "claimed")
            claim = next(kw["body"] for args, kw in calls if kw.get("method") == "POST")
            self.assertEqual(claim["value"], did)
            self.assertTrue(claim["if_absent"])
            self.assertRegex(claim["nonce"], r"^\d{1,19}$")
            self.assertEqual(len(claim["sig"]), 86)

    def test_allocator_returns_exact_fallback_room(self):
        owners = iter(["did:key:z6MkOther", None])
        with patch.object(MODULE, "room_owner", side_effect=lambda *_: next(owners)), \
             patch.object(MODULE, "room_messages", return_value=[]), \
             patch.object(MODULE.secrets, "token_hex", return_value="abc123"):
            room = MODULE.allocate_owned_room(MODULE.BASE_URL, "Alice Smith", "did:key:z6MkMine")
        self.assertEqual(room, "d-alice-smith-abc123")

    def test_new_identity_wizard_has_separate_local_confirmation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = type("Args", (), {"lang": "zh", "config": root / "config.json", "state": root / "state/nonces.json", "base_url": MODULE.BASE_URL})()
            answers = iter(["2", "", "创建", "alice", "3"])
            output = io.StringIO()
            with patch("builtins.input", side_effect=lambda *_: next(answers)), redirect_stdout(output):
                MODULE.command_wizard(args)
            cfg = json.loads(args.config.read_text(encoding="utf-8"))
            key_path = Path(cfg["key_path"])
            self.assertEqual(cfg["identity_mode"], "created-local")
            self.assertTrue(key_path.exists())
            self.assertNotIn("BEGIN PRIVATE KEY", output.getvalue())
            self.assertIn("private_key=local-only", output.getvalue())

    def test_import_wizard_references_existing_key_without_copying_it(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            key_path = root / "existing.pem"
            _key, did = MODULE.generate_key(key_path)
            before = key_path.read_bytes()
            args = type("Args", (), {"lang": "en", "config": root / "config.json", "state": root / "state/nonces.json", "base_url": MODULE.BASE_URL})()
            answers = iter(["1", str(key_path), did, "alice", "3"])
            with patch("builtins.input", side_effect=lambda *_: next(answers)):
                MODULE.command_wizard(args)
            cfg = json.loads(args.config.read_text(encoding="utf-8"))
            self.assertEqual(cfg["identity_mode"], "imported-reference")
            self.assertEqual(Path(cfg["key_path"]), key_path)
            self.assertEqual(key_path.read_bytes(), before)

    def test_owned_room_requires_second_confirmation_and_posts_once(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = type("Args", (), {"lang": "en", "config": root / "config.json", "state": root / "state/nonces.json", "base_url": MODULE.BASE_URL})()
            answers = iter(["2", "", "CREATE", "alice", "2", "CREATE"])
            with patch("builtins.input", side_effect=lambda *_: next(answers)), \
                 patch.object(MODULE, "allocate_owned_room", return_value="d-alice"), \
                 patch.object(MODULE, "claim_room", return_value="claimed") as claim, \
                 patch.object(MODULE, "signed_post") as post:
                MODULE.command_wizard(args)
            claim.assert_called_once()
            post.assert_called_once()
            self.assertEqual(json.loads(args.config.read_text(encoding="utf-8"))["room"], "d-alice")

    def test_public_send_requires_confirmation(self):
        args = type("Args", (), {"confirm_public": False})()
        with self.assertRaisesRegex(ValueError, "confirm-public"):
            MODULE.command_send(args)


if __name__ == "__main__":
    unittest.main()
