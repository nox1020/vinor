"""منطق هوش مصنوعی وینور — DeepSeek API."""
from __future__ import annotations

import os
import re
from typing import Any

import requests
from flask import current_app

from .audience import AUDIENCE_PARTNER, AUDIENCE_PUBLIC
from .config import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ESCALATE_MARKER_RE,
    VINOR_AI_PARTNER_PROMPT,
    VINOR_AI_PUBLIC_PROMPT,
    get_deepseek_api_key,
)
from .context import append_admin_answers_block, build_partner_context, build_public_context
from .context_cache import get_partner_context, get_public_context
from .credits import (
    apply_credit_guard,
    budget_config,
    clear_api_balance_depleted,
    is_api_balance_depleted,
    mark_api_balance_depleted,
    record_api_call,
    store_cached_reply,
)
from .runtime_settings import get_ai_settings
from .escalations import consume_pending_answers, create_escalation
from .land_cards import collect_land_codes, land_cards_payload
from .provider_router import call_ai


def ai_config() -> dict[str, Any]:
    api_key = get_deepseek_api_key()
    cfg = get_ai_settings()
    return {
        "enabled": bool(cfg.get("enabled")),
        "provider": "deepseek",
        "model": DEEPSEEK_MODEL,
        "api_key_set": bool(api_key),
        "api_balance_ok": not is_api_balance_depleted(),
    }


def _friendly_deepseek_error(status: int, body: Any) -> str:
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
    max_ctx = budget_config()["max_context_chars"]
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
    cfg = budget_config()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt(user_key, audience)},
    ]
    if history:
        for item in history[-cfg["max_history"] :]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()[: cfg["max_msg_chars"]]
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text[: cfg["max_msg_chars"]]})
    return messages


def _call_deepseek(messages: list[dict[str, str]]) -> dict[str, Any]:
    api_key = get_deepseek_api_key()
    if not api_key:
        return {
            "ok": False,
            "error": "کلید API هوش مصنوعی تنظیم نشده است.",
            "error_code": "no_api_key",
        }
    if is_api_balance_depleted():
        return {
            "ok": False,
            "error": "اعتبار API هوش مصنوعی کافی نیست.",
            "error_code": "balance_depleted",
            "balance_depleted": True,
        }

    model = DEEPSEEK_MODEL
    url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    bcfg = budget_config()
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": bcfg["max_tokens"],
        "temperature": bcfg["temperature"],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
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
        return {
            "ok": False,
            "error": "اتصال به سرویس هوش مصنوعی برقرار نشد. لطفاً دوباره تلاش کنید.",
            "error_code": "deepseek_network",
        }

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
        out: dict[str, Any] = {
            "ok": False,
            "error": err_msg,
            "error_code": "deepseek_api",
        }
        if resp.status_code == 402 or "insufficientbalance" in blob:
            mark_api_balance_depleted()
            out["balance_depleted"] = True
        return out

    clear_api_balance_depleted()
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


def _escalation_fallback_reply(
    *,
    user_key: str,
    audience: str,
    user_message: str,
    thread_id: str | None,
    reason: str,
) -> dict[str, Any]:
    """وقتی API در دسترس نیست — ثبت سوال برای ادمین و پیام به کاربر."""
    esc = create_escalation(
        user_key=user_key,
        audience=audience,
        question=user_message[:200],
        user_message=user_message,
        thread_id=thread_id,
    )
    if reason == "balance":
        reply = "به زودی به شما پاسخ خواهم داد."
        if esc.get("ok"):
            return {
                "ok": True,
                "reply": reply,
                "escalated": True,
                "escalation_id": str(esc.get("id") or ""),
                "meta": {"provider": "escalation", "reason": reason},
            }
        return {
            "ok": True,
            "reply": reply,
            "escalated": False,
            "meta": {"provider": "escalation", "reason": reason},
        }

    if reason == "no_key":
        intro = "سرویس هوش مصنوعی هنوز پیکربندی نشده است. "
    else:
        intro = "پاسخ خودکار AI موقتاً در دسترس نیست. "

    if esc.get("ok"):
        reply = (
            intro
            + "سوال شما برای تیم وینور ثبت شد؛ به‌زودی در همین گفتگو پاسخ می‌گیرید."
        )
        out: dict[str, Any] = {
            "ok": True,
            "reply": reply,
            "escalated": True,
            "escalation_id": str(esc.get("id") or ""),
            "meta": {"provider": "escalation", "reason": reason},
        }
    else:
        out = {
            "ok": False,
            "error": intro + "لطفاً بعداً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.",
            "error_code": "api_unavailable",
        }
    return out


def generate_reply(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    user_key: str | None = None,
    phone: str | None = None,
    audience: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    key = (user_key or phone or "").strip()
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER

    text = (message or "").strip()
    if not text:
        return {"ok": False, "error": "پیام خالی است."}

    cfg = ai_config()
    if not cfg["enabled"]:
        return {"ok": False, "error": "سرویس هوش مصنوعی موقتاً غیرفعال است."}

    guard = apply_credit_guard(key, aud, text)
    if guard is not None:
        if guard.get("ok") and guard.get("land_codes"):
            guard["land_cards"] = land_cards_payload(
                key, guard["land_codes"], audience=aud
            )
        return guard

    messages = _build_messages(text, history, user_key=key, audience=aud)
    result = call_ai(messages)
    if not result.get("ok"):
        reason = None
        if result.get("balance_depleted") or is_api_balance_depleted():
            reason = "balance"
        elif not cfg["api_key_set"] or result.get("error_code") == "no_api_key":
            reason = "no_key"
        if reason:
            fallback = _escalation_fallback_reply(
                user_key=key,
                audience=aud,
                user_message=text,
                thread_id=thread_id,
                reason=reason,
            )
            if fallback.get("ok"):
                return fallback
        return result

    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    if meta.get("provider") == "deepseek":
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
