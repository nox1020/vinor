"""Pre-call payload token profiler — تخمین بخش‌ها قبل از ارسال به DeepSeek."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from flask import current_app

from .token_diag import breakdown_prompt_sections

_LOG = logging.getLogger(__name__)

_SECTION_KEYS = (
    "system_tokens",
    "developer_tokens",
    "user_tokens",
    "history_tokens",
    "tool_schema_tokens",
    "memory_tokens",
    "rag_tokens",
    "tool_result_tokens",
)


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def payload_profiler_enabled() -> bool:
    return _env_bool("VINOR_AI_PAYLOAD_PROFILER", "1")


def profile_messages_for_round(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    round_index: int = 0,
    tools_sent: int | None = None,
) -> dict[str, Any]:
    """تخمین توکن هر بخش payload همان دور (قبل از call_ai)."""
    bd = breakdown_prompt_sections(messages, tools=tools, api_input_tokens=None)
    system_tok = int(bd.get("system_total_tokens") or 0)
    developer_tok = int(bd.get("developer_tokens") or 0)
    user_tok = int(bd.get("user_tokens") or 0)
    history_tok = int(bd.get("history_tokens") or 0)
    tool_schema_tok = int(bd.get("tool_schema_tokens") or 0)
    memory_tok = int(bd.get("memory_tokens") or 0)
    rag_tok = int(bd.get("rag_context_tokens") or 0)
    tool_result_tok = int(bd.get("tool_result_tokens") or 0)
    total = int(bd.get("estimated_input_tokens") or 0)
    if total <= 0:
        total = (
            system_tok
            + developer_tok
            + user_tok
            + history_tok
            + tool_schema_tok
            + memory_tok
            + rag_tok
            + tool_result_tok
        )

    sent = tools_sent
    if sent is None:
        sent = len(tools) if tools else 0

    return {
        "round": int(round_index),
        "system_tokens": system_tok,
        "developer_tokens": developer_tok,
        "user_tokens": user_tok,
        "history_tokens": history_tok,
        "tool_schema_tokens": tool_schema_tok,
        "memory_tokens": memory_tok,
        "rag_tokens": rag_tok,
        "tool_result_tokens": tool_result_tok,
        "total_payload_tokens": total,
        "tools_sent": int(sent),
        "estimated_messages_tokens": int(bd.get("estimated_messages_tokens") or 0),
    }


def delta_round0_round1(
    round0: dict[str, Any],
    round1: dict[str, Any],
) -> dict[str, Any]:
    """اختلاف توکن بین دور ۰ و ۱ (مثبت = رشد در دور ۱)."""
    out: dict[str, Any] = {}
    for key in _SECTION_KEYS + ("total_payload_tokens",):
        a = int(round0.get(key) or 0)
        b = int(round1.get(key) or 0)
        out[key] = b - a
    out["round0_total"] = int(round0.get("total_payload_tokens") or 0)
    out["round1_total"] = int(round1.get("total_payload_tokens") or 0)
    return out


def merge_request_summary(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    """درصد سهم هر بخش بر اساس آخرین دور pre-call + دلتای ۰→۱."""
    if not rounds:
        return {"rounds": [], "shares_pct": {}}

    last = rounds[-1]
    total = int(last.get("total_payload_tokens") or 0) or 1

    def pct(n: int) -> float:
        return round(100.0 * n / total, 1)

    shares = {
        "system_tokens": pct(int(last.get("system_tokens") or 0)),
        "developer_tokens": pct(int(last.get("developer_tokens") or 0)),
        "user_tokens": pct(int(last.get("user_tokens") or 0)),
        "history_tokens": pct(int(last.get("history_tokens") or 0)),
        "tool_schema_tokens": pct(int(last.get("tool_schema_tokens") or 0)),
        "memory_tokens": pct(int(last.get("memory_tokens") or 0)),
        "rag_tokens": pct(int(last.get("rag_tokens") or 0)),
        "tool_result_tokens": pct(int(last.get("tool_result_tokens") or 0)),
    }

    summary: dict[str, Any] = {
        "rounds": list(rounds),
        "shares_pct": shares,
        "final_round_total_tokens": total,
        "api_rounds_profiled": len(rounds),
    }
    if len(rounds) >= 2:
        summary["delta_round0_round1"] = delta_round0_round1(rounds[0], rounds[1])
    return summary


def _profile_log_path() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "instance"))
    return os.path.join(base, "data", "ai_payload_profile.jsonl")


def _format_shares_log(shares: dict[str, float]) -> str:
    labels = (
        ("system_tokens", "سیستم"),
        ("developer_tokens", "توسعه‌دهنده"),
        ("user_tokens", "کاربر"),
        ("history_tokens", "تاریخچه"),
        ("tool_schema_tokens", "اسکیمای ابزار"),
        ("memory_tokens", "حافظه"),
        ("rag_tokens", "RAG"),
        ("tool_result_tokens", "نتیجهٔ ابزار"),
    )
    parts = [f"{fa} {shares.get(k, 0)}%" for k, fa in labels]
    return " | ".join(parts)


def finalize_payload_profile_request(
    rounds: list[dict[str, Any]],
    *,
    user_key: str = "",
    audience: str = "",
    voice: str = "",
    api_rounds: int = 0,
    request_id: str = "",
) -> dict[str, Any] | None:
    """پایان درخواست: JSONL + یک خط INFO با سهم‌ها و دلتا."""
    if not payload_profiler_enabled() or not rounds:
        return None

    summary = merge_request_summary(rounds)
    row = {
        "ts": int(time.time()),
        "user": user_key,
        "audience": audience,
        "voice": voice,
        "request_id": request_id,
        "api_rounds": int(api_rounds or len(rounds)),
        **summary,
    }

    path = _profile_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass

    shares = summary.get("shares_pct") or {}
    msg = f"PayloadProfiler سهم توکن (آخرین دور): {_format_shares_log(shares)}"
    delta = summary.get("delta_round0_round1")
    if isinstance(delta, dict):
        dt = int(delta.get("total_payload_tokens") or 0)
        msg += (
            f" | دلتا دور۰→۱ کل: {dt:+d}"
            f" (hist {int(delta.get('history_tokens') or 0):+d},"
            f" tool_res {int(delta.get('tool_result_tokens') or 0):+d},"
            f" schema {int(delta.get('tool_schema_tokens') or 0):+d})"
        )
    try:
        current_app.logger.info(msg)
    except Exception:
        _LOG.info(msg)

    return row
