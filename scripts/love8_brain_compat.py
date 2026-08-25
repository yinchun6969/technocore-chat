#!/usr/bin/env python3
"""Compatibility layer for Love8 Brain v2.2.1.

Handles OpenAI-compatible providers/models that return final JSON in
reasoning_content, choices[].text, output_text, or intermittently return an
empty content field. All terminal failures are fail-closed to `observe`.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

VERSION = "2.2.1"


def _join_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("output_text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return ""


def _candidate_texts(raw: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message", {}) if isinstance(first, dict) else {}
        if isinstance(message, dict):
            for key in ("content", "reasoning_content", "reasoning", "analysis"):
                text = _join_content(message.get(key))
                if text:
                    out.append((f"message.{key}", text))
        text = _join_content(first.get("text")) if isinstance(first, dict) else ""
        if text:
            out.append(("choice.text", text))
    for key in ("output_text", "content", "response"):
        text = _join_content(raw.get(key))
        if text:
            out.append((key, text))
    return out


def _extract_with_brain(brain, raw: dict[str, Any]) -> dict[str, Any] | None:
    for source, text in _candidate_texts(raw):
        try:
            result = brain.extract_json(text)
            if isinstance(result, dict):
                result.setdefault("_compat_source", source)
                return result
        except Exception:
            continue
    return None


def _request(url: str, headers: dict[str, str], body: dict[str, Any], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = json.loads(response.read().decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("API returned non-object JSON")
    return raw


def make_chat(brain):
    """Return a drop-in replacement for love8_brain.chat()."""

    def compat_chat(cfg: dict[str, str], user_payload: str, timeout: int = 45) -> dict[str, Any]:
        url = brain.api_endpoint(cfg["BRAIN_API_BASE"])
        token_cap = max(int(cfg.get("BRAIN_MAX_TOKENS", "1800") or 1800), 1200)
        base_body: dict[str, Any] = {
            "model": cfg["BRAIN_MODEL"],
            "messages": [
                {"role": "system", "content": brain.SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            "temperature": float(cfg.get("BRAIN_TEMPERATURE", "0.2")),
            "max_tokens": token_cap,
        }
        headers = {
            "Authorization": "Bearer " + cfg["BRAIN_API_KEY"],
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"love8-brain-compat/{VERSION}",
        }

        raw: dict[str, Any] | None = None
        try:
            raw = _request(url, headers, base_body, timeout)
        except urllib.error.HTTPError as exc:
            # Some compatible endpoints reject max_tokens. Retry without it.
            if exc.code == 400:
                retry_body = dict(base_body)
                retry_body.pop("max_tokens", None)
                raw = _request(url, headers, retry_body, timeout)
            else:
                raise

        parsed = _extract_with_brain(brain, raw)
        if parsed is not None:
            return parsed

        # Reasoning models can spend the whole first completion on hidden/visible
        # reasoning and leave message.content empty. Retry once with a compact
        # final-answer instruction and a larger completion budget.
        retry_messages = [
            {
                "role": "system",
                "content": brain.SYSTEM_PROMPT
                + "\nIMPORTANT: Do not explain your reasoning. Output the requested JSON object immediately and nothing else.",
            },
            {"role": "user", "content": user_payload},
        ]
        retry_body = {
            "model": cfg["BRAIN_MODEL"],
            "messages": retry_messages,
            "temperature": 0.0,
            "max_tokens": max(token_cap, 2200),
        }
        try:
            raw2 = _request(url, headers, retry_body, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                retry_body.pop("max_tokens", None)
                raw2 = _request(url, headers, retry_body, timeout)
            else:
                raise

        parsed = _extract_with_brain(brain, raw2)
        if parsed is not None:
            parsed.setdefault("_compat_retry", True)
            return parsed

        # Fail closed: network/API is alive but provider supplied no usable final
        # answer. Never guess a reply or post to Technocore.
        return {
            "action": "observe",
            "target_index": -1,
            "bot_probability": 50,
            "human_likelihood": 0,
            "scam_risk": 0,
            "conversation_quality": 0,
            "reason": "provider returned no parseable final JSON; fail-closed observe",
            "topics": [],
            "reply": "",
            "memory_summary": "",
            "_compat_empty_fallback": True,
        }

    return compat_chat
