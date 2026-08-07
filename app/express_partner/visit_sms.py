# -*- coding: utf-8 -*-
"""پیامک‌های بازدید و معامله ملک برای همکار."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from flask import current_app

from ..services.sms import send_sms_direct, normalize_iran_mobile, is_valid_iran_mobile
from ..utils.dates import format_iso_date_jalali
from ..utils.storage import load_settings, load_sms_history, save_sms_history
from app.services.sms_config import get_sms_line_number

from .visit_requests import (
    APPROVED_STATUS,
    CANCELLED_STATUS,
    COMPLETED_STATUS,
    DONE_PENDING_STATUS,
    PENDING_STATUS,
)

PARTNER_LAND_TX_EVENTS = frozenset({
    "visit_submitted",
    "visit_pending",
    "visit_approved",
    "visit_done_pending",
    "visit_done_rejected",
    "visit_rejected",
    "visit_completed",
    "deal_started",
    "deal_released",
})

_STATUS_TO_EVENT = {
    PENDING_STATUS: "visit_pending",
    APPROVED_STATUS: "visit_approved",
    DONE_PENDING_STATUS: "visit_done_pending",
    CANCELLED_STATUS: "visit_rejected",
    COMPLETED_STATUS: "visit_completed",
}


def _format_visit_date_sms(iso_date: str) -> str:
    jalali = format_iso_date_jalali(iso_date)
    return jalali or (iso_date or "")[:10] or "—"


def _land_short(land_title: str, land_code: str) -> str:
    code = (land_code or "").strip()
    title = (land_title or "").strip()
    if code:
        return code
    return title or "ملک"


def _append_sms_history(entry: dict) -> None:
    try:
        history = load_sms_history(current_app) or []
        if not isinstance(history, list):
            history = []
        history.append(entry)
        if len(history) > 5000:
            history = history[-5000:]
        save_sms_history(history, current_app)
    except Exception:
        current_app.logger.exception("Failed to append SMS history")


def visit_status_change_event(new_status: str, prev_status: str) -> Optional[str]:
    """رویداد پیامک برای تغییر وضعیت درخواست بازدید توسط ادمین."""
    new_st = (new_status or "").strip()
    prev_st = (prev_status or "").strip()
    if not new_st or new_st == prev_st:
        return None
    if new_st == APPROVED_STATUS and prev_st == DONE_PENDING_STATUS:
        return "visit_done_rejected"
    return _STATUS_TO_EVENT.get(new_st)


def _build_message(event: str, ctx: Dict[str, Any]) -> str:
    """الگوی یکسان: وینور + خبر کوتاه (+ جزئیات لازم)."""
    land = _land_short(str(ctx.get("land_title") or ""), str(ctx.get("land_code") or ""))
    vdate = _format_visit_date_sms(str(ctx.get("visit_date") or ""))
    note = (ctx.get("admin_note") or "").strip()
    if len(note) > 60:
        note = note[:60] + "…"

    if event in ("visit_submitted", "visit_pending"):
        msg = f"وینور\nبازدید نهایی شد · {land}"
        if vdate and vdate != "—":
            msg += f"\n{vdate}"
        return msg
    if event == "visit_approved":
        return f"وینور\nبازدیدت تأیید شد · {land}\n{vdate}"
    if event == "visit_rejected":
        msg = (
            f"وینور\nبازدید منتفی شد · {land}\n"
            "ممنون از تلاشت. حالا بازاریابی مجدد: دیوار+نردبان+اینستا"
        )
        if note:
            msg += f"\n{note}"
        return msg
    if event == "visit_done_pending":
        return f"وینور\nانجام بازدید ثبت شد · {land}\nمنتظر تأیید"
    if event == "visit_done_rejected":
        msg = (
            f"وینور\nتأیید بازدید منتفی شد · {land}\n"
            "تو تلاشت رو کردی. دوباره دیوار/اینستا و معرفی کن"
        )
        if note:
            msg += f"\n{note}"
        return msg
    if event == "visit_completed":
        return f"وینور\nبازدید تأیید شد · {land}\nمی‌تونی معامله بزنی"
    if event == "deal_started":
        return f"وینور\nمعامله شروع شد · {land}"
    if event == "deal_released":
        return (
            f"وینور\nمعامله منتفی شد · {land}\n"
            "ممنون از تلاشت 🌿 دوباره دیوار+نردبان+اینستا"
        )
    return ""


def notify_partner_land_tx_sms(
    *,
    partner_phone: str,
    event: str,
    land_code: str = "",
    land_title: str = "",
    visit_date: str = "",
    admin_note: str = "",
    reference_id: str = "",
    visit_commission_pending: bool = False,
) -> Dict[str, Any]:
    """ارسال پیامک تغییر بازدید/معامله به همکار."""
    ev = (event or "").strip()
    if ev not in PARTNER_LAND_TX_EVENTS:
        return {"ok": False, "skipped": True, "error": "invalid_event"}

    settings = load_settings(current_app) or {}
    sms_line_number = (
        settings.get("sms_line_number") or get_sms_line_number() or "09981801922"
    ).strip()
    mobile = normalize_iran_mobile(partner_phone)

    if not is_valid_iran_mobile(mobile):
        current_app.logger.warning(
            "Partner land tx SMS skipped: invalid phone %r event=%s",
            partner_phone,
            ev,
        )
        return {"ok": False, "skipped": True, "error": "invalid_partner_phone"}

    if ev == "visit_approved":
        custom = (settings.get("visit_approval_sms_message") or "").strip()
        if custom:
            msg = custom
        else:
            msg = _build_message(ev, {
                "land_code": land_code,
                "land_title": land_title,
                "visit_date": visit_date,
                "admin_note": admin_note,
            })
    else:
        msg = _build_message(ev, {
            "land_code": land_code,
            "land_title": land_title,
            "visit_date": visit_date,
            "admin_note": admin_note,
            "visit_commission_pending": visit_commission_pending,
        })

    if not msg:
        return {"ok": False, "skipped": True, "error": "empty_message"}

    sms_result = send_sms_direct(mobile=mobile, message=msg, line_number=sms_line_number, record_history=False)
    ok = bool(sms_result.get("ok"))
    err: Optional[str] = None
    if not ok:
        body = sms_result.get("body") or {}
        err = str(body.get("message") or body.get("error") or "sms_send_failed")
        current_app.logger.error(
            "Partner land tx SMS failed mobile=%s event=%s status=%s body=%s",
            mobile,
            ev,
            sms_result.get("status"),
            body,
        )

    _append_sms_history({
        "type": f"partner_land_tx_{ev}",
        "mobile": mobile,
        "partner_phone": partner_phone,
        "event": ev,
        "land_code": land_code,
        "reference_id": reference_id,
        "message": msg,
        "ok": ok,
        "error": err,
        "status_code": sms_result.get("status", 0),
        "response": sms_result.get("body", {}),
        "created_at": datetime.utcnow().isoformat() + "Z",
    })

    # منتفی/رد: تشکر گرم + راهنمای بازاریابی مجدد در چت و اعلان
    if ev in ("visit_rejected", "visit_done_rejected", "deal_released"):
        try:
            from .sales_coach import deliver_voided_encouragement

            reason_map = {
                "visit_rejected": "بازدید منتفی شد",
                "visit_done_rejected": "تأیید بازدید منتفی شد",
                "deal_released": "معامله منتفی شد",
            }
            deliver_voided_encouragement(
                partner_phone=mobile,
                land_code=str(land_code or ""),
                land_title=str(land_title or ""),
                reason=reason_map.get(ev, "پیگیری منتفی شد"),
            )
        except Exception:
            current_app.logger.exception(
                "voided encouragement failed event=%s phone=%s", ev, mobile
            )
    # تأییدها و پیشرفت: هم پیامک (بالا) هم اطلاع در چت + قدم بعدی
    elif ev in (
        "visit_approved",
        "visit_done_pending",
        "visit_completed",
        "deal_started",
    ):
        try:
            from .sales_coach import deliver_partner_progress_update

            deliver_partner_progress_update(
                partner_phone=mobile,
                event=ev,
                land_code=str(land_code or ""),
                land_title=str(land_title or ""),
                visit_date=str(visit_date or ""),
                visit_commission_pending=bool(visit_commission_pending),
            )
        except Exception:
            current_app.logger.exception(
                "progress chat update failed event=%s phone=%s", ev, mobile
            )

    return {"ok": ok, "skipped": False, "error": err}


def send_visit_partner_approval_sms(
    *,
    partner_phone: str,
    partner_name: str = "",
    land_code: str,
    land_title: str,
    visit_date: str,
) -> Dict[str, Any]:
    """سازگاری با کد قبلی — تأیید بازدید."""
    del partner_name
    return notify_partner_land_tx_sms(
        partner_phone=partner_phone,
        event="visit_approved",
        land_code=land_code,
        land_title=land_title,
        visit_date=visit_date,
    )
