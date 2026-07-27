"""تشخیص مصرف توکن prompt — JSONL با VINOR_AI_TOKEN_DIAG (پیش‌فرض روشن)."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from flask import current_app

from .token_analytics import estimate_messages_tokens, estimate_tokens

# آستانه‌های اعمال بهینه‌سازی شرطی (درصد از کل ورودی تخمینی)
THRESHOLD_HISTORY_PCT = 25.0
THRESHOLD_TOOLS_PCT = 20.0
THRESHOLD_SYSTEM_PCT = 15.0
THRESHOLD_MEMORY_PCT = 20.0


def token_diag_enabled() -> bool:
    return (os.environ.get("VINOR_AI_TOKEN_DIAG") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def threshold_fixes_enabled() -> bool:
    return (os.environ.get("VINOR_AI_TOKEN_THRESHOLD_FIX") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def estimate_tools_schema_tokens(tools: list[dict[str, Any]] | None) -> int:
    if not tools:
        return 0
    try:
        raw = json.dumps(tools, ensure_ascii=False)
    except Exception:
        raw = str(tools)
    # schema معمولاً ~۱.۱۵ برابر متن خام در API شمرده می‌شود؛ heuristic محافظه‌کار
    return max(1, int(estimate_tokens(raw) * 1.12))


def breakdown_prompt_sections(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    api_input_tokens: int | None = None,
) -> dict[str, Any]:
    """تفکیک بخش‌های پیام‌ها + ابزار (خارج از messages)."""
    from .services import _prompt_token_parts

    parts = _prompt_token_parts(messages)
    system_core = int(parts.get("system_prompt_tokens") or 0)
    context = int(parts.get("context_tokens") or 0)
    history = int(parts.get("history_tokens") or 0)
    user = int(parts.get("user_tokens") or 0)
    memory = int(parts.get("memory_tokens") or 0)
    tool_results = int(parts.get("execution_tokens") or 0)
    developer = 0
    rag_extra = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        if role == "developer":
            developer += estimate_tokens(str(m.get("content") or ""))

    layer_keys = (
        "planning_tokens",
        "analysis_tokens",
        "recommendation_tokens",
        "customer_memory_tokens",
        "negotiation_tokens",
        "customer_success_tokens",
        "parallel_merge_tokens",
        "decision_tokens",
    )
    layer_total = sum(int(parts.get(k) or 0) for k in layer_keys)
    tools_tok = estimate_tools_schema_tokens(tools)
    msg_est = estimate_messages_tokens(messages)
    estimated_input = msg_est + tools_tok
    total_in = int(api_input_tokens) if api_input_tokens else estimated_input

    def pct(n: int) -> float:
        return round(100.0 * n / total_in, 1) if total_in else 0.0

    system_all = system_core + layer_total
    memory_all = memory + int(parts.get("customer_memory_tokens") or 0)
    rag_all = context + rag_extra

    flags = _behavior_flags(messages, tools=tools)

    return {
        "system_tokens": system_core,
        "system_layer_tokens": layer_total,
        "system_total_tokens": system_all,
        "developer_tokens": developer,
        "history_tokens": history,
        "memory_tokens": memory_all,
        "rag_context_tokens": rag_all,
        "tool_schema_tokens": tools_tok,
        "tool_result_tokens": tool_results,
        "user_tokens": user,
        "estimated_messages_tokens": msg_est,
        "estimated_input_tokens": estimated_input,
        "api_input_tokens": int(api_input_tokens or 0),
        "input_tokens_used": total_in,
        "pct_system": pct(system_all),
        "pct_history": pct(history),
        "pct_memory": pct(memory_all),
        "pct_rag": pct(rag_all),
        "pct_tools": pct(tools_tok),
        "pct_user": pct(user),
        "pct_tool_results": pct(tool_results),
        "flags": flags,
        "parts_raw": parts,
    }


def _behavior_flags(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
) -> dict[str, bool]:
    hist_user_asst = sum(
        1
        for m in messages
        if isinstance(m, dict) and str(m.get("role") or "") in ("user", "assistant")
    )
    has_summary = any(
        isinstance(m, dict)
        and str(m.get("role") or "") == "system"
        and "خلاصه گفتگو" in str(m.get("content") or "")
        for m in messages
    )
    has_property_ctx = any(
        isinstance(m, dict)
        and str(m.get("role") or "") == "system"
        and ("--- آگهی" in str(m.get("content") or "") or "--- فایل" in str(m.get("content") or ""))
        for m in messages
    )
    has_goal = any(
        isinstance(m, dict)
        and str(m.get("role") or "") == "system"
        and "وینور" in str(m.get("content") or "")[:200]
        for m in messages
    )
    mem_block = any(
        isinstance(m, dict)
        and str(m.get("role") or "") == "system"
        and "=== حافظه مرتبط کاربر ===" in str(m.get("content") or "")
        for m in messages
    )
    return {
        "full_history_each_request": hist_user_asst > 0 and not has_summary,
        "history_summary_built": has_summary,
        "tool_schema_sent": bool(tools),
        "tool_schema_resent_each_api_round": bool(tools),
        "property_context_in_prompt": has_property_ctx,
        "vinor_rules_resent": has_goal,
        "agent_base_prompt_rebuilt": has_goal,
        "memory_full_inject": mem_block,
        "memory_retrieval_mode": mem_block,
    }


def apply_threshold_fixes(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    voice: str,
    user_message: str = "",
    chip_intent: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None, dict[str, Any]]:
    """بهینه‌سازی شرطی بدون تغییر منطق کسب‌وکار — فقط وقتی آستانه رد شود."""
    applied: dict[str, Any] = {}
    if not threshold_fixes_enabled():
        return messages, tools, applied

    bd = breakdown_prompt_sections(messages, tools=tools)
    total = int(bd.get("estimated_input_tokens") or 0) or 1

    msgs = list(messages)
    tlist = list(tools) if tools else None

    if float(bd.get("pct_history") or 0) >= THRESHOLD_HISTORY_PCT:
        trimmed = _trim_history_messages(msgs, target_pct=THRESHOLD_HISTORY_PCT - 5, total_est=total)
        if trimmed:
            msgs = trimmed
            applied["history_sliding_window"] = True

    if float(bd.get("pct_tools") or 0) >= THRESHOLD_TOOLS_PCT and tlist:
        try:
            from .tools.selection import per_round_tool_selection_enabled

            if per_round_tool_selection_enabled():
                pass  # انتخاب در _run_agent_loop هر دور جداگانه
            else:
                from .agent_tools import tools_schema_subset_for_request

                subset = tools_schema_subset_for_request(
                    voice,
                    user_message=user_message,
                    chip_intent=chip_intent,
                    schemas=tlist,
                )
                if subset and len(subset) < len(tlist):
                    tlist = subset
                    applied["dynamic_tool_subset"] = True
        except Exception:
            from .agent_tools import tools_schema_subset_for_request

            subset = tools_schema_subset_for_request(
                voice,
                user_message=user_message,
                chip_intent=chip_intent,
                schemas=tlist,
            )
            if subset and len(subset) < len(tlist):
                tlist = subset
                applied["dynamic_tool_subset"] = True

    if float(bd.get("pct_system") or 0) >= THRESHOLD_SYSTEM_PCT:
        stripped = _lazy_drop_optional_system_modules(msgs)
        if stripped:
            msgs = stripped
            applied["system_lazy_modules"] = True

    if float(bd.get("pct_memory") or 0) >= THRESHOLD_MEMORY_PCT:
        msgs = _shrink_memory_blocks(msgs, ratio=0.55)
        applied["memory_retrieval_cap"] = True

    return msgs, tlist, applied


def _trim_history_messages(
    messages: list[dict[str, Any]],
    *,
    target_pct: float,
    total_est: int,
) -> list[dict[str, Any]] | None:
    """حذف قدیمی‌ترین جفت user/assistant از میانهٔ لیست."""
    head: list[dict[str, Any]] = []
    hist: list[dict[str, Any]] = []
    tail: list[dict[str, Any]] = []
    past_system = True
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        if past_system and role == "system":
            head.append(m)
            continue
        past_system = False
        if role in ("user", "assistant", "tool"):
            hist.append(m)
        else:
            tail.append(m)
    if len(hist) < 4:
        return None
    out_hist = list(hist)
    changed = False
    while out_hist and estimate_tokens(str(out_hist[0].get("content") or "")) > 0:
        hist_tok = sum(estimate_tokens(str(x.get("content") or "")) for x in out_hist)
        if 100.0 * hist_tok / max(1, total_est) <= target_pct:
            break
        out_hist.pop(0)
        if out_hist and str(out_hist[0].get("role") or "") == str(hist[0].get("role") or ""):
            pass
        changed = True
        if len(out_hist) < 2:
            break
    if not changed:
        return None
    return head + out_hist + tail


def _lazy_drop_optional_system_modules(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """حذف hintهای فروش/قیف اختیاری؛ base prompt و context حفظ می‌شود."""
    optional_markers = (
        "=== پیگیری ===",
        "=== مذاکره ===",
        "=== پیشنهاد فایل ===",
        "=== تحلیل فایل ===",
        "=== همکاری ===",
        "=== تصمیم ===",
        "=== یافتهٔ برنامه‌ریز ===",
        "مرحلهٔ قیف",
    )
    out: list[dict[str, Any]] = []
    dropped = 0
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        if str(m.get("role") or "") != "system":
            out.append(m)
            continue
        content = str(m.get("content") or "")
        if any(mark in content for mark in optional_markers):
            dropped += 1
            continue
        out.append(m)
    return out if dropped else None


def _shrink_memory_blocks(messages: list[dict[str, Any]], *, ratio: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        content = str(m.get("content") or "")
        if str(m.get("role") or "") == "system" and "=== حافظه مرتبط کاربر ===" in content:
            cap = max(80, int(len(content) * ratio))
            content = content[:cap].rstrip() + "…"
            out.append({**m, "content": content})
        else:
            out.append(m)
    return out


def merge_tool_selection_into_breakdown(
    payload: dict[str, Any],
    tool_selection: dict[str, Any] | None,
) -> dict[str, Any]:
    """فیلدهای گزارش per-request برای schema ابزار."""
    out = dict(payload)
    ts = tool_selection if isinstance(tool_selection, dict) else {}
    sent = int(ts.get("tools_sent_count") or 0)
    used_n = int(ts.get("tools_actually_used_count") or 0)
    schema_tok = int(ts.get("tool_schema_tokens") or 0)
    if schema_tok <= 0 and sent > 0:
        schema_tok = int(out.get("tool_schema_tokens") or 0)
    if schema_tok > 0:
        out["tool_schema_tokens"] = schema_tok
    out["tools_sent_count"] = sent
    out["tools_actually_used_count"] = used_n
    out["tools_actually_used"] = list(ts.get("tools_actually_used") or [])
    rounds = ts.get("tool_rounds")
    if isinstance(rounds, list):
        out["tool_rounds"] = rounds
    flags = dict(out.get("flags") or {})
    if ts.get("per_round_tools") is not None:
        flags["per_round_tool_selection"] = bool(ts.get("per_round_tools"))
    if rounds and len(rounds) > 1:
        flags["tool_schema_resent_each_api_round"] = any(
            int(r.get("tools_sent") or 0) > 0 for r in rounds[1:]
        )
    elif sent > 0:
        flags["tool_schema_resent_each_api_round"] = False
    out["flags"] = flags
    return out


def record_token_breakdown(
    payload: dict[str, Any],
    *,
    user_key: str = "",
    audience: str = "",
    voice: str = "",
    output_tokens: int = 0,
    fixes_applied: dict[str, Any] | None = None,
    tool_selection: dict[str, Any] | None = None,
) -> None:
    if not token_diag_enabled():
        return
    path = _breakdown_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = merge_tool_selection_into_breakdown(payload, tool_selection)
    row["ts"] = int(time.time())
    row["user"] = user_key
    row["audience"] = audience
    row["voice"] = voice
    row["output_tokens"] = int(output_tokens or 0)
    if fixes_applied:
        row["fixes_applied"] = fixes_applied
    line = json.dumps(row, ensure_ascii=False)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _breakdown_path() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "instance"))
    return os.path.join(base, "data", "ai_token_breakdown.jsonl")
