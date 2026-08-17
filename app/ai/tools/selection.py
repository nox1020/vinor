"""انتخاب ابزار قبل از هر فراخوانی LLM — هدف: ۱–۳ schema در اکثر درخواست‌ها."""
from __future__ import annotations

from typing import Any

from app.ai.audience import VOICE_ADMIN, VOICE_PARTNER, VOICE_PUBLIC, VOICE_SPECIAL
from app.ai.intents import is_guidance_only, message_signals
from app.ai.agent_tools import (
    TOOL_APP_STATUS,
    TOOL_COOP_INFO,
    TOOL_COMPLETE_VISIT,
    TOOL_DEAL,
    TOOL_FOLLOWUP,
    TOOL_FORGET_MEMORY,
    TOOL_LEAD,
    TOOL_LISTING,
    TOOL_LOG_CALL,
    TOOL_NEXT,
    TOOL_PROPOSE_APPLY,
    TOOL_RELEASE,
    TOOL_SEARCH,
    TOOL_VISIT,
)

from .registry import _schema_tool_name, schemas_for_tool_names

_CHIP_TOOL_NAMES: dict[str, frozenset[str]] = {
    "coop_levels": frozenset({TOOL_COOP_INFO}),
    "coop_terms": frozenset({TOOL_COOP_INFO}),
    "coop_how": frozenset({TOOL_COOP_INFO}),
    "coop_apply": frozenset({TOOL_COOP_INFO, TOOL_PROPOSE_APPLY}),
    "coop_status": frozenset({TOOL_APP_STATUS}),
    "next_action": frozenset({TOOL_NEXT}),
    "marketing": frozenset({TOOL_LISTING}),
    "visit": frozenset({TOOL_VISIT}),
    "complete_visit": frozenset({TOOL_COMPLETE_VISIT}),
    "deal": frozenset({TOOL_DEAL}),
    "release": frozenset({TOOL_RELEASE}),
    "find_land": frozenset({TOOL_SEARCH}),
    "have_customer": frozenset({TOOL_LEAD}),
    "log_call": frozenset({TOOL_LOG_CALL}),
    "followup": frozenset({TOOL_FOLLOWUP}),
}

def _env_bool(name: str, default: str = "1") -> bool:
    import os

    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def per_round_tool_selection_enabled() -> bool:
    return _env_bool("VINOR_AI_PER_ROUND_TOOLS", "1")


def tool_selection_report_defaults() -> dict[str, Any]:
    return {
        "tools_sent_count": 0,
        "tools_actually_used_count": 0,
        "tools_actually_used": [],
        "tool_schema_tokens": 0,
        "tool_rounds": [],
        "per_round_tools": True,
    }


def _normalize_chip(chip_intent: str) -> str:
    key = str(chip_intent or "").strip().lower()
    return key if key in _CHIP_TOOL_NAMES else ""


def _message_signals(msg: str) -> dict[str, bool]:
    """سازگاری با فراخوان‌های قبلی — منبع واحد در app.ai.intents است."""
    return message_signals(msg)


def _is_guidance_only_message(user_message: str, chip_intent: str = "") -> bool:
    return is_guidance_only(user_message, chip_intent)


