"""Offline tests: real function transforms, scheduler guards and transactional deployment."""
import ast
import copy
import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


repair = module('cadence321', 'repair-research-cadence-v3.2.1.py')
v32 = module('patch32', 'patch-research-context-v3.2.py')


def fixture(name):
    for path in (HERE / 'fixtures' / name, HERE / name, HERE.parent / 'wire-room-v31' / name):
        if path.is_file():
            return path
    raise FileNotFoundError(name)


DIRECTOR = v32.patched_director(fixture('autonomous-rnd-v5.py').read_text())
CONTEXT = (HERE / 'research_context_v32.py').read_text()
TELEGRAM = v32.patched_telegram(fixture('telegram-control-v1.py').read_text())


class Transforms(unittest.TestCase):
    def test_idempotent_and_only_expected_director_changes(self):
        expected = DIRECTOR.replace('"RND_V5_MIN_GAP_SECONDS": "21600"', '"RND_V5_MIN_GAP_SECONDS": "7200"').replace(
            '"RND_V5_MAX_DAILY": "4"', '"RND_V5_MAX_DAILY": "12"').replace(
            'number("RND_V5_MAX_DAILY", 1, 8)', 'number("RND_V5_MAX_DAILY", 1, 12)')
        self.assertEqual(repair.director_patch(DIRECTOR), expected)
        self.assertEqual(repair.director_patch(expected), expected)
        ctx = repair.context_patch(CONTEXT)
        self.assertEqual(repair.context_patch(ctx), ctx)

    def test_unknown_layout_and_ambiguous_guard_refused(self):
        for src in (DIRECTOR.replace('# RESEARCH_CONTEXT_V32', ''),
                    DIRECTOR.replace('number("RND_V5_MAX_DAILY", 1, 8)', 'number("RND_V5_MAX_DAILY", 1, 9)'),
                    DIRECTOR + '\nx = number("RND_V5_MAX_DAILY", 1, 8)\n'):
            with self.assertRaises(ValueError):
                repair.director_patch(src)
        with self.assertRaises(ValueError):
            repair.context_patch(CONTEXT.replace('def current(', 'def other('))

    def context(self):
        ctx = types.ModuleType('patched_context')
        exec(compile(repair.context_patch(CONTEXT), 'patched-context', 'exec'), ctx.__dict__)
        self.card = {'request_id': 'req', 'title': '候选问题', 'kind': 'bug',
                     'stages': {'wf': {'stage': 'WORKFLOW_TASK'}}, 'workflow_ids': ['wf']}
        ctx.load = lambda rid: copy.deepcopy(self.card) if rid == 'req' else {}
        return ctx

    def test_idle_history_not_claimed_as_running(self):
        ctx = self.context()
        state = {'active_request': None, 'history': [{'request_id': 'req'}]}
        result = ctx.render(ctx.current(state), detailed=True)
        self.assertIn('Director 当前无活动请求', result)
        self.assertIn('历史最后观测：Love8 曾创建研究任务', result)
        self.assertNotIn('等待 Builder', result)
        self.assertNotIn('_director_active', self.card)
        self.assertNotIn('已取消', result)

    def test_active_and_event_views_keep_real_stage(self):
        ctx = self.context()
        for card in (ctx.current({'active_request': {'request_id': 'req'}}), self.card):
            self.assertIn('等待 Builder', ctx.render(card))
            self.assertNotIn('Director 当前无活动请求', ctx.render(card))

    def test_missing_active_card_does_not_fall_back_to_other_request(self):
        ctx = self.context()
        result = ctx.current({'active_request': {'request_id': 'missing'}, 'history': [{'request_id': 'req'}]})
        self.assertEqual(result, {})

    def test_completed_history_not_confirmed_bug(self):
        ctx = self.context()
        self.card['stages']['wf']['stage'] = 'COMPLETE'
        result = ctx.render(ctx.current({'active_request': {}, 'history': [{'request_id': 'req'}]}))
        self.assertIn('曾观测到流程完成（不等于 Bug 已核实）', result)

    def test_model_context_includes_historical_warning(self):
        ctx = self.context()
        self.assertIn('Director 当前无活动请求', ctx.model_context({'history': [{'request_id': 'req'}]}, ''))


