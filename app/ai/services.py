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
_PLANNING_SKIP_INTENTS = frozenset(
    {
        "visit",
        "complete_visit",
        "deal",
        "release",
        "coop_apply",
    }
)

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
    try:
        from app.supervisor.service import current_flags

        flags = current_flags()
        if flags is not None:
            max_ctx = min(int(max_ctx), int(flags.context_budget_chars or max_ctx))
    except Exception:
        pass
    focus_codes: list[str] = []
    try:
        from .chat_store import recent_thread_land_codes

        focus_codes = recent_thread_land_codes(
            user_key, thread_id, audience=aud, limit=3
        )
    except Exception:
        focus_codes = []
    # تضمین: مأموریت/پرونده هم در فوکوس بیاید حتی اگر هنوز در messages نباشد
    try:
        from .agent_tools import resolve_conversation_land_code

        resolved = resolve_conversation_land_code(user_key, thread_id=thread_id)
        if resolved and resolved not in focus_codes:
            focus_codes = [resolved] + list(focus_codes)
    except Exception:
        pass
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
        # Memory is retrieved here for observability + later injection as a
        # SEPARATE system message (keeps core prompt cache and token accounting clean).
        mem_text, mem_meta = _memory_block_for_prompt(
            user_key=user_key,
            audience=aud,
            user_message=user_message,
            thread_id=thread_id,
            remaining_chars=max(0, max_ctx - len(ctx)),
        )
        _set_memory_obs(mem_meta)
        _set_memory_prompt_text(mem_text)
        return ctx[:max_ctx]
    except Exception as exc:
        try:
            current_app.logger.warning("AI context build failed: %s", exc)
        except Exception:
            pass
        return ""


def _memory_block_for_prompt(
    *,
    user_key: str,
    audience: str,
    user_message: str,
    thread_id: str | None,
    remaining_chars: int,
) -> tuple[str, dict[str, int]]:
    empty = {
        "memory_retrieved": 0,
        "memory_used": 0,
        "memory_tokens": 0,
    }
    if remaining_chars < 60:
        return "", empty
    try:
        from app.supervisor.service import allow_component

        if not allow_component("memory", default=True):
            return "", empty
    except Exception:
        pass
    try:
        from app.memory.config import memory_budget_chars
        from app.memory.service import retrieve_memory_for_prompt

        result = retrieve_memory_for_prompt(
            user_key=user_key,
            query=user_message,
            audience=audience,
            thread_id=thread_id,
            budget_chars=min(memory_budget_chars(), remaining_chars),
        )
        text = (result.text or "").strip()
        if not text:
            return "", {
                "memory_retrieved": int(result.retrieved_count or 0),
                "memory_used": 0,
                "memory_tokens": 0,
            }
        # Hard budget: never exceed remaining context room.
        if len(text) > remaining_chars:
            text = text[: max(0, remaining_chars - 1)].rstrip() + "…"
        return text, {
            "memory_retrieved": int(result.retrieved_count or 0),
            "memory_used": int(result.used_count or 0),
            "memory_tokens": int(estimate_tokens(text)),
        }
    except Exception:
        return "", empty


def _set_memory_obs(meta: dict[str, int]) -> None:
    try:
        from flask import g

        g.ai_memory_obs = dict(meta or {})
    except Exception:
        pass


def _set_memory_prompt_text(text: str) -> None:
    try:
        from flask import g

        g.ai_memory_prompt_text = (text or "").strip()
    except Exception:
        pass


def _get_memory_prompt_text() -> str:
    try:
        from flask import g

        return str(getattr(g, "ai_memory_prompt_text", "") or "").strip()
    except Exception:
        return ""


def _get_memory_obs() -> dict[str, int]:
    try:
        from flask import g

        raw = getattr(g, "ai_memory_obs", None)
        if isinstance(raw, dict):
            return {
                "memory_retrieved": int(raw.get("memory_retrieved") or 0),
                "memory_used": int(raw.get("memory_used") or 0),
                "memory_tokens": int(raw.get("memory_tokens") or 0),
            }
    except Exception:
        pass
    return {"memory_retrieved": 0, "memory_used": 0, "memory_tokens": 0}


def _set_planning_obs(outcome: Any) -> None:
    try:
        from flask import g

        g.ai_planning_obs = {
            "planning_time_ms": int(getattr(outcome, "planning_time_ms", 0) or 0),
            "tasks_count": int(getattr(outcome, "tasks_count", 0) or 0),
            "executed_tasks": int(getattr(outcome, "executed_tasks", 0) or 0),
            "planning_tokens": int(getattr(outcome, "planning_tokens", 0) or 0),
            "execution_tokens": int(getattr(outcome, "execution_tokens", 0) or 0),
            "plan_type": str(getattr(getattr(outcome, "plan", None), "plan_type", "") or ""),
        }
    except Exception:
        pass


