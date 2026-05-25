"""منطق هوش مصنوعی وینور — هسته DeepSeek."""
from __future__ import annotations

import os
import re
from typing import Any

import requests
from flask import current_app

from .audience import AUDIENCE_PARTNER, AUDIENCE_PUBLIC
from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ESCALATE_MARKER_RE,
    VINOR_AI_PARTNER_PROMPT,
    VINOR_AI_PUBLIC_PROMPT,
)
from .context import append_admin_answers_block, build_partner_context, build_public_context
from .context_cache import get_partner_context, get_public_context
from .credits import apply_credit_guard, budget_config, record_api_call, store_cached_reply
from .escalations import consume_pending_answers, create_escalation
from .land_cards import collect_land_codes, land_cards_payload


def ai_config() -> dict[str, Any]:
    return {
        "enabled": os.environ.get("VINOR_AI_ENABLED", "1").lower() not in ("0", "false", "no"),
        "provider": "deepseek",
        "model": os.environ.get("VINOR_AI_MODEL") or DEEPSEEK_MODEL,
        "api_key_set": bool((DEEPSEEK_API_KEY or "").strip()),
    }


def _friendly_deepseek_error(status: int, body: Any) -> str:
    """پیام خطای قابل‌فهم برای کاربر."""
    raw = ""
    code = ""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            raw = str(err.get("message") or "").strip()
            code = str(err.get("code") or "").strip()
        raw = raw or str(body.get("message") or "").strip()

    blob = f"{raw} {code}".lower()
    if status == 402 or "insufficientbalance" in blob:
        return (
            "اعتبار API هوش مصنوعی (DeepSeek) کافی نیست. "
            "لطفاً حساب DeepSeek را شارژ کنید یا با پشتیبانی وینور تماس بگیرید."
        )
    if status == 401:
        return "کلید API هوش مصنوعی نامعتبر است. لطفاً با پشتیبانی وینور تماس بگیرید."
    if status == 429:
        return "درخواست‌های زیاد به سرویس AI. لطفاً چند لحظه بعد دوباره تلاش کنید."
    if raw:
        return f"خطا در سرویس هوش مصنوعی: {raw}"
    return "خطا در دریافت پاسخ از سرویس هوش مصنوعی. لطفاً دوباره تلاش کنید."


def _strip_escalate_marker(text: str) -> tuple[str, str | None]:
    if not text:
        return "", None
    m = re.search(ESCALATE_MARKER_RE, text, flags=re.DOTALL)
    if not m:
        return text.strip(), None
    summary = (m.group(1) or "").strip() or None
    cleaned = re.sub(ESCALATE_MARKER_RE, "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, summary


def _build_system_prompt(
    user_key: str | None,
    audience: str | None = None,
) -> str:
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    base = VINOR_AI_PARTNER_PROMPT if aud == AUDIENCE_PARTNER else VINOR_AI_PUBLIC_PROMPT
    if not user_key:
        return base
    cfg = budget_config()
    max_ctx = cfg["max_context_chars"]
    try:
        if aud == AUDIENCE_PARTNER:
            ctx = get_partner_context(
                user_key,
                lambda: build_partner_context(user_key),
            )[:max_ctx]
        else:
            ctx = get_public_context(build_public_context)[:max_ctx]
        notes = consume_pending_answers(user_key, audience=aud)
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
    user_key: str | None = None,
    audience: str | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt(user_key, audience)},
    ]
    cfg = budget_config()
    max_hist = cfg["max_history"]
    max_msg = cfg["max_msg_chars"]
    if history:
        for item in history[-max_hist:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()[:max_msg]
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text[:max_msg]})
    return messages


def _call_deepseek(messages: list[dict[str, str]]) -> dict[str, Any]:
    cfg = ai_config()
    model = cfg["model"]
    url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    cfg = budget_config()
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": cfg["max_tokens"],
        "temperature": cfg["temperature"],
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
        err_msg = _friendly_deepseek_error(resp.status_code, body)
        try:
            current_app.logger.error(
                "DeepSeek API error | status=%s | body=%s",
                resp.status_code,
                body,
            )
        except Exception:
            pass
        return {"ok": False, "error": err_msg, "error_code": "deepseek_api"}

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
    user_key: str | None = None,
    phone: str | None = None,
    audience: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """phone برای سازگاری قدیمی؛ user_key و audience اولویت دارند."""
    key = (user_key or phone or "").strip()
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER

    text = (message or "").strip()
    if not text:
        return {"ok": False, "error": "پیام خالی است."}

    cfg = ai_config()
    if not cfg["enabled"]:
        return {"ok": False, "error": "سرویس هوش مصنوعی موقتاً غیرفعال است."}
    if not cfg["api_key_set"]:
        return {"ok": False, "error": "کلید API تنظیم نشده است."}

    guard = apply_credit_guard(key, aud, text)
    if guard is not None:
        if guard.get("ok") and guard.get("land_codes"):
            guard["land_cards"] = land_cards_payload(
                key, guard["land_codes"], audience=aud
            )
        return guard

    messages = _build_messages(text, history, user_key=key, audience=aud)
    result = _call_deepseek(messages)
    if not result.get("ok"):
        return result

    record_api_call(key, aud)

    raw_reply = result.get("reply") or ""
    reply, escalate_q = _strip_escalate_marker(raw_reply)
    reply, land_codes = collect_land_codes(
        reply, user_text=text, phone=key, audience=aud
    )
    escalated = False
    escalation_id = ""

    if escalate_q is not None:
        esc = create_escalation(
            user_key=key,
            audience=aud,
            question=escalate_q or text[:200],
            user_message=text,
            thread_id=thread_id,
        )
        if esc.get("ok"):
            escalated = True
            escalation_id = str(esc.get("id") or "")
        else:
            try:
                current_app.logger.warning(
                    "AI escalation not saved | user=%s | err=%s",
                    key,
                    esc.get("error"),
                )
            except Exception:
                pass
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
    result["audience"] = aud
    result["escalated"] = escalated
    if escalation_id:
        result["escalation_id"] = escalation_id
    if land_codes:
        result["land_codes"] = land_codes
        result["land_cards"] = land_cards_payload(key, land_codes, audience=aud)

    store_cached_reply(key, aud, text, result)
    return result
