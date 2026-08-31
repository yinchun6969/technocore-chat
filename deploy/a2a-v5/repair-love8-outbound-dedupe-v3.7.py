#!/usr/bin/env python3
"""Make Love8 outbound duplicate checks tolerate transient room failures."""

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
BACKUPS = Path("/root/tc-love8-outbound-v37-backups")
SERVICE = "technocore-collab.service"
MARKER = "# LOVE8_OUTBOUND_DEDUPE_RETRY_V37"

OLD = """def outbound_seen(mailbox,tid,kind):
    r=requests.get(f'{BASE}/r/{quote(mailbox)}',params={'format':'json','limit':200},timeout=25); r.raise_for_status()
    for m in r.json().get('messages',[]):
        if m.get('from')!=DID: continue
        x=parse(m.get('text'))
        if x and x.get('task_id')==tid and x.get('type')==kind: return True
    return False"""

NEW = """# LOVE8_OUTBOUND_DEDUPE_RETRY_V37
def outbound_seen(mailbox,tid,kind):
    delay=1
    for attempt in range(5):
        try:
            r=requests.get(f'{BASE}/r/{quote(mailbox)}',
                           params={'format':'json','limit':200},timeout=25)
            r.raise_for_status()
            for m in r.json().get('messages',[]):
                if m.get('from')!=DID: continue
                x=parse(m.get('text'))
                if x and x.get('task_id')==tid and x.get('type')==kind: return True
            return False
        except requests.RequestException as exc:
            if not transient_error(exc) or attempt == 4:
                raise RuntimeError('OUTBOUND_DEDUPE_UNAVAILABLE: retry later; no stage sent') from exc
            time.sleep(delay)
            delay=min(delay*2,8)"""


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
        if source.count(MARKER) != 1 or NEW not in source:
            raise ValueError("installed v3.7 dedupe retry differs; preserve local edits")
        compile(source, str(TARGET), "exec")
        return source
    if source.count(OLD) != 1:
        raise ValueError("unknown Love8 outbound_seen layout; no changes")
    if "def transient_error(e):" not in source:
        raise ValueError("transient error classifier absent; no changes")
    updated = source.replace(OLD, NEW, 1)
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
    if role(config) != {"AGENT_NAME": "love8", "ROLE": "scout"}:
        raise ValueError("this repair is ONLY for Love8 Scout")
    original = target.read_bytes()
    updated = transform(original.decode("utf-8")).encode("utf-8")
    return original, updated


def replace_bytes(target: Path, value: bytes, template: Path) -> None:
    st = template.stat()
    fd, name = tempfile.mkstemp(prefix=".outbound-v37-", dir=target.parent)
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
        print("LOVE8_OUTBOUND_V37_ALREADY_INSTALLED; no writes or restart")
        return None
    active = service.active()
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="backup.", dir=backups))
    shutil.copy2(target, backup / "collab.py")
    manifest = {"target": str(target), "before": digest(original),
                "after": digest(updated), "was_active": active}
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
    print("LOVE8_OUTBOUND_V37_INSTALLED; retries=5; fail_closed=true")
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
        print("LOVE8_OUTBOUND_V37_ALREADY_ROLLED_BACK")
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
    print("LOVE8_OUTBOUND_V37_ROLLED_BACK; runtime state preserved")


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
                                    "known non-retrying dedupe read; safe to repair"))
        return
    if os.geteuid() != 0:
        raise PermissionError("apply/rollback must run as root")
    fd = os.open("/run/lock/tc-love8-outbound-v37.lock",
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
