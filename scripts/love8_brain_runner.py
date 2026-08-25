#!/usr/bin/env python3
"""Runtime wrapper for Love8 Brain v2.2.0.
Loads the Brain module and binds the v2.1.1 guard globally so memory-stage helpers stay fail-closed.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

PATH = Path('/opt/love8-agent/social/love8_brain.py')
spec = importlib.util.spec_from_file_location('love8_brain_v220', PATH)
if spec is None or spec.loader is None:
    raise SystemExit('cannot load love8_brain.py')
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)
brain.guard = brain.load_guard()

if __name__ == '__main__':
    raise SystemExit(brain.main())