def select_tool_names_for_request(
    voice: str | None,
    *,
    user_message: str = "",
    chip_intent: str = "",
    user_key: str = "",
    thread_id: str = "",
) -> list[str]:
    """نام ابزارهای پیشنهادی برای دور tool-calling (بدون ساخت schema)."""
    v = (voice or "").strip().lower()
    chip = _normalize_chip(chip_intent)
    msg = f"{user_message} {chip_intent}".strip()
    sig = _message_signals(msg)
    keep: set[str] = set()

    if v == VOICE_ADMIN:
        from app.ai.admin_tools import (
            TOOL_ADMIN_LIST_QUEUE,
            TOOL_ADMIN_OPS_SUMMARY,
            TOOL_ADMIN_PARTNER_STATUS,
            TOOL_ADMIN_SEARCH_LANDS,
            TOOL_ANSWER_ESCALATION,
            TOOL_PROPOSE_BROADCAST_PUSH,
            TOOL_PROPOSE_BROADCAST_SMS,
            TOOL_PROPOSE_COMMISSION,
            TOOL_PROPOSE_PARTNER_DECISION,
            TOOL_PROPOSE_VISIT_ADMIN,
        )

        if sig["admin_queue"] or len(msg) < 8:
            keep.add(TOOL_ADMIN_OPS_SUMMARY)
        else:
            keep.add(TOOL_ADMIN_SEARCH_LANDS)
        if sig["admin_partner"]:
            keep.update({TOOL_ADMIN_PARTNER_STATUS, TOOL_PROPOSE_PARTNER_DECISION})
        if sig["admin_msg"]:
            keep.update({TOOL_PROPOSE_BROADCAST_SMS, TOOL_PROPOSE_BROADCAST_PUSH})
        if sig["admin_visit"]:
            keep.add(TOOL_PROPOSE_VISIT_ADMIN)
        if sig["admin_money"]:
            keep.add(TOOL_PROPOSE_COMMISSION)
        if sig["admin_esc"]:
            keep.add(TOOL_ANSWER_ESCALATION)
        if not keep:
            keep.add(TOOL_ADMIN_OPS_SUMMARY)
        if len(keep) > 3:
            priority = [
                TOOL_ADMIN_OPS_SUMMARY,
                TOOL_ADMIN_SEARCH_LANDS,
                TOOL_ADMIN_LIST_QUEUE,
                TOOL_ADMIN_PARTNER_STATUS,
            ]
            trimmed: list[str] = []
            for p in priority:
                if p in keep and p not in trimmed:
                    trimmed.append(p)
                if len(trimmed) >= 3:
                    break
            for n in sorted(keep):
                if n not in trimmed and len(trimmed) < 3:
                    trimmed.append(n)
            return trimmed[:3]
        return sorted(keep)[:3]

    if v == VOICE_PUBLIC:
        if chip:
            return sorted(_CHIP_TOOL_NAMES[chip])
        if _is_guidance_only_message(user_message, chip_intent):
            return []
        if sig["coop"]:
            keep.update({TOOL_COOP_INFO, TOOL_APP_STATUS, TOOL_PROPOSE_APPLY})
        elif sig["forget"]:
            keep.add(TOOL_FORGET_MEMORY)
        else:
            keep.add(TOOL_SEARCH)
        return sorted(keep)[:3]

    if v in (VOICE_PARTNER, VOICE_SPECIAL):
        awaiting_visit = ""
        awaiting_lead = ""
        customer_ready = False
        if user_key:
            try:
                from app.ai.agent_tools import (
                    lead_form_awaiting,
                    partner_customer_ready_for_visit,
                    visit_form_awaiting,
                )

                awaiting_visit = visit_form_awaiting(user_key, thread_id or None)
                awaiting_lead = lead_form_awaiting(user_key, thread_id or None)
                customer_ready = partner_customer_ready_for_visit(
                    user_key, thread_id or None
                )
            except Exception:
                awaiting_visit = ""
                awaiting_lead = ""
                customer_ready = False
        if awaiting_visit:
            return [TOOL_VISIT]
        if chip and chip != "have_customer":
            names = set(_CHIP_TOOL_NAMES[chip])
            if chip == "find_land" and customer_ready:
                names.add(TOOL_VISIT)
            return sorted(names)
        if awaiting_lead or chip == "have_customer":
            return [TOOL_LEAD]
        if _is_guidance_only_message(user_message, chip_intent):
            return []
        if sig["visit"]:
            keep.update({TOOL_VISIT, TOOL_COMPLETE_VISIT})
        elif sig["deal"]:
            keep.update({TOOL_DEAL, TOOL_RELEASE})
        elif sig["listing"]:
            keep.add(TOOL_LISTING)
        elif sig["lead"]:
            keep.add(TOOL_LEAD)
        elif sig["crm"]:
            keep.update({TOOL_LOG_CALL, TOOL_FOLLOWUP})
        elif sig["search"]:
            keep.add(TOOL_SEARCH)
            if customer_ready:
                keep.add(TOOL_VISIT)
            elif len(keep) < 3:
                keep.add(TOOL_NEXT)
        elif sig["forget"]:
            keep.add(TOOL_FORGET_MEMORY)
        else:
            return []
        if sig["forget"] and len(keep) < 3:
            keep.add(TOOL_FORGET_MEMORY)
        return sorted(keep)[:3]

    return [TOOL_SEARCH]


def _needs_tools_this_round(
    messages: list[dict[str, Any]],
    *,
    round_index: int,
    max_tool_rounds: int,
    catalog: list[dict[str, Any]] | None,
) -> bool:
    if not catalog:
        return False
    if round_index >= max_tool_rounds:
        return False
    # پس از اجرای ابزار، دور بعدی پاسخ نهایی است — بدون schema
    for m in reversed(messages):
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        if role == "tool":
            return False
        if role in ("user", "assistant"):
            break
    return True


def select_tools_for_api_round(
    voice: str | None,
    *,
    round_index: int,
    max_tool_rounds: int,
    user_message: str = "",
    chip_intent: str = "",
    messages: list[dict[str, Any]] | None = None,
    catalog: list[dict[str, Any]] | None = None,
    user_key: str = "",
    thread_id: str = "",
) -> list[dict[str, Any]]:
    """schemaهای همان دور API؛ خالی = tools=[] در درخواست."""
    cat = list(catalog) if catalog else []
    if not _needs_tools_this_round(
        messages or [],
        round_index=round_index,
        max_tool_rounds=max_tool_rounds,
        catalog=cat,
    ):
        return []

    if not per_round_tool_selection_enabled():
        return cat

    names = select_tool_names_for_request(
        voice,
        user_message=user_message,
        chip_intent=chip_intent,
        user_key=user_key,
        thread_id=thread_id,
    )
    if not names:
        return []
    by_name = {_schema_tool_name(s): s for s in cat}
    picked = [by_name[n] for n in names if n in by_name]
    if picked:
        return picked
    return schemas_for_tool_names(voice, frozenset(names))


def filter_catalog_subset(
    voice: str | None,
    *,
    user_message: str = "",
    chip_intent: str = "",
    catalog: list[dict[str, Any]] | None = None,
    user_key: str = "",
    thread_id: str = "",
) -> list[dict[str, Any]]:
    """سازگاری با token_diag threshold — همان انتخاب per-request."""
    cat = list(catalog) if catalog else []
    if not cat or not per_round_tool_selection_enabled():
        return cat
    names = select_tool_names_for_request(
        voice,
        user_message=user_message,
        chip_intent=chip_intent,
        user_key=user_key,
        thread_id=thread_id,
    )
    if not names:
        return []
    by_name = {_schema_tool_name(s): s for s in cat}
    picked = [by_name[n] for n in names if n in by_name]
    return picked if picked else cat
