#!/usr/bin/env python3
"""Narrow Love8 deep-room bridge. No runtime import, network or invitations."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

TARGET = Path('/opt/love8-agent/social/love8_deep_rooms_v242.py')
SOURCE = Path('/opt/technocore-collab/state/peers.json')
BACKUPS = Path('/root/tc-love8-peer-bridge-v243-backups')
KNOWN = {
    'did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e': ('aizong', 'builder'),
    'did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje': ('ai2ai', 'reviewer/challenger'),
}
OLD_ROWS = '''def peer_rows():
    d=load_json(PEERS,{});return [p for p in d.get("peers",[]) if isinstance(p,dict)] if isinstance(d,dict) else []'''
NEW_ROWS = '''def peer_rows():
    # LOVE8_PINNED_PEER_BRIDGE_V243: local pinned routes only, no discovery.
    known = {
        "did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e": ("aizong", "builder"),
        "did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje": ("ai2ai", "reviewer/challenger"),
    }
    pinned = json.loads(Path("/opt/technocore-collab/state/peers.json").read_text(encoding="utf-8"))
    if not isinstance(pinned, dict):
        raise ValueError("invalid pinned peer mapping")
    rows = []
    for did, (name, role) in known.items():
        route = pinned.get(did)
        if not isinstance(route, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", route):
            raise ValueError("missing or invalid pinned route for " + name)
        rows.append({"did": did, "name": name, "role": role,
                     "fingerprint": fp(did), "mailbox": route if route.startswith("mb-") else "",
                     "_pinned_route": route, "source": "local-collab-pins"})
    return rows'''
OLD_INVITE = '''def send_invite(g,conf,social,peer,text):
    mb=str(peer.get("mailbox","") or "")'''
NEW_INVITE = '''def send_invite(g,conf,social,peer,text):
    # Re-read the local pin at delivery; never use a stale or remote hint.
    if "_pinned_route" in peer:
        try:
            current = next((p for p in peer_rows() if p["did"] == peer.get("did")), None)
            if current is None or current["_pinned_route"] != peer["_pinned_route"]:
                return False, "pinned route changed; retry selection"
            route = current["_pinned_route"]
            g.signed_post(conf["BASE"].rstrip("/"),conf["DID"],conf["KEY"],route,text,social)
            social.setdefault("writes",[]).append(time.time())
            return True, "pinned-mailbox" if route.startswith("mb-") else "pinned-room"
        except Exception as exc:
            return False, "pinned delivery failed: " + type(exc).__name__
    mb=str(peer.get("mailbox","") or "")'''


def transform(text):
    if NEW_ROWS in text and NEW_INVITE in text:
        return text
    if text.count(OLD_ROWS) != 1 or text.count(OLD_INVITE) != 1:
        raise ValueError('unsupported installed code; no changes made')
    result = text.replace(OLD_ROWS, NEW_ROWS).replace(OLD_INVITE, NEW_INVITE)
    ast.parse(result)
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('symlink refused: ' + str(part))


def atomic(path, data, metadata):
    fd, name = tempfile.mkstemp(prefix='.peer-bridge-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchown(stream.fileno(), metadata['uid'], metadata['gid'])
            os.fchmod(stream.fileno(), metadata['mode'])
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run as root on Love8')
    safe(TARGET)
    safe(SOURCE)
    safe(BACKUPS)
    if args.rollback:
        directory = args.rollback.absolute()
        if directory.parent != BACKUPS or not directory.name.startswith('backup.'):
            raise ValueError('invalid backup directory')
        safe(directory / 'manifest.json')
        safe(directory / 'original.py')
        manifest = json.loads((directory / 'manifest.json').read_text())
        original = (directory / 'original.py').read_bytes()
        if digest(original) != manifest['before'] or digest(TARGET.read_bytes()) != manifest['after']:
            raise ValueError('backup or installed code changed; refusing rollback')
        atomic(TARGET, original, manifest)
        print('LOVE8_PEER_BRIDGE_V243_ROLLED_BACK; state and services unchanged')
        return
    pins = json.loads(SOURCE.read_text())
    if not isinstance(pins, dict) or not all(did in pins for did in KNOWN):
        raise ValueError('expected existing Aizong and AI2AI pins; refusing to invent peers')
    import re
    for did in KNOWN:
        if not isinstance(pins[did], str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', pins[did]):
            raise ValueError('invalid pinned route')
    original = TARGET.read_bytes()
    patched = transform(original.decode()).encode()
    print('PINNED_PEERS=2; aizong=builder; ai2ai=reviewer/challenger')
    if args.check:
        print('PREFLIGHT_PASS; no writes, runtime imports, posts or invitations')
        return
    if original == patched:
        print('LOVE8_PEER_BRIDGE_V243_ALREADY_INSTALLED')
        return
    metadata = TARGET.stat()
    manifest = {'before': digest(original), 'after': digest(patched),
                'uid': metadata.st_uid, 'gid': metadata.st_gid, 'mode': stat.S_IMODE(metadata.st_mode)}
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='backup.', dir=BACKUPS))
    (directory / 'original.py').write_bytes(original)
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    shutil.copyfile(__file__, directory / 'repair.py')
    print('backup=' + str(directory), flush=True)
    if TARGET.read_bytes() != original:
        raise ValueError('code changed during backup; no patch applied')
    atomic(TARGET, patched, manifest)
    print('LOVE8_PEER_BRIDGE_V243_INSTALLED')
    print('rollback=python3 ' + str(directory / 'repair.py') + ' --rollback ' + str(directory))
    print('Only peer reading and pinned invitation routing changed; no services restarted.')
    print('No room created or invitation sent by installer. Next cron run uses the bridge.')
    print('Existing external-contact quality gates, room limits and A2A state unchanged.')


if __name__ == '__main__':
    main()
