#!/usr/bin/env python3
"""Build a read-only, provenance-safe visual snapshot of Technocore.

The Atlas is deliberately outside the service core. It reads only the public
room directory and public room tails, keeps message bodies out of snapshots,
and emits plain SVG so the result is reproducible without extra dependencies.

Examples:

    python tools/technocore_atlas.py collect --output atlas.json
    python tools/technocore_atlas.py render --input atlas.json --output atlas.svg

The collector never follows URLs found in messages and never writes to
Technocore. Public room names and message fields are still untrusted input;
the renderer escapes every value before placing it in SVG.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

USER_AGENT = "technocore-atlas/0.1"
MAX_RESPONSE_BYTES = 2_000_000
ROOM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
DID_RE = re.compile(r"^did:key:z6Mk[A-Za-z0-9]+$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
A2A_TYPES = {
    "TASK",
    "ACK",
    "RESULT",
    "CHALLENGE",
    "COMPLETE",
    "WORKFLOW_TASK",
    "BUILD_RESULT",
    "REVISED_RESULT",
    "SCHEDULER_REQUEST",
}
SECRET_KEY_RE = re.compile(r"(?:secret|token|password|private|api[_-]?key|seed|credential)", re.I)
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


def _base_url(value: str) -> str:
    """Validate and normalize an HTTP(S) service origin."""

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must include an http or https scheme and host")
    if (
        parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("base URL must be an origin without credentials, path, query or fragment")
    return value.rstrip("/")


def _url(base: str, path: str, **params: int | str) -> str:
    query = urlencode(params)
    return f"{base}{path}" + (f"?{query}" if query else "")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "redirect blocked", headers, fp)


def fetch_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch one bounded JSON response with a neutral user agent."""

    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with build_opener(NoRedirect).open(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response too large: {url}")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {url}")
    return payload


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _int_or_none(value: Any) -> int | None:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _short_author(raw: str) -> tuple[str, str, bool]:
    """Return a stable ID, safe display label and whether it is a DID writer."""

    value = raw.strip() or "unknown"
    stable_id = _sha256(value)[:12]
    if DID_RE.fullmatch(value):
        suffix = value.removeprefix("did:key:")
        return stable_id, f"did:key:{suffix[:8]}…{suffix[-4:]}", True
    return stable_id, f"~{value[:20]}", False


def _a2a_metadata(text: str) -> tuple[str, str | None]:
    """Extract only bounded, allow-listed workflow metadata from a message."""

    if not text.startswith("A2A1 "):
        return "MESSAGE", None
    try:
        payload = json.loads(text[5:])
    except (TypeError, ValueError, json.JSONDecodeError):
        return "A2A1_INVALID", None
    if not isinstance(payload, dict):
        return "A2A1_INVALID", None
    kind = payload.get("type")
    kind = kind if isinstance(kind, str) and kind in A2A_TYPES else "A2A1_OTHER"
    task_id = payload.get("task_id")
    task_id = task_id if isinstance(task_id, str) and TASK_ID_RE.fullmatch(task_id) else None
    return kind, task_id


@dataclass(frozen=True)
class TraceMessage:
    seq: int | None
    ts: str
    author_id: str
    author: str
    did_writer: bool
    signed: bool
    nonce: str | None
    kind: str
    task_id: str | None
    text_sha256: str


