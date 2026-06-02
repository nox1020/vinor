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
    PENDING_STATUS,
)

PARTNER_LAND_TX_EVENTS = frozenset({
    "visit_submitted",
    "visit_pending",
    "visit_approved",
    "visit_rejected",
    "visit_completed",
    "deal_started",
    "deal_released",
})

_STATUS_TO_EVENT = {
    PENDING_STATUS: "visit_pending",
    APPROVED_STATUS: "visit_approved",
    CANCELLED_STATUS: "visit_rejected",
    COMPLETED_STATUS: "visit_completed",
}


def _format_visit_date_sms(iso_date: str) -> str:
    jalali = format_iso_date_jalali(iso_date)
    return jalali or (iso_date or "")[:10] or "—"


def _land_label(land_title: str, land_code: str) -> str:
    title = (land_title or "").strip()
    code = (land_code or "").strip()
    if title and code:
        return f"{title} ({code})"
    return title or code or "—"


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
    return _STATUS_TO_EVENT.get(new_st)


def _build_message(event: str, ctx: Dict[str, Any]) -> str:
    land = _land_label(str(ctx.get("land_title") or ""), str(ctx.get("land_code") or ""))
    vdate = _format_visit_date_sms(str(ctx.get("visit_date") or ""))
    note = (ctx.get("admin_note") or "").strip()

    if event == "visit_submitted":
        return (
            f"وینور اکسپرس\n"
            f"درخواست بازدید ثبت شد.\n"
            f"ملک: {land}\n"
            f"تاریخ بازدید: {vdate}\n"
            f"وضعیت: در انتظار تأیید ادمین"
        )
    if event == "visit_pending":
        return (
            f"وینور اکسپرس\n"
            f"درخواست بازدید شما\n"
            f"ملک: {land}\n"
            f"وضعیت: در انتظار تأیید"
        )
    if event == "visit_approved":
        return (
            f"وینور اکسپرس\n"
            f"درخواست بازدید تأیید شد.\n"
            f"ملک: {land}\n"
            f"تاریخ بازدید: {vdate}\n"
            f"اکنون می‌توانید درخواست معامله ثبت کنید."
        )
    if event == "visit_rejected":
        lines = [
            "وینور اکسپرس",
            "درخواست بازدید رد شد.",
            f"ملک: {land}",
        ]
        if note:
            lines.append(f"یادداشت: {note}")
        return "\n".join(lines)
    if event == "visit_completed":
        return (
            f"وینور اکسپرس\n"
            f"بازدید و معامله ثبت شد.\n"
            f"ملک: {land}\n"
            f"وضعیت: تکمیل‌شده"
        )
    if event == "deal_started":
        return (
            f"وینور اکسپرس\n"
            f"درخواست معامله ثبت شد.\n"
            f"ملک: {land}\n"
            f"وضعیت فایل: در حال معامله\n"
            f"پورسانت شما در صف تأیید قرار گرفت."
        )
    if event == "deal_released":
        return (
            f"وینور اکسپرس\n"
            f"معامله رفع شد.\n"
            f"ملک: {land}\n"
            f"وضعیت فایل: فعال"
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
) -> Dict[str, Any]:
    """ارسال پیامک تغییر بازدید/معامله به همکار."""
    ev = (event or "").strip()
    if ev not in PARTNER_LAND_TX_EVENTS:
        return {"ok": False, "skipped": True, "error": "invalid_event"}

    settings = load_settings(current_app) or {}
    sms_line_number = (
        settings.get("sms_line_number") or get_sms_line_number() or "300089930616"
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
        })

    if not msg:
        return {"ok": False, "skipped": True, "error": "empty_message"}

    sms_result = send_sms_direct(mobile=mobile, message=msg, line_number=sms_line_number)
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
