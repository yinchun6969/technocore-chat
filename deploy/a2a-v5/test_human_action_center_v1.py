#!/usr/bin/env python3
"""Unit tests for the local human-action inbox."""

from __future__ import annotations

import importlib.util
import tempfile
import time
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().with_name("human_action_center_v1.py")
SPEC = importlib.util.spec_from_file_location("human_action_center_v1", MODULE)
assert SPEC is not None and SPEC.loader is not None
actions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(actions)

TASK = "wf-action-center-test-0001"
ROOT = "a" * 64
SHA = "b" * 64


def receipt(score: int = 95, verified: bool = True) -> dict:
    return {
        "evidence_verified": verified,
        "evidence_merkle_root": ROOT,
        "artifact_sha256": SHA,
        "cross_validation_score": score,
    }


def artifact(title: str, findings: str, proposal: str, tests: str, questions: str = "None") -> str:
    return f"""# Title
{title}
## Objective
Audit a verified workflow.
## Verified Evidence
Two independently signed sources were compared.
## Cross-Validation
The evidence root and artifact hash were checked.
## Findings
{findings}
## Design Proposal
{proposal}
## Minimal Test Matrix
{tests}
## Open Questions
{questions}
## Provenance
Bound to {TASK} and {ROOT}.
"""


class ClassificationTests(unittest.TestCase):
    def test_verified_high_impact_bug_with_fix_and_tests_is_p1(self) -> None:
        text = artifact(
            "Bug: signed workflow cannot complete",
            "A reproducible retry race condition leaves the cross-node workflow blocked.",
            "Fix with an atomic upsert guard and preserve the first action ID.",
            "1. Reproduce the blocked workflow.\n2. Verify the fix.\n3. Restart keeps state.",
        )
        value = actions.classify(TASK, text, receipt())
        self.assertIsNotNone(value)
        self.assertEqual(value["priority"], "P1")
        self.assertEqual(value["kind"], "PR_CANDIDATE")
        self.assertFalse(value["policy"]["auto_pr"])

    def test_critical_marker_overrides_pr_candidate(self) -> None:
        text = artifact(
            "Private key leak in debug output",
            "The verified finding describes a private key leak.",
            "Fix by rejecting the unsafe output and adding a guard.",
            "1. Secret fixture is hidden.\n2. Redacted output remains deterministic.\n3. Clean data passes.",
        )
        value = actions.classify(TASK, text, receipt())
        self.assertEqual(value["priority"], "P0")
        self.assertEqual(value["kind"], "CRITICAL_CONFIRMATION")

    def test_minor_bug_and_routine_human_choice_are_not_reported(self) -> None:
        minor = artifact(
            "Bug: duplicate workflow alert",
            "A retry can emit a harmless duplicate display alert.",
            "Fix with an atomic upsert guard.",
            "1. Duplicate event is deduplicated.\n2. New event creates one action.\n3. Restart keeps state.",
        )
        self.assertIsNone(actions.classify(TASK, minor, receipt()))

        text = artifact(
            "Release policy choice",
            "The evidence supports two safe options and requires approval.",
            "Preserve read-only behavior until an operator decides.",
            "1. Default remains read only.\n2. Approval is recorded.\n3. No external write is executed.",
            "Needs confirmation from the repository owner.",
        )
        self.assertIsNone(actions.classify(TASK, text, receipt(score=100)))

    def test_high_impact_bug_below_95_is_not_reported(self) -> None:
        text = artifact(
            "Bug: cross-node workflow blocked",
            "A persistent failure means the signed workflow cannot complete.",
            "Fix with validation and preserve the last good state.",
            "1. Reproduce failure.\n2. Verify recovery.\n3. Restart remains safe.",
        )
        self.assertIsNone(actions.classify(TASK, text, receipt(score=94)))

    def test_unverified_or_weak_result_is_not_actionable(self) -> None:
        text = artifact("General notes", "No issue found.", "Observe only.", "No tests proposed.")
        self.assertIsNone(actions.classify(TASK, text, receipt(verified=False)))
        self.assertIsNone(actions.classify(TASK, text, receipt(score=60)))


class QueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "human-actions.json"
        self.action = actions.classify(
            TASK,
            artifact(
                "Bug: cross-node workflow blocked", "A persistent failure blocks the core workflow.",
                "Fix with an atomic guard and validate state.",
                "1. Reproduce the block.\n2. Restart is safe.\n3. Recovery remains visible.",
            ),
            receipt(),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_upsert_is_deterministic_and_deduplicated(self) -> None:
        created, first = actions.upsert(self.action, self.path)
        duplicate, second = actions.upsert(dict(self.action), self.path)
        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertEqual(first["alert_id"], second["alert_id"])
        self.assertEqual(actions.counts(self.path), {"P0": 0, "P1": 1, "P2": 0, "total": 1})

    def test_snooze_and_resolve_lifecycle(self) -> None:
        actions.upsert(self.action, self.path)
        alert_id = self.action["alert_id"]
        snoozed = actions.update(alert_id, "snoozed", "telegram:123", snooze_seconds=3600, path=self.path)
        self.assertGreater(snoozed["snoozed_until"], int(time.time()))
        self.assertEqual(actions.active(self.path), [])
        self.assertEqual(len(actions.active(self.path, include_snoozed=True)), 1)
        resolved = actions.update(alert_id, "resolved", "telegram:123", path=self.path)
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(actions.counts(self.path)["total"], 0)

    def test_public_projection_excludes_local_summary_and_history(self) -> None:
        projection = actions.public_projection(self.action)
        self.assertNotIn("summary", projection)
        self.assertNotIn("history", projection)
        self.assertNotIn("policy", projection)

    def test_legacy_p1_and_p2_are_hidden_without_deleting_history(self) -> None:
        actions.upsert(self.action, self.path)
        value = actions.load(self.path)
        current = value["actions"][self.action["alert_id"]]
        current["decision_basis"] = "deterministic-markers+verified-artifact"
        legacy_p2 = dict(current)
        legacy_p2["alert_id"] = "act-" + "c" * 16
        legacy_p2["priority"] = "P2"
        value["actions"][legacy_p2["alert_id"]] = legacy_p2
        actions._write_unlocked(self.path, value)

        self.assertEqual(actions.active(self.path), [])
        self.assertEqual(len(actions.load(self.path)["actions"]), 2)


if __name__ == "__main__":
    unittest.main()
