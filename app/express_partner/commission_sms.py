# -*- coding: utf-8 -*-
"""پیامک اطلاع‌رسانی تراکنش‌های پورسانت/برداشت به همکار."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from flask import current_app

from ..services.sms import send_sms_direct, normalize_iran_mobile, is_valid_iran_mobile
from ..utils.storage import load_settings, load_sms_history, save_sms_history
from app.services.sms_config import get_sms_line_number

PARTNER_TXN_EVENTS = frozenset({
    "commission_pending",
    "commission_approved",
    "commission_paid",
    "commission_rejected",
    "withdrawal_requested",
    "withdrawal_cancelled",
    "withdrawal_approved",
    "withdrawal_rejected",
    "withdrawal_paid",
})


def _format_toman(amount: Any) -> str:
    try:
        v = max(0, int(str(amount).replace(",", "").strip() or "0"))
    except Exception:
        v = 0
    if v == 0:
        return "0"
    return f"{v:,}".replace(",", "،")


def _txn_title(*, commission_type: str = "", land_code: str = "") -> str:
    ct = (commission_type or "").strip()
    code = (land_code or "").strip()
    if ct == "referral" or code == "referral":
        return "پورسانت دعوت"
    if code:
        return f"پورسانت فروش (کد ملک: {code})"
    return "پورسانت"


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


def _build_message(event: str, ctx: Dict[str, Any]) -> str:
    amt = _format_toman(ctx.get("amount"))
    title = (ctx.get("title") or "").strip() or _txn_title(
        commission_type=str(ctx.get("commission_type") or ""),
        land_code=str(ctx.get("land_code") or ""),
    )
    bank = (ctx.get("bank_summary") or "").strip()

    if event == "commission_pending":
        return (
            f"وینور اکسپرس\n{title}\n"
            f"مبلغ: {amt} تومان\n"
            f"وضعیت: در انتظار تأیید"
        )
    if event == "commission_approved":
        return (
            f"وینور اکسپرس\n{title}\n"
            f"مبلغ: {amt} تومان\n"
            f"وضعیت: تأیید شد — در موجودی قابل برداشت"
        )
    if event == "commission_paid":
        return (
            f"وینور اکسپرس\n{title}\n"
            f"مبلغ: {amt} تومان\n"
            f"وضعیت: پرداخت‌شده"
        )
    if event == "commission_rejected":
        return (
            f"وینور اکسپرس\n{title}\n"
            f"مبلغ: {amt} تومان\n"
            f"وضعیت: رد شد"
        )
    if event == "withdrawal_requested":
        lines = [
            "وینور اکسپرس",
            "درخواست برداشت ثبت شد.",
            f"مبلغ: {amt} تومان",
            "وضعیت: در انتظار بررسی",
        ]
        if bank:
            lines.append(f"حساب: {bank}")
        return "\n".join(lines)
    if event == "withdrawal_cancelled":
        return (
            f"وینور اکسپرس\n"
            f"درخواست برداشت لغو شد.\n"
            f"مبلغ: {amt} تومان"
        )
    if event == "withdrawal_approved":
        return (
            f"وینور اکسپرس\n"
            f"درخواست برداشت تأیید شد.\n"
            f"مبلغ: {amt} تومان\n"
            f"در حال واریز به حساب شما"
        )
    if event == "withdrawal_rejected":
        return (
            f"وینور اکسپرس\n"
            f"درخواست برداشت رد شد.\n"
            f"مبلغ: {amt} تومان"
        )
    if event == "withdrawal_paid":
        lines = [
            "وینور اکسپرس",
            "واریز برداشت به حساب شما انجام شد.",
            f"مبلغ: {amt} تومان",
        ]
        if bank:
            lines.append(f"حساب: {bank}")
        return "\n".join(lines)
    return ""


def notify_partner_commission_txn(
    *,
    partner_phone: str,
    event: str,
    amount: Any = 0,
    land_code: str = "",
    commission_type: str = "",
    bank_summary: str = "",
    reference_id: str = "",
) -> Dict[str, Any]:
    """ارسال پیامک تراکنش پورسانت/برداشت به همکار."""
    ev = (event or "").strip()
    if ev not in PARTNER_TXN_EVENTS:
        return {"ok": False, "skipped": True, "error": "invalid_event"}

    settings = load_settings(current_app) or {}
    sms_line_number = (
        settings.get("sms_line_number") or get_sms_line_number() or "300089930616"
    ).strip()
    mobile = normalize_iran_mobile(partner_phone)

    if not is_valid_iran_mobile(mobile):
        current_app.logger.warning(
            "Partner commission txn SMS skipped: invalid phone %r event=%s",
            partner_phone,
            ev,
        )
        return {"ok": False, "skipped": True, "error": "invalid_partner_phone"}

    ctx = {
        "amount": amount,
        "land_code": land_code,
        "commission_type": commission_type,
        "bank_summary": bank_summary,
        "title": _txn_title(commission_type=commission_type, land_code=land_code),
    }
    msg = _build_message(ev, ctx)
    if not msg:
        return {"ok": False, "skipped": True, "error": "empty_message"}

    sms_result = send_sms_direct(mobile=mobile, message=msg, line_number=sms_line_number)
    ok = bool(sms_result.get("ok"))
    err: Optional[str] = None
    if not ok:
        body = sms_result.get("body") or {}
        err = str(body.get("message") or body.get("error") or "sms_send_failed")
        current_app.logger.error(
            "Partner commission txn SMS failed mobile=%s event=%s status=%s body=%s",
            mobile,
            ev,
            sms_result.get("status"),
            body,
        )

    _append_sms_history({
        "type": f"partner_txn_{ev}",
        "mobile": mobile,
        "partner_phone": partner_phone,
        "event": ev,
        "reference_id": reference_id,
        "land_code": land_code,
        "amount": _format_toman(amount),
        "message": msg,
        "ok": ok,
        "error": err,
        "status_code": sms_result.get("status", 0),
        "response": sms_result.get("body", {}),
        "created_at": datetime.utcnow().isoformat() + "Z",
    })
    return {"ok": ok, "skipped": False, "error": err}
