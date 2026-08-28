#!/usr/bin/env python3
"""Offline transforms and transactional AI2AI-only cadence repair.

Never imports agent.py, restores live state, posts messages, or changes identities.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

BASE = Path('/opt/technocore-a2a/rnd-v5')
SERVICES = ('technocore-a2a-rnd-v5.service', 'technocore-a2a-telegram.service')
BACKUPS = Path('/root/tc-a2a-cadence-v321-backups')
DROPIN = Path('/etc/systemd/system/technocore-a2a-rnd-v5.service.d/99-research-cadence-v321.conf')
LAUNCHER = Path('/usr/local/bin/tc-a2a-cadence-v321-rollback')
FILES = (BASE / 'autonomous-rnd-v5.py', BASE / 'research_context_v32.py', DROPIN, LAUNCHER)
ENV = {'RND_V5_MIN_GAP_SECONDS': '7200', 'RND_V5_MAX_DAILY': '12'}
CONFIG = ('[Service]\nEnvironment="RND_V5_MIN_GAP_SECONDS=7200"\n'
          'Environment="RND_V5_MAX_DAILY=12"\n').encode()


def upgrade_once(source, before, after):
    if source.count(after) == 1 and source.count(before) == after.count(before):
        return source
    if source.count(before) == 1 and after not in source:
        return source.replace(before, after, 1)
    raise ValueError('unsupported or ambiguous source layout: ' + before[:70])


def director_patch(source):
    if '# RESEARCH_CONTEXT_V32' not in source:
        raise ValueError('verified research-context v3.2 must be installed first')
    for before, after in (
        ('"RND_V5_MIN_GAP_SECONDS": "21600"', '"RND_V5_MIN_GAP_SECONDS": "7200"'),
        ('"RND_V5_MAX_DAILY": "4"', '"RND_V5_MAX_DAILY": "12"'),
        ('number("RND_V5_MAX_DAILY", 1, 8)', 'number("RND_V5_MAX_DAILY", 1, 12)'),
    ):
        source = upgrade_once(source, before, after)
    compile(source, 'autonomous-rnd-v5.py', 'exec')
    return source


OLD_CURRENT = '''def current(state: dict) -> dict:
    active = state.get("active_request")
    if isinstance(active, dict):
        return load(str(active.get("request_id", "")))
    history = state.get("history", [])
    for row in reversed(history[-30:]):
        if isinstance(row, dict) and (card := load(str(row.get("request_id", "")))):
            return card
    return {}'''

NEW_CURRENT = '''def current(state: dict) -> dict:
    active = state.get("active_request")
    if isinstance(active, dict) and active.get("request_id"):
        card = load(str(active["request_id"]))
        return {**card, "_director_active": True} if card else {}
    history = state.get("history", [])
    for row in reversed(history[-30:]):
        if isinstance(row, dict) and (card := load(str(row.get("request_id", "")))):
            # View metadata only: never persist it or claim remote cancellation.
            return {**card, "_director_active": False}
    return {}'''

OLD_RENDER = '    lines.append("进度：" + STAGES.get(stage, str(card.get("dispatch", "等待阶段证据"))))'
NEW_RENDER = '''    if card.get("_director_active") is False:
        lines.append("调度状态：Director 当前无活动请求；以下仅为历史记录，不代表远端任务仍在运行。")
        observed = {"WORKFLOW_TASK": "Love8 曾创建研究任务", "BUILD_RESULT": "曾收到 Builder 分析结果",
                    "CHALLENGE": "曾收到 Reviewer 质疑", "REVISED_RESULT": "曾收到修订结果",
                    "COMPLETE": "曾观测到流程完成（不等于 Bug 已核实）"}
        lines.append("历史最后观测：" + observed.get(stage, "尚无已关联的工作流阶段证据"))
    else:
        lines.append("进度：" + STAGES.get(stage, str(card.get("dispatch", "等待阶段证据"))))'''


def context_patch(source):
    source = upgrade_once(source, OLD_CURRENT, NEW_CURRENT)
    source = upgrade_once(source, OLD_RENDER, NEW_RENDER)
    compile(source, 'research_context_v32.py', 'exec')
    return source


def at(root, path):
    return root / str(path).lstrip('/')


def safe_path(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError('symlink path refused: ' + str(path))
    if path.exists() and not path.is_file():
        raise RuntimeError('not a regular file: ' + str(path))


def metadata(path):
    safe_path(path)
    if not path.exists():
        return {'existed': False}
    s = path.stat()
    return {'existed': True, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'mode': s.st_mode & 0o777, 'uid': s.st_uid, 'gid': s.st_gid}


def atomic(path, data, meta):
    fd, tmp = tempfile.mkstemp(prefix='.cadence-v321-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), meta.get('mode', 0o644))
            os.fchown(f.fileno(), meta.get('uid', 0), meta.get('gid', 0))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Services:
    def call(self, *args):
        return subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)

    def state(self, unit):
        return self.call('systemctl', 'is-active', unit).stdout.strip()

    def action(self, action, unit=None):
        args = ('systemctl', action) + ((unit,) if unit else ())
        if self.call(*args).returncode:
            raise RuntimeError('service action failed: ' + action + ' ' + (unit or ''))

    def healthy(self, unit):
        for _ in range(3):
            time.sleep(1)
            if self.state(unit) != 'active':
                raise RuntimeError('service is not stable: ' + unit)

    def verify_environment(self):
        pid = self.call('systemctl', 'show', SERVICES[0], '-p', 'MainPID', '--value').stdout.strip()
        if not pid.isdigit() or int(pid) <= 1:
            raise RuntimeError('Director PID unavailable; cannot verify live cadence')
        values = {}
        # Read only the two configured limits; never print the environment.
        for item in Path('/proc', pid, 'environ').read_bytes().split(b'\0'):
            key, _, val = item.partition(b'=')
            name = key.decode(errors='replace')
            if name in ENV:
                values[name] = val.decode(errors='replace')
        if values != ENV:
            raise RuntimeError('live cadence differs from 7200/12; inspect conflicting unit configuration')


def restore(backup, root, service, require_match=True):
    backup = backup.resolve()
    if backup.parent != at(root, BACKUPS).resolve() or not backup.name.startswith('backup.'):
        raise ValueError('invalid v3.2.1 backup path')
    manifest = json.loads((backup / 'manifest.json').read_text())
    targets = [at(root, p) for p in FILES]
    for i, path in enumerate(targets):
        present = metadata(path)
        if require_match and present != manifest['installed'][str(i)]:
            raise RuntimeError('changed since install; inspect before rollback: ' + str(path))
        meta = manifest['files'][str(i)]
        if meta['existed'] and metadata(backup / f'{i}.original')['sha256'] != meta['sha256']:
            raise RuntimeError('backup checksum mismatch; nothing restored')
    for u in SERVICES:
        service.action('stop', u)
    for i, path in enumerate(targets):
        meta = manifest['files'][str(i)]
        if meta['existed']:
            atomic(path, (backup / f'{i}.original').read_bytes(), meta)
        elif path.exists():
            path.unlink()  # Only this release's exact new drop-in/launcher.
    service.action('daemon-reload')
    for u in SERVICES:
        if manifest['services'][u] == 'active':
            service.action('start', u)
            service.healthy(u)
    print('ROLLBACK_DONE; original code/config restored; new drop-in/launcher removed if absent before; live state retained')


def install(root=Path('/'), service=None):
    service = service or Services()
    targets = [at(root, p) for p in FILES]
    originals = {str(i): metadata(p) for i, p in enumerate(targets)}
    if not all(originals[str(i)]['existed'] for i in (0, 1)):
        raise RuntimeError('Director and research_context_v32.py must already exist')
    tg = at(root, BASE / 'telegram-control-v1.py')
    safe_path(tg)
    if '# RESEARCH_CONTEXT_V32' not in tg.read_text():
        raise RuntimeError('Telegram research-context v3.2 hook missing')
    data = [director_patch(targets[0].read_text()).encode(), context_patch(targets[1].read_text()).encode(), CONFIG]
    states = {u: service.state(u) for u in SERVICES}
    if any(v != 'active' for v in states.values()):
        raise RuntimeError('Director/Telegram must be stable and active; no service was started or changed')
    if all(p.exists() and p.read_bytes() == d for p, d in zip(targets, data)):
        service.verify_environment()
        print('CADENCE_V321_ALREADY_INSTALLED; no changes or restart')
        return None
    backup_root = at(root, BACKUPS)
    if any(p.is_symlink() for p in (backup_root, *backup_root.parents)):
        raise RuntimeError('symlink backup root refused')
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='backup.', dir=backup_root))
    manifest = {'version': '3.2.1', 'files': originals, 'services': states}
    for i, path in enumerate(targets):
        if originals[str(i)]['existed']:
            shutil.copyfile(path, backup / f'{i}.original')
    helper = backup / 'repair.py'
    shutil.copyfile(Path(__file__), helper)
    helper.chmod(0o700)
    data.append(f"#!/bin/sh\nexec /usr/bin/python3 '{helper}' --rollback '{backup}'\n".encode())
    manifest_file = backup / 'manifest.json'
    manifest_file.write_text(json.dumps(manifest, indent=2))
    print('backup=' + str(backup), flush=True)
    stopped, changed = [], False
    try:
        for u in SERVICES:
            service.action('stop', u)
            stopped.append(u)
        for i, path in enumerate(targets):
            if metadata(path) != originals[str(i)]:
                raise RuntimeError('file changed during preflight; no code overwritten')
        for i, (path, content) in enumerate(zip(targets, data)):
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            meta = originals[str(i)] if originals[str(i)]['existed'] else {'mode': 0o700 if i == 3 else 0o644}
            changed = True
            atomic(path, content, meta)
        manifest['installed'] = {str(i): metadata(p) for i, p in enumerate(targets)}
        manifest_file.write_text(json.dumps(manifest, indent=2))
        service.action('daemon-reload')
        for u in SERVICES:
            service.action('start', u)
            service.healthy(u)
        service.verify_environment()
    except Exception:
        if changed:
            restore(backup, root, service, require_match=False)
        else:
            for u in stopped:
                service.action('start', u)
        raise
    print('RESEARCH_CADENCE_V321_INSTALLED')
    print('live_min_gap_seconds=7200; live_max_daily=12; code_daily_ceiling=12')
    print('history_view=last_observed_not_running; single_flight=retained; notification_quota=unchanged')
    print('daily_counts/queues/history/identities/cursors/nonces/peers=untouched')
    print('Reviewer/Curator/Love8/Aizong=not_modified_or_restarted')
    print('rollback=' + str(LAUNCHER))
    return backup


def validate_node(path):
    values = []
    for line in path.read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key.strip() == 'AGENT_NAME':
            values.append(value.strip())
    if len(values) != 1 or values[0] not in ('ai2ai', '"ai2ai"', "'ai2ai'"):
        raise ValueError('AI2AI configuration required; nothing changed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run on AI2AI as root')
    validate_node(Path('/opt/technocore-a2a/.env'))
    with open('/run/lock/tc-a2a-cadence-v321.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.rollback:
            restore(args.rollback, Path('/'), Services())
        else:
            install()
