# app/services/sms_history.py
"""ثبت و نرمال‌سازی سابقهٔ ارسال پیامک در کل سیستم."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from flask import current_app

from app.utils.storage import load_sms_history, save_sms_history
from app.services.sms import sms_ir_error_message

SMS_SOURCE_LABELS: dict[str, str] = {
    "admin_colleagues": "ادمین · همکاران",
    "admin_colleagues_direct": "ادمین · مستقیم",
    "admin_colleagues_scheduled": "ادمین · زمان‌دار",
    "admin_colleagues_recurring": "ادمین · تکرارشونده",
    "admin_partner_message": "ادمین · پیام همکار",
    "admin_system_template_test": "ادمین · تست قالب",
    "admin_pending_action": "ادمین · اقدام",
    "api": "API",
    "api_bulk": "API · گروهی",
    "ai_escalation": "AI · هشدار",
    "reach": "Reach",
    "otp": "کد تأیید",
    "sales_coach": "مربی فروش",
    "express_partner_application": "درخواست همکاری",
    "daily_celebration": "تبریک روزانه",
    "vinor_plus_lifecycle": "وینور پلاس",
    "new_express_land_broadcast": "زمین جدید",
    "android_apk_update_broadcast": "به‌روزرسانی APK",
    "postchi": "پستچی",
    "system": "سیستم",
}


def sms_source_label(source: object) -> str:
    key = str(source or "").strip()
    if not key:
        return SMS_SOURCE_LABELS["system"]
    if key in SMS_SOURCE_LABELS:
        return SMS_SOURCE_LABELS[key]
    if key.startswith("admin_pending_action_"):
        return SMS_SOURCE_LABELS["admin_pending_action"]
    return key.replace("_", " ")


def normalize_sms_history_row(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        return {}
    out = dict(row)
    mobile = str(out.get("mobile") or out.get("phone") or out.get("recipient_phone") or "").strip()
    if mobile:
        out["mobile"] = mobile
    if "success" not in out:
        if "ok" in out:
            out["success"] = bool(out.get("ok"))
        else:
            out["success"] = False
    if not out.get("source"):
        out["source"] = "system"
    err = str(out.get("error") or "").strip()
    if not err or err == "Unknown error":
        resp = out.get("response")
        if isinstance(resp, dict):
            derived = sms_ir_error_message(resp, "")
            if derived:
                out["error"] = derived
    return out


def append_sms_history_entry(
    *,
    mobile: str,
    success: bool,
    source: str = "system",
    recipient_name: str | None = None,
    message: str | None = None,
    template_id: int | None = None,
    parameters: dict | None = None,
    status_code: int = 0,
    response: Any = None,
    error: str | None = None,
) -> None:
    try:
        history = load_sms_history(current_app) or []
        if not isinstance(history, list):
            history = []
        entry: dict[str, Any] = {
            "id": len(history) + 1,
            "mobile": str(mobile or "").strip(),
            "recipient_name": recipient_name,
            "template_id": template_id,
            "parameters": parameters or {},
            "success": bool(success),
            "status_code": int(status_code or 0),
            "response": response if isinstance(response, dict) else {},
            "source": str(source or "system").strip() or "system",
            "created_at": datetime.now().isoformat(),
            "error": error,
        }
        if message:
            entry["message"] = str(message)[:500]
        history.append(entry)
        if len(history) > 10000:
            history = history[-10000:]
        save_sms_history(history, current_app)
    except Exception as exc:
        try:
            current_app.logger.error("Failed to append SMS history: %s", exc)
        except Exception:
            pass


def record_sms_send_result(
    result: Mapping[str, Any],
    *,
    mobile: str,
    source: str = "system",
    recipient_name: str | None = None,
    message: str | None = None,
    template_id: int | None = None,
    parameters: dict | None = None,
    record_history: bool = True,
) -> None:
    if not record_history:
        return
    ok = bool(result.get("ok"))
    body = result.get("body") or {}
    err = None
    if not ok:
        err = sms_ir_error_message(body)
    append_sms_history_entry(
        mobile=mobile,
        success=ok,
        source=source,
        recipient_name=recipient_name,
        message=message,
        template_id=template_id,
        parameters=parameters,
        status_code=int(result.get("status") or 0),
        response=body if isinstance(body, dict) else {"raw": str(body)[:500]},
        error=err,
    )
