"""حلقهٔ کوتاه tool-calling — حداکثر ۱ دور ابزار سپس پاسخ نهایی.

این تنها جایی است که مدل و ابزار با هم حرف می‌زنند. مجوز ابزار در
`agent_tools.run_tool` دوباره بررسی می‌شود. قبلاً `services._run_agent_loop` بود.
"""
from __future__ import annotations

import json
from typing import Any

MAX_TOOL_ROUNDS = 1  # ۱ دور ابزار + ۱ پاسخ نهایی
MAX_TOOL_RESULT_CHARS = 800

# کلیدهای سنگین/تکراری که برای مدل لازم نیستند
_TOOL_RESULT_DROP_KEYS = frozenset(
    {
        "available_dates",  # labels کافی است
        "copies",  # متن کامل در کارت UI است
        "copy_blocks_count",
        "payload",
    }
)


def compact_tool_model_payload(payload: Any) -> Any:
    """کاهش حجم JSON برگشتی ابزار برای مدل بدون حذف وضعیت/instruction."""
    if not isinstance(payload, dict):
        return payload
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in _TOOL_RESULT_DROP_KEYS:
            continue
        if k == "lands" and isinstance(v, list):
            slim: list[Any] = []
            for row in v[:3]:
                if not isinstance(row, dict):
                    continue
                slim.append(
                    {
                        "code": row.get("code"),
                        "title": str(row.get("title") or "")[:80],
                        "summary": str(row.get("summary") or "")[:160],
                        "city": row.get("city"),
                        "assigned": row.get("assigned"),
                    }
                )
            out[k] = slim
        elif k == "instruction" and isinstance(v, str) and len(v) > 220:
            out[k] = v[:217] + "…"
        elif k == "note" and isinstance(v, str) and len(v) > 160:
            out[k] = v[:157] + "…"
        else:
            out[k] = v
    return out


def tool_selection_payload(
    tool_rounds: list[dict[str, Any]],
    tools_used: set[str],
    schema_tokens_total: int,
) -> dict[str, Any]:
    from .tools.selection import per_round_tool_selection_enabled

    sent_counts = [int(r.get("tools_sent") or 0) for r in tool_rounds]
    tools_sent_count = max(sent_counts) if sent_counts else 0
    used_list = sorted(tools_used)
    return {
        "tools_sent_count": tools_sent_count,
        "tools_actually_used_count": len(used_list),
        "tools_actually_used": used_list,
        "tool_schema_tokens": int(schema_tokens_total),
        "tool_rounds": tool_rounds,
        "per_round_tools": per_round_tool_selection_enabled(),
    }


