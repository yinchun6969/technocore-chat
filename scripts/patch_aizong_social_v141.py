#!/usr/bin/env python3
"""Patch an installed aizong Social v1.4.0 core to v1.4.1 Provenance Calibration."""

from __future__ import annotations

import argparse
from pathlib import Path

TARGET_VERSION = "1.4.1"


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"PATCH_MISMATCH[{label}]: {old[:160]!r}")
    return source.replace(old, new, 1)


def patch_source(source: str) -> str:
    if 'VERSION = "1.4.1"' in source:
        return source
    if 'VERSION = "1.4.0"' not in source:
        raise RuntimeError("expected aizong Social v1.4.0 source")

    source = _replace_once(
        source,
        '"""aizong Social v1.4.0: contribution-first persistent-DID relationship intelligence."""',
        '"""aizong Social v1.4.1: anti-farming provenance-calibrated persistent-DID intelligence."""',
        "docstring",
    )
    source = _replace_once(source, 'VERSION = "1.4.0"', 'VERSION = "1.4.1"', "version")
    source = _replace_once(
        source,
        "import argparse\nimport base64\n",
        "import argparse\nimport base64\nimport difflib\n",
        "difflib-import",
    )

    source = _replace_once(
        source,
        "- Prefer technically useful answers, concrete coordination, debugging insight, interoperability notes,\n"
        "  or specific questions that can lead to a verifiable contribution.\n"
        "- Do not optimize public behavior for faucets, airdrops, allocations, farming, points, or rewards.\n",
        "- Prefer technically useful answers, concrete coordination, debugging insight, interoperability notes,\n"
        "  or specific questions that can lead to a verifiable contribution.\n"
        "- Originality matters: never reuse a stock contribution template or lightly paraphrase prior output.\n"
        "- Mark provenance_worthy only for a specific new fact, test/reproduction, measurement, code/interoperability\n"
        "  finding, or concrete coordination artifact. Generic questions, greetings, praise and status are not provenance.\n"
        "- Score evidence_strength only from supplied context; never invent tests, measurements, URLs or results.\n"
        "- durable_state_value estimates whether the interaction contains information worth remembering beyond chat.\n"
        "- Do not optimize public behavior for faucets, airdrops, allocations, farming, points, or rewards.\n",
        "anti-farming-policy",
    )

    source = _replace_once(
        source,
        '  "contribution_value": 0-100,\n'
        '  "provenance_worthy": true|false,\n'
        '  "contribution_type": "technical_help|coordination|discovery|discussion|other",\n',
        '  "contribution_value": 0-100,\n'
        '  "originality_score": 0-100,\n'
        '  "evidence_strength": 0-100,\n'
        '  "durable_state_value": 0-100,\n'
        '  "evidence_kind": "none|observed_test|reproduction|measurement|code_change|interoperability|coordination",\n'
        '  "provenance_worthy": true|false,\n'
        '  "contribution_type": "technical_help|coordination|discovery|discussion|other",\n',
        "brain-schema",
    )

    source = _replace_once(
        source,
        '        "contribution_value": _bounded_int(decision.get("contribution_value")),\n'
        '        "provenance_worthy": bool(decision.get("provenance_worthy", False)),\n'
        '        "contribution_type": _single_line(\n',
        '        "contribution_value": _bounded_int(decision.get("contribution_value")),\n'
        '        "originality_score": _bounded_int(decision.get("originality_score")),\n'
        '        "evidence_strength": _bounded_int(decision.get("evidence_strength")),\n'
        '        "durable_state_value": _bounded_int(decision.get("durable_state_value")),\n'
        '        "evidence_kind": _single_line(str(decision.get("evidence_kind", "none")), 40),\n'
        '        "provenance_worthy": bool(decision.get("provenance_worthy", False)),\n'
        '        "contribution_type": _single_line(\n',
        "brain-result",
    )

    helpers = r'''


def _provenance_percent(name: str, default: int) -> int:
    return _strategy_limit(name, default, 0, 100)


def _normalise_provenance_text(text: str) -> str:
    value = text.lower()
    value = re.sub(r"https?://\S+", " <url> ", value)
    value = re.sub(r"did:key:[a-z0-9:_-]+", " <did> ", value)
    value = re.sub(r"\b[0-9a-f]{24,}\b", " <blob> ", value)
    value = re.sub(r"\b[1-9a-hj-np-za-km-z]{32,}\b", " <blob> ", value)
    value = re.sub(r"\d+", " <n> ", value)
    value = re.sub(r"[^a-z0-9_<>\s]+", " ", value)
    return " ".join(value.split())


def _max_ledger_similarity(path: Path, text: str, limit: int = 120) -> float:
    candidate = _normalise_provenance_text(text)
    if len(candidate) < 24 or not path.exists():
        return 0.0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return 0.0
    best = 0.0
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        prior = _normalise_provenance_text(str(item.get("text", "")))
        if len(prior) < 24:
            continue
        best = max(best, difflib.SequenceMatcher(None, candidate, prior).ratio())
    return best


def _strategy_metric(state: dict[str, Any], key: str) -> None:
    metrics = state.setdefault("strategy_metrics", {})
    metrics[key] = int(metrics.get(key, 0) or 0) + 1


def _anti_farming_allows_text(path: Path, text: str) -> tuple[bool, str, float]:
    similarity = _max_ledger_similarity(path, text)
    block_at = _provenance_percent("TC_TEMPLATE_BLOCK_SIMILARITY_PCT", 92) / 100.0
    if similarity >= block_at:
        return False, f"near-template output similarity={similarity:.2f}", similarity
    return True, "", similarity


def _calibrate_provenance(
    decision: dict[str, Any], text: str, path: Path
) -> tuple[bool, str, float]:
    similarity = _max_ledger_similarity(path, text)
    brain_worthy = bool(decision.get("provenance_worthy", False))
    value = _bounded_int(decision.get("contribution_value"))
    originality = _bounded_int(decision.get("originality_score"))
    evidence = _bounded_int(decision.get("evidence_strength"))
    contribution_type = str(decision.get("contribution_type", "other"))

    min_value = _provenance_percent("TC_PROVENANCE_MIN_VALUE", 75)
    min_originality = _provenance_percent("TC_PROVENANCE_MIN_ORIGINALITY", 70)
    min_evidence = _provenance_percent("TC_PROVENANCE_MIN_EVIDENCE", 60)
    max_similarity = _provenance_percent("TC_PROVENANCE_MAX_SIMILARITY_PCT", 82) / 100.0
    discussion_min = _provenance_percent("TC_PROVENANCE_DISCUSSION_MIN_VALUE", 85)

    if not brain_worthy:
        return False, "brain did not nominate provenance", similarity
    if value < min_value:
        return False, f"contribution value {value} below provenance {min_value}", similarity
    if originality < min_originality:
        return False, f"originality {originality} below {min_originality}", similarity
    if evidence < min_evidence:
        return False, f"evidence {evidence} below {min_evidence}", similarity
    if contribution_type == "discussion" and value < discussion_min:
        return False, f"discussion value {value} below {discussion_min}", similarity
    if similarity >= max_similarity:
        return False, f"similarity {similarity:.2f} above provenance ceiling", similarity
    return True, "calibrated strong provenance", similarity
'''
    source = _replace_once(
        source,
        "\ndef _strategy_limit(name: str, default: int, low: int, high: int) -> int:",
        helpers + "\n\ndef _strategy_limit(name: str, default: int, low: int, high: int) -> int:",
        "provenance-helpers",
    )

    source = _replace_once(
        source,
        '''    text = _single_line(str(decision.get("text", fallback)))
    mode = str(decision.get("mode", "rules"))
    if args.dry_run:
''',
        '''    text = _single_line(str(decision.get("text", fallback)))
    mode = str(decision.get("mode", "rules"))
    ledger_path = Path(args.ledger)
    anti_ok, anti_reason, template_similarity = _anti_farming_allows_text(ledger_path, text)
    if not anti_ok:
        _strategy_metric(state, "template_blocks")
        save_state(state_path, state)
        log(f"strategy skipped action={kind} room={room} reason={anti_reason}")
        return False

    brain_provenance_worthy = bool(decision.get("provenance_worthy", False))
    calibrated_worthy, provenance_reason, template_similarity = _calibrate_provenance(
        decision, text, ledger_path
    )
    decision["brain_provenance_worthy"] = brain_provenance_worthy
    decision["provenance_worthy"] = calibrated_worthy
    decision["provenance_reason"] = provenance_reason
    decision["template_similarity"] = round(template_similarity, 4)
    if brain_provenance_worthy and not calibrated_worthy:
        _strategy_metric(state, "provenance_downgraded")
    if args.dry_run:
''',
        "calibration-before-send",
    )

    source = _replace_once(
        source,
        '''        "contribution_value": contribution_value,
        "provenance_worthy": bool(decision.get("provenance_worthy", False)),
        "contribution_type": _single_line(str(decision.get("contribution_type", "other")), 40),
''',
        '''        "contribution_value": contribution_value,
        "originality_score": _bounded_int(decision.get("originality_score")),
        "evidence_strength": _bounded_int(decision.get("evidence_strength")),
        "durable_state_value": _bounded_int(decision.get("durable_state_value")),
        "evidence_kind": _single_line(str(decision.get("evidence_kind", "none")), 40),
        "brain_provenance_worthy": bool(decision.get("brain_provenance_worthy", False)),
        "provenance_worthy": bool(decision.get("provenance_worthy", False)),
        "provenance_reason": _single_line(str(decision.get("provenance_reason", "")), 160),
        "template_similarity": float(decision.get("template_similarity", 0.0) or 0.0),
        "contribution_type": _single_line(str(decision.get("contribution_type", "other")), 40),
''',
        "ledger-calibration-fields",
    )

    source = _replace_once(
        source,
        '''        f"sent action={kind} room={room} seq={last_seq} brain={mode} "
        f"contribution={contribution_value}"
''',
        '''        f"sent action={kind} room={room} seq={last_seq} brain={mode} "
        f"contribution={contribution_value} worthy={bool(decision.get('provenance_worthy'))} "
        f"similarity={float(decision.get('template_similarity', 0.0) or 0.0):.2f}"
''',
        "send-log",
    )

    return source


def patch_file(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    patched = patch_source(source)
    if patched == source:
        return False
    path.write_text(patched, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    changed = patch_file(args.path)
    status = "applied" if changed else "already present"
    print(f"aizong v{TARGET_VERSION} patch {status}: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
