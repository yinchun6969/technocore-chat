#!/usr/bin/env python3
"""Offline, fail-closed transformations for the source/alert repair release."""

import ast
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER = "# RESEARCH_ALERT_INTEGRITY_V554"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def director(source):
    # The context patch depends on the Director room outbox, not on replacing
    # agent.py. Compose this missing prerequisite into the same transaction.
    # Its transformer validates the old layout and preserves other functions.
    if "def flush_discussion_posts_v31(" not in source:
        wire = load("director_room_patch", "repair-wire-room-v3.1.py")
        source = wire.patch_director(source)
    patch = load("context_patch", "patch-research-context-v3.2.py")
    source = patch.patched_director(source)
    for marker in (
        "research_context.make_card",
        "research_context.wire_goal",
        "research_context.collect",
    ):
        if marker not in source:
            raise ValueError("incomplete Director context patch: " + marker)
    source = source.replace(
        "(history only)", "(unordered stage labels; history only, NOT execution order)"
    )
    ast.parse(source)
    return source


def telegram(source):
    patch = load("context_patch", "patch-research-context-v3.2.py")
    source = patch.patched_telegram(source)
    if MARKER not in source:
        anchor = '    event = str(row.get("event", "")).strip()'
        # Repeated provider failures are operational notices, not project bugs.
        # Rate limit by event/workflow/hour using the existing persisted outbox;
        # failed sends still retry the same record without advancing its offset.
        source = patch.replace_once(source, anchor, anchor + "\n    " + MARKER)
        anchor = '                        if event_name == "director_wait":'
        replacement = """                        if event_name in {"rnd_artifact_rejected", "rnd_director_error", "director_error"}:
                            try:
                                bucket = int(float(row.get("ts", 0))) // 3600
                            except (ValueError, TypeError):
                                bucket = int(time.time()) // 3600
                            key = "ops-v554|" + event_name + "|" + str(bucket)
                        elif event_name == "director_wait":"""
        source = patch.replace_once(source, anchor, replacement)
    source = source.replace("交叉验证：", "文本检查分（非漏洞置信度）：")
    source = source.replace("🔔 AI2AI 自主研究进度", "🔧 AI2AI 运行状态（非项目漏洞）")
    ast.parse(source)
    return source


ACTION_GUARD = r"""
# RESEARCH_ALERT_INTEGRITY_V554
_legacy_classify_v554 = classify


def classify(task_id: str, artifact: str, receipt: dict) -> dict | None:
    # Signed provenance authenticates content, not the truth of model claims.
    # Do not promote negated/hypothetical findings through keyword matching.
    findings = _section(artifact, "## Findings")
    uncertain = re.compile(
        r"未验证|未证实|无法确认|不能确认|证据不足|未发现|没有发现|不构成|"
        r"尚未|假设|如果|可能|候选异常|"
        r"\b(?:unverified|unconfirmed|hypothetical|insufficient|candidate anomaly)\b|"
        r"\b(?:cannot|can't|could not)\s+(?:be\s+)?(?:confirm|verify|reproduce)|"
        r"\bno\s+(?:\w+\s+){0,3}(?:bug|defect|leak|evidence|reproducibility)|"
        r"\bnot\s+(?:a\s+)?(?:verified|confirmed|reproduced)|\bif\b",
        re.I,
    )
    if not findings.strip() or uncertain.search(findings):
        return None
    if not isinstance(receipt, dict):
        return None
    # Bind classification to the supplied content even during offline rechecks.
    if receipt.get("artifact_sha256") != hashlib.sha256(artifact.encode()).hexdigest():
        return None
    # The legacy score measures vocabulary, not severity or independent evidence.
    checked = dict(receipt, cross_validation_score=100)
    result = _legacy_classify_v554(task_id, artifact, checked)
    if result:
        result["cross_validation_score"] = receipt.get("cross_validation_score", 0)
        result["validation_status"] = "reported_high_impact_requires_human_verification"
    return result
"""


def actions(source):
    if MARKER in source:
        ast.parse(source)
        return source
    patch = load("context_patch", "patch-research-context-v3.2.py")
    if 'DECISION_BASIS = "verified-high-severity-v2"' not in source:
        raise ValueError("install high-severity action-center.3 first; unsupported policy")
    # Keep policy identity so existing acknowledgements and snoozes survive.
    # A qualifying reclassification must refresh an old hidden record in place.
    source = patch.replace_once(
        source,
        "        if isinstance(existing, dict):\n            return False, existing",
        """        if isinstance(existing, dict):
            if existing.get("decision_basis") != action.get("decision_basis"):
                for key in ("status", "created_at", "snoozed_until", "history"):
                    if key in existing:
                        action[key] = existing[key]
                value["actions"][alert_id] = action
                value["updated_at"] = int(time.time())
                _write_unlocked(path, value)
                return False, action
            return False, existing""",
    )
    source = patch.replace_once(
        source,
        '    finding_scope = title + " " + findings',
        "    finding_scope = findings  # A title is not a factual finding.",
    )
    source = patch.replace_once(
        source,
        "HIGH_IMPACT_MARKERS = (",
        """HIGH_IMPACT_MARKERS = (
    "读取其他租户", "读取其他用户", "跨租户", "跨用户越权", "授权校验缺陷",
    "cross-tenant", "other tenants", "other users' private",""",
    )
    source += ACTION_GUARD
    ast.parse(source)
    return source
