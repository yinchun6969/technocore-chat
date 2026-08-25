#!/usr/bin/env python3
"""Patch an installed aizong Social v1.3.0 core to v1.3.1 Network Resilience."""

from __future__ import annotations

import argparse
from pathlib import Path

TARGET_VERSION = "1.3.1"


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"PATCH_MISMATCH[{label}]: {old[:140]!r}")
    return source.replace(old, new, 1)


def patch_source(source: str) -> str:
    if 'VERSION = "1.3.1"' in source:
        return source
    if 'VERSION = "1.3.0"' not in source:
        raise RuntimeError("expected aizong Social v1.3.0 source")

    source = _replace_once(
        source,
        '"""aizong Social v1.3.0: long-context Technocore relationship intelligence with 2X social capacity."""',
        '"""aizong Social v1.3.1: network-resilient long-context Technocore relationship intelligence."""',
        "docstring",
    )
    source = _replace_once(source, 'VERSION = "1.3.0"', 'VERSION = "1.3.1"', "version")

    helpers = """\n\n_TRANSIENT_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}\n\n\ndef _env_int(name: str, default: int, low: int, high: int) -> int:\n    try:\n        value = int(os.getenv(name, str(default)))\n    except ValueError:\n        value = default\n    return min(max(value, low), high)\n\n\ndef _retry_delay(attempt: int) -> float:\n    base_ms = _env_int("TC_NET_BACKOFF_BASE_MS", 1000, 100, 10000)\n    base = base_ms / 1000.0\n    return min(base * (2 ** max(attempt - 1, 0)) + random.uniform(0, 0.25), 15.0)\n\n\ndef _read_request(\n    request: urllib.request.Request,\n    *,\n    timeout: int,\n    attempts: int,\n    label: str,\n    timeout_step: int = 0,\n) -> bytes:\n    last_exc: Exception | None = None\n    for attempt in range(1, attempts + 1):\n        attempt_timeout = min(timeout + (attempt - 1) * timeout_step, 120)\n        try:\n            with urllib.request.urlopen(request, timeout=attempt_timeout) as response:\n                return response.read()\n        except urllib.error.HTTPError as exc:\n            if exc.code not in _TRANSIENT_HTTP_STATUS:\n                raise\n            last_exc = exc\n            detail = f"HTTP {exc.code}"\n        except (urllib.error.URLError, TimeoutError) as exc:\n            last_exc = exc\n            detail = type(exc).__name__\n        if attempt < attempts:\n            delay = _retry_delay(attempt)\n            log(\n                f"WARN transient {label} attempt={attempt}/{attempts} "\n                f"error={detail} retry_in={delay:.1f}s"\n            )\n            time.sleep(delay)\n    if last_exc is None:\n        raise RuntimeError(f"{label} retry loop ended without result")\n    raise last_exc\n\n\ndef _network_health(state: dict[str, Any]) -> dict[str, Any]:\n    return state.setdefault("network_health", {})\n\n\ndef _cooldown_remaining(state: dict[str, Any], endpoint: str) -> int:\n    health = _network_health(state)\n    until = int(health.get(f"{endpoint}_cooldown_until", 0) or 0)\n    return max(0, until - int(time.time()))\n\n\ndef _note_endpoint_success(state: dict[str, Any], endpoint: str) -> None:\n    health = _network_health(state)\n    health[f"{endpoint}_consecutive_failures"] = 0\n    health[f"{endpoint}_last_success_at"] = int(time.time())\n\n\ndef _note_endpoint_failure(state: dict[str, Any], endpoint: str, exc: Exception) -> None:\n    health = _network_health(state)\n    key = f"{endpoint}_consecutive_failures"\n    failures = int(health.get(key, 0) or 0) + 1\n    health[key] = failures\n    health[f"{endpoint}_last_failure_at"] = int(time.time())\n    health[f"{endpoint}_last_error"] = _single_line(f"{type(exc).__name__}: {exc}", 240)\n    if endpoint == "brain":\n        threshold = _env_int("TC_BRAIN_COOLDOWN_AFTER", 3, 2, 10)\n        seconds = _env_int("TC_BRAIN_COOLDOWN_SECONDS", 900, 60, 3600)\n    else:\n        threshold = _env_int("TC_NET_COOLDOWN_AFTER", 3, 2, 10)\n        seconds = _env_int("TC_NET_COOLDOWN_SECONDS", 900, 60, 3600)\n    if failures >= threshold:\n        health[f"{endpoint}_cooldown_until"] = int(time.time()) + seconds\n"""
    source = _replace_once(
        source,
        "\ndef load_shell_config(path: Path) -> dict[str, str]:",
        helpers + "\n\ndef load_shell_config(path: Path) -> dict[str, str]:",
        "retry-helpers",
    )

    source = _replace_once(
        source,
        """    with urllib.request.urlopen(request, timeout=timeout) as response:\n        payload = response.read().decode("utf-8")\n    data = json.loads(payload)""",
        """    attempts = _env_int("TC_NET_RETRIES", 3, 1, 5)\n    payload = _read_request(\n        request, timeout=timeout, attempts=attempts, label="technocore-get"\n    ).decode("utf-8")\n    data = json.loads(payload)""",
        "http-json-retry",
    )

    source = _replace_once(
        source,
        """    with urllib.request.urlopen(request, timeout=20) as response:\n        payload = response.read().decode("utf-8")\n    try:\n        data = json.loads(payload)""",
        """    # Signed writes are intentionally not blindly retried: if the server accepted\n    # the write but the response was lost, a retry could create ambiguity or duplicates.\n    payload = _read_request(\n        request, timeout=20, attempts=1, label="signed-post"\n    ).decode("utf-8")\n    try:\n        data = json.loads(payload)""",
        "signed-post-no-retry",
    )

    source = _replace_once(
        source,
        """    timeout = min(max(int(brain.get("BRAIN_TIMEOUT", "25")), 5), 60)\n    max_tokens = min(max(int(brain.get("BRAIN_MAX_TOKENS", "1536")), 256), 4096)""",
        """    timeout = min(max(int(brain.get("BRAIN_TIMEOUT", "60")), 15), 120)\n    brain_attempts = min(max(int(brain.get("BRAIN_RETRIES", "3")), 1), 3)\n    max_tokens = min(max(int(brain.get("BRAIN_MAX_TOKENS", "1536")), 256), 4096)""",
        "brain-timeout-retries",
    )

    source = _replace_once(
        source,
        """    with urllib.request.urlopen(request, timeout=timeout) as response:\n        data = json.loads(response.read().decode("utf-8"))\n    if not isinstance(data, dict):""",
        """    raw = _read_request(\n        request,\n        timeout=timeout,\n        attempts=brain_attempts,\n        label="brain",\n        timeout_step=15,\n    )\n    data = json.loads(raw.decode("utf-8"))\n    if not isinstance(data, dict):""",
        "brain-http-retry",
    )

    old_brain_try = """    try:\n        decision = call_brain(\n            brain,\n            room=room,\n            action=action,\n            nick=nick,\n            state=state,\n            trusted_topics=trusted_topics,\n        )\n    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:\n        log(f"WARN brain fallback: {type(exc).__name__}: {exc}")\n        return {"mode": "fallback", "reply": True, "text": fallback}\n    if decision.get("mode") == "disabled":"""
    new_brain_try = """    if brain.get("BRAIN_URL") and brain.get("BRAIN_MODEL"):\n        remaining = _cooldown_remaining(state, "brain")\n        if remaining > 0:\n            return {\n                "mode": "deferred",\n                "reply": False,\n                "reason": f"brain transport cooldown active ({remaining}s)",\n            }\n    try:\n        decision = call_brain(\n            brain,\n            room=room,\n            action=action,\n            nick=nick,\n            state=state,\n            trusted_topics=trusted_topics,\n        )\n    except (\n        urllib.error.HTTPError,\n        urllib.error.URLError,\n        TimeoutError,\n        ValueError,\n        json.JSONDecodeError,\n    ) as exc:\n        _note_endpoint_failure(state, "brain", exc)\n        log(f"WARN brain deferred: {type(exc).__name__}: {exc}")\n        return {\n            "mode": "deferred",\n            "reply": False,\n            "reason": "brain transport unavailable; retry next cycle",\n        }\n    _note_endpoint_success(state, "brain")\n    if decision.get("mode") == "disabled":"""
    source = _replace_once(source, old_brain_try, new_brain_try, "brain-safe-defer")

    source = _replace_once(
        source,
        """    state = load_state(state_path)\n    own_ids = {nick, did}\n    rooms = candidate_rooms(base, args.rooms)\n    log(""",
        """    state = load_state(state_path)\n    own_ids = {nick, did}\n    remaining = _cooldown_remaining(state, "network")\n    if remaining > 0:\n        save_state(state_path, state)\n        log(f"network cooldown active; observe paused for {remaining}s")\n        return False\n    try:\n        rooms = candidate_rooms(base, args.rooms)\n    except (\n        urllib.error.HTTPError,\n        urllib.error.URLError,\n        TimeoutError,\n        ValueError,\n        json.JSONDecodeError,\n    ) as exc:\n        _note_endpoint_failure(state, "network", exc)\n        save_state(state_path, state)\n        log(f"WARN room discovery deferred: {type(exc).__name__}: {exc}")\n        return False\n    _note_endpoint_success(state, "network")\n    log(""",
        "discovery-fail-soft",
    )

    source = _replace_once(
        source,
        """    decision = brain_decision(\n        brain,\n        room=room,\n        action=action,\n        nick=nick,\n        state=state,\n        fallback=fallback,\n        trusted_topics=trusted_topics,\n    )\n    apply_contact_memory(state, action, decision)""",
        """    decision = brain_decision(\n        brain,\n        room=room,\n        action=action,\n        nick=nick,\n        state=state,\n        fallback=fallback,\n        trusted_topics=trusted_topics,\n    )\n    if decision.get("mode") == "deferred":\n        save_state(state_path, state)\n        reason = _single_line(str(decision.get("reason", "")), 160)\n        log(f"brain deferred action={kind} room={room} reason={reason}")\n        return False\n    apply_contact_memory(state, action, decision)""",
        "deferred-preserves-action",
    )

    source = _replace_once(
        source,
        """    except urllib.error.HTTPError as exc:\n        body = exc.read().decode("utf-8", errors="replace")[:500]\n        log(f"WARN action={kind} room={room} HTTP {exc.code}: {body}")\n        save_state(state_path, state)\n        return False\n\n    now = int(time.time())""",
        """    except urllib.error.HTTPError as exc:\n        body = exc.read().decode("utf-8", errors="replace")[:500]\n        log(f"WARN action={kind} room={room} HTTP {exc.code}: {body}")\n        save_state(state_path, state)\n        return False\n    except (urllib.error.URLError, TimeoutError) as exc:\n        log(\n            f"WARN action={kind} room={room} signed-post transport failed; "\n            "not retrying automatically to avoid duplicate public writes"\n        )\n        save_state(state_path, state)\n        return False\n\n    now = int(time.time())""",
        "signed-post-fail-soft",
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
    print(f"aizong v{TARGET_VERSION} patch {status}: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