class ReachedEvidence(Exception):
    pass


class Cadence(unittest.TestCase):
    def run_tick(self, count=4, gap=7200, manual=False, active=False, cap='12'):
        source = repair.director_patch(DIRECTOR)
        nodes = ast.parse(source)
        defaults = next(n for n in nodes.body if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets))
        funcs = [n for n in nodes.body if isinstance(n, ast.FunctionDef) and n.name in {'number', 'setting', 'tick', 'daily_count'}]
        self.observed = []
        state = {'boot_at': 1, 'daily': {'2026-08-28': count}, 'last_request_at': 100000 - gap,
                 'manual_queue_offset': 745, 'history': [{'request_id': 'old'}]}
        self.state = state
        ns = {'os': os, 'DISCUSSION_ROOM_DEFAULT': 'ai2ai', 'now': lambda: 100000, 'utc_day': lambda: '2026-08-28', 'load_state': lambda: state,
              'save_state': lambda s: None, 'ensure_discussion_room': lambda s: None,
              'flush_discussion_posts_v31': lambda s: None, 'next_manual_request': lambda s: ({'goal': 'research'} if manual else None, 745),
              'workflow_snapshot': lambda: ({}, True), 'discussion_enabled': lambda: False,
              'observe_workflow_stages': lambda *a: self.observed.append('stage'),
              'observe_scheduler_delivery': lambda *a: self.observed.append('delivery'),
              'active_request': lambda *a: 'wf-existing' if active else '', 'log': lambda *a, **k: None}
        def evidence(*args):
            raise ReachedEvidence()
        ns['evidence_pack'] = evidence
        exec(compile(ast.Module(body=[defaults, *funcs], type_ignores=[]), 'selected-director-functions', 'exec'), ns)
        with patch.dict(os.environ, {'RND_V5_MAX_DAILY': cap, 'RND_V5_MIN_GAP_SECONDS': '7200'}):
            ns['tick']()

    def test_count_four_and_eleven_can_reach_research(self):
        for count in (4, 11):
            with self.assertRaises(ReachedEvidence):
                self.run_tick(count=count)
            self.assertEqual(self.state['daily']['2026-08-28'], count)
            self.assertEqual(self.state['manual_queue_offset'], 745)

    def test_count_twelve_stops_but_observation_still_runs(self):
        self.run_tick(count=12)
        self.assertEqual(self.observed, ['stage', 'delivery'])

    def test_ceiling_stays_bounded_at_twelve(self):
        self.run_tick(count=12, cap='999')
        self.assertNotIn('research_scan_after', self.state)

    def test_gap_boundary_and_manual_priority(self):
        self.run_tick(gap=7199)
        self.assertNotIn('research_scan_after', self.state)
        with self.assertRaises(ReachedEvidence):
            self.run_tick(gap=1, manual=True)

    def test_manual_still_respects_cap_and_single_flight(self):
        self.run_tick(count=12, manual=True)
        self.assertNotIn('research_scan_after', self.state)
        self.run_tick(count=4, manual=True, active=True)
        self.assertNotIn('research_scan_after', self.state)


class Services:
    def __init__(self):
        self.values = {u: 'active' for u in repair.SERVICES}
        self.actions = []
        self.fail = ''

    def state(self, u):
        return self.values[u]

    def action(self, action, u=None):
        self.actions.append((action, u))
        if action == self.fail:
            self.fail = ''
            raise RuntimeError('simulated service failure')
        if u:
            self.values[u] = 'active' if action == 'start' else 'inactive'

    def healthy(self, u):
        if self.fail == 'health':
            self.fail = ''
            raise RuntimeError('simulated unhealthy service')

    def verify_environment(self):
        if self.fail == 'env':
            self.fail = ''
            raise RuntimeError('simulated conflicting environment')