def _get_planning_obs() -> dict[str, Any]:
    try:
        from flask import g

        raw = getattr(g, "ai_planning_obs", None)
        if isinstance(raw, dict):
            return dict(raw)
    except Exception:
        pass
    return {
        "planning_time_ms": 0,
        "tasks_count": 0,
        "executed_tasks": 0,
        "planning_tokens": 0,
        "execution_tokens": 0,
        "plan_type": "",
    }


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
        mem_text = _get_memory_prompt_text()
        if mem_text:
            messages.append({"role": "system", "content": mem_text})
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
    if (os.environ.get("VINOR_HISTORY_SUMMARY") or "1").strip().lower() not in ("1", "true", "yes", "on"):
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
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] = []
    if isinstance(body, dict):
        choices = body.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            if isinstance(msg, dict):
                reply = str(msg.get("content") or "").strip()
                # DeepSeek thinking mode: must replay reasoning_content after tool calls
                if "reasoning_content" in msg:
                    raw_rc = msg.get("reasoning_content")
                    reasoning_content = "" if raw_rc is None else str(raw_rc)
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

    out_ok: dict[str, Any] = {
        "ok": True,
        "reply": reply,
        "tool_calls": tool_calls,
        "meta": {
            "provider": "deepseek",
            "model": model,
            "usage": usage,
        },
    }
    if reasoning_content is not None:
        out_ok["reasoning_content"] = reasoning_content
    return out_ok


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
        # DeepSeek thinking mode: reasoning_content MUST be passed back with tool_calls
        if "reasoning_content" in result:
            asst_msg["reasoning_content"] = result.get("reasoning_content") or ""
        else:
            asst_msg["reasoning_content"] = ""
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
                from app.ai.card_registry import normalize_card

                agent_actions.append(normalize_card(ui))
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

    # فوکوس فایل موضوع گفتگو از همان ابتدا — ابزارها/مدل کد نپرسند
    try:
        from flask import g
        from .agent_tools import resolve_conversation_land_code

        g.ai_tool_thread_id = (thread_id or "").strip() or None
        g.ai_tool_audience = aud
        g.ai_last_user_message = text
        focus0 = resolve_conversation_land_code(key, thread_id=thread_id)
        if focus0:
            g.ai_focus_land_code = focus0
    except Exception:
        pass

    cfg = ai_config()
    if not cfg["enabled"]:
        return {"ok": False, "error": "سرویس هوش مصنوعی موقتاً غیرفعال است."}

    guard = apply_credit_guard(key, aud, text)
    if guard is not None:
        if guard.get("ok") and guard.get("land_codes"):
            codes = guard.get("land_codes") or []
            guard["land_cards"] = land_cards_payload(key, codes, audience=aud)
            try:
                from .land_cards import render_land_cards_html

                land_html = render_land_cards_html(key, codes, audience=aud) or ""
                if land_html:
                    prev = str(guard.get("cards_html") or "")
                    guard["cards_html"] = land_html + prev
            except Exception:
                pass
        return guard

    from .intents import normalize_chip_intent

    intent = normalize_chip_intent(chip_intent)
    # Conversation Engine (Phase 11.5): before Supervisor — form workflows via chat.
    conversation_handled = False
    try:
        from app.conversation.service import try_conversation_engine

        ce = try_conversation_engine(
            message=text,
            user_key=key,
            audience=aud,
            voice=voice,
            chip_intent=intent or "",
            thread_id=thread_id,
        )
        if isinstance(ce, dict) and ce.get("ok") and ce.get("handled") and not ce.get("pass_to_supervisor"):
            conversation_handled = True
            # Executive + Goals still run (objects outside prompt); then early return.
            try:
                from app.executive.service import plan_execution
                from app.goals.service import run_goals

                plan_execution(
                    message=text,
                    audience=aud,
                    intent=intent or "",
                    conversation_handled=True,
                )
                run_goals(
                    message=text,
                    user_key=key,
                    audience=aud,
                    intent=intent or "",
                )
            except Exception:
                pass
            meta = dict(ce.get("meta") or {"provider": "conversation_engine"})
            meta.setdefault("workflow_form_only", True)
            meta.setdefault("persists_business", False)
            return {
                "ok": True,
                "reply": str(ce.get("reply") or "").strip(),
                "land_codes": [],
                "land_cards": [],
                "agent_actions": list(ce.get("agent_actions") or []),
                "meta": meta,
            }
    except Exception as exc:
        try:
            current_app.logger.warning(
                "conversation_engine outer fail-open | user=%s thread=%s err=%s",
                (key or "")[:32],
                (thread_id or "")[:48],
                exc,
                exc_info=True,
            )
        except Exception:
            pass

    # Executive AI (Phase 26) + Goal Engine (Phase 20) — before Supervisor/Workflow.
    exec_plan = None
    try:
        from app.executive.service import plan_execution
        from app.goals.service import run_goals

        exec_plan = plan_execution(
            message=text,
            audience=aud,
            intent=intent or "",
            conversation_handled=False,
        )
        if exec_plan.run_goals:
            run_goals(
                message=text,
                user_key=key,
                audience=aud,
                intent=intent or "",
            )
    except Exception:
        exec_plan = None

    # Supervisor / Orchestrator (rule-based): decide which components to run.
    try:
        run_sup = exec_plan is None or bool(exec_plan.run_supervisor)
        if run_sup:
            from app.supervisor.service import orchestrate_request, set_supervisor_context

            sup_out = orchestrate_request(
                message=text,
                audience=aud,
                voice=voice,
                chip_intent=intent or "",
                user_key=key,
            )
            set_supervisor_context(sup_out)
            # Multi-Agent (Phase 8): Supervisor route → AgentSelector (lazy, at most one).
            try:
                run_ag = exec_plan is None or bool(exec_plan.run_agents)
                if run_ag:
                    from app.agents.service import prepare_agent_after_supervisor

                    route = ""
                    budget = 3000
                    if sup_out is not None:
                        route = str(sup_out.workflow.route or "")
                        budget = int(sup_out.workflow.flags.context_budget_chars or 3000)
                    prepare_agent_after_supervisor(
                        message=text,
                        route=route,
                        audience=aud,
                        voice=voice,
                        chip_intent=intent or "",
                        user_key=key,
                        thread_id=thread_id,
                        context_budget_chars=budget,
                    )
                    # Adaptive Execution (Phase 9): state/confidence outside Prompt.
                    try:
                        from app.adaptive.service import (
                            after_agent_prepare_adaptive,
                            begin_adaptive,
                        )
                        from app.agents.service import get_agent_obs

                        begin_adaptive(
                            message=text,
                            route=route,
                            audience=aud,
                            voice=voice,
                            chip_intent=intent or "",
                            user_key=key,
                        )
                        aobs = get_agent_obs()
                        after_agent_prepare_adaptive(
                            agent_status=str(aobs.get("agent_status") or ""),
                            used_components=list(aobs.get("agent_used_components") or []),
                            selected_agent=str(aobs.get("selected_agent") or ""),
                        )
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        try:
            from app.supervisor.service import set_supervisor_context

            set_supervisor_context(None)
        except Exception:
            pass
        try:
            from app.agents.service import set_agent_obs

            set_agent_obs(None)
        except Exception:
            pass
        try:
            from app.adaptive.service import clear_adaptive

            clear_adaptive()
        except Exception:
            pass
    # شروع تازهٔ ثبت بازدید — نام/شماره قبلی پاک شود، ولی کد فایل موضوع حفظ شود
    if intent == "visit" and key:
        try:
            from .agent_tools import reset_visit_draft_keep_land

            focus_land = reset_visit_draft_keep_land(key, thread_id=thread_id)
            try:
                from flask import g

                if focus_land:
                    g.ai_focus_land_code = focus_land
                g.ai_tool_thread_id = (thread_id or "").strip() or None
                g.ai_tool_audience = aud
            except Exception:
                pass
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
    try:
        from app.supervisor.service import allow_component, current_flags

        if not allow_component("tools", default=True):
            tools = []
        flags = current_flags()
    except Exception:
        flags = None
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
    # Planning Layer (once): gated by Supervisor; Plan never enters Prompt fully.
    plan_out = None
    allow_planning = True
    inject_hint = True
    seed_tools = True
    try:
        from app.supervisor.service import allow_component, current_flags

        allow_planning = allow_component("planning", default=True)
        fl = current_flags()
        if fl is not None:
            inject_hint = bool(fl.inject_planning_hint)
            seed_tools = bool(fl.seed_planning_tools)
    except Exception:
        pass
    # Adaptive retry strategy "lean": skip planning hint/seed (no new prompt text).
    try:
        from app.adaptive.service import use_lean_strategy

        if use_lean_strategy():
            inject_hint = False
            seed_tools = False
    except Exception:
        pass
    if key and intent not in _PLANNING_SKIP_INTENTS and allow_planning:
        try:
            from app.planning.service import run_planning_once

            plan_out = run_planning_once(
                goal=text,
                user_key=key,
                audience=aud,
                voice=voice,
                thread_id=thread_id,
                chip_intent=intent or "",
            )
        except Exception:
            plan_out = None
    if plan_out is not None:
        _set_planning_obs(plan_out)
        if inject_hint and plan_out.compact_hint:
            messages.append({"role": "system", "content": plan_out.compact_hint})
        if seed_tools and plan_out.seed_messages:
            messages.extend(plan_out.seed_messages)
    # Agents → Prompt hints. Phase 16: Parallel merge hint only (no per-agent re-run/re-hint).
    try:
        from app.agents.parallel.config import parallel_enabled
        from app.agents.parallel.service import get_parallel_merge_hint, get_parallel_obs
        from app.agents.service import get_agent_obs

        aobs = get_agent_obs()
        selected = str(aobs.get("selected_agent") or "")
        parallel_obs = get_parallel_obs() if parallel_enabled() else {}
        # Phase 17: prefer Decision hint (replaces parallel merge hint when present).
        try:
            from app.decision.config import decision_enabled
            from app.decision.service import get_decision_hint, get_decision_obs

            if decision_enabled() and get_decision_obs().get("selected_property"):
                dhint = get_decision_hint()
                if dhint:
                    messages.append({"role": "system", "content": dhint})
                elif parallel_obs.get("merged_agents"):
                    phint = get_parallel_merge_hint()
                    if phint:
                        messages.append({"role": "system", "content": phint})
            elif parallel_obs.get("merged_agents"):
                phint = get_parallel_merge_hint()
                if phint:
                    messages.append({"role": "system", "content": phint})
        except Exception:
            if parallel_obs.get("merged_agents"):
                phint = get_parallel_merge_hint()
                if phint:
                    messages.append({"role": "system", "content": phint})
        # Sequential per-agent hints only when Parallel did not merge (Decision may still apply above).
        if not parallel_obs.get("merged_agents"):
            from app.agents.analysis.service import get_analysis_hint, should_run_analysis

            route_now = str((aobs.get("agent_reason") or ""))
            try:
                from app.supervisor.service import get_supervisor_obs

                route_now = str(get_supervisor_obs().get("routed_workflow") or route_now)
            except Exception:
                pass
            need_analysis = selected in ("property_analysis", "recommendation") or should_run_analysis(
                route=route_now, message=text, chip_intent=intent or ""
            )
            analysis_categories = []
            codes = []
            if plan_out is not None:
                codes = [str(c).strip() for c in (plan_out.land_codes or []) if str(c).strip()]
            shared = {
                "pipeline": "planning|memory|rag|tools|llm",
                "property_search_agent": True,
                "search_handoff": True,
                "reused_rag": True,
                "reused_memory": True,
                "reused_planning": True,
                "planning_land_codes": codes,
                "property_codes": codes,
                "land_codes": codes,
            }
            if need_analysis:
                from app.agents.analysis.service import run_property_analysis as _run_pa

                ar = _run_pa(
                    property_codes=codes,
                    message=text,
                    route=route_now,
                    audience=aud,
                    user_key=key,
                    shared=shared,
                )
                if ar is not None:
                    analysis_categories = list(ar.categories or [])
                    shared["analysis_categories"] = analysis_categories
                hint = get_analysis_hint()
                if hint and selected != "recommendation":
                    messages.append({"role": "system", "content": hint})
            try:
                from app.agents.recommendation.service import (
                    get_recommendation_hint,
                    run_recommendation,
                    should_run_recommendation,
                )

                need_rec = selected == "recommendation" or should_run_recommendation(
                    route=route_now, message=text, chip_intent=intent or ""
                )
                if need_rec:
                    run_recommendation(
                        property_codes=codes,
                        message=text,
                        route=route_now,
                        audience=aud,
                        user_key=key,
                        shared=shared,
                        analysis_categories=analysis_categories,
                    )
                    rhint = get_recommendation_hint()
                    if rhint:
                        messages.append({"role": "system", "content": rhint})
            except Exception:
                pass
            try:
                from app.agents.customer_memory.service import (
                    get_customer_memory_hint,
                    run_customer_memory,
                    should_run_customer_memory,
                )

                need_cm = selected == "customer_memory" or should_run_customer_memory(
                    route=route_now, message=text, chip_intent=intent or ""
                )
                if need_cm:
                    run_customer_memory(
                        message=text,
                        route=route_now,
                        audience=aud,
                        user_key=key,
                        shared=shared,
                    )
                    cmhint = get_customer_memory_hint()
                    if cmhint:
                        messages.append({"role": "system", "content": cmhint})
            except Exception:
                pass
            try:
                from app.agents.negotiation.service import (
                    get_negotiation_hint,
                    run_negotiation,
                    should_run_negotiation,
                )

                need_neg = selected == "negotiation" or should_run_negotiation(
                    route=route_now, message=text, chip_intent=intent or ""
                )
                if need_neg:
                    run_negotiation(
                        message=text,
                        route=route_now,
                        audience=aud,
                        user_key=key,
                        shared=shared,
                    )
                    nhint = get_negotiation_hint()
                    if nhint:
                        messages.append({"role": "system", "content": nhint})
            except Exception:
                pass
            try:
                from app.agents.customer_success.service import (
                    get_customer_success_hint,
                    run_customer_success,
                    should_run_customer_success,
                )

                need_cs = selected == "follow_up" or should_run_customer_success(
                    route=route_now, message=text, chip_intent=intent or ""
                )
                if need_cs:
                    run_customer_success(
                        message=text,
                        route=route_now,
                        audience=aud,
                        user_key=key,
                        shared=shared,
                    )
                    cshint = get_customer_success_hint()
                    if cshint:
                        messages.append({"role": "system", "content": cshint})
            except Exception:
                pass
    except Exception:
        pass
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
        try:
            from app.adaptive.service import fail_adaptive

            fail_adaptive(error=str(result.get("error") or result.get("error_code") or "llm_failed"))
        except Exception:
            pass
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
    if plan_out is not None:
        for code in plan_out.land_codes or []:
            c = str(code).strip()
            if c and c not in land_codes:
                land_codes.append(c)
    land_codes = land_codes[:5]

    from app.ai.card_registry import normalize_card

    agent_actions = [
        normalize_card(a)
        for a in (result.get("agent_actions") or [])
        if isinstance(a, dict)
    ]
    if plan_out is not None:
        for a in plan_out.agent_actions or []:
            if isinstance(a, dict):
                agent_actions.append(normalize_card(a))
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
    card_parts: list[str] = []
    if land_codes:
        result["land_codes"] = land_codes
        result["land_cards"] = land_cards_payload(key, land_codes, audience=aud)
        try:
            from .land_cards import render_land_cards_html

            land_html = render_land_cards_html(key, land_codes, audience=aud) or ""
            if land_html:
                card_parts.append(land_html)
        except Exception:
            pass
    if agent_actions:
        result["agent_actions"] = agent_actions
        try:
            actions_html = render_agent_actions_html(agent_actions)
            if actions_html:
                card_parts.append(actions_html)
        except Exception:
            pass
    if card_parts:
        result["cards_html"] = "".join(card_parts)

    # Adaptive: evaluate quality + confidence (objects only — no prompt injection).
    try:
        from app.adaptive.service import after_response_adaptive

        after_response_adaptive(
            reply=reply,
            land_codes=land_codes or [],
            ok=True,
        )
    except Exception:
        pass

    store_cached_reply(key, aud, text, result)
    # Memory ingest after successful reply (non-blocking for UX).
    try:
        from app.memory.service import learn_from_exchange

        learn_from_exchange(
            user_key=key,
            user_message=text,
            assistant_reply=reply,
            audience=aud,
            thread_id=thread_id,
            land_codes=land_codes or [],
        )
    except Exception:
        pass
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
        "memory_tokens": 0,
    }
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        tok = estimate_tokens(content)
        if role == "system":
            if "=== حافظه مرتبط کاربر ===" in content:
                parts["memory_tokens"] += tok
            elif "=== یافتهٔ برنامه‌ریز ===" in content:
                parts["planning_tokens"] = parts.get("planning_tokens", 0) + tok
            elif "=== تحلیل فایل ===" in content:
                parts["analysis_tokens"] = parts.get("analysis_tokens", 0) + tok
            elif "=== پیشنهاد فایل ===" in content:
                parts["recommendation_tokens"] = parts.get("recommendation_tokens", 0) + tok
            elif "=== پروفایل مشتری ===" in content:
                parts["customer_memory_tokens"] = parts.get("customer_memory_tokens", 0) + tok
            elif "=== مذاکره ===" in content:
                parts["negotiation_tokens"] = parts.get("negotiation_tokens", 0) + tok
            elif "=== پیگیری ===" in content:
                parts["customer_success_tokens"] = parts.get("customer_success_tokens", 0) + tok
            elif "=== همکاری ===" in content:
                parts["parallel_merge_tokens"] = parts.get("parallel_merge_tokens", 0) + tok
            elif "=== تصمیم ===" in content:
                parts["decision_tokens"] = parts.get("decision_tokens", 0) + tok
            elif "=== اطلاعات داخلی وینور ===" in content or "--- آگهی" in content or "--- فایل" in content:
                parts["context_tokens"] += tok
            else:
                parts["system_prompt_tokens"] += tok
        elif role == "tool":
            parts["execution_tokens"] = parts.get("execution_tokens", 0) + tok
        elif role == "user":
            if m is messages[-1]:
                parts["user_tokens"] += tok
            else:
                parts["history_tokens"] += tok
        elif role == "assistant":
            parts["history_tokens"] += tok
    parts.setdefault("planning_tokens", 0)
    parts.setdefault("execution_tokens", 0)
    parts.setdefault("customer_memory_tokens", 0)
    parts.setdefault("negotiation_tokens", 0)
    parts.setdefault("customer_success_tokens", 0)
    parts.setdefault("parallel_merge_tokens", 0)
    parts.setdefault("decision_tokens", 0)
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
        mem_obs = _get_memory_obs()
        plan_obs = _get_planning_obs()
        try:
            from app.supervisor.service import get_supervisor_obs

            sup_obs = get_supervisor_obs()
        except Exception:
            sup_obs = {}
        try:
            from app.agents.service import get_agent_obs

            agent_obs = get_agent_obs()
        except Exception:
            agent_obs = {}
        try:
            from app.adaptive.service import get_adaptive_obs

            adaptive_obs = get_adaptive_obs()
        except Exception:
            adaptive_obs = {}
        try:
            from app.agents.analysis.service import get_analysis_obs

            analysis_obs = get_analysis_obs()
        except Exception:
            analysis_obs = {}
        try:
            from app.agents.recommendation.service import get_recommendation_obs

            rec_obs = get_recommendation_obs()
        except Exception:
            rec_obs = {}
        try:
            from app.agents.customer_memory.service import get_customer_memory_obs

            cm_obs = get_customer_memory_obs()
        except Exception:
            cm_obs = {}
        try:
            from app.agents.negotiation.service import get_negotiation_obs

            neg_obs = get_negotiation_obs()
        except Exception:
            neg_obs = {}
        try:
            from app.agents.customer_success.service import get_customer_success_obs

            cs_obs = get_customer_success_obs()
        except Exception:
            cs_obs = {}
        try:
            from app.agents.parallel.service import get_parallel_obs

            parallel_obs = get_parallel_obs()
        except Exception:
            parallel_obs = {}
        try:
            from app.decision.service import get_decision_obs

            decision_obs = get_decision_obs()
        except Exception:
            decision_obs = {}
        try:
            from app.business_intelligence.service import get_bi_obs

            bi_obs = get_bi_obs()
        except Exception:
            bi_obs = {}
        try:
            from app.conversation.service import get_conversation_obs

            conv_obs = get_conversation_obs()
        except Exception:
            conv_obs = {}
        memory_tokens = int(prompt_parts.get("memory_tokens") or mem_obs.get("memory_tokens") or 0)
        planning_tokens = int(prompt_parts.get("planning_tokens") or plan_obs.get("planning_tokens") or 0)
        execution_tokens = int(prompt_parts.get("execution_tokens") or plan_obs.get("execution_tokens") or 0)
        agent_tokens = int(agent_obs.get("agent_tokens") or 0)
        analysis_tokens = int(
            prompt_parts.get("analysis_tokens") or analysis_obs.get("analysis_tokens") or 0
        )
        recommendation_tokens = int(
            prompt_parts.get("recommendation_tokens")
            or rec_obs.get("recommendation_tokens")
            or 0
        )
        customer_memory_tokens = int(
            prompt_parts.get("customer_memory_tokens")
            or cm_obs.get("customer_memory_tokens")
            or 0
        )
        negotiation_tokens = int(
            prompt_parts.get("negotiation_tokens")
            or neg_obs.get("negotiation_tokens")
            or 0
        )
        customer_success_tokens = int(
            prompt_parts.get("customer_success_tokens")
            or cs_obs.get("customer_success_tokens")
            or 0
        )
        parallel_merge_tokens = int(
            prompt_parts.get("parallel_merge_tokens")
            or parallel_obs.get("parallel_merge_tokens")
            or 0
        )
        decision_tokens = int(
            prompt_parts.get("decision_tokens") or decision_obs.get("decision_tokens") or 0
        )
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
            "memory_retrieved": int(mem_obs.get("memory_retrieved") or 0),
            "memory_used": int(mem_obs.get("memory_used") or 0),
            "memory_tokens": memory_tokens,
            "planning_time_ms": int(plan_obs.get("planning_time_ms") or 0),
            "tasks_count": int(plan_obs.get("tasks_count") or 0),
            "executed_tasks": int(plan_obs.get("executed_tasks") or 0),
            "planning_tokens": planning_tokens,
            "execution_tokens": execution_tokens,
            "plan_type": str(plan_obs.get("plan_type") or ""),
            "routed_workflow": str(sup_obs.get("routed_workflow") or ""),
            "executed_components": list(sup_obs.get("executed_components") or []),
            "skipped_components": list(sup_obs.get("skipped_components") or []),
            "routing_time_ms": int(sup_obs.get("routing_time_ms") or 0),
            "selected_agent": str(agent_obs.get("selected_agent") or ""),
            "skipped_agents": list(agent_obs.get("skipped_agents") or []),
            "agent_status": str(agent_obs.get("agent_status") or ""),
            "agent_tokens": agent_tokens,
            "agent_execution_time_ms": int(agent_obs.get("agent_execution_time_ms") or 0),
            "analysis_time_ms": int(analysis_obs.get("analysis_time_ms") or 0),
            "analysis_tokens": analysis_tokens,
            "analysis_cache_hit": bool(analysis_obs.get("analysis_cache_hit")),
            "analysis_reused_context": bool(analysis_obs.get("analysis_reused_context")),
            "analysis_reused_rag": bool(analysis_obs.get("analysis_reused_rag")),
            "analysis_reused_memory": bool(analysis_obs.get("analysis_reused_memory")),
            "analysis_reused_planning": bool(analysis_obs.get("analysis_reused_planning")),
            "recommendation_time_ms": int(rec_obs.get("recommendation_time_ms") or 0),
            "recommendation_tokens": recommendation_tokens,
            "recommendation_score": float(rec_obs.get("recommendation_score") or 0),
            "selected_property": str(rec_obs.get("selected_property") or ""),
            "recommendation_cache_hit": bool(rec_obs.get("recommendation_cache_hit")),
            "recommendation_reuse_search": bool(rec_obs.get("recommendation_reuse_search")),
            "recommendation_reuse_analysis": bool(rec_obs.get("recommendation_reuse_analysis")),
            "recommendation_reuse_memory": bool(rec_obs.get("recommendation_reuse_memory")),
            "profile_build_time_ms": int(cm_obs.get("profile_build_time_ms") or 0),
            "relationship_score": float(cm_obs.get("relationship_score") or 0),
            "preference_count": int(cm_obs.get("preference_count") or 0),
            "profile_confidence": float(cm_obs.get("profile_confidence") or 0),
            "customer_memory_tokens": customer_memory_tokens,
            "customer_memory_cache_hit": bool(cm_obs.get("customer_memory_cache_hit")),
            "customer_memory_reuse_memory": bool(cm_obs.get("customer_memory_reuse_memory")),
            "customer_memory_reuse_workflow": bool(cm_obs.get("customer_memory_reuse_workflow")),
            "customer_memory_reuse_recommendation": bool(
                cm_obs.get("customer_memory_reuse_recommendation")
            ),
            "negotiation_time_ms": int(neg_obs.get("negotiation_time_ms") or 0),
            "negotiation_tokens": negotiation_tokens,
            "negotiation_confidence": float(neg_obs.get("negotiation_confidence") or 0),
            "negotiation_risk": float(neg_obs.get("negotiation_risk") or 0),
            "deal_probability": float(neg_obs.get("deal_probability") or 0),
            "negotiation_cache_hit": bool(neg_obs.get("negotiation_cache_hit")),
            "negotiation_reuse_analysis": bool(neg_obs.get("negotiation_reuse_analysis")),
            "negotiation_reuse_recommendation": bool(
                neg_obs.get("negotiation_reuse_recommendation")
            ),
            "negotiation_reuse_customer_profile": bool(
                neg_obs.get("negotiation_reuse_customer_profile")
            ),
            "customer_success_time_ms": int(cs_obs.get("customer_success_time_ms") or 0),
            "customer_success_tokens": customer_success_tokens,
            "customer_stage": str(cs_obs.get("customer_stage") or ""),
            "cs_conversion_probability": float(cs_obs.get("conversion_probability") or 0),
            "cs_next_action": str(cs_obs.get("next_action") or ""),
            "cs_priority": str(cs_obs.get("priority") or ""),
            "customer_success_confidence": float(cs_obs.get("customer_success_confidence") or 0),
            "customer_success_cache_hit": bool(cs_obs.get("customer_success_cache_hit")),
            "customer_success_reuse_analysis": bool(cs_obs.get("customer_success_reuse_analysis")),
            "customer_success_reuse_recommendation": bool(
                cs_obs.get("customer_success_reuse_recommendation")
            ),
            "customer_success_reuse_negotiation": bool(
                cs_obs.get("customer_success_reuse_negotiation")
            ),
            "customer_success_reuse_customer_profile": bool(
                cs_obs.get("customer_success_reuse_customer_profile")
            ),
            "parallel_tasks": int(parallel_obs.get("parallel_tasks") or 0),
            "parallel_execution_time_ms": int(parallel_obs.get("parallel_execution_time_ms") or 0),
            "parallel_merge_tokens": parallel_merge_tokens,
            "merged_agents": list(parallel_obs.get("merged_agents") or []),
            "parallel_skipped_agents": list(parallel_obs.get("skipped_agents") or []),
            "execution_graph": list(parallel_obs.get("execution_graph") or []),
            "decision_time_ms": int(decision_obs.get("decision_time_ms") or 0),
            "decision_score": float(decision_obs.get("decision_score") or 0),
            "decision_confidence": float(decision_obs.get("decision_confidence") or 0),
            "conflict_count": int(decision_obs.get("conflict_count") or 0),
            "alternative_count": int(decision_obs.get("alternative_count") or 0),
            "decision_selected_property": str(decision_obs.get("selected_property") or ""),
            "decision_tokens": decision_tokens,
            "conflict_resolve_time_ms": int(decision_obs.get("conflict_resolve_time_ms") or 0),
            "decision_next_step": str(decision_obs.get("next_step") or ""),
            "bi_market_score": float(bi_obs.get("market_score") or 0),
            "bi_property_score": float(bi_obs.get("property_score") or 0),
            "bi_lead_score": float(bi_obs.get("lead_score") or 0),
            "bi_trend_score": float(bi_obs.get("trend_score") or 0),
            "bi_opportunity_score": float(bi_obs.get("opportunity_score") or 0),
            "bi_analysis_time_ms": int(bi_obs.get("analysis_time_ms") or 0),
            "detected_role": str(conv_obs.get("detected_role") or ""),
            "detected_intent": str(conv_obs.get("detected_intent") or ""),
            "conversation_workflow": str(conv_obs.get("workflow") or ""),
            "workflow_name": str(conv_obs.get("workflow_name") or ""),
            "conversation_state": str(
                conv_obs.get("workflow_state") or conv_obs.get("conversation_state") or ""
            ),
            "conversation_step": str(conv_obs.get("current_step") or ""),
            "completed_fields": list(conv_obs.get("completed_fields") or []),
            "completed_steps": list(conv_obs.get("completed_steps") or []),
            "missing_fields": list(conv_obs.get("missing_fields") or []),
            "missing_steps": list(conv_obs.get("missing_steps") or []),
            "validation_errors": list(conv_obs.get("validation_errors") or []),
            "conversation_extra_tokens": int(conv_obs.get("conversation_extra_tokens") or 0),
            "workflow_extra_tokens": int(conv_obs.get("workflow_extra_tokens") or 0),
            "workflow_state": str(
                conv_obs.get("workflow_state")
                or adaptive_obs.get("workflow_state")
                or ""
            ),
            "confidence_score": float(adaptive_obs.get("confidence_score") or 0),
            "retry_count": int(adaptive_obs.get("retry_count") or 0),
            "recovery_count": int(adaptive_obs.get("recovery_count") or 0),
            "skipped_steps": list(adaptive_obs.get("skipped_steps") or []),
            "adaptive_extra_tokens": int(adaptive_obs.get("adaptive_extra_tokens") or 0),
            "total_tokens": input_tokens + output_tokens,
            "total_prompt_tokens": input_tokens,
            "prompt_tokens": input_tokens,
            "total_cost": usage_cost(usage),
            "response_time_ms": int((time.perf_counter() - started) * 1000),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "api_rounds": int(result.get("api_rounds") or 0),
            "cache_hit": bool((meta.get("provider") == "cache") if isinstance(meta, dict) else False),
        }
        record_token_analytics(row)
        # Phase 17.5: Evaluation & Observability — outside prompt, 0% token impact.
        try:
            from uuid import uuid4

            from app.evaluation.service import record_evaluation

            record_evaluation(
                analytics_row=row,
                request_id=str(row.get("request_id") or uuid4().hex[:16]),
            )
        except Exception:
            pass
        # Phase 24: Self Reflection — post-turn, outside prompt.
        try:
            from app.executive.service import get_executive_plan
            from app.self_reflection.service import run_reflection

            eplan = get_executive_plan()
            if eplan.get("run_reflection", True):
                shared = {}
                try:
                    from flask import g

                    shared = {
                        "goals": getattr(g, "ai_goals", None) or {},
                        "decision": getattr(g, "ai_decision", None) or {},
                    }
                except Exception:
                    pass
                run_reflection(analytics_row=row, shared=shared)
        except Exception:
            pass
    except Exception:
        pass
