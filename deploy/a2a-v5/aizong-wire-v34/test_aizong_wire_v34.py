import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('repair', ROOT / 'repair-aizong-wire-v3.4.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def scope(block=r.WIRE):
    ns = dict(json=json, hashlib=hashlib, DID='did:key:' + 'x' * 48,
              MAILBOX='mb-p-' + 'f' * 32, ROLE='builder', MAX_A2A_WIRE_BYTES=3400)
    exec(compile(block, '<isolated-pure-functions>', 'exec'), ns)
    return ns


def fixture():
    return 'import json, hashlib\nMAX_A2A_WIRE_BYTES=3400\n' + r.OLD + '\ndef parse(text):\n    return text\n'


class Encoder(unittest.TestCase):
    def setUp(self):
        self.ns = scope()

    def encode(self, kind='BUILD_RESULT', **kw):
        value = self.ns['payload'](kind, 'wf-real-test', **kw)
        self.assertTrue(value.startswith('A2A1 '))
        self.assertLessEqual(len(value.encode()), 3400)
        data = json.loads(value[5:])
        self.assertEqual(data['role'], 'builder')
        self.assertEqual(data['task_id'], 'wf-real-test')
        return data

    def test_original_chinese_bug_reproduced(self):
        with self.assertRaisesRegex(ValueError, 'too large after compaction'):
            scope(r.OLD)['payload']('BUILD_RESULT', 'wf-real-test',
                                   goal='中' * 1400, build_result='文' * 1800)

    def test_original_revision_bug_reproduced(self):
        with self.assertRaisesRegex(ValueError, 'too large after compaction'):
            scope(r.OLD)['payload']('REVISED_RESULT', 'wf-real-test',
                goal='中' * 900, challenge='核' * 1100, revised_result='改' * 1700)

    def test_small_payload_byte_identical(self):
        for kind in ('ACK', 'TASK', 'RESULT', 'BUILD_RESULT', 'COMPLETE'):
            a = self.ns['payload'](kind, 'wf', goal='测试😀 "x" \\ \n', status='ok')
            self.assertEqual(a, scope(r.OLD)['payload'](kind, 'wf', goal='测试😀 "x" \\ \n', status='ok'))

    def test_chinese_metadata_and_priority(self):
        kw = dict(goal='中' * 1400, build_result='文' * 1800, scout_did='did:key:scout',
                  reviewer_did='did:key:reviewer', builder_did='did:key:builder',
                  evidence_sha256='e' * 64, policy={'mode': 'read-only'})
        before = json.dumps(kw)
        obj = self.encode(**kw)
        self.assertGreater(len(obj['build_result']), len(obj['goal']))
        self.assertEqual(obj['policy'], kw['policy'])
        self.assertEqual(obj['evidence_sha256'], kw['evidence_sha256'])
        self.assertEqual(obj['reviewer_did'], kw['reviewer_did'])
        self.assertEqual(json.dumps(kw), before)
        original = {'v': 1, 'type': 'BUILD_RESULT', 'task_id': 'wf-real-test',
                    'from_did': self.ns['DID'], 'reply_mailbox': self.ns['MAILBOX'],
                    'role': 'builder', **kw}
        self.assertEqual(obj['_wire']['original_sha256'],
                         hashlib.sha256(self.ns['_wire_encode_v34'](original).encode()).hexdigest())
        self.assertTrue(obj['build_result'].endswith('...[truncated]'))

    def test_revision_priority(self):
        obj = self.encode('REVISED_RESULT', goal='中' * 900, challenge='核' * 1100,
                          revised_result='改' * 1700)
        self.assertGreater(len(obj['revised_result']), len(obj['challenge']))

    def test_all_stage_kinds(self):
        for kind, field in [('TASK', 'goal'), ('WORKFLOW_TASK', 'goal'), ('RESULT', 'result'),
                            ('BUILD_RESULT', 'build_result'), ('CHALLENGE', 'challenge'),
                            ('REVISED_RESULT', 'revised_result'), ('COMPLETE', 'final_summary')]:
            with self.subTest(kind=kind):
                self.assertTrue(self.encode(kind, **{field: '核验😀' * 2000})['_wire']['truncated'])

    def test_protected_fields(self):
        for key in ('v', 'type', 'task_id', 'from_did', 'reply_mailbox', 'role', '_wire'):
            with self.assertRaises(ValueError):
                self.ns['payload']('TASK', 'wf', **{key: 'override'})

    def test_structural_overflow_fails_closed(self):
        for kw in (dict(metadata='x' * 4000), dict(goal='中' * 500, metadata='x' * 4000)):
            with self.assertRaisesRegex(ValueError, 'structural metadata'):
                self.encode(**kw)

    def test_random_unicode_and_escapes(self):
        rng = random.Random(34)
        for _ in range(120):
            a = ''.join(rng.choices('中😀x"\\\n\t\x00𝄞', k=rng.randrange(100, 2200)))
            b = ''.join(rng.choices('结果é\r\\y', k=rng.randrange(100, 2000)))
            self.encode(goal=a, build_result=b)

    def test_builder_workflow_delivers_before_mark(self):
        # Execute only the source handler with stubbed AI/transport, no API/keys.
        text = (ROOT / 'workflow_fixture.py').read_text()
        fn = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == 'workflow_handle')
        ns = self.ns
        records = []
        seen = set()
        ns.update(AGENT='aizong', LOVE8_DID='love8', AIZONG_DID='aizong', AI2AI_DID='ai2ai',
                  WF_TYPES={'WORKFLOW_TASK', 'CHALLENGE', 'COMPLETE'},
                  wf_key=lambda sender, x: sender + x['type'] + x['task_id'],
                  wf_seen=lambda: seen, wf_mark=lambda key: seen.add(key),
                  ai=lambda prompt: '独立分析证据和反例' * 500,
                  ledger=lambda event, **kw: records.append(('ledger', event)),
                  wf_send=lambda peer, kind, tid, **kw: records.append(('sent', json.loads(ns['payload'](kind, tid, **kw)[5:]))))
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<handler>', 'exec'), ns)
        self.assertTrue(ns['workflow_handle']('love8', {'type': 'WORKFLOW_TASK', 'task_id': 'wf', 'goal': '研究中文问题' * 300}))
        self.assertEqual(records[0][1]['type'], 'BUILD_RESULT')
        self.assertEqual(records[1], ('ledger', 'workflow_build_result'))
        self.assertEqual(len(seen), 1)
        ns['workflow_handle']('ai2ai', {'type': 'CHALLENGE', 'task_id': 'wf', 'goal': '目标' * 500, 'challenge': '反例' * 600})
        self.assertEqual(records[2][1]['type'], 'REVISED_RESULT')
        self.assertEqual(records[3], ('ledger', 'workflow_revised_result'))


