# -*- coding: utf-8 -*-
"""پیامک‌های مربوط به درخواست بازدید همکار."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from flask import current_app

from ..services.sms import send_sms_direct, normalize_iran_mobile, is_valid_iran_mobile
from ..utils.dates import format_iso_date_jalali
from ..utils.storage import load_settings, load_sms_history, save_sms_history
from app.services.sms_config import get_sms_line_number


def _format_visit_date_sms(iso_date: str) -> str:
    jalali = format_iso_date_jalali(iso_date)
    return jalali or (iso_date or "")[:10] or "—"


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


def send_visit_partner_approval_sms(
    *,
    partner_phone: str,
    partner_name: str,
    land_code: str,
    land_title: str,
    visit_date: str,
) -> Dict[str, Any]:
    """پیامک تأیید بازدید برای همکار درخواست‌دهنده."""
    settings = load_settings(current_app) or {}
    sms_line_number = (settings.get("sms_line_number") or get_sms_line_number() or "300089930616").strip()
    mobile = normalize_iran_mobile(partner_phone)

    if not is_valid_iran_mobile(mobile):
        current_app.logger.warning(
            "Visit partner approval SMS skipped: invalid phone %r", partner_phone
        )
        return {"ok": False, "skipped": True, "error": "invalid_partner_phone"}

    title = (land_title or "").strip() or (land_code or "").strip() or "—"
    vdate = _format_visit_date_sms(visit_date)
    custom = (settings.get("visit_approval_sms_message") or "").strip()
    if custom:
        msg = custom
    else:
        msg = (
            f"درخواست بازدید شما تأیید شد.\n"
            f"فایل: {title}\n"
            f"تاریخ بازدید: {vdate}\n"
            f"اکنون می‌توانید درخواست معامله ثبت کنید. وینور"
        )

    sms_result = send_sms_direct(mobile=mobile, message=msg, line_number=sms_line_number)
    ok = bool(sms_result.get("ok"))
    err = None
    if not ok:
        body = sms_result.get("body") or {}
        err = str(body.get("message") or body.get("error") or "sms_send_failed")
        current_app.logger.error(
            "Visit partner approval SMS failed mobile=%s status=%s body=%s",
            mobile,
            sms_result.get("status"),
            body,
        )

    _append_sms_history({
        "type": "visit_partner_approved",
        "mobile": mobile,
        "partner_phone": partner_phone,
        "land_code": land_code,
        "message": msg,
        "ok": ok,
        "error": err,
        "status_code": sms_result.get("status", 0),
        "response": sms_result.get("body", {}),
        "created_at": datetime.utcnow().isoformat() + "Z",
    })
    return {"ok": ok, "skipped": False, "error": err}
