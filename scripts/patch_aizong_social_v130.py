#!/usr/bin/env python3
"""Patch an installed aizong Social v1.2.0 core to v1.3.0 Long-Context 2X."""

from __future__ import annotations

import argparse
from pathlib import Path

TARGET_VERSION = "1.3.0"


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"PATCH_MISMATCH[{label}]: {old[:100]!r}")
    return source.replace(old, new, 1)


def patch_source(source: str) -> str:
    if 'VERSION = "1.3.0"' in source:
        return source
    if 'VERSION = "1.2.0"' not in source:
        raise RuntimeError("expected aizong Social v1.2.0 source")

    replacements = [
        (
            '"""aizong Social v1.2.0: autonomous Technocore relationship intelligence."""',
            '"""aizong Social v1.3.0: long-context Technocore relationship intelligence with 2X social capacity."""',
            "docstring",
        ),
        ('VERSION = "1.2.0"', 'VERSION = "1.3.0"', "version"),
        ('for item in raw[:20]:', 'for item in raw[:40]:', "trusted-topic-capacity"),
        (
            'for item in action.get("messages", [])[-8:]:',
            'for item in action.get("messages", [])[-16:]:',
            "brain-recent-messages",
        ),
        (
            '"summary": str(contact.get("memory", {}).get("summary", ""))[:320],',
            '"summary": str(contact.get("memory", {}).get("summary", ""))[:640],',
            "memory-summary-context",
        ),
        (
            '"capabilities": contact.get("memory", {}).get("capabilities", [])[:6],',
            '"capabilities": contact.get("memory", {}).get("capabilities", [])[:12],',
            "memory-capabilities-context",
        ),
        (
            '"projects": contact.get("memory", {}).get("projects", [])[:6],',
            '"projects": contact.get("memory", {}).get("projects", [])[:12],',
            "memory-projects-context",
        ),
        (
            '"interests": contact.get("memory", {}).get("interests", [])[:6],',
            '"interests": contact.get("memory", {}).get("interests", [])[:12],',
            "memory-interests-context",
        ),
        (
            '"topics": contact.get("memory", {}).get("topics", [])[:8],',
            '"topics": contact.get("memory", {}).get("topics", [])[:16],',
            "memory-topics-context",
        ),
        (
            '"trusted_operator_topics": trusted_topics[:8],',
            '"trusted_operator_topics": trusted_topics[:16],',
            "trusted-topics-context",
        ),
        (
            'max_tokens = min(max(int(brain.get("BRAIN_MAX_TOKENS", "768")), 128), 2048)',
            'max_tokens = min(max(int(brain.get("BRAIN_MAX_TOKENS", "1536")), 256), 4096)',
            "brain-token-budget",
        ),
        (
            '"summary": _single_line(str(memory.get("summary", "")), 320),',
            '"summary": _single_line(str(memory.get("summary", "")), 640),',
            "memory-summary-output",
        ),
        (
            '"capabilities": _clean_list(memory.get("capabilities"), limit=6),',
            '"capabilities": _clean_list(memory.get("capabilities"), limit=12),',
            "memory-capabilities-output",
        ),
        (
            '"projects": _clean_list(memory.get("projects"), limit=6),',
            '"projects": _clean_list(memory.get("projects"), limit=12),',
            "memory-projects-output",
        ),
        (
            '"interests": _clean_list(memory.get("interests"), limit=6),',
            '"interests": _clean_list(memory.get("interests"), limit=12),',
            "memory-interests-output",
        ),
        (
            '"topics": _clean_list(memory.get("topics"), limit=8),',
            '"topics": _clean_list(memory.get("topics"), limit=16),',
            "memory-topics-output",
        ),
        (
            'current.get("capabilities"), memory.get("capabilities"), limit=8',
            'current.get("capabilities"), memory.get("capabilities"), limit=16',
            "memory-capabilities-store",
        ),
        (
            'current["projects"] = _merge_list(current.get("projects"), memory.get("projects"), limit=8)',
            'current["projects"] = _merge_list(current.get("projects"), memory.get("projects"), limit=16)',
            "memory-projects-store",
        ),
        (
            'current.get("interests"), memory.get("interests"), limit=8',
            'current.get("interests"), memory.get("interests"), limit=16',
            "memory-interests-store",
        ),
        (
            'current["topics"] = _merge_list(current.get("topics"), memory.get("topics"), limit=12)',
            'current["topics"] = _merge_list(current.get("topics"), memory.get("topics"), limit=24)',
            "memory-topics-store",
        ),
        (
            '    *,\n    max_followups: int,\n    reply_cooldown: int,\n) -> dict[str, Any] | None:\n    data = http_json(f"{base}/r/{room}?format=json&limit=20")',
            '    *,\n    message_limit: int,\n    max_followups: int,\n    reply_cooldown: int,\n) -> dict[str, Any] | None:\n    data = http_json(f"{base}/r/{room}?format=json&limit={message_limit}")',
            "room-message-limit",
        ),
        (
            '                own_ids,\n                max_followups=args.max_followups,',
            '                own_ids,\n                message_limit=args.message_limit,\n                max_followups=args.max_followups,',
            "room-message-call",
        ),
        (
            'parser.add_argument("--rooms", type=int, default=int(os.getenv("TC_SOCIAL_ROOMS", "5")))\n    parser.add_argument(\n        "--hourly-writes",',
            'parser.add_argument("--rooms", type=int, default=int(os.getenv("TC_SOCIAL_ROOMS", "10")))\n    parser.add_argument(\n        "--message-limit",\n        type=int,\n        default=int(os.getenv("TC_SOCIAL_ROOM_MESSAGE_LIMIT", "40")),\n    )\n    parser.add_argument(\n        "--hourly-writes",',
            "parser-message-limit",
        ),
        (
            'default=int(os.getenv("TC_SOCIAL_HOURLY_WRITES", "3")),',
            'default=int(os.getenv("TC_SOCIAL_HOURLY_WRITES", "6")),',
            "hourly-default",
        ),
        (
            'default=int(os.getenv("TC_SOCIAL_DAILY_WRITES", "12")),',
            'default=int(os.getenv("TC_SOCIAL_DAILY_WRITES", "24")),',
            "daily-default",
        ),
        (
            'default=int(os.getenv("TC_SOCIAL_MAX_FOLLOWUPS", "6")),',
            'default=int(os.getenv("TC_SOCIAL_MAX_FOLLOWUPS", "12")),',
            "followup-default",
        ),
        (
            '    args.rooms = min(max(args.rooms, 1), 10)\n    args.hourly_writes = min(max(args.hourly_writes, 1), 6)\n    args.daily_writes = min(max(args.daily_writes, 1), 24)\n    args.max_followups = min(max(args.max_followups, 1), 12)',
            '    args.rooms = min(max(args.rooms, 1), 20)\n    args.message_limit = min(max(args.message_limit, 10), 80)\n    args.hourly_writes = min(max(args.hourly_writes, 1), 12)\n    args.daily_writes = min(max(args.daily_writes, 1), 48)\n    args.max_followups = min(max(args.max_followups, 1), 24)',
            "runtime-caps",
        ),
        (
            'f"aizong Social v{VERSION} started interval={args.interval}s rooms={args.rooms} "\n        f"writes={args.hourly_writes}/h,{args.daily_writes}/day reconnect={args.reconnect_after}s"',
            'f"aizong Social v{VERSION} started interval={args.interval}s rooms={args.rooms} "\n        f"msgs={args.message_limit}/room writes={args.hourly_writes}/h,{args.daily_writes}/day "\n        f"reconnect={args.reconnect_after}s"',
            "startup-log",
        ),
    ]

    for old, new, label in replacements:
        source = _replace_once(source, old, new, label)

    context_old = '''        "recent_public_messages": messages,\n    }\n    timeout = min(max(int(brain.get("BRAIN_TIMEOUT", "25")), 5), 60)'''
    context_new = '''        "recent_public_messages": messages,\n    }\n    user_content = json.dumps(user_context, ensure_ascii=False)\n    context_cap = min(\n        max(int(brain.get("BRAIN_CONTEXT_MAX_CHARS", "60000")), 12000), 120000\n    )\n    while len(user_content) > context_cap and len(messages) > 4:\n        messages.pop(0)\n        user_context["recent_public_messages"] = messages\n        user_content = json.dumps(user_context, ensure_ascii=False)\n    if len(user_content) > context_cap:\n        user_content = user_content[:context_cap]\n    timeout = min(max(int(brain.get("BRAIN_TIMEOUT", "25")), 5), 60)'''
    source = _replace_once(source, context_old, context_new, "context-ceiling")
    source = _replace_once(
        source,
        '{"role": "user", "content": json.dumps(user_context, ensure_ascii=False)},',
        '{"role": "user", "content": user_content},',
        "context-payload",
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
    print(f"aizong v{TARGET_VERSION} patch {'applied' if changed else 'already present'}: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
