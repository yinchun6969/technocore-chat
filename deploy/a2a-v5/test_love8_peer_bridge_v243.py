import ast
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location('bridge', ROOT / 'repair-love8-peer-bridge-v243.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.original = (ROOT / 'fixtures/love8_deep_rooms_v242.py').read_text()
        self.pins = dict(zip(bridge.KNOWN, ['d-aizong', 'mb-p-reviewer']))
        self.ns = {'json': json, 'Path': Path, 're': re, 'fp': lambda x: x, 'time': time}
        # Execute only the two patched functions, never the runtime module.
        exec(bridge.NEW_ROWS, self.ns)
        tree = ast.parse(bridge.transform(self.original))
        invite = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'send_invite')
        exec(compile(ast.Module(body=[invite], type_ignores=[]), '<test>', 'exec'), self.ns)

    def rows(self):
        with patch.object(Path, 'read_text', return_value=json.dumps(self.pins)):
            return self.ns['peer_rows']()

    def test_transform_idempotent(self):
        new = bridge.transform(self.original)
        self.assertEqual(new, bridge.transform(new))
        ast.parse(new)

    def test_unknown_version_refused(self):
        with self.assertRaises(ValueError):
            bridge.transform('def peer_rows(): return []')

    def test_two_pins_and_room_not_mailbox(self):
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['mailbox'], '')
        self.assertEqual(rows[0]['_pinned_route'], 'd-aizong')

    def test_unknown_did_excluded(self):
        self.pins['did:key:unknown'] = 'mb-unknown'
        self.assertEqual(len(self.rows()), 2)

    def test_missing_pin_fails_closed(self):
        self.pins.pop(next(iter(self.pins)))
        with self.assertRaises(ValueError):
            self.rows()

    def test_invalid_route_fails_closed(self):
        self.pins[next(iter(self.pins))] = 'https://example.com'
        with self.assertRaises(ValueError):
            self.rows()

    def test_pinned_delivery(self):
        calls = []
        class Guard:
            def signed_post(self, *args):
                calls.append(args)
        for row in self.rows():
            state = {}
            with patch.object(Path, 'read_text', return_value=json.dumps(self.pins)):
                ok, reason = self.ns['send_invite'](Guard(), {'BASE': 'https://test/', 'DID': 'test', 'KEY': 'test'}, state, row, 'test')
            self.assertTrue(ok)
            self.assertEqual(calls[-1][3], row['_pinned_route'])
            self.assertEqual(len(state['writes']), 1)

    def test_changed_route_not_sent(self):
        row = self.rows()[0]
        self.pins[row['did']] = 'other-room'
        with patch.object(Path, 'read_text', return_value=json.dumps(self.pins)):
            ok, _ = self.ns['send_invite'](None, {}, {}, row, 'test')
        self.assertFalse(ok)

    def test_check_apply_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target, source, backups = root / 'target.py', root / 'peers.json', root / 'backups'
            target.write_text(self.original)
            target.chmod(0o640)
            source.write_text(json.dumps(self.pins))
            with patch.multiple(bridge, TARGET=target, SOURCE=source, BACKUPS=backups), patch('os.geteuid', return_value=0):
                with patch('sys.argv', ['repair', '--check']): bridge.main()
                self.assertFalse(backups.exists())
                with patch('sys.argv', ['repair', '--apply']): bridge.main()
                self.assertEqual(target.stat().st_mode & 0o777, 0o640)
                directory = next(backups.iterdir())
                with patch('sys.argv', ['repair', '--apply']): bridge.main()
                self.assertEqual(len(list(backups.iterdir())), 1)
                with patch('sys.argv', ['repair', '--rollback', str(directory)]): bridge.main()
                self.assertEqual(target.read_text(), self.original)
                self.assertEqual(json.loads(source.read_text()), self.pins)


if __name__ == '__main__':
    unittest.main()
