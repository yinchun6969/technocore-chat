#!/usr/bin/env python3
"""Deterministic unit coverage for v5.5 evidence, Merkle and Saga rules."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("evidence_v55_test", HERE / "evidence_v55.py")
assert SPEC and SPEC.loader
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


def stages(task_id: str = "wf-v55-test"):
    result = {}
    for index, stage in enumerate(evidence.STAGE_ORDER, 1):
        result[stage] = {
            "seq": index,
            "from": evidence.EXPECTED_SIGNERS[stage],
            "room": f"room-{index}",
            "message_ts": f"2026-08-30T03:0{index}:00Z",
            "obj": {"type": stage, "task_id": task_id, "value": f"stage-{index}"},
        }
    return result


class EvidenceV55Tests(unittest.TestCase):
    def test_bundle_is_deterministic_and_verified(self):
        first = evidence.build_bundle("wf-v55-test", stages())
        second = evidence.build_bundle("wf-v55-test", copy.deepcopy(stages()))
        self.assertEqual(first, second)
        self.assertTrue(evidence.verify_bundle(first))
        self.assertEqual(first["evidence_count"], 5)
        self.assertRegex(first["merkle_root"], r"^[0-9a-f]{64}$")

    def test_payload_or_signer_tamper_fails(self):
        bundle = evidence.build_bundle("wf-v55-test", stages())
        bundle["evidence"][1]["payload_sha256"] = "0" * 64
        with self.assertRaisesRegex(evidence.EvidenceError, "leaf hash mismatch"):
            evidence.verify_bundle(bundle)

        changed = stages()
        changed["CHALLENGE"]["from"] = evidence.LOVE8_DID
        with self.assertRaisesRegex(evidence.EvidenceError, "signer mismatch"):
            evidence.build_bundle("wf-v55-test", changed)

    def test_workflow_binding_and_replay_fail(self):
        changed = stages()
        changed["BUILD_RESULT"]["obj"]["task_id"] = "wf-other"
        with self.assertRaisesRegex(evidence.EvidenceError, "workflow binding"):
            evidence.build_bundle("wf-v55-test", changed)

        bundle = evidence.build_bundle("wf-v55-test", stages())
        bundle["evidence"][1]["signer_did"] = bundle["evidence"][0]["signer_did"]
        bundle["evidence"][1]["locator"] = dict(bundle["evidence"][0]["locator"])
        with self.assertRaises(evidence.EvidenceError):
            evidence.verify_bundle(bundle)

    def test_saga_stops_at_first_missing_stage(self):
        partial = stages()
        partial.pop("BUILD_RESULT")
        checkpoint = evidence.saga_checkpoint("wf-v55-test", partial)
        self.assertEqual(checkpoint["state"], "TASK_SIGNED")
        self.assertEqual(checkpoint["resume_from"], "BUILD_RESULT")
        self.assertEqual(len(checkpoint["transitions"]), 1)

    def test_saga_reaches_verified_and_carries_nonce_timestamp_hash(self):
        checkpoint = evidence.saga_checkpoint("wf-v55-test", stages(), artifact_verified=True)
        self.assertEqual(checkpoint["state"], "ARTIFACT_VERIFIED")
        row = checkpoint["transitions"][0]
        self.assertEqual(row["task_id"], "wf-v55-test")
        self.assertGreater(row["nonce"], 0)
        self.assertGreater(row["timestamp"], 0)
        self.assertRegex(row["evidence_hash"], r"^[0-9a-f]{64}$")

    def test_iso_and_unix_timestamp_normalization(self):
        self.assertEqual(evidence.parse_timestamp("2026-08-30T03:01:00Z"), 1788058860000)
        self.assertEqual(evidence.parse_timestamp(1788058860), 1788058860000)
        self.assertEqual(evidence.parse_timestamp(1788058860000), 1788058860000)


if __name__ == "__main__":
    unittest.main()
