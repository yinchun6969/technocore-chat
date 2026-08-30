#!/usr/bin/env python3
"""Fail-closed patch: Telegram /brief exposes verified artifact pairs only."""

import argparse
import ast
import os
from pathlib import Path


MARKER = "# VERIFIED_BRIEF_V551"


def replace_function(source: str, name: str, body: str) -> str:
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(nodes) != 1:
        raise ValueError("unsupported function: " + name)
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    return "".join(lines[:node.lineno - 1]) + body.strip() + "\n" + "".join(lines[node.end_lineno:])


LATEST = r'''
def _verified_artifact_pair(md_path: Path, meta: dict) -> bool:
    if not isinstance(meta, dict) or meta.get("workflow_id") != md_path.stem:
        return False
    if meta.get("evidence_verified") is not True:
        return False
    bundle = meta.get("evidence_bundle")
    if not isinstance(bundle, dict) or bundle.get("workflow_id") != md_path.stem:
        return False
    if meta.get("evidence_merkle_root") != bundle.get("merkle_root"):
        return False
    try:
        spec = importlib.util.spec_from_file_location(
            "technocore_evidence_v551_brief", ROOT / "rnd-v5" / "evidence_v55.py"
        )
        if spec is None or spec.loader is None:
            return False
        evidence = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(evidence)
        evidence.verify_bundle(bundle)
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return False
    return hashlib.sha256(text.encode()).hexdigest() == meta.get("artifact_sha256")


def latest() -> tuple[Path | None, str]:
    try:
        receipts = sorted(ARTIFACTS.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return None, ""
    for receipt in receipts:
        md_path = receipt.with_suffix(".md")
        if not md_path.is_file():
            continue
        meta = read_json(receipt, {})
        if not _verified_artifact_pair(md_path, meta):
            continue
        try:
            return md_path, md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None, ""
'''


BRIEF = r'''
def brief() -> str:
    path, artifact = latest()
    if path is not None:
        meta = read_json(path.with_suffix(".json"), {})
        return (
            f"最新已验证研究简报\nworkflow: {path.stem}\n"
            f"cross_validation_score: {meta.get('cross_validation_score', 'unknown')}\n"
            f"evidence_merkle_root: {meta.get('evidence_merkle_root', 'unknown')}\n\n"
            + safe_text(artifact, 3200)
        )
    state = read_json(DIRECTOR_STATE, {})
    card = research_context.current(state) if isinstance(state, dict) else {}
    if card:
        return (
            "当前/最近研究卡片（尚无通过 v5.5.1 验证的 artifact）\nrequest: "
            + str(card.get("request_id")) + "\n" + research_context.render(card, detailed=True)
        )
    active = state.get("active_request", {}) if isinstance(state, dict) else {}
    goal = active.get("goal", "") if isinstance(active, dict) else ""
    return "目前没有通过 v5.5.1 验证的研究档案。已记录目标：" + compact(goal, 700)
'''


def patch(source: str) -> str:
    if MARKER in source:
        ast.parse(source)
        return source
    if "# RESEARCH_CONTEXT_V32" not in source:
        raise ValueError("research context v3.2 marker missing; refusing a downgrade-prone patch")
    if "import importlib.util\n" not in source:
        source = source.replace("import hashlib\n", "import hashlib\nimport importlib.util\n", 1)
    source = replace_function(source, "latest", LATEST)
    source = replace_function(source, "brief", BRIEF)
    source = source.replace("from __future__ import annotations\n", "from __future__ import annotations\n\n" + MARKER + "\n", 1)
    ast.parse(source)
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("telegram", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = patch(args.telegram.read_text(encoding="utf-8"))
    compile(source, str(args.telegram), "exec")
    if args.apply:
        mode, uid, gid = args.telegram.stat().st_mode & 0o777, args.telegram.stat().st_uid, args.telegram.stat().st_gid
        temporary = args.telegram.with_name(args.telegram.name + ".v551-new")
        if temporary.exists() or temporary.is_symlink():
            raise RuntimeError("staging path already exists: " + str(temporary))
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(source)
        os.chmod(temporary, mode)
        os.chown(temporary, uid, gid)
        os.replace(temporary, args.telegram)
    print("VERIFIED_BRIEF_V551_PREFLIGHT=PASS" + ("; applied" if args.apply else "; no writes"))


if __name__ == "__main__":
    main()
