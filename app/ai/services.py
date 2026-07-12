"""منطق هوش مصنوعی وینور — DeepSeek API."""
from __future__ import annotations

import json
import re
from typing import Any

import requests
from flask import current_app

from .agent_tools import (
    agent_system_hint,
    parse_tool_arguments,
    render_agent_actions_html,
    run_tool,
    tools_schema_for_voice,
)
from .audience import (
    AUDIENCE_PARTNER,
    AUDIENCE_PUBLIC,
    resolve_ai_voice,
    voice_label_fa,
)
from .config import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ESCALATE_MARKER_RE,
    get_deepseek_api_key,
    prompt_for_voice,
)
from .context import (
    append_admin_answers_block,
    build_partner_context_base,
    build_partner_land_context,
    build_partner_status_context,
    build_public_context_base,
    build_public_land_context,
)
from .context_cache import get_partner_context_base, get_public_context_base
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

_MAX_TOOL_ROUNDS = 2

LAND_MARKER_RE = re.compile(r"\[\[LAND:[^\]]+\]\]\s*", re.IGNORECASE)


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


def _api_error_blob(body: Any) -> str:
    if not isinstance(body, dict):
        return str(body).lower()
    err = body.get("error")
    if isinstance(err, dict):
        return f"{err.get('message') or ''} {err.get('code') or ''}".lower()
    return str(body).lower()


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


def _strip_listing_dump_when_copy_cards(text: str) -> str:
    """وقتی کارت کپی هست، بلاک کد و تکرار متن آگهی را از پیام حذف کن."""
    raw = (text or "").strip()
    if not raw:
        return ""
    cleaned = re.sub(r"```[\s\S]*?```", "", raw).strip()
    cleaned = re.sub(
        r"(?im)^(?:\*\*)?(?:متن دیوار|کپشن اینستا|متن آگهی(?: دیوار)?|آگهی دیوار)(?:\*\*)?\s*:?\s*$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) < 8:
        return "آماده‌ست — از کارت‌های زیر کپی کن و منتشر کن."
    return cleaned


def _build_system_prompt(
    user_key: str | None,
    audience: str | None = None,
    *,
    user_message: str = "",
) -> str:
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    if not user_key:
        return ""
    max_ctx = budget_config()["max_context_chars"]
    try:
        if aud == AUDIENCE_PARTNER:
            base = get_partner_context_base(
                user_key,
                lambda: build_partner_context_base(user_key),
            )
            status_ctx = build_partner_status_context(user_key)
            land_ctx = build_partner_land_context(user_key, user_message)
            parts = [base]
            if status_ctx:
                parts.append(status_ctx)
            if land_ctx:
                parts.append(land_ctx)
            ctx = "\n".join(parts)
        else:
            base = get_public_context_base(build_public_context_base)
            land_ctx = build_public_land_context(user_message)
            ctx = base
            if land_ctx:
                ctx = f"{base}\n{land_ctx}"
        notes = consume_pending_answers(user_key, audience=aud)
        ctx = append_admin_answers_block(ctx, notes)
        return ctx[:max_ctx]
    except Exception as exc:
        try:
            current_app.logger.warning("AI context build failed: %s", exc)
        except Exception:
            pass
        return ""


def _trim_history_content(role: str, content: str, cfg: dict[str, Any]) -> str:
    text = (content or "").strip()
    if role == "assistant":
        text = LAND_MARKER_RE.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        limit = int(cfg.get("max_assistant_history_chars") or cfg["max_msg_chars"])
    else:
        limit = int(cfg["max_msg_chars"])
    return text[:limit]


def _build_messages(
    text: str,
    history: list[dict[str, str]] | None,
    *,
    user_key: str | None = None,
    audience: str | None = None,
    voice: str | None = None,
    with_tools: bool = False,
) -> list[dict[str, Any]]:
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    cfg = budget_config()
    resolved_voice = voice or resolve_ai_voice(phone=user_key or "", audience=aud)
    base_prompt = prompt_for_voice(resolved_voice)
    messages: list[dict[str, Any]] = [{"role": "system", "content": base_prompt}]
    # یادآوری کوتاه نقش در هر درخواست (کم‌حجم، خارج از کش زمینه)
    messages.append({
        "role": "system",
        "content": f"نقش فعلی مخاطب: {voice_label_fa(resolved_voice)}. لحن و سطح راهنمایی را دقیقاً با این نقش هماهنگ کن.",
    })
    if with_tools:
        messages.append({"role": "system", "content": agent_system_hint(resolved_voice)})
    if user_key:
        ctx = _build_system_prompt(user_key, audience, user_message=text)
        if ctx:
            messages.append({"role": "system", "content": ctx})
    if history:
        for item in history[-cfg["max_history"] :]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = _trim_history_content(role, str(item.get("content") or ""), cfg)
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text[: cfg["max_msg_chars"]]})
    return messages


