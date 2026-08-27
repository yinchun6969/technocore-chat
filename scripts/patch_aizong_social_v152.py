#!/usr/bin/env python3
"""Patch Social v1.5.1 to v1.5.2 capacity-aware identity rooms."""

from __future__ import annotations

import argparse
from pathlib import Path

TARGET_VERSION = "1.5.2"


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"PATCH_MISMATCH[{label}]: {old[:240]!r}")
    return source.replace(old, new, 1)


def patch_source(source: str) -> str:
    if 'VERSION = "1.5.2"' in source:
        return source
    if 'VERSION = "1.5.1"' not in source:
        raise RuntimeError("expected Social v1.5.1 source")

    source = _replace_once(
        source,
        '"""Social v1.5.1: identity-named deep-collaboration rooms with collision-safe allocation."""',
        '"""Social v1.5.2: capacity-aware identity-named deep-collaboration rooms."""',
        "docstring",
    )
    source = _replace_once(source, 'VERSION = "1.5.1"', 'VERSION = "1.5.2"', "version")

    source = _replace_once(
        source,
        """def _identity_room_base() -> str:\n""",
        """def _valid_existing_room(room: str) -> bool:\n    return bool(\n        re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", room)\n        and room != "events"\n    )\n\n\ndef _identity_room_base() -> str:\n""",
        "existing-room-validator",
    )

    source = _replace_once(
        source,
        """def _home_room_name() -> str:\n    resolved = os.getenv("TC_HOME_ROOM_RESOLVED", "").strip().lower()\n    if _valid_home_room(resolved):\n        return resolved\n    return _identity_room_base()\n""",
        """def _home_room_name() -> str:\n    resolved = os.getenv("TC_HOME_ROOM_RESOLVED", "").strip().lower()\n    if _valid_existing_room(resolved):\n        return resolved\n    return _identity_room_base()\n""",
        "resolved-fallback-room",
    )

    source = _replace_once(
        source,
        """def _ensure_home_room(\n""",
        r"""def _room_capacity_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "room limit reached" in text or "20480 is the cap" in text:
        return True
    code = int(getattr(exc, "code", 0) or 0)
    if code != 400:
        return False
    try:
        body = exc.read().decode("utf-8", "replace").lower()
    except Exception:
        body = ""
    return "room limit reached" in body or "20480 is the cap" in body


def _capacity_fallback_room(base: str, did: str, nick: str) -> tuple[str, int] | None:
    configured = os.getenv("TC_HUB_CAPACITY_FALLBACK", "").strip().lower()
    room = configured or f"d-{nick}"
    if not _valid_existing_room(room):
        return None
    try:
        data = http_json(f"{base}/r/{room}?format=json&limit=80")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    messages = data.get("messages", []) if isinstance(data, dict) else []
    rows = [item for item in messages if isinstance(item, dict)] if isinstance(messages, list) else []
    if not any(str(item.get("from", "")) == did for item in rows):
        return None
    last_seq = int(data.get("last_seq", 0) or 0) if isinstance(data, dict) else 0
    return room, last_seq


def _ensure_home_room(
""",
        "capacity-helpers",
    )

    source = _replace_once(
        source,
        """    hub = _hub_state(state)\n    now = int(time.time())\n    verify_every = _strategy_limit("TC_HUB_VERIFY_INTERVAL", 21600, 1800, 86400)\n    persisted = str(hub.get("room", "") or "").strip().lower()\n""",
        """    hub = _hub_state(state)\n    now = int(time.time())\n    verify_every = _strategy_limit("TC_HUB_VERIFY_INTERVAL", 21600, 1800, 86400)\n    capacity_retry = _strategy_limit("TC_HUB_CAPACITY_RETRY", 21600, 1800, 86400)\n    capacity_wait_until = int(hub.get("capacity_wait_until", 0) or 0)\n    persisted = str(hub.get("room", "") or "").strip().lower()\n    if capacity_wait_until > now:\n        if _valid_existing_room(persisted) and bool(hub.get("bootstrapped")):\n            os.environ["TC_HOME_ROOM_RESOLVED"] = persisted\n        return\n""",
        "capacity-backoff",
    )

    source = _replace_once(
        source,
        """        _valid_home_room(persisted)\n        and _candidate_belongs_to_base(persisted, _identity_room_base())\n""",
        """        _valid_existing_room(persisted)\n        and (\n            _candidate_belongs_to_base(persisted, _identity_room_base())\n            or str(hub.get("bootstrap_mode", "")).startswith("capacity-fallback")\n        )\n""",
        "fallback-fast-path",
    )

    source = _replace_once(
        source,
        """    try:\n        response = signed_post(base, did, key, room, text, state)\n    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:\n        log(f"WARN home room bootstrap deferred room={room}: {type(exc).__name__}: {exc}")\n        return\n\n    seq = int(response.get("last_seq", 0) or 0)\n""",
        """    try:\n        response = signed_post(base, did, key, room, text, state)\n    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:\n        if _room_capacity_error(exc):\n            hub["desired_room"] = room\n            hub["capacity_blocked_at"] = now\n            hub["capacity_wait_until"] = now + capacity_retry\n            hub["last_capacity_error"] = "global room capacity reached"\n            try:\n                fallback = _capacity_fallback_room(base, did, nick)\n            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as fallback_exc:\n                fallback = None\n                hub["fallback_error"] = _single_line(\n                    f"{type(fallback_exc).__name__}: {fallback_exc}", 180\n                )\n            if fallback is not None:\n                fallback_room, fallback_seq = fallback\n                hub["room"] = fallback_room\n                hub["owner_did"] = did\n                hub["bootstrapped"] = True\n                hub["bootstrap_mode"] = "capacity-fallback-existing"\n                hub["fallback_since"] = now\n                hub["last_verified_at"] = now\n                hub["last_seen_seq"] = fallback_seq\n                os.environ["TC_HOME_ROOM_RESOLVED"] = fallback_room\n                log(\n                    f"WARN identity room capacity full; using existing owned room={fallback_room} "\n                    f"until retry room={room}"\n                )\n            else:\n                hub["bootstrapped"] = False\n                hub["bootstrap_mode"] = "capacity-wait"\n                os.environ.pop("TC_HOME_ROOM_RESOLVED", None)\n                log(\n                    f"WARN identity room capacity full; no verified owned fallback; "\n                    f"retry_after={capacity_retry}s desired={room}"\n                )\n            return\n        log(f"WARN home room bootstrap deferred room={room}: {type(exc).__name__}: {exc}")\n        return\n\n    seq = int(response.get("last_seq", 0) or 0)\n""",
        "capacity-bootstrap-fallback",
    )

    source = _replace_once(
        source,
        """    hub["bootstrapped"] = True\n    hub["owner_did"] = did\n    hub["bootstrap_mode"] = "signed-create"\n""",
        """    hub["bootstrapped"] = True\n    hub["owner_did"] = did\n    hub["bootstrap_mode"] = "signed-create"\n    hub.pop("capacity_wait_until", None)\n    hub.pop("capacity_blocked_at", None)\n    hub.pop("last_capacity_error", None)\n    hub.pop("fallback_error", None)\n""",
        "clear-capacity-state",
    )

    return source


def patch_file(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    patched = patch_source(source)
    if patched == source:
        return False
    path.write_text(patched, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    changed = patch_file(args.path)
    status = "applied" if changed else "already present"
    print(f"Social v{TARGET_VERSION} patch {status}: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
