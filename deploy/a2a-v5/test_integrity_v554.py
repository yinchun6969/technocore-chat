"""Offline release regressions: no network, credentials, or real services."""

import ast
import hashlib
import importlib.util
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load(filename):
    spec = importlib.util.spec_from_file_location(filename, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repair = load("repair-integrity-v554.py")
deploy = load("deploy-integrity-v554.py")


class Integrity(unittest.TestCase):
    def setUp(self):
        self.action_source = (HERE / "human_action_center_v1.py").read_text()
        self.actions = types.ModuleType("patched_actions")
        exec(compile(repair.actions(self.action_source), "actions", "exec"), self.actions.__dict__)

    def classify(self, findings, score=85):
        text = (
            "# Title\nBug report\n## Findings\n"
            + findings
            + "\n## Design Proposal\nFix the guard.\n## Minimal Test Matrix\n"
            + "Reproduce against pinned source, compare expected and actual output."
        )
        receipt = {
            "evidence_verified": True,
            "cross_validation_score": score,
            "evidence_merkle_root": "a" * 64,
            "artifact_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        return self.actions.classify("wf-integrity-test", text, receipt)

    def test_unverified_high_score_does_not_alert(self):
        for claim in (
            "No bug can be confirmed. Core workflow failure.",
            "未发现私钥泄露。",
            "核心工作流错误，尚未验证。",
            "If COMPLETE is terminal, core workflow failure.",
        ):
            self.assertIsNone(self.classify(claim, 100), claim)

    def test_severity_not_vocabulary_score(self):
        self.assertEqual(self.classify("Reproduced bug: service unavailable.")["priority"], "P1")
        self.assertEqual(self.classify("Reproduced private key leak.")["priority"], "P0")
        self.assertIsNone(self.classify("Reproduced bug: harmless display typo.", 100))

    def test_patcher_idempotency_and_compile(self):
        for filename, transform in (
            ("autonomous-rnd-v5.py", repair.director),
            ("telegram-control-v1.py", repair.telegram),
            ("human_action_center_v1.py", repair.actions),
        ):
            value = transform((HERE / filename).read_text())
            self.assertEqual(transform(value), value)
            compile(value, filename, "exec")

    def test_content_binding(self):
        self.assertIsNone(
            self.actions.classify(
                "wf-integrity-test",
                "private key leak",
                {"evidence_verified": True, "artifact_sha256": "b" * 64},
            )
        )

    def test_classification_queue_and_telegram_render(self):
        source = repair.telegram((HERE / "telegram-control-v1.py").read_text())
        tree = ast.parse(source)
        selected: list[ast.stmt] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in {
                "compact",
                "safe_text",
                "event_message",
            }:
                selected.append(node)
            elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "NOTIFY_LABELS" for t in node.targets
            ):
                selected.append(node)
        namespace: dict[str, Any] = {
            "research_context": types.SimpleNamespace(lookup_event=lambda row: {})
        }
        exec(compile(ast.Module(body=selected, type_ignores=[]), "renderer", "exec"), namespace)
        row = self.classify("Reproduced bug: service unavailable.")
        with tempfile.TemporaryDirectory() as temp:
            created, saved = self.actions.upsert(row, Path(temp) / "queue.json")
            self.assertTrue(created)
            message = namespace["event_message"](dict(saved, event="human_action_created"))
            self.assertIn("P1 PR 候选", message)
            self.assertIn("非漏洞置信度", message)
            self.assertIn(saved["alert_id"], message)
            self.assertFalse(self.actions.upsert(row, Path(temp) / "queue.json")[0])

    def test_legacy_refresh_keeps_human_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            queue = Path(temp) / "queue.json"
            row = self.classify("Reproduced bug: service unavailable.")
            old = dict(row, decision_basis="old", status="acknowledged")
            self.actions.upsert(old, queue)
            created, saved = self.actions.upsert(row, queue)
            self.assertFalse(created)
            self.assertEqual(saved["status"], "acknowledged")
            self.assertEqual(len(self.actions.active(queue)), 1)

    def test_transaction_and_rollback(self):
        class Services:
            fail = False

            def state(self, unit):
                return "active"

            def stop(self, unit):
                pass

            def start(self, unit):
                pass

            def healthy(self, unit):
                return True

            def runtime_group(self):
                import os

                return os.getgid()

            def readable(self):
                if self.fail:
                    raise RuntimeError("simulated import failure")

        for failure in (False, True):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                originals = {}
                for path in deploy.FILES:
                    target = deploy.at(root, path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if path.name in {
                        "autonomous-rnd-v5.py",
                        "telegram-control-v1.py",
                        "human_action_center_v1.py",
                    }:
                        target.write_bytes((HERE / path.name).read_bytes())
                        originals[target] = target.read_bytes()
                state = root / "opt/technocore-a2a/rnd-v5-state/director.json"
                state.parent.mkdir(parents=True)
                state.write_text('{"cursor":123}')
                service = Services()
                service.fail = failure
                if failure:
                    with self.assertRaises(RuntimeError):
                        deploy.install(HERE, root, service)
                else:
                    backup = deploy.install(HERE, root, service)
                    self.assertIsNone(deploy.install(HERE, root, service))
                    deploy.restore(backup, root, service)
                self.assertEqual(state.read_text(), '{"cursor":123}')
                for path, content in originals.items():
                    self.assertEqual(path.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
