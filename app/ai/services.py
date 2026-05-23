"""منطق هوش مصنوعی وینور — هسته DeepSeek."""
from __future__ import annotations

import os
from typing import Any

import requests
from flask import current_app

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    VINOR_AI_SYSTEM_PROMPT,
)

_MAX_HISTORY = 20
_MAX_MSG_CHARS = 4000


def ai_config() -> dict[str, Any]:
    return {
        "enabled": os.environ.get("VINOR_AI_ENABLED", "1").lower() not in ("0", "false", "no"),
        "provider": "deepseek",
        "model": os.environ.get("VINOR_AI_MODEL") or DEEPSEEK_MODEL,
        "api_key_set": bool((DEEPSEEK_API_KEY or "").strip()),
    }


def _build_messages(text: str, history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": VINOR_AI_SYSTEM_PROMPT},
    ]
    if history:
        for item in history[-_MAX_HISTORY:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()[:_MAX_MSG_CHARS]
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text[:_MAX_MSG_CHARS]})
    return messages


def _call_deepseek(messages: list[dict[str, str]]) -> dict[str, Any]:
    cfg = ai_config()
    model = cfg["model"]
    url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": 2048,
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=90)
    except requests.RequestException as exc:
        try:
            current_app.logger.error("DeepSeek request failed: %s", exc)
        except Exception:
            pass
        return {"ok": False, "error": "اتصال به سرویس هوش مصنوعی برقرار نشد. لطفاً دوباره تلاش کنید."}

    content_type = (resp.headers.get("content-type") or "").lower()
    body: Any
    if content_type.startswith("application/json"):
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:500]}
    else:
        body = {"raw": resp.text[:500]}

    if not (200 <= resp.status_code < 300):
        err_msg = "خطا در دریافت پاسخ از DeepSeek."
        if isinstance(body, dict):
            err_msg = (
                str(body.get("error", {}).get("message") or body.get("message") or err_msg)
                if isinstance(body.get("error"), dict)
                else str(body.get("message") or err_msg)
            )
        try:
            current_app.logger.error(
                "DeepSeek API error | status=%s | body=%s",
                resp.status_code,
                body,
            )
        except Exception:
            pass
        return {"ok": False, "error": err_msg}

    reply = ""
    if isinstance(body, dict):
        choices = body.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            if isinstance(msg, dict):
                reply = str(msg.get("content") or "").strip()

    if not reply:
        return {"ok": False, "error": "پاسخی از مدل دریافت نشد."}

    usage = body.get("usage") if isinstance(body, dict) else None
    return {
        "ok": True,
        "reply": reply,
        "meta": {
            "provider": "deepseek",
            "model": model,
            "usage": usage,
        },
    }


def generate_reply(message: str, *, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    text = (message or "").strip()
    if not text:
        return {"ok": False, "error": "پیام خالی است."}

    cfg = ai_config()
    if not cfg["enabled"]:
        return {"ok": False, "error": "سرویس هوش مصنوعی موقتاً غیرفعال است."}
    if not cfg["api_key_set"]:
        return {"ok": False, "error": "کلید API تنظیم نشده است."}

    messages = _build_messages(text, history)
    return _call_deepseek(messages)
