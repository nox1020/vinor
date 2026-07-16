"""منطق هوش مصنوعی وینور — DeepSeek API."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from uuid import uuid4

import requests
from flask import current_app

from .agent_tools import (
    agent_system_hint,
    parse_tool_arguments,
    render_agent_actions_html,
    run_tool,
    tools_schema_for_voice,
    try_continue_visit_from_user_message,
)
from .audience import (
    AUDIENCE_PARTNER,
    AUDIENCE_PUBLIC,
    resolve_ai_voice,
)
from .config import (
    DEEPSEEK_BASE_URL,
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
from .runtime_settings import (
    get_ai_settings,
    model_choice_label,
    resolve_deepseek_model,
)
from .escalations import consume_pending_answers, create_escalation
from .land_cards import collect_land_codes, land_cards_payload
from .provider_router import call_ai
from .token_analytics import (
    estimate_messages_tokens,
    estimate_tokens,
    record_token_analytics,
    usage_cost,
)

_MAX_TOOL_ROUNDS = 2
_MAX_TOOL_RESULT_CHARS = 1800
_PROMPT_CACHE: dict[str, tuple[float, str]] = {}
_PROMPT_CACHE_TTL_SEC = 20.0

# کلیدهای سنگین/تکراری که برای مدل لازم نیستند
_TOOL_RESULT_DROP_KEYS = frozenset(
    {
        "available_dates",  # labels کافی است
        "copies",  # متن کامل در کارت UI است
        "copy_blocks_count",
        "payload",
    }
)


def _compact_tool_model_payload(payload: Any) -> Any:
    """کاهش حجم JSON برگشتی ابزار برای مدل بدون حذف وضعیت/instruction."""
    if not isinstance(payload, dict):
        return payload
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in _TOOL_RESULT_DROP_KEYS:
            continue
        if k == "lands" and isinstance(v, list) and len(v) > 5:
            out[k] = v[:5]
        elif k == "instruction" and isinstance(v, str) and len(v) > 420:
            out[k] = v[:417] + "…"
        else:
            out[k] = v
    return out

LAND_MARKER_RE = re.compile(r"\[\[LAND:[^\]]+\]\]\s*", re.IGNORECASE)


def ai_config() -> dict[str, Any]:
    api_key = get_deepseek_api_key()
    cfg = get_ai_settings()
    choice = str(cfg.get("model_choice") or "auto")
    return {
        "enabled": bool(cfg.get("enabled")),
        "provider": "deepseek",
        "model_choice": choice,
        "model_choice_label": model_choice_label(choice),
        "model": resolve_deepseek_model(),
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
    thread_id: str | None = None,
) -> str:
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    if not user_key:
        return ""
    max_ctx = budget_config()["max_context_chars"]
    focus_codes: list[str] = []
    try:
        from .chat_store import recent_thread_land_codes

        focus_codes = recent_thread_land_codes(
            user_key, thread_id, audience=aud, limit=3
        )
    except Exception:
        focus_codes = []
    try:
        core_cache_key = _system_context_cache_key(
            user_key=user_key,
            audience=aud,
            user_message=user_message,
            thread_id=thread_id,
            focus_codes=focus_codes,
        )
        cached_core = _get_prompt_cache(core_cache_key)
        if cached_core is not None:
            ctx = cached_core
        elif aud == AUDIENCE_PARTNER:
            base = get_partner_context_base(
                user_key,
                lambda: build_partner_context_base(user_key),
            )
            status_ctx = build_partner_status_context(user_key)
            land_ctx = build_partner_land_context(
                user_key, user_message, focus_codes=focus_codes
            )
            parts = [base]
            if status_ctx:
                parts.append(status_ctx)
            if land_ctx:
                parts.append(land_ctx)
            ctx = "\n".join(parts)
            _set_prompt_cache(core_cache_key, ctx)
        else:
            base = get_public_context_base(build_public_context_base)
            land_ctx = build_public_land_context(
                user_message, focus_codes=focus_codes
            )
            ctx = base
            if land_ctx:
                ctx = f"{base}\n{land_ctx}"
            _set_prompt_cache(core_cache_key, ctx)
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
    chip_intent: str | None = None,
    thread_id: str | None = None,
) -> list[dict[str, Any]]:
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    cfg = budget_config()
    resolved_voice = voice or resolve_ai_voice(phone=user_key or "", audience=aud)
    base_prompt = prompt_for_voice(resolved_voice)
    messages: list[dict[str, Any]] = [{"role": "system", "content": base_prompt}]
    if with_tools:
        messages.append({"role": "system", "content": agent_system_hint(resolved_voice)})
    if chip_intent:
        from .intents import hint_for_chip_intent

        hint = hint_for_chip_intent(chip_intent)
        if hint:
            messages.append({"role": "system", "content": hint})
    if user_key:
        ctx = _build_system_prompt(
            user_key, audience, user_message=text, thread_id=thread_id
        )
        if ctx:
            messages.append({"role": "system", "content": ctx})
    if history:
        keep_last = int(cfg["max_history"])
        summary = _summarize_older_history(history, keep_last=keep_last)
        if summary:
            reduced_keep = max(2, keep_last - 2)
            dropped = history[-keep_last:-reduced_keep] if keep_last > reduced_keep else []
            dropped_tokens = 0
            for item in dropped:
                if isinstance(item, dict):
                    dropped_tokens += estimate_tokens(str(item.get("content") or ""))
            if estimate_tokens(summary) < dropped_tokens:
                messages.append({"role": "system", "content": summary})
                keep_last = reduced_keep
        for item in history[-keep_last:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = _trim_history_content(role, str(item.get("content") or ""), cfg)
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text[: cfg["max_msg_chars"]]})
    return messages


def _summarize_older_history(
    history: list[dict[str, str]] | None,
    *,
    keep_last: int,
) -> str:
    if (os.environ.get("VINOR_HISTORY_SUMMARY") or "0").strip().lower() not in ("1", "true", "yes", "on"):
        return ""
    rows = [h for h in (history or []) if isinstance(h, dict)]
    if len(rows) <= max(0, int(keep_last)):
        return ""
    older = rows[: -int(keep_last)]
    # Keep only the latest meaningful slices from old part.
    picked = older[-6:]
    bits: list[str] = []
    for item in picked:
        role = str(item.get("role") or "").strip()
        if role not in ("user", "assistant"):
            continue
        content = re.sub(r"\s+", " ", str(item.get("content") or "").strip())
        if not content:
            continue
        prefix = "کاربر" if role == "user" else "دستیار"
        bits.append(f"{prefix}: {content[:80]}")
    if not bits:
        return ""
    return "خلاصه گفتگوهای قبلی:\n- " + "\n- ".join(bits[:6])


def _system_context_cache_key(
    *,
    user_key: str,
    audience: str,
    user_message: str,
    thread_id: str | None,
    focus_codes: list[str],
) -> str:
    payload = {
        "u": user_key,
        "a": audience,
        "m": (user_message or "").strip()[:180].lower(),
        "t": thread_id or "",
        "f": focus_codes[:3],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _get_prompt_cache(key: str) -> str | None:
    item = _PROMPT_CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if (time.time() - ts) > _PROMPT_CACHE_TTL_SEC:
        _PROMPT_CACHE.pop(key, None)
        return None
    return value


def _set_prompt_cache(key: str, value: str) -> None:
    _PROMPT_CACHE[key] = (time.time(), value)
    if len(_PROMPT_CACHE) > 600:
        # simple trim of oldest 100 entries
        old_keys = sorted(_PROMPT_CACHE.items(), key=lambda x: x[1][0])[:100]
        for k, _ in old_keys:
            _PROMPT_CACHE.pop(k, None)


# DeepSeek V3.2/V4 گاهی tool call را به‌صورت DSML داخل content می‌فرستد
# (نه در فیلد structured tool_calls). هر دو شکل ｜ و | و تکرار دوبل پشتیبانی می‌شود.
_DSML_PIPE = r"(?:｜{1,2}|\|{1,2})"
_DSML_TAG_OPEN = rf"<{_DSML_PIPE}DSML{_DSML_PIPE}"
_DSML_TAG_CLOSE = rf"</{_DSML_PIPE}DSML{_DSML_PIPE}"
_DSML_BLOCK_RE = re.compile(
    rf"{_DSML_TAG_OPEN}(?:tool_calls|function_calls)\s*>(.*?)"
    rf"{_DSML_TAG_CLOSE}(?:tool_calls|function_calls)\s*>",
    re.DOTALL | re.IGNORECASE,
)
_DSML_INVOKE_RE = re.compile(
    rf"{_DSML_TAG_OPEN}invoke\s+name=\"([^\"]+)\"\s*>(.*?)"
    rf"{_DSML_TAG_CLOSE}invoke\s*>",
    re.DOTALL | re.IGNORECASE,
)
_DSML_PARAM_RE = re.compile(
    rf"{_DSML_TAG_OPEN}parameter\s+name=\"([^\"]+)\"\s+string=\"(true|false)\"\s*>(.*?)"
    rf"{_DSML_TAG_CLOSE}parameter\s*>",
    re.DOTALL | re.IGNORECASE,
)
_DSML_ANY_TAG_RE = re.compile(
    rf"</?{_DSML_PIPE}DSML{_DSML_PIPE}[^>]*>",
    re.IGNORECASE,
)


def _parse_dsml_invokes(blob: str, *, id_prefix: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for idx, inv in enumerate(_DSML_INVOKE_RE.finditer(blob or "")):
        name = (inv.group(1) or "").strip()
        if not name:
            continue
        args: dict[str, Any] = {}
        for pm in _DSML_PARAM_RE.finditer(inv.group(2) or ""):
            pname = (pm.group(1) or "").strip()
            if not pname:
                continue
            is_string = (pm.group(2) or "").lower() == "true"
            raw_val = pm.group(3) if pm.group(3) is not None else ""
            if is_string:
                args[pname] = raw_val
            else:
                try:
                    args[pname] = json.loads(raw_val)
                except Exception:
                    args[pname] = raw_val
        calls.append(
            {
                "id": f"{id_prefix}_{idx}_{uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        )
    return calls


def _extract_dsml_tool_calls(content: str) -> tuple[str, list[dict[str, Any]]]:
    """استخراج tool_calls از مارکاپ DSML و پاک‌کردن آن از متن قابل‌نمایش."""
    text = content or ""
    if "DSML" not in text:
        return text, []

    tool_calls: list[dict[str, Any]] = []
    cleaned = text
    for bi, block in enumerate(_DSML_BLOCK_RE.finditer(text)):
        tool_calls.extend(_parse_dsml_invokes(block.group(1), id_prefix=f"call_dsml_{bi}"))
        cleaned = cleaned.replace(block.group(0), "", 1)

    if not tool_calls:
        tool_calls = _parse_dsml_invokes(cleaned, id_prefix="call_dsml_loose")
        if tool_calls:
            cleaned = _DSML_INVOKE_RE.sub("", cleaned)

    # بلوک ناقص/بریده‌شده: از اولین تگ DSML تا انتها حذف شود
    if "DSML" in cleaned:
        cut = re.search(_DSML_TAG_OPEN, cleaned)
        if cut:
            cleaned = cleaned[: cut.start()]
        cleaned = _DSML_ANY_TAG_RE.sub("", cleaned)

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, tool_calls


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

    model = resolve_deepseek_model(has_tools=bool(tools))
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
        current_app.logger.info(
            "DeepSeek request | model=%s tools=%s choice=%s",
            model,
            len(tools) if tools else 0,
            get_ai_settings().get("model_choice"),
        )
    except Exception:
        pass
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

    # بعضی مدل‌ها/اندپوینت‌ها DSML را فقط داخل content می‌فرستند، نه در tool_calls
    if reply and "DSML" in reply:
        cleaned, dsml_calls = _extract_dsml_tool_calls(reply)
        reply = cleaned
        if not tool_calls and dsml_calls:
            tool_calls = dsml_calls
            try:
                current_app.logger.info(
                    "DeepSeek DSML fallback | parsed_tools=%s",
                    len(dsml_calls),
                )
            except Exception:
                pass

    usage = body.get("usage") if isinstance(body, dict) else None
    if isinstance(usage, dict):
        try:
            hit = int(usage.get("prompt_cache_hit_tokens") or 0)
            miss = int(usage.get("prompt_cache_miss_tokens") or 0)
            prompt_tok = usage.get("prompt_tokens")
            if hit or miss or prompt_tok:
                current_app.logger.info(
                    "DeepSeek tokens | model=%s prompt=%s cache_hit=%s cache_miss=%s completion=%s tools=%s",
                    model,
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
    thread_id: str | None = None,
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
                thread_id=thread_id,
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
            model_payload = _compact_tool_model_payload(model_payload)
            try:
                content = json.dumps(model_payload, ensure_ascii=False)[:_MAX_TOOL_RESULT_CHARS]
            except Exception:
                content = str(model_payload)[:_MAX_TOOL_RESULT_CHARS]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": content,
                }
            )
            # مرحلهٔ اجباری بازدید: متن را خود سیستم بگوید (مدل «نام‌خانوادگی» اختراع نکند)
            speak = ""
            if isinstance(model_payload, dict):
                speak = str(model_payload.get("speak_exactly") or "").strip()
            if speak:
                forced_actions = list(agent_actions)
                return {
                    "ok": True,
                    "reply": speak,
                    "agent_actions": forced_actions,
                    "tool_land_codes": tool_land_codes,
                    "api_rounds": api_rounds,
                    "meta": result.get("meta") if isinstance(result.get("meta"), dict) else {"provider": "deepseek"},
                }

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
    chip_intent: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
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

    from .intents import normalize_chip_intent

    intent = normalize_chip_intent(chip_intent)
    # شروع تازهٔ ثبت بازدید / بازدید مجدد — پیش‌نویس قبلی فیلدها را قاطی نکند
    if intent == "visit" and key:
        try:
            from .agent_tools import clear_visit_draft

            clear_visit_draft(key)
        except Exception:
            pass
    # ادامهٔ مرحله‌ای بازدید (نام/موبایل/تاریخ) بدون اینکه مدل دوباره نام‌خانوادگی بپرسد
    if intent != "visit" and key:
        try:
            from flask import g

            g.ai_last_user_message = (text or "").strip()
        except Exception:
            pass
        short = try_continue_visit_from_user_message(
            key,
            text,
            audience=aud,
            voice=voice,
            thread_id=thread_id,
        )
        if short and short.get("ok"):
            reply = str(short.get("reply") or "").strip()
            agent_actions = [
                a for a in (short.get("agent_actions") or []) if isinstance(a, dict)
            ]
            actions_html = render_agent_actions_html(agent_actions) if agent_actions else ""
            return {
                "ok": True,
                "reply": reply,
                "land_codes": [],
                "land_cards": [],
                "agent_actions": agent_actions,
                "agent_actions_html": actions_html,
                "meta": short.get("meta") or {"provider": "visit_step"},
            }
    tools = tools_schema_for_voice(voice) if key else []
    messages = _build_messages(
        text,
        history,
        user_key=key,
        audience=aud,
        voice=voice,
        with_tools=bool(tools),
        chip_intent=intent or None,
        thread_id=thread_id,
    )
    prompt_parts = _prompt_token_parts(messages)
    try:
        from flask import g

        g.ai_last_user_message = (text or "").strip()
    except Exception:
        pass
    result = _run_agent_loop(
        messages,
        tools=tools or None,
        phone=key,
        audience=aud,
        voice=voice,
        thread_id=thread_id,
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
        _record_request_analytics(
            user_key=key,
            audience=aud,
            voice=voice,
            messages=messages,
            prompt_parts=prompt_parts,
            result=result,
            started=started,
        )
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
            if actions_html:
                result["cards_html"] = actions_html
        except Exception:
            pass
    # کارت فایل فقط در land_cards (نوار بالای خانه) — داخل چت cards_html نگذار

    store_cached_reply(key, aud, text, result)
    _record_request_analytics(
        user_key=key,
        audience=aud,
        voice=voice,
        messages=messages,
        prompt_parts=prompt_parts,
        result=result,
        started=started,
    )
    return result


def _prompt_token_parts(messages: list[dict[str, Any]]) -> dict[str, int]:
    parts = {
        "system_prompt_tokens": 0,
        "context_tokens": 0,
        "history_tokens": 0,
        "user_tokens": 0,
    }
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        tok = estimate_tokens(content)
        if role == "system":
            if "=== اطلاعات داخلی وینور ===" in content or "--- آگهی" in content or "--- فایل" in content:
                parts["context_tokens"] += tok
            else:
                parts["system_prompt_tokens"] += tok
        elif role == "user":
            if m is messages[-1]:
                parts["user_tokens"] += tok
            else:
                parts["history_tokens"] += tok
        elif role == "assistant":
            parts["history_tokens"] += tok
    return parts


def _record_request_analytics(
    *,
    user_key: str,
    audience: str,
    voice: str,
    messages: list[dict[str, Any]],
    prompt_parts: dict[str, int],
    result: dict[str, Any],
    started: float,
) -> None:
    try:
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
        input_tokens = int(usage.get("prompt_tokens") or 0) or estimate_messages_tokens(messages)
        output_tokens = int(usage.get("completion_tokens") or 0) or estimate_tokens(result.get("reply") or "")
        rag_tokens = int(prompt_parts.get("context_tokens") or 0)
        row = {
            "user": user_key,
            "audience": audience,
            "voice": voice,
            "ok": bool(result.get("ok")),
            "provider": meta.get("provider") or "",
            "model": meta.get("model") or "",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "system_prompt_tokens": int(prompt_parts.get("system_prompt_tokens") or 0),
            "context_tokens": int(prompt_parts.get("context_tokens") or 0),
            "history_tokens": int(prompt_parts.get("history_tokens") or 0),
            "rag_tokens": rag_tokens,
            "total_tokens": input_tokens + output_tokens,
            "total_cost": usage_cost(usage),
            "response_time_ms": int((time.perf_counter() - started) * 1000),
            "api_rounds": int(result.get("api_rounds") or 0),
            "cache_hit": bool((meta.get("provider") == "cache") if isinstance(meta, dict) else False),
        }
        record_token_analytics(row)
    except Exception:
        pass
