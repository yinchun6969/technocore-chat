#!/usr/bin/env python3
"""Resolve Atlas v2 room-only configuration without exporting credentials."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.technocore_atlas import WORKFLOW_SIGNERS, _is_workflow_room

MAX_PEERS_BYTES = 512_000


def resolve_workflow_rooms(path: Path) -> tuple[str, ...]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("pinned peers file is absent or unsafe")
    with path.open("rb") as handle:
        raw = handle.read(MAX_PEERS_BYTES + 1)
    if len(raw) > MAX_PEERS_BYTES:
        raise ValueError("pinned peers file exceeds bound")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("pinned peers must be a DID-to-room object")
    required_dids = (WORKFLOW_SIGNERS["WORKFLOW_TASK"], WORKFLOW_SIGNERS["BUILD_RESULT"])
    rooms = ["d-aizong"]
    for did in required_dids:
        room = value.get(did)
        if not isinstance(room, str) or not _is_workflow_room(room):
            raise ValueError("required v5 peer mailbox is not pinned")
        rooms.append(room)
    return tuple(dict.fromkeys(rooms))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("peers", type=Path)
    args = parser.parse_args(argv)
    try:
        print(",".join(resolve_workflow_rooms(args.peers)))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"atlas config error: {type(exc).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