def run_agent_loop(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    phone: str,
    audience: str,
    voice: str,
    thread_id: str | None = None,
    max_tokens: int | None = None,
    user_message: str = "",
    chip_intent: str = "",
) -> dict[str, Any]:
    from .agent_tools import parse_tool_arguments
    from .card_registry import normalize_card
    from .provider import call_model
    from .token_diag import estimate_tools_schema_tokens
    from .tools.registry import execute as execute_tool
    from .tools.selection import (
        per_round_tool_selection_enabled,
        select_tools_for_api_round,
    )

    agent_actions: list[dict[str, Any]] = []
    tool_land_codes: list[str] = []
    result: dict[str, Any] = {"ok": False, "error": "پاسخی دریافت نشد."}
    api_rounds = 0
    tool_catalog = list(tools) if tools else None
    tools_used: set[str] = set()
    tool_rounds: list[dict[str, Any]] = []
    schema_tokens_total = 0
    payload_profiler_rounds: list[dict[str, Any]] = []

    def _stash_payload_profiler_rounds() -> None:
        if not payload_profiler_rounds:
            return
        try:
            from flask import g

            g.ai_payload_profiler_rounds = payload_profiler_rounds
        except Exception:
            pass

    for round_i in range(MAX_TOOL_ROUNDS + 1):
        if per_round_tool_selection_enabled():
            round_tools = select_tools_for_api_round(
                voice,
                round_index=round_i,
                max_tool_rounds=MAX_TOOL_ROUNDS,
                user_message=user_message,
                chip_intent=chip_intent,
                messages=messages,
                catalog=tool_catalog,
                user_key=phone,
                thread_id=thread_id or "",
            )
        else:
            allow_tools = bool(tool_catalog) and round_i < MAX_TOOL_ROUNDS
            round_tools = list(tool_catalog) if allow_tools and tool_catalog else []

        round_tok = estimate_tools_schema_tokens(round_tools)
        schema_tokens_total += round_tok
        tool_rounds.append(
            {
                "round": round_i,
                "tools_sent": len(round_tools),
                "tool_names": [
                    str(
                        (t.get("function") or {}).get("name") or ""
                        if isinstance(t, dict)
                        else ""
                    ).strip()
                    for t in round_tools
                    if isinstance(t, dict)
                ],
                "tool_schema_tokens": round_tok,
            }
        )

        try:
            from .payload_profiler import (
                payload_profiler_enabled,
                profile_messages_for_round,
            )

            if payload_profiler_enabled():
                payload_profiler_rounds.append(
                    profile_messages_for_round(
                        messages,
                        round_tools,
                        round_index=round_i,
                        tools_sent=len(round_tools),
                    )
                )
        except Exception:
            pass

        result = call_model(messages, tools=round_tools, max_tokens=max_tokens)
        api_rounds += 1
        if not result.get("ok"):
            break

        tool_calls = result.get("tool_calls") if round_tools else None
        if not isinstance(tool_calls, list):
            tool_calls = []
        if not tool_calls:
            break

        asst_msg: dict[str, Any] = {
            "role": "assistant",
            "content": result.get("reply") or None,
            "tool_calls": tool_calls,
        }
        # Thinking mode: reasoning_content فقط وقتی واقعاً هست باید برگردد.
        rc = result.get("reasoning_content")
        if isinstance(rc, str) and rc.strip():
            asst_msg["reasoning_content"] = rc
        messages.append(asst_msg)

        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            tc_id = str(tc.get("id") or "")
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = str(fn.get("name") or "").strip()
            if name:
                tools_used.add(name)
            args = parse_tool_arguments(fn.get("arguments"))
            tool_out = execute_tool(
                name,
                args,
                phone=phone,
                audience=audience,
                voice=voice,
                thread_id=thread_id,
            )
            ui = tool_out.get("ui_action")
            if isinstance(ui, dict):
                agent_actions.append(normalize_card(ui))
            # کارت فایل: جستجوی فروش یا جستجوی ادمین با show_cards
            if name in ("search_lands", "admin_search_lands"):
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
            model_payload = compact_tool_model_payload(model_payload)
            try:
                content = json.dumps(model_payload, ensure_ascii=False)[
                    :MAX_TOOL_RESULT_CHARS
                ]
            except Exception:
                content = str(model_payload)[:MAX_TOOL_RESULT_CHARS]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": content,
                }
            )
            # مرحلهٔ اجباری بازدید: متن را خود سیستم بگوید (مدل چیزی اختراع نکند)
            speak = ""
            if isinstance(model_payload, dict):
                speak = str(model_payload.get("speak_exactly") or "").strip()
            if speak:
                _stash_payload_profiler_rounds()
                return {
                    "ok": True,
                    "reply": speak,
                    "agent_actions": list(agent_actions),
                    "tool_land_codes": tool_land_codes,
                    "api_rounds": api_rounds,
                    "meta": result.get("meta")
                    if isinstance(result.get("meta"), dict)
                    else {"provider": "deepseek"},
                    "tool_selection": tool_selection_payload(
                        tool_rounds, tools_used, schema_tokens_total
                    ),
                }

    _stash_payload_profiler_rounds()

    if result.get("ok"):
        result["agent_actions"] = agent_actions
        result["tool_land_codes"] = tool_land_codes
        result["api_rounds"] = api_rounds
        result["tool_selection"] = tool_selection_payload(
            tool_rounds, tools_used, schema_tokens_total
        )
    return result
