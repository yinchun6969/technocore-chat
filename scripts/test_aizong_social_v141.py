#!/usr/bin/env python3
"""Smoke tests for aizong Social Brain v1.4.1 Provenance Calibration."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_PROGRAM = ROOT / "scripts" / "aizong_social.py"
PATCH_130 = ROOT / "scripts" / "patch_aizong_social_v130.py"
PATCH_131 = ROOT / "scripts" / "patch_aizong_social_v131.py"
PATCH_140 = ROOT / "scripts" / "patch_aizong_social_v140.py"
PATCH_141 = ROOT / "scripts" / "patch_aizong_social_v141.py"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patched_module() -> tuple[Any, str]:
    p130 = load_module("aizong_p130_for_v141", PATCH_130)
    p131 = load_module("aizong_p131_for_v141", PATCH_131)
    p140 = load_module("aizong_p140_for_v141", PATCH_140)
    p141 = load_module("aizong_p141", PATCH_141)
    source = BASE_PROGRAM.read_text(encoding="utf-8")
    source = p130.patch_source(source)
    source = p131.patch_source(source)
    source = p140.patch_source(source)
    patched = p141.patch_source(source)
    assert p141.patch_source(patched) == patched
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
        handle.write(patched)
        path = Path(handle.name)
    try:
        return load_module("aizong_social_v141", path), patched
    finally:
        path.unlink(missing_ok=True)


def set_env(values: dict[str, str]) -> dict[str, str | None]:
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    return old


def restore_env(old: dict[str, str | None]) -> None:
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_patch_contract() -> None:
    mod, source = patched_module()
    assert mod.VERSION == "1.4.1"
    for field in (
        "originality_score",
        "evidence_strength",
        "durable_state_value",
        "evidence_kind",
    ):
        assert field in mod.BRAIN_SYSTEM
    assert "never reuse a stock contribution template" in mod.BRAIN_SYSTEM
    assert "Generic questions, greetings, praise and status are not provenance" in mod.BRAIN_SYSTEM
    assert "TC_TEMPLATE_BLOCK_SIMILARITY_PCT" in source
    assert "TC_PROVENANCE_MIN_VALUE" in source
    assert "contribution-ledger.jsonl" in source
    # Preserve previous strategy, resilience and hard safety gates.
    assert "TC_STRATEGY_ROOM_DAILY_CAP" in source
    assert 'TC_NET_RETRIES", 3' in source
    assert 'brain.get("BRAIN_TIMEOUT", "60")' in source
    assert 'rules["prompt_injection_risk"] >= 70' in source
    assert 'rules["scam_risk"] >= 70' in source


def write_ledger(path: Path, texts: list[str]) -> None:
    rows = [{"text": text, "contribution_value": 70} for text in texts]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_template_similarity_gate() -> None:
    mod, _ = patched_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger = Path(tmpdir) / "ledger.jsonl"
        prior = (
            "DID rotation should keep a monotonic nonce and verify state before signing. "
            "Replay protection must reference the prior key transition."
        )
        write_ledger(ledger, [prior])
        old = set_env({"TC_TEMPLATE_BLOCK_SIMILARITY_PCT": "92"})
        try:
            allowed, _, similarity = mod._anti_farming_allows_text(ledger, prior)
            assert not allowed
            assert similarity >= 0.99
            distinct = (
                "The 502 appears only after the proxy buffers the signed POST response; "
                "a follow-up GET can distinguish timeout-after-commit from a rejected write."
            )
            allowed, _, similarity = mod._anti_farming_allows_text(ledger, distinct)
            assert allowed
            assert similarity < 0.92
        finally:
            restore_env(old)


def test_provenance_calibration() -> None:
    mod, _ = patched_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger = Path(tmpdir) / "ledger.jsonl"
        write_ledger(
            ledger,
            ["Old note about mailbox signing and nonce ordering that is deliberately unrelated."],
        )
        old = set_env(
            {
                "TC_PROVENANCE_MIN_VALUE": "75",
                "TC_PROVENANCE_MIN_ORIGINALITY": "70",
                "TC_PROVENANCE_MIN_EVIDENCE": "60",
                "TC_PROVENANCE_MAX_SIMILARITY_PCT": "82",
                "TC_PROVENANCE_DISCUSSION_MIN_VALUE": "85",
            }
        )
        try:
            text = (
                "Measured retry behavior shows the first POST can commit before the client times out; "
                "checking the returned room sequence before retrying avoids a duplicate signed write."
            )
            strong = {
                "provenance_worthy": True,
                "contribution_value": 82,
                "originality_score": 88,
                "evidence_strength": 75,
                "contribution_type": "technical_help",
            }
            assert mod._calibrate_provenance(strong, text, ledger)[0]

            weak_value = dict(strong, contribution_value=74)
            assert not mod._calibrate_provenance(weak_value, text, ledger)[0]
            weak_originality = dict(strong, originality_score=69)
            assert not mod._calibrate_provenance(weak_originality, text, ledger)[0]
            weak_evidence = dict(strong, evidence_strength=59)
            assert not mod._calibrate_provenance(weak_evidence, text, ledger)[0]
            discussion = dict(strong, contribution_type="discussion", contribution_value=80)
            assert not mod._calibrate_provenance(discussion, text, ledger)[0]
            not_nominated = dict(strong, provenance_worthy=False)
            assert not mod._calibrate_provenance(not_nominated, text, ledger)[0]
        finally:
            restore_env(old)


def test_similarity_downgrades_provenance_before_send_block() -> None:
    mod, _ = patched_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger = Path(tmpdir) / "ledger.jsonl"
        prior = (
            "Compatibility test found timeout after commit on signed POST; check room sequence "
            "before retrying to avoid duplicate writes."
        )
        write_ledger(ledger, [prior])
        candidate = (
            "Compatibility test found timeout after commit on signed POST; inspect room sequence "
            "before retrying to avoid duplicate writes safely."
        )
        decision = {
            "provenance_worthy": True,
            "contribution_value": 90,
            "originality_score": 90,
            "evidence_strength": 90,
            "contribution_type": "technical_help",
        }
        old = set_env(
            {
                "TC_PROVENANCE_MAX_SIMILARITY_PCT": "82",
                "TC_TEMPLATE_BLOCK_SIMILARITY_PCT": "99",
            }
        )
        try:
            anti_ok, _, similarity = mod._anti_farming_allows_text(ledger, candidate)
            assert anti_ok
            assert similarity >= 0.82
            worthy, reason, _ = mod._calibrate_provenance(decision, candidate, ledger)
            assert not worthy
            assert "similarity" in reason
        finally:
            restore_env(old)


def main() -> int:
    test_patch_contract()
    test_template_similarity_gate()
    test_provenance_calibration()
    test_similarity_downgrades_provenance_before_send_block()
    print("aizong Social v1.4.1 provenance calibration smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
