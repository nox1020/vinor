"""منطق هوش مصنوعی وینور — هسته DeepSeek."""
from __future__ import annotations

import os
import re
from typing import Any

import requests
from flask import current_app

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ESCALATE_MARKER_RE,
    VINOR_AI_SYSTEM_PROMPT,
)
from .context import append_admin_answers_block, build_partner_context
from .escalations import consume_pending_answers, create_escalation
from .land_cards import collect_land_codes, land_cards_payload

_MAX_HISTORY = 20
_MAX_MSG_CHARS = 4000
_MAX_CONTEXT_CHARS = 14000


def ai_config() -> dict[str, Any]:
    return {
        "enabled": os.environ.get("VINOR_AI_ENABLED", "1").lower() not in ("0", "false", "no"),
        "provider": "deepseek",
        "model": os.environ.get("VINOR_AI_MODEL") or DEEPSEEK_MODEL,
        "api_key_set": bool((DEEPSEEK_API_KEY or "").strip()),
    }


def _strip_escalate_marker(text: str) -> tuple[str, str | None]:
    """حذف مارکر از پاسخ؛ برگرداندن خلاصه سوال برای ارجاع."""
    if not text:
        return "", None
    m = re.search(ESCALATE_MARKER_RE, text, flags=re.DOTALL)
    if not m:
        return text.strip(), None
    summary = (m.group(1) or "").strip() or None
    cleaned = re.sub(ESCALATE_MARKER_RE, "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, summary


def _build_system_prompt(phone: str | None) -> str:
    base = VINOR_AI_SYSTEM_PROMPT
    if not phone:
        return base
    try:
        ctx = build_partner_context(phone)[:_MAX_CONTEXT_CHARS]
        notes = consume_pending_answers(phone)
        ctx = append_admin_answers_block(ctx, notes)
        return f"{base}\n\n{ctx}"
    except Exception as exc:
        try:
            current_app.logger.warning("AI context build failed: %s", exc)
        except Exception:
            pass
        return base


def _build_messages(
    text: str,
    history: list[dict[str, str]] | None,
    *,
    phone: str | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt(phone)},
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
        "temperature": 0.55,
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


def generate_reply(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    phone: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    text = (message or "").strip()
    if not text:
        return {"ok": False, "error": "پیام خالی است."}

    cfg = ai_config()
    if not cfg["enabled"]:
        return {"ok": False, "error": "سرویس هوش مصنوعی موقتاً غیرفعال است."}
    if not cfg["api_key_set"]:
        return {"ok": False, "error": "کلید API تنظیم نشده است."}

    messages = _build_messages(text, history, phone=phone)
    result = _call_deepseek(messages)
    if not result.get("ok"):
        return result

    raw_reply = result.get("reply") or ""
    reply, escalate_q = _strip_escalate_marker(raw_reply)
    reply, land_codes = collect_land_codes(reply, user_text=text, phone=phone or "")
    escalated = False
    escalation_id = ""

    if escalate_q is not None:
        esc = create_escalation(
            partner_phone=phone or "",
            question=escalate_q or text[:200],
            user_message=text,
            thread_id=thread_id,
        )
        if esc.get("ok"):
            escalated = True
            escalation_id = str(esc.get("id") or "")
        if not reply or len(reply) < 20:
            reply = (
                "سوال شما را برای تیم وینور ثبت کردم. "
                "به‌محض دریافت پاسخ از پشتیبانی، در همین گفتگو به شما اطلاع می‌دهم."
            )
        elif "ثبت" not in reply and "تیم" not in reply:
            reply = (
                reply.rstrip()
                + "\n\nسوال شما برای تیم وینور ثبت شد؛ به‌زودی در همین چت پاسخ می‌گیرید."
            )

    result["reply"] = reply
    result["escalated"] = escalated
    if escalation_id:
        result["escalation_id"] = escalation_id
    if land_codes:
        result["land_codes"] = land_codes
        result["land_cards"] = land_cards_payload(phone or "", land_codes)
    return result
