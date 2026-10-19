"""Emit domain events into Conversation (system / timeline messages + case).

Call sites should use ``emit_chat_event`` whenever a domain mutation succeeds.
"""
from __future__ import annotations

from typing import Any

from app.ai.audience import AUDIENCE_ADMIN, AUDIENCE_PARTNER
from app.ai.message_types import (
    MSG_ERROR,
    MSG_PROGRESS,
    MSG_SYSTEM,
    MSG_TIMELINE,
    MSG_WARNING,
)


# Map progress/domain event keys → human labels (timeline)
EVENT_LABELS: dict[str, str] = {
    "mission_started": "ماموریت ایجاد شد",
    "mission_completed": "ماموریت تکمیل شد",
    "mission_abandoned": "ماموریت رها شد",
    "land_suggested": "فایل پیشنهاد شد",
    "visit_requested": "بازدید درخواست شد",
    "visit_approved": "بازدید توسط مدیر تایید شد",
    "visit_scheduled": "زمان بازدید مشخص شد",
    "visit_done_pending": "اعلام انجام بازدید ثبت شد",
    "visit_completed": "بازدید انجام شد",
    "visit_cancelled": "بازدید لغو شد",
    "visit_no_show": "عدم حضور ثبت شد",
    "deal_started": "معامله شروع شد",
    "deal_pending": "معامله در انتظار تایید است",
    "deal_approved": "معامله نهایی شد",
    "deal_released": "معامله لغو / بسته شد",
    "commission_created": "پورسانت ثبت شد",
    "commission_approved": "پورسانت تایید شد",
    "commission_paid": "پورسانت پرداخت شد",
    "commission_rejected": "پورسانت رد شد",
    "payment_recorded": "پرداخت ثبت شد",
    "contract_created": "قرارداد ثبت شد",
    "case_closed": "پرونده بسته شد",
    "admin_replied": "پاسخ تیم وینور ثبت شد",
    "card_confirmed": "اقدام تایید شد",
    "card_cancelled": "اقدام لغو شد",
    "card_expired": "اقدام منقضی شد",
    "error": "خطا",
    "warning": "هشدار",
}


def _resolve_thread_id(
    user_key: str,
    *,
    audience: str,
    thread_id: str = "",
    land_code: str = "",
) -> str:
    tid = str(thread_id or "").strip()
    if tid:
        return tid
    code = str(land_code or "").strip()
    if audience == AUDIENCE_PARTNER and code:
        try:
            from app.express_partner.partner_missions import get_active_mission

            mission = get_active_mission(user_key)
            if mission and str(mission.get("land_code") or "").strip() == code:
                mt = str(mission.get("thread_id") or "").strip()
                if mt:
                    return mt
        except Exception:
            pass
    try:
        from app.ai.chat_store import ensure_active_thread

        return ensure_active_thread(user_key, audience=audience)
    except Exception:
        return ""


def emit_chat_event(
    user_key: str,
    *,
    event: str,
    body: str = "",
    audience: str = AUDIENCE_PARTNER,
    thread_id: str = "",
    land_code: str = "",
    msg_type: str = MSG_SYSTEM,
    agent_actions: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    case_status: str | None = None,
    update_case: bool = True,
) -> dict[str, Any]:
    """Append a system/timeline message and optionally update the Case timeline."""
    from app.ai.chat_store import append_typed_message

    ev = str(event or "").strip() or "update"
    label = EVENT_LABELS.get(ev, ev)
    text = (body or "").strip() or label
    tid = _resolve_thread_id(
        user_key, audience=audience, thread_id=thread_id, land_code=land_code
    )
    if not tid:
        return {"ok": False, "error": "no_thread"}

    mtype = str(msg_type or MSG_SYSTEM).strip() or MSG_SYSTEM
    if mtype not in (MSG_SYSTEM, MSG_TIMELINE, MSG_PROGRESS, MSG_WARNING, MSG_ERROR):
        # Domain flavors still render as system-ish in UI
        if mtype in ("visit", "deal", "commission", "mission", "payment", "contract"):
            mtype = MSG_TIMELINE
        else:
            mtype = MSG_SYSTEM

    msgs, out_tid = append_typed_message(
        user_key,
        text,
        thread_id=tid,
        audience=audience,
        msg_type=mtype,
        source="system",
        land_codes=[land_code] if land_code else None,
        agent_actions=agent_actions,
        event=ev,
        meta=meta,
        include_land_cards=False,
    )

    case = None
    if update_case:
        try:
            from app.ai.case_store import append_case_timeline

            case = append_case_timeline(
                user_key,
                out_tid,
                audience=audience,
                event=ev,
                label=label,
                land_code=land_code,
                meta=meta,
                case_status=case_status,
            )
        except Exception:
            case = None

    try:
        from app.supervisor_agent.service import report_from_chat_event

        if audience != AUDIENCE_ADMIN:
            report_from_chat_event(
                event=ev,
                body=text,
                land_code=land_code,
                user_key=user_key,
                meta=meta,
            )
    except Exception:
        pass

    return {
        "ok": True,
        "thread_id": out_tid,
        "messages": msgs,
        "event": ev,
        "case_id": (case or {}).get("id") if case else "",
    }


def emit_timeline(
    user_key: str,
    *,
    event: str,
    body: str = "",
    audience: str = AUDIENCE_PARTNER,
    thread_id: str = "",
    land_code: str = "",
    meta: dict[str, Any] | None = None,
    case_status: str | None = None,
) -> dict[str, Any]:
    return emit_chat_event(
        user_key,
        event=event,
        body=body,
        audience=audience,
        thread_id=thread_id,
        land_code=land_code,
        msg_type=MSG_TIMELINE,
        meta=meta,
        case_status=case_status,
    )
