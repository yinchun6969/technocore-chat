#!/usr/bin/env python3
"""Runtime wrapper for Love8 Brain v2.2.1.
Loads the Brain core, v2.1.1 guard, and OpenAI-compatible reasoning-model adapter.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

ROOT = Path('/opt/love8-agent/social')
BRAIN_PATH = ROOT / 'love8_brain.py'
COMPAT_PATH = ROOT / 'love8_brain_compat.py'


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


brain = load_module('love8_brain_v220_core', BRAIN_PATH)
brain.guard = brain.load_guard()

if COMPAT_PATH.exists():
    compat = load_module('love8_brain_compat_v221', COMPAT_PATH)
    brain.chat = compat.make_chat(brain)

if __name__ == '__main__':
    raise SystemExit(brain.main())
