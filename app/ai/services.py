"""منطق هوش مصنوعی وینور — آفلاین + DeepSeek در شرایط خاص."""
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
from .credits import (
    apply_credit_guard,
    budget_config,
    clear_api_balance_depleted,
    mark_api_balance_depleted,
    record_api_call,
    store_cached_reply,
)
from .escalations import consume_pending_answers, create_escalation
from .land_cards import collect_land_codes, land_cards_payload
from .offline_config import offline_runtime_config
from .offline_engine import call_offline_chat, offline_available, offline_status
from .provider_router import (
    allow_api_fallback_after_offline_fail,
    allow_offline_fallback_after_api_fail,
    provider_mode,
    route_info,
    should_use_deepseek,
)


def ai_config() -> dict[str, Any]:
    mode = provider_mode()
    off = offline_status()
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("VINOR_DEEPSEEK_API_KEY") or DEEPSEEK_API_KEY or "").strip()
    return {
        "enabled": os.environ.get("VINOR_AI_ENABLED", "1").lower() not in ("0", "false", "no"),
        "provider_mode": mode,
        "provider": "offline" if mode == "offline" or (mode == "auto" and off.get("available")) else "deepseek",
        "model": os.environ.get("VINOR_AI_MODEL") or DEEPSEEK_MODEL,
        "api_key_set": bool(api_key),
        "offline": off,
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
            "در حال استفاده از مدل آفلاین محلی هستیم؛ برای سوالات پیچیده پس از شارژ حساب دوباره تلاش کنید."
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
    *,
    compact: bool = False,
) -> str:
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    base = VINOR_AI_PARTNER_PROMPT if aud == AUDIENCE_PARTNER else VINOR_AI_PUBLIC_PROMPT
    if not user_key:
        return base
    if compact:
        max_ctx = offline_runtime_config()["context_chars"]
    else:
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
    compact: bool = False,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": _build_system_prompt(user_key, audience, compact=compact),
        },
    ]
    if compact:
        oc = offline_runtime_config()
        max_hist = oc["history"]
        max_msg = min(budget_config()["max_msg_chars"], 2000)
    else:
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
    bcfg = budget_config()
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("VINOR_DEEPSEEK_API_KEY") or DEEPSEEK_API_KEY or "").strip()
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
        out: dict[str, Any] = {
            "ok": False,
            "error": err_msg,
            "error_code": "deepseek_api",
            "http_status": resp.status_code,
        }
        if resp.status_code == 402:
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


def _invoke_model(
    messages: list[dict[str, str]],
    *,
    use_api: bool,
    route_reason: str,
) -> dict[str, Any]:
    cfg = ai_config()

    if use_api and cfg["api_key_set"]:
        result = _call_deepseek(messages)
        if result.get("ok"):
            return result
        if (
            allow_offline_fallback_after_api_fail()
            and offline_available()
            and (
                result.get("balance_depleted")
                or result.get("error_code") == "deepseek_api"
            )
        ):
            try:
                current_app.logger.info(
                    "AI fallback offline after API fail | reason=%s",
                    route_reason,
                )
            except Exception:
                pass
            off = call_offline_chat(messages)
            if off.get("ok"):
                meta = off.get("meta") or {}
                meta["fallback_from"] = "deepseek"
                meta["route_reason"] = route_reason
                off["meta"] = meta
                return off
        return result

    if offline_available():
        off = call_offline_chat(messages)
        if off.get("ok"):
            meta = off.get("meta") or {}
            meta["route_reason"] = route_reason
            off["meta"] = meta
            return off
        if allow_api_fallback_after_offline_fail() and cfg["api_key_set"]:
            try:
                current_app.logger.info(
                    "AI fallback API after offline fail | reason=%s",
                    route_reason,
                )
            except Exception:
                pass
            return _call_deepseek(messages)
        return off

    if cfg["api_key_set"]:
        return _call_deepseek(messages)

    return {
        "ok": False,
        "error": (
            "مدل آفلاین نصب نشده است. "
            "دستور: pip install -r requirements-offline.txt "
            "سپس python scripts/download_offline_ai_model.py"
        ),
    }


def _finalize_reply(
    result: dict[str, Any],
    *,
    text: str,
    user_key: str,
    audience: str,
    thread_id: str | None,
) -> dict[str, Any]:
    if not result.get("ok"):
        return result

    raw_reply = result.get("reply") or ""
    reply, escalate_q = _strip_escalate_marker(raw_reply)
    reply, land_codes = collect_land_codes(
        reply, user_text=text, phone=user_key, audience=audience
    )
    escalated = False
    escalation_id = ""

    if escalate_q is not None:
        esc = create_escalation(
            user_key=user_key,
            audience=audience,
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
                    user_key,
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
    result["audience"] = audience
    result["escalated"] = escalated
    if escalation_id:
        result["escalation_id"] = escalation_id
    if land_codes:
        result["land_codes"] = land_codes
        result["land_cards"] = land_cards_payload(user_key, land_codes, audience=audience)
    return result


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

    if not cfg["api_key_set"] and not offline_available():
        return {
            "ok": False,
            "error": (
                "هیچ مدل AI فعال نیست. "
                "کلید DeepSeek را تنظیم کنید یا مدل آفلاین را دانلود کنید "
                "(python scripts/download_offline_ai_model.py)."
            ),
        }

    guard = apply_credit_guard(key, aud, text)
    if guard is not None:
        if guard.get("ok") and guard.get("land_codes"):
            guard["land_cards"] = land_cards_payload(
                key, guard["land_codes"], audience=aud
            )
        return guard

    use_api, route_reason = should_use_deepseek(
        text, history=history, user_key=key, audience=aud
    )
    compact = not use_api
    messages = _build_messages(
        text, history, user_key=key, audience=aud, compact=compact
    )

    result = _invoke_model(messages, use_api=use_api, route_reason=route_reason)
    if not result.get("ok"):
        result["route"] = route_info(use_api, route_reason)
        return result

    meta = result.get("meta") or {}
    meta["route"] = route_info(use_api, route_reason)
    result["meta"] = meta

    provider = (meta.get("provider") or "").lower()
    if provider == "deepseek":
        record_api_call(key, aud)

    result = _finalize_reply(
        result, text=text, user_key=key, audience=aud, thread_id=thread_id
    )
    store_cached_reply(key, aud, text, result)
    return result