class Deployment(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.svc = Services()
        for path, data in ((repair.FILES[0], DIRECTOR), (repair.FILES[1], CONTEXT),
                           (repair.BASE / 'telegram-control-v1.py', TELEGRAM)):
            p = repair.at(self.root, path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(data)
            p.chmod(0o640)
        self.original = [repair.metadata(repair.at(self.root, p)) for p in repair.FILES]
        self.state = repair.at(self.root, Path('/opt/technocore-a2a/rnd-v5-state/director.json'))
        self.state.parent.mkdir(parents=True)
        self.state.write_text('{"daily":{"2026-08-28":4},"manual_queue_offset":745}')
        self.state_before = self.state.read_bytes()

    def restored(self):
        self.assertEqual([repair.metadata(repair.at(self.root, p)) for p in repair.FILES], self.original)
        self.assertEqual(self.state.read_bytes(), self.state_before)
        self.assertTrue(all(v == 'active' for v in self.svc.values.values()))

    def test_install_idempotence_and_rollback_preserve_state_and_modes(self):
        backup = repair.install(self.root, self.svc)
        self.assertEqual(repair.at(self.root, repair.DROPIN).read_bytes(), repair.CONFIG)
        self.assertEqual(repair.at(self.root, repair.FILES[0]).stat().st_mode & 0o777, 0o640)
        self.assertEqual(repair.install(self.root, self.svc), None)
        self.assertEqual(self.state.read_bytes(), self.state_before)
        self.state.write_text('{"daily":{"2026-08-28":5},"manual_queue_offset":900}')
        self.state_before = self.state.read_bytes()
        repair.restore(backup, self.root, self.svc)
        self.restored()

    def test_service_failures_restore_original_files(self):
        for failure in ('daemon-reload', 'start', 'health', 'env'):
            with self.subTest(failure=failure):
                self.svc.fail = failure
                with self.assertRaises(RuntimeError):
                    repair.install(self.root, self.svc)
                self.restored()

    def test_inactive_service_stops_before_changes(self):
        self.svc.values[repair.SERVICES[0]] = 'inactive'
        with self.assertRaisesRegex(RuntimeError, 'must be stable'):
            repair.install(self.root, self.svc)
        self.assertEqual(self.svc.actions, [])
        self.assertFalse(repair.at(self.root, repair.BACKUPS).exists())

    def test_rollback_refuses_modified_code_or_permissions(self):
        backup = repair.install(self.root, self.svc)
        p = repair.at(self.root, repair.FILES[0])
        p.chmod(0o600)
        self.svc.actions.clear()
        with self.assertRaisesRegex(RuntimeError, 'changed since'):
            repair.restore(backup, self.root, self.svc)
        self.assertEqual(self.svc.actions, [])

    def test_bad_backup_refused_before_stop(self):
        backup = repair.install(self.root, self.svc)
        (backup / '1.original').write_text('corrupt')
        self.svc.actions.clear()
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            repair.restore(backup, self.root, self.svc)
        self.assertEqual(self.svc.actions, [])

    def test_no_identity_import_and_preflight_refuses_missing_v32(self):
        p = repair.at(self.root, repair.FILES[0])
        p.write_text(DIRECTOR.replace('# RESEARCH_CONTEXT_V32', ''))
        with self.assertRaises(ValueError):
            repair.install(self.root, self.svc)
        self.assertEqual(self.svc.actions, [])

    def test_symlink_refused(self):
        p = repair.at(self.root, repair.DROPIN)
        p.parent.mkdir(parents=True)
        p.symlink_to(self.state)
        with self.assertRaises(RuntimeError):
            repair.install(self.root, self.svc)
        self.assertEqual(self.state.read_bytes(), self.state_before)

    def test_only_ai2ai_accepted_without_shell_expansion(self):
        cfg = self.root / 'config'
        cfg.write_text('AGENT_NAME="ai2ai"\nTOKEN=must-not-print\nDANGER=$(exit 1)\n')
        repair.validate_node(cfg)
        for data in ('AGENT_NAME=love8', 'AGENT_NAME=ai2ai\nAGENT_NAME=ai2ai', 'AGENT_NAME="ai2ai'):
            cfg.write_text(data)
            with self.assertRaises(ValueError):
                repair.validate_node(cfg)


if __name__ == '__main__':
    unittest.main()
