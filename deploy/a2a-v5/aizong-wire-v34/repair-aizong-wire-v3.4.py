#!/usr/bin/env python3
"""Aizong-only v3.4 wire repair; no runtime imports, identity or state edits."""
import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
TARGET = Path('/opt/technocore-collab/bin/collab.py')
CONFIG = Path('/opt/technocore-collab/.env')
BACKUPS = Path('/root/tc-aizong-wire-v34-backups')
SERVICE = 'technocore-collab.service'
OLD = r'''
def payload(kind,tid,**kw):
    obj={'v':1,'type':kind,'task_id':tid,'from_did':DID,'reply_mailbox':MAILBOX,'role':ROLE,**kw}
    def enc(): return 'A2A1 '+json.dumps(obj,separators=(',',':'),ensure_ascii=True)
    text=enc()
    if len(text.encode('utf-8')) <= MAX_A2A_WIRE_BYTES:
        return text
    # Preserve the newest stage output as long as possible; compact older context first.
    orders={
      'BUILD_RESULT':['goal','build_result'],
      'CHALLENGE':['build_result','goal','challenge'],
      'REVISED_RESULT':['goal','challenge','revised_result'],
      'COMPLETE':['final_summary'],
      'RESULT':['result'],
      'WORKFLOW_TASK':['goal'],
      'TASK':['goal'],
    }
    mins={'goal':320,'build_result':520,'challenge':520,'revised_result':700,'final_summary':500,'result':700}
    for key in orders.get(kind, list(kw.keys())):
        while len(enc().encode('utf-8')) > MAX_A2A_WIRE_BYTES and isinstance(obj.get(key),str) and len(obj[key]) > mins.get(key,160):
            over=len(enc().encode('utf-8'))-MAX_A2A_WIRE_BYTES
            cut=max(96,over+96)
            keep=max(mins.get(key,160),len(obj[key])-cut)
            obj[key]=obj[key][:keep]
    text=enc()
    if len(text.encode('utf-8')) > MAX_A2A_WIRE_BYTES:
        raise ValueError(f'A2A payload too large after compaction: {len(text.encode("utf-8"))} bytes')
    return text
'''
WIRE = r'''
# A2A_WIRE_GUARD_V34

def _wire_encode_v34(obj):
    # Keep ASCII escaping: the server's Unicode sweep must not change JSON
    # string values after signing. Budget the actual escaped representation.
    return 'A2A1 ' + json.dumps(obj, separators=(',', ':'), ensure_ascii=True)

def _wire_cost_v34(text):
    return len(json.dumps(text, ensure_ascii=True).encode('utf-8')) - 2

def _wire_prefix_v34(text, budget):
    if _wire_cost_v34(text) <= budget:
        return text
    suffix = '...[truncated]'
    if budget < _wire_cost_v34(suffix):
        raise ValueError('A2A text budget is too small')
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _wire_cost_v34(text[:mid] + suffix) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + suffix

def payload(kind, tid, **kw):
    reserved = {'v', 'type', 'task_id', 'from_did', 'reply_mailbox', 'role', '_wire'}
    if reserved.intersection(kw):
        raise ValueError('A2A protected envelope field override')
    obj = {'v': 1, 'type': kind, 'task_id': tid,
           'from_did': DID, 'reply_mailbox': MAILBOX, 'role': ROLE, **kw}
    original = _wire_encode_v34(obj)
    if len(original.encode('utf-8')) <= MAX_A2A_WIRE_BYTES:
        return original
    # Only narrative fields may be shortened. IDs, routes, policy, role,
    # evidence hashes and every other structured field remain byte-identical.
    fields = [k for k in ('goal', 'build_result', 'challenge', 'revised_result',
                         'final_summary', 'result')
              if isinstance(obj.get(k), str) and obj[k]]
    if not fields:
        raise ValueError('A2A structural metadata exceeds wire budget')
    originals = {k: obj[k] for k in fields}
    obj['_wire'] = {'truncated': True,
                    'original_sha256': hashlib.sha256(original.encode()).hexdigest(),
                    'fields': fields[:]}
    for key in fields:
        obj[key] = ''
    available = MAX_A2A_WIRE_BYTES - len(_wire_encode_v34(obj).encode('utf-8'))
    costs = {k: _wire_cost_v34(originals[k]) for k in fields}
    allocations = {k: min(costs[k], 96) for k in fields}
    if available < sum(allocations.values()):
        raise ValueError('A2A structural metadata leaves no useful text budget')
    left = available - sum(allocations.values())
    primary = {'CHALLENGE': 'challenge', 'BUILD_RESULT': 'build_result',
               'REVISED_RESULT': 'revised_result', 'COMPLETE': 'final_summary',
               'RESULT': 'result'}.get(kind, 'goal')
    # Weighted, work-conserving allocation; redistribute unused space from
    # small fields. There are no fixed character minima that can exceed bytes.
    while left:
        hungry = [k for k in fields if allocations[k] < costs[k]]
        if not hungry:
            break
        weights = {k: 4 if k == primary else 1 for k in hungry}
        total = sum(weights.values())
        before = left
        for key in hungry:
            grant = min(left, costs[key] - allocations[key],
                        max(1, before * weights[key] // total))
            allocations[key] += grant
            left -= grant
        if before == left:
            break
    for key in fields:
        obj[key] = _wire_prefix_v34(originals[key], allocations[key])
    obj['_wire']['fields'] = [k for k in fields if obj[k] != originals[k]]
    text = _wire_encode_v34(obj)
    if len(text.encode('utf-8')) > MAX_A2A_WIRE_BYTES:
        raise ValueError('A2A wire budget invariant failed')
    return text
'''