class Transform(unittest.TestCase):
    def test_patch_idempotent_preserves_other_code(self):
        src = fixture()
        result = r.transform(src)
        self.assertEqual(r.transform(result), result)
        self.assertTrue(result.endswith('\ndef parse(text):\n    return text\n'))
        self.assertIn('A2A_WIRE_GUARD_V34', result)

    def test_unknown_code_refused(self):
        with self.assertRaises(ValueError):
            r.transform(fixture().replace("'goal':320", "'goal':321"))

    def test_changed_helper_refused(self):
        with self.assertRaises(ValueError):
            r.transform(r.transform(fixture()).replace('min(costs[k], 96)', 'min(costs[k], 95)'))

    def test_wrong_limit_and_duplicate_refused(self):
        for src in (fixture().replace('=3400', '=9000'), fixture() + r.OLD):
            with self.assertRaises(ValueError):
                r.transform(src)


class FakeService:
    def __init__(self, active=True, fail=False):
        self.running = active
        self.calls = []
        self.fail = fail
    def active(self):
        return self.running
    def stop(self):
        self.calls.append('stop')
        self.running = False
    def start(self):
        self.calls.append('start')
        if self.fail:
            self.fail = False
            raise RuntimeError('simulated service start failure')
        self.running = True


class Deployment(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'collab.py'
        self.target.write_text(fixture())
        self.target.chmod(0o640)
        self.config = self.root / '.env'
        self.config.write_text('AGENT_NAME=aizong\nROLE=builder\n')
        self.before, self.after = r.preflight(self.target, self.config)
        self.backups = self.root / 'backups'

    def test_check_readonly_and_wrong_role(self):
        self.assertFalse(self.backups.exists())
        self.assertEqual(self.target.read_bytes(), self.before)
        self.config.write_text('AGENT_NAME=love8\nROLE=scout\n')
        with self.assertRaises(ValueError):
            r.preflight(self.target, self.config)

    def test_apply_rollback_preserve_mode_and_state(self):
        state = self.root / 'cursor.txt'
        state.write_text('123')
        svc = FakeService()
        backup = r.apply(self.target, self.before, self.after, self.backups, svc)
        self.assertEqual(svc.calls, ['stop', 'start'])
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.target.read_bytes(), self.after)
        r.rollback(backup, self.target, svc)
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(state.read_text(), '123')
        count = len(svc.calls)
        r.rollback(backup, self.target, svc)
        self.assertEqual(len(svc.calls), count)

    def test_inactive_service_not_started(self):
        svc = FakeService(active=False)
        r.apply(self.target, self.before, self.after, self.backups, svc)
        self.assertEqual(svc.calls, [])

    def test_start_failure_restores_code(self):
        svc = FakeService(fail=True)
        with self.assertRaisesRegex(RuntimeError, 'simulated'):
            r.apply(self.target, self.before, self.after, self.backups, svc)
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertTrue(svc.running)

    def test_rollback_refuses_drift(self):
        svc = FakeService()
        backup = r.apply(self.target, self.before, self.after, self.backups, svc)
        self.target.write_text(self.target.read_text() + '# user edit\n')
        with self.assertRaisesRegex(ValueError, 'changed after repair'):
            r.rollback(backup, self.target, svc)
        self.assertTrue(self.target.read_text().endswith('# user edit\n'))

    def test_idempotent_no_backup_or_restart(self):
        svc = FakeService()
        self.target.write_bytes(self.after)
        self.assertIsNone(r.apply(self.target, self.after, self.after, self.backups, svc))
        self.assertFalse(self.backups.exists())
        self.assertEqual(svc.calls, [])

    def test_symlink_refused(self):
        link = self.root / 'link.py'
        link.symlink_to(self.target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            r.preflight(link, self.config)

    def test_concurrent_edit_before_apply_refused(self):
        self.target.write_text(fixture() + '# changed\n')
        svc = FakeService()
        with self.assertRaisesRegex(ValueError, 'changed during backup'):
            r.apply(self.target, self.before, self.after, self.backups, svc)
        self.assertEqual(svc.calls, [])
        self.assertTrue(self.target.read_text().endswith('# changed\n'))

    def test_corrupt_backup_refused(self):
        svc = FakeService()
        backup = r.apply(self.target, self.before, self.after, self.backups, svc)
        (backup / 'collab.py').write_text('# corruption\n')
        count = len(svc.calls)
        with self.assertRaisesRegex(ValueError, 'integrity'):
            r.rollback(backup, self.target, svc)
        self.assertEqual(len(svc.calls), count)
        self.assertEqual(self.target.read_bytes(), self.after)


if __name__ == '__main__':
    unittest.main()