def _call_deepseek(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": bcfg["max_tokens"],
        "temperature": bcfg["temperature"],
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
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
        blob = _api_error_blob(body)
        depleted = resp.status_code == 402 or "insufficientbalance" in blob
        try:
            if depleted:
                current_app.logger.warning(
                    "DeepSeek balance depleted (402) — API calls paused until recharge"
                )
            else:
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
        if depleted:
            mark_api_balance_depleted()
            out["balance_depleted"] = True
        return out

    clear_api_balance_depleted()
    reply = ""
    tool_calls: list[dict[str, Any]] = []
    if isinstance(body, dict):
        choices = body.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            if isinstance(msg, dict):
                reply = str(msg.get("content") or "").strip()
                raw_calls = msg.get("tool_calls") or []
                if isinstance(raw_calls, list):
                    for tc in raw_calls:
                        if isinstance(tc, dict) and tc.get("id"):
                            tool_calls.append(tc)

    usage = body.get("usage") if isinstance(body, dict) else None
    if isinstance(usage, dict):
        try:
            hit = int(usage.get("prompt_cache_hit_tokens") or 0)
            miss = int(usage.get("prompt_cache_miss_tokens") or 0)
            prompt_tok = usage.get("prompt_tokens")
            if hit or miss or prompt_tok:
                current_app.logger.info(
                    "DeepSeek tokens | prompt=%s cache_hit=%s cache_miss=%s completion=%s tools=%s",
                    prompt_tok,
                    hit,
                    miss,
                    usage.get("completion_tokens"),
                    len(tool_calls),
                )
        except Exception:
            pass

    if not reply and not tool_calls:
        return {"ok": False, "error": "پاسخی از مدل دریافت نشد."}

    return {
        "ok": True,
        "reply": reply,
        "tool_calls": tool_calls,
        "meta": {
            "provider": "deepseek",
            "model": model,
            "usage": usage,
        },
    }


def _run_agent_loop(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    phone: str,
    audience: str,
    voice: str,
) -> dict[str, Any]:
    """حلقه کوتاه tool-calling؛ حداکثر ۲ دور ابزار سپس پاسخ نهایی."""
    agent_actions: list[dict[str, Any]] = []
    tool_land_codes: list[str] = []
    result: dict[str, Any] = {"ok": False, "error": "پاسخی دریافت نشد."}
    api_rounds = 0

    for round_i in range(_MAX_TOOL_ROUNDS + 1):
        allow_tools = bool(tools) and round_i < _MAX_TOOL_ROUNDS
        result = call_ai(messages, tools=tools if allow_tools else None)
        api_rounds += 1
        if not result.get("ok"):
            break

        tool_calls = result.get("tool_calls") if allow_tools else None
        if not isinstance(tool_calls, list):
            tool_calls = []
        if not tool_calls:
            break

        asst_msg: dict[str, Any] = {
            "role": "assistant",
            "content": result.get("reply") or None,
            "tool_calls": tool_calls,
        }
        messages.append(asst_msg)

        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            tc_id = str(tc.get("id") or "")
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = str(fn.get("name") or "").strip()
            args = parse_tool_arguments(fn.get("arguments"))
            tool_out = run_tool(
                name,
                args,
                phone=phone,
                audience=audience,
                voice=voice,
            )
            ui = tool_out.get("ui_action")
            if isinstance(ui, dict):
                agent_actions.append(ui)
            # کارت فایل فقط از جستجو — نه از اکشن‌های فروش/آگهی
            if name == "search_lands":
                for code in tool_out.get("land_codes") or []:
                    c = str(code).strip()
                    if c and c not in tool_land_codes:
                        tool_land_codes.append(c)
            model_payload = tool_out.get("model_result")
            if model_payload is None:
                model_payload = {
                    "ok": bool(tool_out.get("ok")),
                    "error": tool_out.get("error"),
                }
            try:
                content = json.dumps(model_payload, ensure_ascii=False)[:4000]
            except Exception:
                content = str(model_payload)[:4000]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": content,
                }
            )

    if result.get("ok"):
        result["agent_actions"] = agent_actions
        result["tool_land_codes"] = tool_land_codes
        result["api_rounds"] = api_rounds
    return result


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
    voice = resolve_ai_voice(phone=key, audience=aud)

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

    tools = tools_schema_for_voice(voice) if key else []
    messages = _build_messages(
        text,
        history,
        user_key=key,
        audience=aud,
        voice=voice,
        with_tools=bool(tools),
    )
    result = _run_agent_loop(
        messages,
        tools=tools or None,
        phone=key,
        audience=aud,
        voice=voice,
    )
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
    for code in result.get("tool_land_codes") or []:
        c = str(code).strip()
        if c and c not in land_codes:
            land_codes.append(c)
    land_codes = land_codes[:5]

    agent_actions = [
        a for a in (result.get("agent_actions") or []) if isinstance(a, dict)
    ]
    if any(str(a.get("type") or "") == "copy_blocks" for a in agent_actions):
        reply = _strip_listing_dump_when_copy_cards(reply)
    # اگر کارت تأیید اکشن هست، کارت فایل همان کد را دوباره نشان نده
    action_codes = {
        str(a.get("land_code") or "").strip()
        for a in agent_actions
        if str(a.get("type") or "").startswith("confirm_")
    }
    if action_codes:
        land_codes = [c for c in land_codes if c not in action_codes]
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

    if not reply and agent_actions:
        reply = "جزئیات را در کارت زیر بررسی کنید."

    result["reply"] = reply
    result["audience"] = aud
    result["voice"] = voice
    result["escalated"] = escalated
    if escalation_id:
        result["escalation_id"] = escalation_id
    if land_codes:
        result["land_codes"] = land_codes
        result["land_cards"] = land_cards_payload(key, land_codes, audience=aud)
    if agent_actions:
        result["agent_actions"] = agent_actions
        try:
            actions_html = render_agent_actions_html(agent_actions)
            land_html = ""
            if land_codes:
                from app.ai.land_cards import render_land_cards_html

                land_html = render_land_cards_html(key, land_codes, audience=aud) or ""
            if land_html and actions_html:
                result["cards_html"] = land_html + actions_html
            elif actions_html:
                result["cards_html"] = actions_html
            elif land_html:
                result["cards_html"] = land_html
        except Exception:
            pass

    store_cached_reply(key, aud, text, result)
    return result
