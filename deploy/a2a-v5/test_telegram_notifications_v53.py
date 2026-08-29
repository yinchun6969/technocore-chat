#!/usr/bin/env python3
"""Focused tests for Telegram workflow and PR milestone rendering."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("telegram-control-v1.py")


def load_renderer():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    wanted = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "NOTIFY_LABELS"
            for target in node.targets
        ):
            wanted.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"compact", "event_message"}:
            wanted.append(node)
    namespace: dict[str, object] = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["event_message"]


class TelegramNotificationTests(unittest.TestCase):
    def setUp(self):
        self.render = load_renderer()

    def test_recovered_revision_is_notified(self):
        text = self.render({
            "event": "workflow_revised_result_recovered",
            "workflow_id": "wf-test",
        })
        self.assertIn("恢复并提交修订结果", text)
        self.assertIn("wf-test", text)

    def test_created_pr_contains_link_branch_and_commit(self):
        text = self.render({
            "event": "github_pr_created",
            "workflow_id": "wf-test",
            "pr_url": "https://github.com/example/project/pull/42",
            "branch": "feat/test",
            "commit_sha": "abc123",
        })
        self.assertIn("GitHub PR 已创建", text)
        self.assertIn("https://github.com/example/project/pull/42", text)
        self.assertIn("feat/test", text)
        self.assertIn("abc123", text)

    def test_non_github_link_is_not_forwarded(self):
        text = self.render({
            "event": "github_pr_created",
            "pr_url": "https://example.invalid/not-a-pr",
        })
        self.assertNotIn("example.invalid", text)


if __name__ == "__main__":
    unittest.main()
