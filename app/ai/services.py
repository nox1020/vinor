"""تماس HTTP با DeepSeek + آداپتور سازگاری `generate_reply`.

هدف محصول قفل: app/ai/goal.py · roadmap/AGENT_GOAL.md
یک ایجنت = یک بازاریاب؛ فروش فایل سیستم از چت.

ارکستراسیون یک نوبت چت به `app/ai/assistant.py` منتقل شده است. این ماژول اکنون
دو کار دارد:
  ۱) `_call_deepseek` — تنها پیاده‌سازی HTTP مدل (به همراه fallback مارکاپ DSML).
  ۲) `generate_reply` — همان امضای قبلی برای routeها و مسیرهای legacy.

نام‌های خصوصی قدیمی در پایان فایل به ماژول‌های جدید alias شده‌اند تا
scriptهای benchmark و token_diag بدون تغییر کار کنند.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

import requests
from flask import current_app

from .config import DEEPSEEK_BASE_URL, get_deepseek_api_key
from .credits import (
    budget_config,
    clear_api_balance_depleted,
    is_api_balance_depleted,
    is_spend_fuse_tripped,
    mark_api_balance_depleted,
    record_spend_usage,
    spend_fuse_status,
    SPEND_FUSE_ERROR,
)
from .runtime_settings import (
    assert_flash_model,
    get_ai_settings,
    model_choice_label,
    resolve_deepseek_model,
    thinking_enabled,
)


def ai_config() -> dict[str, Any]:
    api_key = get_deepseek_api_key()
    cfg = get_ai_settings()
    choice = str(cfg.get("model_choice") or "auto")
    fuse = spend_fuse_status()
    return {
        "enabled": bool(cfg.get("enabled")),
        "provider": "deepseek",
        "model_choice": choice,
        "model_choice_label": model_choice_label(choice),
        "model": resolve_deepseek_model(),
        "thinking_enabled": thinking_enabled(),
        "api_key_set": bool(api_key),
        "api_balance_ok": not is_api_balance_depleted(),
        "spend_fuse": fuse,
        "spend_fuse_ok": not bool(fuse.get("tripped")),
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
        tool_calls.extend(
            _parse_dsml_invokes(block.group(1), id_prefix=f"call_dsml_{bi}")
        )
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
    max_tokens: int | None = None,
    temperature: float | None = None,
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
    if is_spend_fuse_tripped():
        return {
            "ok": False,
            "error": SPEND_FUSE_ERROR,
            "error_code": "spend_fuse",
            "spend_fuse": True,
        }

    model = assert_flash_model(resolve_deepseek_model(has_tools=bool(tools)))
    url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    bcfg = budget_config()
    use_thinking = thinking_enabled()
    # با thinking، max_tokens خیلی کوچک ممکن است فقط reasoning بسوزاند و content خالی بماند
    raw_max = int(max_tokens) if max_tokens is not None else bcfg["max_tokens"]
    if use_thinking:
        raw_max = max(raw_max, 256)
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": raw_max,
        # V4 پیش‌فرض thinking روشن است — بدون این فلگ، هزاران توکن reasoning می‌سوزد.
        "thinking": {"type": "enabled" if use_thinking else "disabled"},
    }
    # temperature در thinking mode بی‌اثر است؛ فقط در حالت غیرفعال بفرست
    if not use_thinking:
        payload["temperature"] = (
            float(temperature) if temperature is not None else bcfg["temperature"]
        )
    # سقف سخت completion — حتی اگر caller عدد بزرگ بدهد
    payload["max_tokens"] = max(32, min(int(payload["max_tokens"]), 512))
    if tools is not None:
        payload["tools"] = tools
        if tools:
            payload["tool_choice"] = "auto"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        current_app.logger.info(
            "DeepSeek request | model=%s tools=%s choice=%s thinking=%s",
            model,
            len(tools) if tools else 0,
            get_ai_settings().get("model_choice"),
            "on" if use_thinking else "off",
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
            record_spend_usage(
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
            )
        except Exception:
            pass
        try:
            hit = int(usage.get("prompt_cache_hit_tokens") or 0)
            miss = int(usage.get("prompt_cache_miss_tokens") or 0)
            prompt_tok = usage.get("prompt_tokens")
            if hit or miss or prompt_tok:
                current_app.logger.info(
                    "DeepSeek tokens | model=%s prompt=%s cache_hit=%s cache_miss=%s "
                    "completion=%s tools=%s",
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


def generate_reply(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    user_key: str | None = None,
    phone: str | None = None,
    audience: str | None = None,
    thread_id: str | None = None,
    chip_intent: str | None = None,
    voice: str | None = None,
) -> dict[str, Any]:
    """آداپتور سازگاری — منطق واقعی در `VinorAssistant.handle`."""
    from .assistant import VinorAssistant

    return VinorAssistant().handle(
        message,
        user_key=(user_key or phone or "").strip(),
        audience=audience,
        thread_id=thread_id,
        chip_intent=chip_intent,
        voice=voice,
        history=history,
    )


# --- نام‌های قدیمی (scripts/benchmark_*, token_diag, تست‌ها) ----------------
from .postprocess import (  # noqa: E402
    enforce_response_style as _enforce_vinor_response_style,
    sanitize_unconfirmed_action_claims as _sanitize_unconfirmed_action_claims,
    strip_escalate_marker as _strip_escalate_marker,
    strip_listing_dump_when_copy_cards as _strip_listing_dump_when_copy_cards,
)
from .prompts import (  # noqa: E402
    LAND_MARKER_RE,
    append_internal_hint as _append_sales_hint,
    build_admin_ops_context as _build_admin_ops_context,
    build_messages as _build_messages,
    build_system_context as _build_system_prompt,
    get_memory_obs as _get_memory_obs,
    get_planning_obs as _get_planning_obs,
    normalize_chat_audience as _normalize_chat_audience,
    prompt_token_parts as _prompt_token_parts,
    summarize_older_history as _summarize_older_history,
)
from .request_analytics import (  # noqa: E402
    record_request_analytics as _record_request_analytics,
)
from .runner import (  # noqa: E402
    compact_tool_model_payload as _compact_tool_model_payload,
    run_agent_loop as _run_agent_loop,
)

__all__ = [
    "ai_config",
    "generate_reply",
    "_call_deepseek",
    "_build_messages",
    "_prompt_token_parts",
    "_run_agent_loop",
    "_compact_tool_model_payload",
    "_enforce_vinor_response_style",
    "LAND_MARKER_RE",
]