@dataclass(frozen=True)
class TraceRoom:
    name: str
    message_count: int
    last_seq: int | None
    messages: tuple[TraceMessage, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LocalTraceEvent:
    ts: str
    event: str
    agent: str
    role: str
    message_type: str
    task_id: str | None
    peer_id: str | None
    outcome: str


@dataclass(frozen=True)
class Snapshot:
    schema: str
    observed_at: str
    base_url: str
    rooms: tuple[TraceRoom, ...]
    summary: dict[str, int]
    local_events: tuple[LocalTraceEvent, ...] = field(default_factory=tuple)
    collection_errors: int = 0
    local_provenance_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_public_room(name: str) -> bool:
    """Avoid private room classes even if a server lists one accidentally."""

    if not ROOM_NAME_RE.fullmatch(name):
        return False
    # Classes compose in any order; all mailboxes are outside Atlas's scope.
    for prefix in name.split("-")[:-1]:
        if prefix in {"p", "mb"}:
            return False
        if prefix not in {"d", "e"}:
            break
    return True


def _trace_message(row: Any) -> TraceMessage | None:
    if not isinstance(row, dict):
        return None
    raw_from = str(row.get("from", ""))
    author_id, author, did_writer = _short_author(raw_from)
    text = row.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    kind, task_id = _a2a_metadata(text)
    nonce_value = row.get("nonce")
    nonce = str(nonce_value) if nonce_value is not None else None
    return TraceMessage(
        seq=_int_or_none(row.get("seq")),
        ts=str(row.get("ts", ""))[:64],
        author_id=author_id,
        author=author,
        did_writer=did_writer,
        signed=did_writer and nonce is not None,
        nonce=nonce[:32] if nonce else None,
        kind=kind,
        task_id=task_id,
        text_sha256=_sha256(text),
    )


def _public_room_names(listing: dict[str, Any], limit: int) -> list[str]:
    names: list[str] = []
    for item in listing.get("rooms", []):
        if not isinstance(item, dict):
            continue
        name = item.get("room")
        if isinstance(name, str) and _is_public_room(name) and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def collect_snapshot(
    base_url: str,
    *,
    room_limit: int = 12,
    messages_per_room: int = 100,
    timeout: float = 10.0,
    fetcher: Callable[[str, float], dict[str, Any]] = fetch_json,
    selected_rooms: tuple[str, ...] = (),
) -> Snapshot:
    """Read public room metadata and bounded public tails; never writes."""

    base = _base_url(base_url)
    if room_limit < 1 or room_limit > 200:
        raise ValueError("room_limit must be between 1 and 200")
    if messages_per_room < 1 or messages_per_room > 200:
        raise ValueError("messages_per_room must be between 1 and 200")

    if not 0 < timeout <= 30:
        raise ValueError("timeout must be between 0 and 30 seconds")
    if len(selected_rooms) > room_limit or any(not _is_public_room(r) for r in selected_rooms):
        raise ValueError("selected rooms must be public non-mailbox names within room_limit")
    if selected_rooms:
        names = list(dict.fromkeys(selected_rooms))
    else:
        listing = fetcher(_url(base, "/rooms", format="json", limit=room_limit), timeout)
        names = _public_room_names(listing, room_limit)
    rooms: list[TraceRoom] = []
    collection_errors = 0
    for name in names:
        try:
            detail = fetcher(
                _url(base, f"/r/{quote(name, safe='')}", format="json", limit=messages_per_room),
                timeout,
            )
            if not isinstance(detail.get("messages"), list):
                raise ValueError("room response must contain a messages array")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            collection_errors += 1
            continue
        messages = tuple(
            message
            for message in (_trace_message(row) for row in detail.get("messages", []))
            if message is not None
        )
        rooms.append(
            TraceRoom(
                name=name,
                message_count=len(messages),
                last_seq=_int_or_none(detail.get("last_seq")),
                messages=messages,
            )
        )

    all_messages = [message for room in rooms for message in room.messages]
    kinds = Counter(message.kind for message in all_messages)
    summary = {
        "rooms_observed": len(rooms),
        "messages_observed": len(all_messages),
        "signed_messages": sum(message.signed for message in all_messages),
        "did_writers": len({message.author_id for message in all_messages if message.did_writer}),
        "a2a_messages": sum(
            message.kind.startswith("A2A1") or message.kind in A2A_TYPES for message in all_messages
        ),
        "workflow_tasks": sum(message.task_id is not None for message in all_messages),
        "invalid_a2a_messages": kinds["A2A1_INVALID"],
        "collection_errors": collection_errors,
    }
    return Snapshot(
        schema="technocore-atlas/v1",
        observed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        base_url=base,
        rooms=tuple(rooms),
        summary=summary,
        collection_errors=collection_errors,
    )


def _safe_label(value: Any, fallback: str = "") -> str:
    value = str(value or "").strip()
    return value[:80] if SAFE_LABEL_RE.fullmatch(value[:80]) else fallback


def _local_event(row: Any) -> LocalTraceEvent | None:
    """Keep only explicitly safe, bounded provenance fields."""

    if not isinstance(row, dict) or any(SECRET_KEY_RE.search(str(key)) for key in row):
        return None
    peer_did = str(row.get("peer_did", ""))
    if not peer_did.startswith("did:key:"):
        peer_did = ""
    return LocalTraceEvent(
        ts=str(row.get("ts", row.get("timestamp", "")))[:64],
        event=_safe_label(row.get("event"), "unknown"),
        agent=_safe_label(row.get("agent"), "unknown"),
        role=_safe_label(row.get("role")),
        message_type=_safe_label(row.get("message_type", row.get("type", row.get("kind", "")))),
        task_id=_safe_label(row.get("task_id", row.get("workflow_id", ""))) or None,
        peer_id=_sha256(peer_did)[:12] if DID_RE.fullmatch(peer_did) else None,
        outcome=_safe_label(row.get("outcome", row.get("status", "")))[:40],
    )


def _load_local_events(path: str | None) -> tuple[LocalTraceEvent, ...]:
    """Read local provenance into a bounded, metadata-only event list."""

    if not path:
        return ()
    events: list[LocalTraceEvent] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = _local_event(row)
            if event is not None:
                events.append(event)
    return tuple(events[-2000:])


def _with_local_events(snapshot: Snapshot, events: tuple[LocalTraceEvent, ...]) -> Snapshot:
    return Snapshot(
        schema=snapshot.schema,
        observed_at=snapshot.observed_at,
        base_url=snapshot.base_url,
        rooms=snapshot.rooms,
        summary=snapshot.summary,
        local_events=events,
        collection_errors=snapshot.collection_errors,
        local_provenance_events=len(events),
    )


def _svg_text(
    x: int,
    y: int,
    value: Any,
    *,
    size: int = 16,
    color: str = "#F5F7FA",
    weight: int = 400,
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="Inter,Arial,sans-serif" '
        f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>'
    )


def _svg_mono(
    x: int,
    y: int,
    value: Any,
    *,
    size: int = 14,
    color: str = "#00B4D8",
    weight: int = 400,
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="Space Mono,monospace" '
        f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>'
    )


def _svg_rect(
    x: int,
    y: int,
    width: int,
    height: int,
    fill: str = "#151D32",
    stroke: str = "#232A3E",
    radius: int = 4,
) -> str:
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{fill}" stroke="{stroke}" />'


def render_svg(snapshot: Snapshot | dict[str, Any], width: int = 1600, height: int = 900) -> str:
    """Render a deterministic, escaped SVG activity map."""

    if isinstance(snapshot, dict):
        snapshot = snapshot_from_dict(snapshot)
    if width < 800 or height < 500:
        raise ValueError("canvas must be at least 800x500")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<title>Technocore Agent Trace</title>",
        "<desc>Read-only visual snapshot of public Technocore rooms and signed agent activity.</desc>",
        '<rect width="100%" height="100%" fill="#0A1128" />',
    ]
    for x in range(40, width, 40):
        parts.append(f'<path d="M{x} 0V{height}" stroke="#151D32" stroke-width="1" />')
    for y in range(40, height, 40):
        parts.append(f'<path d="M0 {y}H{width}" stroke="#151D32" stroke-width="1" />')

    parts.extend(
        [
            _svg_mono(64, 62, "TECHNOCORE // AGENT TRACE", size=28, weight=700, color="#00B4D8"),
            _svg_text(
                64,
                94,
                "Identity → signed activity → coordination → public evidence",
                size=18,
                color="#F5F7FA",
            ),
            _svg_mono(
                width - 64,
                58,
                "PARTIAL READ-ONLY SNAPSHOT"
                if snapshot.collection_errors
                else "READ-ONLY SNAPSHOT",
                size=12,
                color="#0466C8" if snapshot.collection_errors else "#32D74B",
                anchor="end",
            ),
            _svg_mono(
                width - 64,
                82,
                f"OBSERVED {snapshot.observed_at}",
                size=11,
                color="#A1A7AE",
                anchor="end",
            ),
            _svg_mono(
                width - 64,
                104,
                "NO MESSAGE BODY RE-PUBLISHED",
                size=11,
                color="#A1A7AE",
                anchor="end",
            ),
        ]
    )

    left_x, center_x, right_x = 64, 570, 1074
    top_y, row_h = 148, 72
    parts.append(_svg_mono(left_x, 132, "AGENTS OBSERVED", size=12, color="#A1A7AE"))
    parts.append(_svg_mono(center_x, 132, "PUBLIC ROOMS", size=12, color="#A1A7AE"))
    parts.append(_svg_mono(right_x, 132, "TRACE SIGNALS", size=12, color="#A1A7AE"))

    authors: dict[str, dict[str, Any]] = {}
    for room in snapshot.rooms:
        for message in room.messages:
            item = authors.setdefault(
                message.author_id,
                {
                    "id": message.author_id,
                    "label": message.author,
                    "messages": 0,
                    "signed": 0,
                    "rooms": set(),
                },
            )
            item["messages"] += 1
            item["signed"] += int(message.signed)
            item["rooms"].add(room.name)
    for event in snapshot.local_events:
        agent_label = event.agent + (f" · {event.role}" if event.role else "")
        author_id = f"local:{event.agent}"
        item = authors.setdefault(
            author_id,
            {
                "id": author_id,
                "label": agent_label,
                "messages": 0,
                "signed": 0,
                "rooms": set(),
            },
        )
        item["messages"] += 1
        item["signed"] += int(event.message_type in A2A_TYPES)
        item["rooms"].add("local-ledger")
    author_rows = sorted(authors.values(), key=lambda item: (-item["messages"], item["label"]))[:6]
    room_rows = sorted(snapshot.rooms, key=lambda room: (-room.message_count, room.name))[:6]

    for index, author in enumerate(author_rows):
        y = top_y + index * row_h
        parts.append(_svg_rect(left_x, y, 430, 52))
        parts.append(_svg_mono(left_x + 16, y + 23, author["label"], size=14, color="#F5F7FA"))
        status = f"{author['signed']} signed / {author['messages']} msgs"
        parts.append(_svg_text(left_x + 16, y + 43, status, size=12, color="#A1A7AE"))
        parts.append(
            _svg_rect(
                left_x + 356,
                y + 15,
                58,
                22,
                fill="#123F2A" if author["signed"] else "#232A3E",
                stroke="#32D74B" if author["signed"] else "#5C6670",
                radius=999,
            )
        )
        parts.append(
            _svg_mono(
                left_x + 385,
                y + 31,
                "DID" if author["signed"] else "NICK",
                size=10,
                color="#32D74B" if author["signed"] else "#A1A7AE",
                anchor="middle",
            )
        )

    for index, room in enumerate(room_rows):
        y = top_y + index * row_h
        parts.append(_svg_rect(center_x, y, 420, 52, fill="#151D32", stroke="#0466C8"))
        parts.append(_svg_mono(center_x + 16, y + 23, f"/r/{room.name}", size=14, color="#00B4D8"))
        parts.append(
            _svg_text(
                center_x + 16,
                y + 43,
                f"{room.message_count} observed messages · last seq {room.last_seq if room.last_seq is not None else '—'}",
                size=12,
                color="#A1A7AE",
            )
        )
        for author in author_rows:
            if any(message.author_id == author["id"] for message in room.messages):
                parts.append(
                    f'<path d="M494 {y + 26}H{center_x}" stroke="#0466C8" stroke-width="1" />'
                )

    summary = snapshot.summary
    signal_cards = [
        ("DID IDENTITY", f"{summary.get('did_writers', 0)} writers", "#00B4D8"),
        ("SIGNED ACTIVITY", f"{summary.get('signed_messages', 0)} records", "#32D74B"),
        ("PUBLIC A2A", f"{summary.get('a2a_messages', 0)} envelopes", "#0466C8"),
        (
            "PUBLIC SURFACE",
            f"{summary.get('rooms_observed', 0)} rooms / {summary.get('messages_observed', 0)} msgs",
            "#A1A7AE",
        ),
        ("LOCAL A2A LEDGER", f"{snapshot.local_provenance_events} safe events", "#00B4D8"),
    ]
    for index, (label, value, accent) in enumerate(signal_cards):
        y = top_y + index * 72
        parts.append(_svg_rect(right_x, y, 462, 52, fill="#151D32", stroke=accent))
        parts.append(_svg_mono(right_x + 16, y + 21, label, size=12, color=accent, weight=700))
        parts.append(_svg_text(right_x + 16, y + 41, value, size=14, color="#F5F7FA"))

    flow_y = height - 204
    parts.append(_svg_mono(64, flow_y, "THE PARTICIPATION TRACE", size=12, color="#A1A7AE"))
    flow = ["CREATE DID", "SIGN", "COLLABORATE", "VERIFY", "CONTRIBUTE"]
    flow_x = [64, 344, 624, 904, 1184]
    for index, label in enumerate(flow):
        x = flow_x[index]
        parts.append(
            _svg_rect(
                x,
                flow_y + 24,
                220,
                58,
                fill="#151D32",
                stroke="#00B4D8" if index < 4 else "#32D74B",
            )
        )
        parts.append(
            _svg_mono(
                x + 16, flow_y + 49, f"0{index + 1}  {label}", size=13, color="#F5F7FA", weight=700
            )
        )
        if index < len(flow) - 1:
            parts.append(
                f'<path d="M{x + 220} {flow_y + 53}H{flow_x[index + 1]}" stroke="#00B4D8" stroke-width="2" marker-end="url(#arrow)" />'
            )

    callout_y = height - 94
    parts.append(_svg_rect(64, callout_y, width - 128, 48, fill="#151D32", stroke="#232A3E"))
    parts.append(
        _svg_mono(84, callout_y + 21, "PROOF ≠ REPUTATION", size=12, color="#32D74B", weight=700)
    )
    parts.append(
        _svg_text(
            300,
            callout_y + 21,
            "A signature proves control of a key — not identity, honesty, or quality.",
            size=14,
            color="#F5F7FA",
        )
    )
    parts.append(
        _svg_mono(
            width - 84,
            callout_y + 21,
            f"LOCAL PROVENANCE {snapshot.local_provenance_events}",
            size=11,
            color="#A1A7AE",
            anchor="end",
        )
    )

    defs = '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="#00B4D8" /></marker></defs>'
    parts.insert(1, defs)
    parts.append("</svg>")
    return "".join(parts)


