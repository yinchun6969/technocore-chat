#!/usr/bin/env python3
"""Love8 Persistent Agent v2.4.1 wrapper.

Keeps the tested v2.4 relationship/topic/contribution core and adds the v2.4.1
append-only permanent-memory lifecycle after each successful persistent cycle.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

VERSION = "2.4.1"
ROOT = Path("/opt/love8-agent/social")
LEGACY = ROOT / "love8_persistent_v240_core.py"
MEMORY = ROOT / "love8_memory_v241.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hourly", action="store_true"); p.add_argument("--finalize", action="store_true")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--status", action="store_true")
    p.add_argument("--verify", nargs="?", const="latest")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    a = p.parse_args()
    legacy = load("love8_persistent_v240_core", LEGACY)
    memory = load("love8_memory_v241_runtime", MEMORY)
    if a.status:
        print("===== LOVE8 PERSISTENT AGENT v2.4.1 =====")
        print("core: v2.4 relationship/topic/contribution engine")
        print("memory: v2.4.1 append-only DID-signed permanent journal")
        legacy.status(); print(); return memory.status()
    if a.verify is not None:
        conf = memory.cfg(); ok, count, head = memory.verify_event_chain(conf); ok2, ledger = memory.verify_canonical(conf)
        print("memory_chain:", "OK" if ok else "FAIL", "events=", count, "head=", head)
        print("canonical_ledger:", "OK" if ok2 else "FAIL", ledger)
        return 0 if ok and ok2 else 2
    if a.hourly or a.finalize:
        rc = legacy.run_cycle(dry_run=a.dry_run, finalize=a.finalize)
        if rc != 0 or a.dry_run: return rc
        result = memory.sync_cycle(finalize=a.finalize)
        print("v2.4.1 permanent_memory:", result)
        return 0
    raise SystemExit("use --hourly, --finalize, --status or --verify")


if __name__ == "__main__": raise SystemExit(main())