def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(node):
    return ast.dump(node, include_attributes=False)


def transform(source):
    tree = ast.parse(source)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if len([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'payload']) != 1:
        raise ValueError('expected exactly one top-level payload function')
    limits = [n for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'MAX_A2A_WIRE_BYTES' for t in n.targets)]
    if len(limits) != 1 or not isinstance(limits[0].value, ast.Constant) or limits[0].value.value != 3400:
        raise ValueError('expected the existing 3400-byte wire limit; no changes')
    new_functions = [n for n in ast.parse(WIRE).body if isinstance(n, ast.FunctionDef)]
    new_payload = next(n for n in new_functions if n.name == 'payload')
    current = funcs['payload']
    if normalized(current) == normalized(new_payload):
        for n in new_functions:
            occurrences = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == n.name]
            if len(occurrences) != 1 or normalized(occurrences[0]) != normalized(n):
                raise ValueError('installed v3.4 helpers differ; preserve local edits')
        return source
    if normalized(current) != normalized(ast.parse(OLD).body[0]):
        raise ValueError('unknown payload implementation; refuse to overwrite it')
    if any(n.name in funcs for n in new_functions if n.name != 'payload'):
        raise ValueError('helper name collision')
    # Both imports already exist in the collab runtime; never execute it here.
    imports = {a.asname or a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
    if not {'json', 'hashlib'} <= imports:
        raise ValueError('required standard-library imports absent')
    lines = source.splitlines(keepends=True)
    updated = ''.join(lines[:current.lineno - 1]) + WIRE.strip() + '\n' + ''.join(lines[current.end_lineno:])
    compile(updated, str(TARGET), 'exec')
    return updated


def self_test():
    ns = {'json': json, 'hashlib': hashlib, 'DID': 'did:key:test',
          'MAILBOX': 'mb-p-test', 'ROLE': 'builder', 'MAX_A2A_WIRE_BYTES': 3400}
    # Only our pure encoder is executed, never the installed collab module.
    exec(compile(WIRE, '<pure-wire-self-test>', 'exec'), ns)
    for kind, field in [('BUILD_RESULT', 'build_result'), ('REVISED_RESULT', 'revised_result')]:
        text = ns['payload'](kind, 'wf-test', goal='中文研究' * 500,
                             **{field: '测试😀\\"\n' * 1000}, reviewer_did='did:key:reviewer')
        obj = json.loads(text[5:])
        assert len(text.encode()) <= 3400
        assert obj['task_id'] == 'wf-test' and obj['role'] == 'builder'
        assert obj['reviewer_did'] == 'did:key:reviewer' and obj['_wire']['truncated']
    print('AIZONG_WIRE_V34_SELF_TEST=PASS')


def regular(path):
    # Reject symlinks in every component, not only the leaf.
    for p in [path, *path.parents]:
        if p.is_symlink():
            raise ValueError('symlink path refused: ' + str(p))
    if not path.is_file():
        raise ValueError('required file absent: ' + str(path))


def preflight(target=TARGET, config=CONFIG):
    regular(target)
    regular(config)
    values = {}
    for line in config.read_text().splitlines():
        parts = shlex.split(line, comments=True)
        if parts and parts[0] == 'export':
            parts = parts[1:]
        for part in parts:
            key, sep, value = part.partition('=')
            if sep and key in ('AGENT_NAME', 'ROLE'):
                values[key] = value
    if values != {'AGENT_NAME': 'aizong', 'ROLE': 'builder'}:
        raise ValueError('this repair is ONLY for Aizong Builder')
    original = target.read_bytes()
    updated = transform(original.decode()).encode()
    return original, updated


def replace_bytes(target, value, template):
    regular(target)
    regular(template)
    st = template.stat()
    fd, name = tempfile.mkstemp(prefix='.wire-v34-', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        shutil.copystat(template, temporary)
        if os.geteuid() == 0:
            os.chown(temporary, st.st_uid, st.st_gid)
        else:
            if (temporary.stat().st_uid, temporary.stat().st_gid) != (st.st_uid, st.st_gid):
                raise PermissionError('cannot preserve file ownership')
        os.chmod(temporary, stat.S_IMODE(st.st_mode))
        os.replace(temporary, target)
        dfd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        temporary.unlink(missing_ok=True)


class Systemd:
    def call(self, *args):
        return subprocess.run(['systemctl', *args, SERVICE], check=True,
                              capture_output=True, text=True, timeout=45).stdout.strip()

    def active(self):
        if self.call('show', '-p', 'LoadState', '--value') != 'loaded':
            raise ValueError('existing collab service not loaded')
        state = self.call('show', '-p', 'ActiveState', '--value')
        if state not in ('active', 'inactive'):
            raise ValueError('service state is ' + state + '; inspect before patching')
        return state == 'active'

    def stop(self):
        self.call('stop')

    def start(self):
        self.call('start')
        time.sleep(3)
        self.call('is-active', '--quiet')


def apply(target, original, updated, backups, service):
    if original == updated:
        print('AIZONG_WIRE_V34_ALREADY_INSTALLED; no writes or restart')
        return None
    was_active = service.active()
    # Backup before stopping or changing anything. No identity/config/state files.
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    for p in [backups, *backups.parents]:
        if p.is_symlink():
            raise ValueError('symlink backup directory refused')
    backup = Path(tempfile.mkdtemp(prefix='backup.', dir=backups))
    shutil.copy2(target, backup / 'collab.py')
    st = target.stat()
    if os.geteuid() == 0:
        os.chown(backup / 'collab.py', st.st_uid, st.st_gid)
    manifest = {'target': str(target), 'before': digest(original), 'after': digest(updated),
                'was_active': was_active, 'uid': st.st_uid, 'gid': st.st_gid,
                'mode': stat.S_IMODE(st.st_mode)}
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copy2(Path(__file__), backup / 'repair.py')
    print('backup=' + str(backup), flush=True)
    print('rollback=python3 ' + str(backup / 'repair.py') + ' --rollback ' + str(backup), flush=True)
    if digest((backup / 'collab.py').read_bytes()) != manifest['before']:
        raise ValueError('source changed during backup; no service change')
    stopped = False
    replaced = False
    try:
        if was_active:
            service.stop()
            stopped = True
        if target.read_bytes() != original:
            raise ValueError('source changed since preflight')
        replaced = True  # Includes a possible failure after atomic rename/fsync.
        replace_bytes(target, updated, backup / 'collab.py')
        if target.read_bytes() != updated:
            raise ValueError('post-write verification failed')
        if was_active:
            service.start()
    except Exception:
        if replaced:
            service.stop()
            if target.read_bytes() not in (original, updated):
                raise ValueError('concurrent source change; use backup after review')
            replace_bytes(target, original, backup / 'collab.py')
        if was_active and stopped:
            service.start()
        raise
    print('AIZONG_WIRE_V34_INSTALLED; wire_limit=3400; service=' + ('active' if was_active else 'inactive (preserved)'))
    print('identity/cursors/nonces/peers/workflow history/service configuration=UNCHANGED')
    return backup


def rollback(backup, target, service):
    regular(backup / 'manifest.json')
    regular(backup / 'collab.py')
    regular(target)
    m = json.loads((backup / 'manifest.json').read_text())
    original = (backup / 'collab.py').read_bytes()
    if m['target'] != str(target) or digest(original) != m['before']:
        raise ValueError('backup integrity/target mismatch')
    if digest(target.read_bytes()) == m['before']:
        print('AIZONG_WIRE_V34_ALREADY_ROLLED_BACK; no restart')
        return
    if digest(target.read_bytes()) != m['after']:
        raise ValueError('current code changed after repair; refuse destructive rollback')
    active = service.active()
    if active:
        service.stop()
    try:
        if digest(target.read_bytes()) != m['after']:
            raise ValueError('source changed during rollback')
        replace_bytes(target, original, backup / 'collab.py')
    finally:
        if active:
            service.start()
    print('AIZONG_WIRE_V34_ROLLED_BACK; all runtime state preserved')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--apply', action='store_true')
    group.add_argument('--rollback', type=Path)
    group.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    self_test()
    if args.self_test:
        return
    if args.check:
        original, updated = preflight()
        print('PREFLIGHT=PASS; ' + ('already installed' if original == updated else 'known v3.3 payload; safe to replace'))
        return
    if os.geteuid() != 0:
        raise PermissionError('apply/rollback must run as root')
    # Lock only this repair; do not take over application locks or change state.
    lockpath = Path('/run/lock/tc-aizong-wire-v34.lock')
    fd = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.rollback:
            if args.rollback.parent != BACKUPS or not args.rollback.name.startswith('backup.'):
                raise ValueError('unexpected rollback directory')
            rollback(args.rollback, TARGET, Systemd())
        else:
            original, updated = preflight()
            apply(TARGET, original, updated, BACKUPS, Systemd())


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not dump runtime configuration, credentials or source into errors.
        print('STOP: ' + type(exc).__name__ + ': ' + str(exc))
        raise SystemExit(1)