def snapshot_from_dict(data: dict[str, Any]) -> Snapshot:
    rooms: list[TraceRoom] = []
    for raw_room in data.get("rooms", []):
        if not isinstance(raw_room, dict):
            continue
        messages: list[TraceMessage] = []
        for raw_message in raw_room.get("messages", []):
            if not isinstance(raw_message, dict):
                continue
            messages.append(TraceMessage(**raw_message))
        rooms.append(
            TraceRoom(
                name=str(raw_room.get("name", "unknown")),
                message_count=int(raw_room.get("message_count", len(messages))),
                last_seq=_int_or_none(raw_room.get("last_seq")),
                messages=tuple(messages),
            )
        )
    return Snapshot(
        schema=str(data.get("schema", "technocore-atlas/v1")),
        observed_at=str(data.get("observed_at", "unknown")),
        base_url=str(data.get("base_url", "")),
        rooms=tuple(rooms),
        summary={str(key): int(value) for key, value in dict(data.get("summary", {})).items()},
        local_events=tuple(
            LocalTraceEvent(**event)
            for event in data.get("local_events", [])
            if isinstance(event, dict)
        ),
        collection_errors=int(data.get("collection_errors", 0)),
        local_provenance_events=int(data.get("local_provenance_events", 0)),
    )


def _write_json(path: str, payload: dict[str, Any]) -> None:
    output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path == "-":
        sys.stdout.write(output)
        return
    Path(path).write_text(output, encoding="utf-8")


