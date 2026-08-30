#!/usr/bin/env python3
"""Isolated, public-only Atlas collector and loopback SVG/JSON reader.

Run as a module: python3 -m tools.atlas_observer refresh|serve.
No agent runtime imports, credentials, ledgers, model calls or remote writes.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit

from tools.atlas_dashboard import dashboard_document
from tools.technocore_atlas import Snapshot, collect_snapshot, fetch_json, render_svg

DEFAULT_ROOM = "yinchun-a2a-rnd-v5"
DEFAULT_STATE = Path("/var/lib/technocore-atlas/observer.json")
STALE_SECONDS = 900
MAX_STATE_BYTES = 8_000_000
TRANSIENT_HTTP_CODES = frozenset({429, 502, 503, 504})
FETCH_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 0.35


def timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_STATE_BYTES + 1)
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError("state exceeds bound")
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("invalid state")
        return state
    except FileNotFoundError:
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Replace one bounded document atomically; never leave half a snapshot."""
    data = json.dumps(state, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_STATE_BYTES:
        raise ValueError("state exceeds bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".atlas-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def refresh(
    path: Path,
    *,
    base: str = "https://technocore.chat",
    rooms: tuple[str, ...] = (DEFAULT_ROOM,),
    workflow_rooms: tuple[str, ...] = (),
    collector: Callable[..., Snapshot] = collect_snapshot,
) -> int:
    state = load_state(path)
    attempted = timestamp()
    state["last_attempt"] = attempted
    fetch_errors: list[str] = []

    def observed_fetch(url: str, timeout: float):
        for attempt in range(FETCH_ATTEMPTS):
            try:
                return fetch_json(url, timeout)
            except HTTPError as exc:
                if attempt + 1 < FETCH_ATTEMPTS and exc.code in TRANSIENT_HTTP_CODES:
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                fetch_errors.append(f"HTTP_{exc.code}")
                raise
            except OSError:
                if attempt + 1 < FETCH_ATTEMPTS:
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                fetch_errors.append("NETWORK_ERROR")
                raise
        raise AssertionError("unreachable")

    try:
        snapshot = collector(
            base,
            selected_rooms=rooms,
            room_limit=12,
            messages_per_room=100,
            timeout=10,
            fetcher=observed_fetch,
            workflow_rooms=workflow_rooms,
        )
        # Keep the last complete snapshot if even one selected room is unavailable.
        if snapshot.collection_errors or snapshot.workflow_collection_errors or not snapshot.rooms:
            raise ValueError("incomplete room collection")
        state.update(
            snapshot=snapshot.to_dict(),
            last_success=attempted,
            last_success_epoch=time.time(),
            last_attempt_ok=True,
            error_code=None,
            consecutive_failures=0,
        )
        result = 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Never copy URLs, response bodies or exception details to public status.
        state.update(
            last_attempt_ok=False,
            error_code=fetch_errors[0] if fetch_errors else type(exc).__name__,
            consecutive_failures=min(9999, int(state.get("consecutive_failures", 0)) + 1),
        )
        result = 1
    save_state(path, state)
    print(json.dumps(status(state)))
    return result


def status(state: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    epoch = state.get("last_success_epoch")
    age = max(0, int((time.time() if now is None else now) - epoch)) if epoch else None
    stale = age is None or age > STALE_SECONDS
    return {
        "schema": "technocore-atlas-observer/v2",
        "status": "waiting"
        if age is None
        else ("stale" if stale else ("ok" if state.get("last_attempt_ok") else "degraded")),
        "last_attempt": state.get("last_attempt"),
        "last_success": state.get("last_success"),
        "last_attempt_ok": bool(state.get("last_attempt_ok")),
        "age_seconds": age,
        "stale": stale,
        "error_code": state.get("error_code"),
        "consecutive_failures": max(0, int(state.get("consecutive_failures", 0))),
        "meaning": (
            "Observed signed stages only; not proof of agent uptime, identity or research quality."
        ),
    }


def svg_document(state: dict[str, Any]) -> bytes:
    info = status(state)
    banner = escape(
        f"{info['status'].upper()} | last success: {info['last_success'] or 'none'} | "
        f"error: {info['error_code'] or 'none'} | "
        "PUBLIC OBSERVATIONS ONLY - refresh this page for latest data"
    )
    snapshot = state.get("snapshot")
    if snapshot:
        svg = render_svg(snapshot)
        # Extend the canvas so the warning cannot obscure existing trace labels.
        svg = svg.replace(
            'height="900" viewBox="0 0 1600 900"', 'height="940" viewBox="0 0 1600 940"', 1
        )
        y = 918
    else:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 100"></svg>'
        y = 48
    color = "#16734b" if info["status"] == "ok" else "#a13f16"
    warning = (
        f'<rect x="0" y="{y - 18}" width="1600" height="40" fill="{color}"/>'
        f'<text x="20" y="{y + 8}" font-size="18" fill="white">{banner}</text>'
    )
    return svg.replace("</svg>", warning + "</svg>").encode("utf-8")


def make_handler(state_path: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def log_message(self, format, *args):  # noqa: A002
            pass  # Do not log arbitrary client paths or headers.

        def send_body(self, code: int, mime: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            # No directory listing, files, input URLs, mutations, or proxy routes.
            port = cast(HTTPServer, self.server).server_port
            if self.headers.get("Host") not in {f"localhost:{port}", f"127.0.0.1:{port}"}:
                self.send_body(403, "text/plain", b"loopback Host required")
                return
            route = urlsplit(self.path).path
            if route not in {"/", "/atlas.svg", "/atlas.json", "/status.json"}:
                self.send_body(404, "text/plain", b"not found")
                return
            try:
                state = load_state(state_path)
                if route == "/":
                    self.send_body(
                        200, "text/html; charset=utf-8", dashboard_document(state, status(state))
                    )
                elif route == "/atlas.svg":
                    self.send_body(200, "image/svg+xml; charset=utf-8", svg_document(state))
                elif route == "/atlas.json":
                    snapshot = state.get("snapshot")
                    body = {"observation": status(state), "snapshot": snapshot}
                    self.send_body(
                        200 if snapshot else 503, "application/json", json.dumps(body).encode()
                    )
                else:
                    self.send_body(200, "application/json", json.dumps(status(state)).encode())
            except (OSError, ValueError, TypeError, KeyError):
                self.send_body(503, "text/plain", b"observer state unavailable")

        def do_POST(self):  # noqa: N802
            self.send_body(405, "text/plain", b"read-only observer")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("refresh", "serve", "status"))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--room", action="append", default=[])
    parser.add_argument(
        "--workflow-rooms",
        default="",
        help="comma-separated pinned v5 workflow sources; names are never returned by the server",
    )
    args = parser.parse_args(argv)
    if args.command == "refresh":
        workflow_rooms = tuple(filter(None, args.workflow_rooms.split(",")))
        return refresh(
            args.state,
            rooms=tuple(args.room) or (DEFAULT_ROOM,),
            workflow_rooms=workflow_rooms,
        )
    if args.command == "status":
        print(json.dumps(status(load_state(args.state)), indent=2))
        return 0
    with ThreadingHTTPServer(("127.0.0.1", 8787), make_handler(args.state)) as server:
        server.daemon_threads = True
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
