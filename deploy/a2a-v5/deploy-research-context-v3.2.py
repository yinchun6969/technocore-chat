#!/usr/bin/env python3
"""Transactional code-only installer/rollback. No identity or cursor restoration."""
from __future__ import annotations

import argparse
import grp
import hashlib
import importlib.util
import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

BASE = Path("/opt/technocore-a2a/rnd-v5")
BACKUPS = Path("/root/tc-research-context-v32-backups")
LAUNCHER = Path("/usr/local/bin/tc-a2a-research-context-v32-rollback")
SERVICES = ("technocore-a2a-rnd-v5.service", "technocore-a2a-telegram.service")
FILES = (BASE / "autonomous-rnd-v5.py", BASE / "telegram-control-v1.py", BASE / "research_context_v32.py", LAUNCHER)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def at(root, path):
    return root / str(path).lstrip("/")


def atomic(path, content, mode, uid, gid):
    fd, name = tempfile.mkstemp(prefix=".research-v32-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
            os.fchown(handle.fileno(), uid, gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Services:
    def call(self, *args):
        return subprocess.run(args, text=True, capture_output=True, timeout=20, check=False)

    def state(self, unit):
        return self.call("systemctl", "is-active", unit).stdout.strip()

    def stop(self, unit):
        if self.call("systemctl", "stop", unit).returncode:
            raise RuntimeError("could not stop " + unit)

    def start(self, unit):
        if self.call("systemctl", "start", unit).returncode:
            raise RuntimeError("could not start " + unit)

    def healthy(self, unit):
        for _ in range(3):
            time.sleep(1)
            if self.state(unit) != "active":
                return False
        return True

    def runtime_group(self):
        user = self.call("systemctl", "show", SERVICES[0], "-p", "User", "--value").stdout.strip() or "root"
        group = self.call("systemctl", "show", SERVICES[0], "-p", "Group", "--value").stdout.strip()
        return grp.getgrnam(group).gr_gid if group else pwd.getpwnam(user).pw_gid

    def readable(self):
        user = self.call("systemctl", "show", SERVICES[0], "-p", "User", "--value").stdout.strip() or "root"
        result = self.call("runuser", "-u", user, "--", "/opt/technocore-a2a/venv/bin/python", "-B", "-c",
                           "import sys; sys.path.insert(0, '/opt/technocore-a2a/rnd-v5'); import research_context_v32")
        if result.returncode:
            raise RuntimeError("Director user cannot read/import new module; no permissions were broadened")


def restore(backup, root, service, require_hash=True):
    backup = backup.resolve()
    allowed_parent = at(root, BACKUPS).resolve()
    if backup.parent != allowed_parent or not backup.name.startswith("backup."):
        raise ValueError("backup is not in the validated v3.2 backup directory")
    manifest = json.loads((backup / "manifest.json").read_text())
    targets = [at(root, path) for path in FILES]
    for i, path in enumerate(targets):
        if path.is_symlink():
            raise RuntimeError("refusing symlink target: " + str(path))
        if require_hash and digest(path) != manifest.get("installed", {}).get(str(i)):
            raise RuntimeError("file changed after install; inspect before rollback: " + str(path))
        meta = manifest["files"][str(i)]
        if meta["existed"] and digest(backup / (str(i) + ".original")) != meta["sha256"]:
            raise RuntimeError("backup checksum mismatch; refusing restore")
    for unit in SERVICES:
        service.stop(unit)
    for i, path in enumerate(targets):
        meta = manifest["files"][str(i)]
        if meta["existed"]:
            saved = backup / (str(i) + ".original")
            atomic(path, saved.read_bytes(), meta["mode"], meta["uid"], meta["gid"])
        elif path.exists():
            path.unlink()  # Exact new module/launcher only, never a state directory.
    for unit in SERVICES:
        if manifest["services"][unit] == "active":
            service.start(unit)
            if not service.healthy(unit):
                raise RuntimeError("restored code but service needs inspection: " + unit)
    print("rollback=done; only code restored; newly added module/launcher removed if absent before; all live state retained")


def install(staging, root=Path("/"), service=None):
    service = service or Services()
    targets = [at(root, p) for p in FILES]
    for path in targets:
        if path.is_symlink():
            raise RuntimeError("refusing symlink target: " + str(path))
    if not all(p.is_file() for p in targets[:2]):
        raise RuntimeError("existing Director and Telegram code required")
    spec = importlib.util.spec_from_file_location("research_patcher32", staging / "patch-research-context-v3.2.py")
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)  # Offline transformer, never agent.py.
    originals = [p.read_text(encoding="utf-8") for p in targets[:2]]
    replacements = [patcher.patched_director(originals[0]).encode(), patcher.patched_telegram(originals[1]).encode(),
                    (staging / "research_context_v32.py").read_bytes()]
    for i, content in enumerate(replacements):
        compile(content, str(FILES[i]), "exec")
    if all(p.is_file() and p.read_bytes() == content for p, content in zip(targets, replacements)):
        print("code_current=YES; no restart or state change")
        return None
    state = {u: service.state(u) for u in SERVICES}
    if any(s not in {"active", "inactive", "failed"} for s in state.values()):
        raise RuntimeError("service is transitioning; wait and inspect before installing")
    backup_root = at(root, BACKUPS)
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix="backup.", dir=backup_root))
    manifest = {"version": "3.2", "services": state, "files": {}}
    for i, path in enumerate(targets):
        if path.exists():
            if not path.is_file():
                raise RuntimeError("target is not a regular file")
            stat = path.stat()
            shutil.copyfile(path, backup / (str(i) + ".original"))
            manifest["files"][str(i)] = {"existed": True, "uid": stat.st_uid, "gid": stat.st_gid,
                "mode": stat.st_mode & 0o777, "sha256": digest(path)}
        else:
            manifest["files"][str(i)] = {"existed": False}
    deploy_copy = backup / "deploy.py"
    shutil.copyfile(Path(__file__), deploy_copy)
    os.chmod(deploy_copy, 0o700)
    manifest_path = backup / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    stopped = []
    changed = False
    try:
        for unit in SERVICES:
            service.stop(unit)
            stopped.append(unit)
        for i, path in enumerate(targets):
            if digest(path) != manifest["files"][str(i)].get("sha256"):
                raise RuntimeError("file changed during preflight; no code overwritten")
        # Forensics only: rollback deliberately does not restore these snapshots.
        for name, path in (("director-state.json", Path("/opt/technocore-a2a/rnd-v5-state/director.json")),
                           ("telegram-notify.json", Path("/opt/technocore-a2a/tg-bot-state/notify.json"))):
            if at(root, path).is_file():
                shutil.copyfile(at(root, path), backup / name)
        group = service.runtime_group()
        replacements.append((f"#!/bin/sh\nexec /usr/bin/python3 '{deploy_copy}' --rollback '{backup}'\n").encode())
        for i, (path, content) in enumerate(zip(targets, replacements)):
            meta = manifest["files"][str(i)]
            mode = meta.get("mode", 0o640 if i == 2 else 0o700)
            uid = meta.get("uid", 0)
            gid = meta.get("gid", group if i == 2 else 0)
            changed = True
            atomic(path, content, mode, uid, gid)
        manifest["installed"] = {str(i): digest(p) for i, p in enumerate(targets)}
        manifest_path.write_text(json.dumps(manifest, indent=2))
        service.readable()
        for unit in SERVICES:
            if state[unit] == "active":
                service.start(unit)
                if not service.healthy(unit):
                    raise RuntimeError("startup check failed: " + unit)
    except Exception:
        if changed:
            restore(backup, root, service, require_hash=False)
        else:
            for unit in stopped:
                if state[unit] == "active":
                    service.start(unit)
        raise
    print("RESEARCH_CONTEXT_V32_INSTALLED")
    print("backup=" + str(backup))
    print("rollback=" + str(LAUNCHER))
    print("Reviewer/Curator/identities/cursors/nonces/peers/service settings unchanged")
    print("No invitations, new rooms, PRs or deployment of components performed")
    for unit in SERVICES:
        print(unit + "=" + service.state(unit))
    return backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", type=Path)
    parser.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("run on AI2AI as root")
    if bool(args.install) == bool(args.rollback):
        parser.error("choose --install or --rollback")
    if args.install:
        config = Path("/opt/technocore-a2a/.env").read_text()
        if not re.search(r"(?m)^AGENT_NAME=['\"]?ai2ai['\"]?\s*$", config):
            raise SystemExit("AI2AI configuration required; no changes made")
        install(args.install)
    else:
        restore(args.rollback, Path("/"), Services())
