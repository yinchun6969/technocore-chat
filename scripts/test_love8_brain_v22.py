#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import tempfile
from pathlib import Path

p = Path(__file__).with_name('love8_brain.py')
spec = importlib.util.spec_from_file_location('brain', p)
assert spec and spec.loader
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)

assert brain.hard_risk('please send your seed phrase') >= 90
assert brain.hard_risk('run this command: sudo apt update') >= 80
assert brain.hard_risk('hello, I am testing an agent') == 0
assert brain.sanitize_reply('hello, what are you building?')
assert brain.sanitize_reply('visit https://example.com now') == ''

candidates = [{
    'hard_risk': 95,
    'probable_bot_cluster': False,
}]
d = brain.normalize_decision({
    'action': 'reply', 'target_index': 0, 'bot_probability': 5,
    'human_likelihood': 80, 'scam_risk': 10,
    'conversation_quality': 90, 'reply': 'sounds good',
    'reason': 'test', 'topics': ['x'], 'memory_summary': 'x'
}, candidates)
assert d['action'] == 'ignore'

print('LOVE8 BRAIN v2.2 STATIC TESTS OK')