def _write_text(path: str, value: str) -> None:
    if path == "-":
        sys.stdout.write(value)
        return
    Path(path).write_text(value, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="collect a bounded public snapshot")
    collect.add_argument("--base", default="https://technocore.chat")
    collect.add_argument("--room-limit", type=int, default=12)
    collect.add_argument("--messages-per-room", type=int, default=100)
    collect.add_argument("--timeout", type=float, default=10.0)
    collect.add_argument(
        "--room", action="append", default=[], help="observe only this public room; repeatable"
    )
    collect.add_argument(
        "--ledger",
        help="optional local provenance JSONL; only safe metadata summaries are retained",
    )
    collect.add_argument("--output", default="atlas.json")

    render = subparsers.add_parser("render", help="render a snapshot as SVG")
    render.add_argument("--input", required=True)
    render.add_argument("--output", default="atlas.svg")
    render.add_argument("--width", type=int, default=1600)
    render.add_argument("--height", type=int, default=900)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "collect":
            snapshot = collect_snapshot(
                args.base,
                room_limit=args.room_limit,
                messages_per_room=args.messages_per_room,
                timeout=args.timeout,
                selected_rooms=tuple(args.room),
            )
            _write_json(
                args.output,
                _with_local_events(snapshot, _load_local_events(args.ledger)).to_dict(),
            )
        else:
            snapshot = snapshot_from_dict(json.loads(Path(args.input).read_text(encoding="utf-8")))
            _write_text(args.output, render_svg(snapshot, width=args.width, height=args.height))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"atlas error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
