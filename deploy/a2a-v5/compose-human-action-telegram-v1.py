#!/usr/bin/env python3
"""Compose the canonical action-aware Telegram controller from pinned sources."""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load " + path.name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compose(source: str) -> str:
    context = load("human_action_context_v32", HERE / "patch-research-context-v3.2.py")
    verified = load("human_action_verified_v551", HERE / "patch-verified-brief-v5.5.1.py")
    result = context.patched_telegram(source)
    result = verified.patch(result)
    compile(result, "telegram-control-v1.py", "exec")
    for marker in (
        "# RESEARCH_CONTEXT_V32", "# VERIFIED_BRIEF_V551",
        "def action_inbox()", '"human_action_created"',
        '"allowed_updates": ["message", "callback_query"]',
    ):
        if marker not in result:
            raise ValueError("composed Telegram marker missing: " + marker)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compose(args.source.read_text(encoding="utf-8"))
    if args.output:
        temporary = args.output.with_name(args.output.name + ".new")
        if temporary.exists() or temporary.is_symlink():
            raise RuntimeError("staging path already exists")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(result)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, args.output)
    print("HUMAN_ACTION_TELEGRAM_COMPOSE=PASS")


if __name__ == "__main__":
    main()
