"""ساخت prompt چت وینور — از config.py / goal.py / context.py مونتاژ می‌شود.

هیچ متن هدف/هویت اینجا تکرار نمی‌شود: `prompt_for_voice` و `GOAL_SYSTEM` منبع
حقیقت می‌مانند و این ماژول فقط ترتیب پیام‌ها، بودجهٔ کاراکتر، حافظه و تاریخچه
را می‌چیند. قبلاً همین کد داخل `services.py` بود.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from flask import current_app

from .audience import (
    AUDIENCE_ADMIN,
    AUDIENCE_PARTNER,
    AUDIENCE_PUBLIC,
    resolve_ai_voice,
)
from .config import prompt_for_voice
from .context import (
    append_admin_answers_block,
    build_partner_context_base,
    build_partner_land_context,
    build_partner_status_context,
    build_public_context_base,
    build_public_land_context,
)
from .context_cache import get_partner_context_base, get_public_context_base
from .credits import budget_config
from .escalations import consume_pending_answers
from .goal import wrap_internal_hint
from .token_analytics import estimate_tokens

LAND_MARKER_RE = re.compile(r"\[\[LAND:[^\]]+\]\]\s*", re.IGNORECASE)

_PROMPT_CACHE: dict[str, tuple[float, str]] = {}


def _prompt_cache_ttl_sec() -> float:
    try:
        from .prompt_optimize import prompt_cache_ttl_sec

        return float(prompt_cache_ttl_sec())
    except Exception:
        return 20.0


def _get_prompt_cache(key: str) -> str | None:
    item = _PROMPT_CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if (time.time() - ts) > _prompt_cache_ttl_sec():
        _PROMPT_CACHE.pop(key, None)
        return None
    return value


def _set_prompt_cache(key: str, value: str) -> None:
    _PROMPT_CACHE[key] = (time.time(), value)
    if len(_PROMPT_CACHE) > 600:
        old_keys = sorted(_PROMPT_CACHE.items(), key=lambda x: x[1][0])[:100]
        for k, _ in old_keys:
            _PROMPT_CACHE.pop(k, None)


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


def normalize_chat_audience(audience: str | None) -> str:
    if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC, AUDIENCE_ADMIN):
        return audience
    return AUDIENCE_PARTNER


def append_internal_hint(messages: list[dict[str, Any]], content: str | None) -> None:
    """Hint داخلی را زیر هویت تک‌بازاریاب به پیام‌ها اضافه کن."""
    wrapped = wrap_internal_hint(content)
    if wrapped:
        messages.append({"role": "system", "content": wrapped})


# --- حافظه (یک فراخوان به app.memory.service) ------------------------------


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


def _system_memory_prompt_for_messages() -> str:
    """دانش مشترک کسب‌وکار برای یک پیام system جدا (fail-open)."""
    try:
        from app.memory.config import system_memory_budget_chars
        from app.memory.system_store import system_memory_prompt_text

        budget = system_memory_budget_chars()
        try:
            from .prompt_optimize import system_memory_char_budget

            budget = system_memory_char_budget(budget)
        except Exception:
            pass
        return (system_memory_prompt_text(max_chars=budget) or "").strip()
    except Exception:
        return ""


def get_memory_obs() -> dict[str, int]:
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


def set_planning_obs(outcome: Any) -> None:
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


def get_planning_obs() -> dict[str, Any]:
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


def build_admin_ops_context() -> str:
    """خلاصهٔ کوتاه صف عملیات برای prompt ادمین."""
    try:
        from .admin_tools import _tool_ops_summary

        out = _tool_ops_summary()
        model = out.get("model_result") if isinstance(out, dict) else None
        if not isinstance(model, dict) or not model.get("ok"):
            return "مخاطب: ادمین عملیات وینور."
        return (
            "مخاطب: ادمین عملیات وینور.\n"
            f"صف: همکاران معلق={model.get('pending_partner_apps', 0)}، "
            f"فایل معلق={model.get('pending_listings', 0)}، "
            f"بازدید={model.get('pending_visits', 0)}، "
            f"پورسانت={model.get('pending_commissions', 0)}، "
            f"برداشت={model.get('open_withdrawals', 0)}، "
            f"escalation={model.get('pending_escalations', 0)}."
        )
    except Exception:
        return "مخاطب: ادمین عملیات وینور."


def build_system_context(
    user_key: str | None,
    audience: str | None = None,
    *,
    user_message: str = "",
    thread_id: str | None = None,
    max_context_chars: int | None = None,
    retrieve_user_memory: bool = True,
) -> str:
    """بلوک «اطلاعات داخلی وینور» — فقط فایل‌های مرتبط، نه کل lands.json."""
    aud = (
        audience
        if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC, AUDIENCE_ADMIN)
        else AUDIENCE_PARTNER
    )
    if not user_key:
        return ""
    max_ctx = (
        int(max_context_chars)
        if max_context_chars is not None
        else budget_config()["max_context_chars"]
    )
    focus_codes: list[str] = []
    try:
        from .chat_store import recent_thread_land_codes

        focus_codes = recent_thread_land_codes(
            user_key, thread_id, audience=aud, limit=3
        )
    except Exception:
        focus_codes = []
    # تضمین: فایل موضوع گفتگو هم در فوکوس بیاید حتی اگر هنوز در messages نباشد
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
        elif aud == AUDIENCE_ADMIN:
            ctx = build_admin_ops_context()
            _set_prompt_cache(core_cache_key, ctx)
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
            land_ctx = build_public_land_context(user_message, focus_codes=focus_codes)
            ctx = base
            if land_ctx:
                ctx = f"{base}\n{land_ctx}"
            _set_prompt_cache(core_cache_key, ctx)
        notes = consume_pending_answers(user_key, audience=aud)
        ctx = append_admin_answers_block(ctx, notes)
        if retrieve_user_memory:
            mem_text, mem_meta = _memory_block_for_prompt(
                user_key=user_key,
                audience=aud,
                user_message=user_message,
                thread_id=thread_id,
                remaining_chars=max(0, max_ctx - len(ctx)),
            )
            _set_memory_obs(mem_meta)
            _set_memory_prompt_text(mem_text)
        else:
            _set_memory_obs(
                {
                    "memory_retrieved": 0,
                    "memory_used": 0,
                    "memory_tokens": 0,
                }
            )
            _set_memory_prompt_text("")
        return ctx[:max_ctx]
    except Exception as exc:
        try:
            current_app.logger.warning("AI context build failed: %s", exc)
        except Exception:
            pass
        return ""


def trim_history_content(role: str, content: str, cfg: dict[str, Any]) -> str:
    text = (content or "").strip()
    if role == "assistant":
        text = LAND_MARKER_RE.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        limit = int(cfg.get("max_assistant_history_chars") or cfg["max_msg_chars"])
    else:
        limit = int(cfg["max_msg_chars"])
    return text[:limit]


def summarize_older_history(
    history: list[dict[str, str]] | None,
    *,
    keep_last: int,
    pick: int = 6,
    char_cap: int = 80,
) -> str:
    if (os.environ.get("VINOR_HISTORY_SUMMARY") or "1").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return ""
    rows = [h for h in (history or []) if isinstance(h, dict)]
    if len(rows) <= max(0, int(keep_last)):
        return ""
    older = rows[: -int(keep_last)]
    n_pick = max(1, min(12, int(pick or 6)))
    picked = older[-n_pick:]
    cap = max(40, min(120, int(char_cap or 80)))
    bits: list[str] = []
    for item in picked:
        role = str(item.get("role") or "").strip()
        if role not in ("user", "assistant"):
            continue
        content = re.sub(r"\s+", " ", str(item.get("content") or "").strip())
        if not content:
            continue
        prefix = "کاربر" if role == "user" else "دستیار"
        bits.append(f"{prefix}: {content[:cap]}")
    if not bits:
        return ""
    return "خلاصه گفتگوهای قبلی:\n- " + "\n- ".join(bits[:n_pick])


def build_messages(
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
    """پیام‌های کامل یک نوبت چت: system → context → حافظه → تاریخچه → کاربر."""
    from .agent_budget import agent_budget
    from .agent_tools import agent_system_hint

    aud = normalize_chat_audience(audience)
    cfg = budget_config()
    resolved_voice = voice or resolve_ai_voice(phone=user_key or "", audience=aud)

    ab = agent_budget(resolved_voice)
    keep_last = int(ab.get("max_history") or cfg["max_history"])
    base_prompt = prompt_for_voice(resolved_voice)
    messages: list[dict[str, Any]] = [{"role": "system", "content": base_prompt}]
    if with_tools:
        try:
            from .prompt_optimize import skip_redundant_tool_hint

            inject_tool_hint = not skip_redundant_tool_hint()
        except Exception:
            inject_tool_hint = True
        if inject_tool_hint:
            messages.append(
                {"role": "system", "content": agent_system_hint(resolved_voice)}
            )
    if chip_intent and ab.get("inject_partner_context", True):
        try:
            from .prompt_optimize import skip_redundant_sales_hints

            skip_chip = with_tools and skip_redundant_sales_hints()
        except Exception:
            skip_chip = False
        if not skip_chip:
            from .intents import hint_for_chip_intent

            hint = hint_for_chip_intent(chip_intent)
            if hint:
                append_internal_hint(messages, hint)
    if user_key and ab.get("inject_partner_context", True):
        # گفتگوی تازه: حافظهٔ سراسری را تزریق نکن تا ادامهٔ چت قبلی حس نشود
        hist_has_user = any(
            isinstance(h, dict) and str(h.get("role") or "") == "user"
            for h in (history or [])
        )
        use_memory = bool(ab.get("inject_user_memory", True)) and hist_has_user
        ctx = build_system_context(
            user_key,
            audience,
            user_message=text,
            thread_id=thread_id,
            max_context_chars=int(
                ab.get("max_context_chars") or cfg["max_context_chars"]
            ),
            retrieve_user_memory=use_memory,
        )
        if ctx:
            messages.append({"role": "system", "content": ctx})
    if ab.get("inject_system_memory", True):
        sys_mem = _system_memory_prompt_for_messages()
        if sys_mem:
            messages.append({"role": "system", "content": sys_mem})
    hist_has_user = any(
        isinstance(h, dict) and str(h.get("role") or "") == "user"
        for h in (history or [])
    )
    if user_key and ab.get("inject_user_memory", True) and hist_has_user:
        mem_text = _get_memory_prompt_text()
        if mem_text:
            messages.append({"role": "system", "content": mem_text})
    if user_key and ab.get("inject_funnel_hint", True) and hist_has_user:
        try:
            from .prompt_optimize import skip_redundant_sales_hints

            skip_funnel = skip_redundant_sales_hints()
        except Exception:
            skip_funnel = False
        if not skip_funnel:
            try:
                from app.supervisor.funnel_service import chat_hint

                fh = chat_hint(user_key)
                if fh:
                    append_internal_hint(messages, fh)
            except Exception:
                pass
    if history:
        try:
            from .prompt_optimize import effective_history_params

            hp = effective_history_params(keep_last)
        except Exception:
            hp = {"window_extra": 6, "summary_pick": 6, "summary_char_cap": 80}
        hist_window = list(history[-(keep_last + int(hp.get("window_extra") or 6)) :])
        summary = summarize_older_history(
            hist_window,
            keep_last=keep_last,
            pick=int(hp.get("summary_pick") or 6),
            char_cap=int(hp.get("summary_char_cap") or 80),
        )
        if summary:
            reduced_keep = max(2, keep_last - 2)
            dropped = (
                hist_window[-keep_last:-reduced_keep] if keep_last > reduced_keep else []
            )
            dropped_tokens = 0
            for item in dropped:
                if isinstance(item, dict):
                    dropped_tokens += estimate_tokens(str(item.get("content") or ""))
            if estimate_tokens(summary) < dropped_tokens:
                messages.append({"role": "system", "content": summary})
                keep_last = reduced_keep
        for item in hist_window[-keep_last:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = trim_history_content(role, str(item.get("content") or ""), cfg)
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text[: cfg["max_msg_chars"]]})
    return messages


def prompt_token_parts(messages: list[dict[str, Any]]) -> dict[str, int]:
    """تفکیک توکن پیام‌ها برای گزارش مصرف."""
    parts = {
        "system_prompt_tokens": 0,
        "context_tokens": 0,
        "history_tokens": 0,
        "user_tokens": 0,
        "memory_tokens": 0,
    }
    section_keys = {
        "=== یافتهٔ برنامه‌ریز ===": "planning_tokens",
        "=== تحلیل فایل ===": "analysis_tokens",
        "=== پیشنهاد فایل ===": "recommendation_tokens",
        "=== پروفایل مشتری ===": "customer_memory_tokens",
        "=== مذاکره ===": "negotiation_tokens",
        "=== پیگیری ===": "customer_success_tokens",
        "=== همکاری ===": "parallel_merge_tokens",
        "=== تصمیم ===": "decision_tokens",
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
            else:
                matched = next(
                    (key for marker, key in section_keys.items() if marker in content),
                    "",
                )
                if matched:
                    parts[matched] = parts.get(matched, 0) + tok
                elif (
                    "=== اطلاعات داخلی وینور ===" in content
                    or "--- آگهی" in content
                    or "--- فایل" in content
                ):
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
    for key in section_keys.values():
        parts.setdefault(key, 0)
    parts.setdefault("execution_tokens", 0)
    return parts
