#!/usr/bin/env python3
"""Repair Aizong Builder polling to use the persisted room cursor."""

from __future__ import annotations

import argparse
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

TARGET = Path("/opt/technocore-collab/bin/collab.py")
CONFIG = Path("/opt/technocore-collab/.env")
BACKUPS = Path("/root/tc-aizong-cursor-v36-backups")
SERVICE = "technocore-collab.service"
MARKER = "# AIZONG_CURSOR_POLL_V36"

FETCH_OLD = """def fetch_messages():
    inbox=FALLBACK_INBOX or MAILBOX
    r=requests.get(f'{BASE}/r/{quote(inbox)}',params={'format':'json','limit':200},timeout=30); r.raise_for_status(); return r.json().get('messages',[])"""

FETCH_NEW = """# AIZONG_CURSOR_POLL_V36
def fetch_messages(since):
    inbox=FALLBACK_INBOX or MAILBOX
    cursor=max(0,int(since))
    r=requests.get(f'{BASE}/r/{quote(inbox)}',
                   params={'since':cursor,'wait':10,'format':'json','limit':200},
                   timeout=30)
    r.raise_for_status()
    return r.json().get('messages',[])"""

RUN_OLD = "            msgs=fetch_messages()"
RUN_NEW = "            msgs=fetch_messages(cur)"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def regular(path: Path) -> None:
    for item in [path, *path.parents]:
        if item.is_symlink():
            raise ValueError("symlink path refused: " + str(item))
    if not path.is_file():
        raise ValueError("required file absent: " + str(path))


def transform(source: str) -> str:
    if MARKER in source:
        if source.count(MARKER) != 1 or FETCH_NEW not in source or RUN_NEW not in source:
            raise ValueError("installed v3.6 cursor polling differs; preserve local edits")
        compile(source, str(TARGET), "exec")
        return source
    if source.count(FETCH_OLD) != 1 or source.count(RUN_OLD) != 1:
        raise ValueError("unknown Aizong polling layout; no changes")
    if "FALLBACK_INBOX=os.environ.get('A2A_FALLBACK_INBOX'" not in source:
        raise ValueError("Aizong fallback inbox is not installed; no changes")
    updated = source.replace(FETCH_OLD, FETCH_NEW, 1).replace(RUN_OLD, RUN_NEW, 1)
    compile(updated, str(TARGET), "exec")
    return updated


def role(config: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        parts = shlex.split(line, comments=True)
        if parts and parts[0] == "export":
            parts = parts[1:]
        for part in parts:
            key, sep, value = part.partition("=")
            if sep and key in {"AGENT_NAME", "ROLE"}:
                values[key] = value
    return values


def preflight(target: Path = TARGET, config: Path = CONFIG) -> tuple[bytes, bytes]:
    regular(target)
    regular(config)
    if role(config) != {"AGENT_NAME": "aizong", "ROLE": "builder"}:
        raise ValueError("this repair is ONLY for Aizong Builder")
    original = target.read_bytes()
    updated = transform(original.decode("utf-8")).encode("utf-8")
    return original, updated


def replace_bytes(target: Path, value: bytes, template: Path) -> None:
    st = template.stat()
    fd, name = tempfile.mkstemp(prefix=".cursor-v36-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copystat(template, temporary)
        if os.geteuid() == 0:
            os.chown(temporary, st.st_uid, st.st_gid)
        os.chmod(temporary, stat.S_IMODE(st.st_mode))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class Systemd:
    def call(self, *args: str) -> str:
        return subprocess.run(["systemctl", *args, SERVICE], check=True,
                              capture_output=True, text=True, timeout=45).stdout.strip()

    def active(self) -> bool:
        if self.call("show", "-p", "LoadState", "--value") != "loaded":
            raise ValueError("existing collab service not loaded")
        state = self.call("show", "-p", "ActiveState", "--value")
        if state not in {"active", "inactive"}:
            raise ValueError("service state requires operator review: " + state)
        return state == "active"

    def stop(self) -> None:
        self.call("stop")

    def start(self) -> None:
        self.call("start")
        time.sleep(3)
        self.call("is-active", "--quiet")


def apply(target: Path, original: bytes, updated: bytes, backups: Path, service: Systemd):
    if original == updated:
        print("AIZONG_CURSOR_V36_ALREADY_INSTALLED; no writes or restart")
        return None
    active = service.active()
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="backup.", dir=backups))
    shutil.copy2(target, backup / "collab.py")
    manifest = {"target": str(target), "before": digest(original), "after": digest(updated),
                "was_active": active}
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copy2(Path(__file__), backup / "repair.py")
    if target.read_bytes() != original:
        raise ValueError("source changed during backup")
    replaced = False
    try:
        if active:
            service.stop()
        replace_bytes(target, updated, backup / "collab.py")
        replaced = True
        if active:
            service.start()
    except Exception:
        if replaced and target.read_bytes() == updated:
            service.stop()
            replace_bytes(target, original, backup / "collab.py")
        if active:
            service.start()
        raise
    print("AIZONG_CURSOR_V36_INSTALLED; polling=since+wait; cursor=preserved")
    print("backup=" + str(backup))
    print("rollback=python3 " + str(backup / "repair.py") + " --rollback " + str(backup))
    return backup


def rollback(backup: Path, target: Path, service: Systemd) -> None:
    regular(backup / "manifest.json")
    regular(backup / "collab.py")
    manifest = json.loads((backup / "manifest.json").read_text())
    original = (backup / "collab.py").read_bytes()
    current = target.read_bytes()
    if digest(current) == manifest["before"]:
        print("AIZONG_CURSOR_V36_ALREADY_ROLLED_BACK")
        return
    if digest(current) != manifest["after"] or digest(original) != manifest["before"]:
        raise ValueError("rollback integrity mismatch or runtime drift")
    active = service.active()
    if active:
        service.stop()
    try:
        replace_bytes(target, original, backup / "collab.py")
    finally:
        if active:
            service.start()
    print("AIZONG_CURSOR_V36_ROLLED_BACK; runtime state preserved")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    if args.check:
        original, updated = preflight()
        print("PREFLIGHT=PASS; " + ("already installed" if original == updated else
                                    "known fixed-URL poller; safe to repair"))
        return
    if os.geteuid() != 0:
        raise PermissionError("apply/rollback must run as root")
    fd = os.open("/run/lock/tc-aizong-cursor-v36.lock",
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.rollback:
            if args.rollback.parent != BACKUPS or not args.rollback.name.startswith("backup."):
                raise ValueError("unexpected rollback directory")
            rollback(args.rollback, TARGET, Systemd())
        else:
            original, updated = preflight()
            apply(TARGET, original, updated, BACKUPS, Systemd())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("STOP: " + type(exc).__name__ + ": " + str(exc))
        raise SystemExit(1)
