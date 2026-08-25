#!/usr/bin/env python3
"""Compatibility layer for Love8 Brain v2.2.2.

Handles OpenAI-compatible providers/models that return final JSON in
reasoning_content, choices[].text, output_text, or intermittently return an
empty content field. Adds configurable long read timeout and bounded retry.
All terminal failures are fail-closed to `observe`.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any

VERSION = "2.2.2"


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


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        return isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout))
    return False


def _request_retry(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: int,
    retries: int,
) -> dict[str, Any]:
    last: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return _request(url, headers, body, timeout)
        except BaseException as exc:
            if not _is_timeout(exc):
                raise
            last = exc
            if attempt >= retries:
                break
            time.sleep(min(2 ** attempt, 4))
    assert last is not None
    raise last


def _fallback(reason: str, timeout: bool = False) -> dict[str, Any]:
    out = {
        "action": "observe",
        "target_index": -1,
        "bot_probability": 50,
        "human_likelihood": 0,
        "scam_risk": 0,
        "conversation_quality": 0,
        "reason": reason,
        "topics": [],
        "reply": "",
        "memory_summary": "",
    }
    if timeout:
        out["_compat_timeout_fallback"] = True
    else:
        out["_compat_empty_fallback"] = True
    return out


def make_chat(brain):
    """Return a drop-in replacement for love8_brain.chat()."""

    def compat_chat(cfg: dict[str, str], user_payload: str, timeout: int = 45) -> dict[str, Any]:
        url = brain.api_endpoint(cfg["BRAIN_API_BASE"])
        configured_timeout = int(cfg.get("BRAIN_TIMEOUT", "150") or 150)
        effective_timeout = min(max(configured_timeout, timeout, 45), 300)
        retries = min(max(int(cfg.get("BRAIN_RETRIES", "1") or 1), 0), 2)
        token_cap = max(int(cfg.get("BRAIN_MAX_TOKENS", "2200") or 2200), 1200)
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

        try:
            try:
                raw = _request_retry(url, headers, base_body, effective_timeout, retries)
            except urllib.error.HTTPError as exc:
                # Some compatible endpoints reject max_tokens. Retry without it.
                if exc.code == 400:
                    retry_body = dict(base_body)
                    retry_body.pop("max_tokens", None)
                    raw = _request_retry(url, headers, retry_body, effective_timeout, retries)
                else:
                    raise
        except BaseException as exc:
            if _is_timeout(exc):
                return _fallback(
                    f"provider read timeout after {effective_timeout}s; fail-closed observe",
                    timeout=True,
                )
            raise

        parsed = _extract_with_brain(brain, raw)
        if parsed is not None:
            parsed.setdefault("_compat_timeout", effective_timeout)
            return parsed

        # Reasoning models can spend the whole first completion on reasoning and
        # leave message.content empty. Retry once with a compact JSON instruction.
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
            "max_tokens": max(token_cap, 2400),
        }
        try:
            try:
                raw2 = _request_retry(url, headers, retry_body, effective_timeout, retries)
            except urllib.error.HTTPError as exc:
                if exc.code == 400:
                    retry_body.pop("max_tokens", None)
                    raw2 = _request_retry(url, headers, retry_body, effective_timeout, retries)
                else:
                    raise
        except BaseException as exc:
            if _is_timeout(exc):
                return _fallback(
                    f"provider compact retry timed out after {effective_timeout}s; fail-closed observe",
                    timeout=True,
                )
            raise

        parsed = _extract_with_brain(brain, raw2)
        if parsed is not None:
            parsed.setdefault("_compat_retry", True)
            parsed.setdefault("_compat_timeout", effective_timeout)
            return parsed

        return _fallback("provider returned no parseable final JSON; fail-closed observe")

    return compat_chat
