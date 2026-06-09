# app/services/sms.py
"""
sms.ir — ارسال OTP و پیامک قالب‌دار/مستقیم.

کلید و قالب: api_keys.py در ریشه پروژه.
"""
import re
import requests
from flask import current_app

from app.services.sms_config import (
    get_sms_api_key,
    get_sms_line_number,
    get_sms_retriever_hash,
    get_sms_template_id,
)

# ارقام فارسی/عربی → لاتین
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def normalize_iran_mobile(phone: str) -> str:
    """شماره موبایل ایران → 09xxxxxxxxx (ارقام ASCII) برای sms.ir."""
    if not phone:
        return ""
    s = str(phone).strip().replace(" ", "").replace("-", "").translate(_DIGIT_TRANSLATION)
    s = re.sub(r"\D+", "", s)
    if s.startswith("0098") and len(s) >= 14 and s[4:].startswith("9"):
        s = "0" + s[4:]
    elif s.startswith("98") and len(s) >= 12 and s[2:].startswith("9"):
        s = "0" + s[2:]
    elif s.startswith("9") and len(s) == 10:
        s = "0" + s
    if len(s) >= 11:
        return s[:11]
    if len(s) == 10:
        return "0" + s
    return s


def is_valid_iran_mobile(phone: str) -> bool:
    return bool(phone) and len(phone) == 11 and phone.startswith("09")


def sms_is_infrastructure_error(error: object) -> bool:
    """خطاهای شبکه/اتصال — کاربر نباید پیام خطای پیامک ببیند."""
    if error is None:
        return True
    e = str(error).lower()
    if e in ("invalid_mobile",):
        return False
    markers = (
        "connection",
        "connectionpool",
        "timeout",
        "timed out",
        "getaddrinfo",
        "name resolution",
        "failed to resolve",
        "max retries",
        "network",
        "refused",
        "unreachable",
        "ssl",
        "certificate",
    )
    return any(m in e for m in markers)


def normalize_otp_code(code: str) -> str:
    """کد OTP — فقط ارقام لاتین، حداکثر ۵ رقم."""
    if not code:
        return ""
    s = str(code).strip().translate(_DIGIT_TRANSLATION)
    return re.sub(r"\D+", "", s)[:5]


def _sms_ir_response_ok(status_code: int, body: object) -> bool:
    """HTTP 2xx + status==1 در بدنهٔ sms.ir."""
    if not (200 <= status_code < 300):
        return False
    if isinstance(body, dict) and body.get("status") is not None:
        try:
            return int(body.get("status")) == 1
        except (TypeError, ValueError):
            return False
    return True


def send_sms_code(phone: str, code: str) -> dict:
    """
    ارسال OTP با قالب sms.ir.

    متن قالب (CODE مثلاً 38415):
        کد ورود شما : (آن را در اختیار هیچ کس نگذارید)
        https://vinor.ir
        <#> CODE
        @vinor.ir #CODE
        HASH

    پارامتر HASH فقط وقتی SMS_RETRIEVER_HASH در api_keys تنظیم شده باشد فرستاده می‌شود.
    """
    mobile = normalize_iran_mobile(phone)
    if not is_valid_iran_mobile(mobile):
        return {
            "ok": False,
            "status": 0,
            "body": {"error": "invalid_mobile", "mobile": mobile},
        }

    url = "https://api.sms.ir/v1/send/verify"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": get_sms_api_key(),
    }
    data = {
        "mobile": mobile,
        "templateId": get_sms_template_id(),
        "parameters": [{"name": "CODE", "value": str(code)}],
    }
    retriever_hash = get_sms_retriever_hash()
    if retriever_hash:
        data["parameters"].append({"name": "HASH", "value": retriever_hash})
    else:
        try:
            current_app.logger.warning(
                "SMS_RETRIEVER_HASH is empty — APK auto-fill needs hash as last line after "
                "@vinor.ir #CODE (see AppSignatureHelper logcat)."
            )
        except Exception:
            pass
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        content_type = resp.headers.get("content-type", "")
        body = (
            resp.json()
            if content_type.lower().startswith("application/json")
            else {"raw": resp.text}
        )
        ok = _sms_ir_response_ok(resp.status_code, body)
        if not ok:
            try:
                current_app.logger.error(
                    "OTP SMS failed | status=%s | phone=%s | body=%s",
                    resp.status_code,
                    mobile,
                    body,
                )
            except Exception:
                pass
        return {"ok": ok, "status": resp.status_code, "body": body}
    except Exception as e:
        try:
            current_app.logger.error("SMS error: %s", e)
        except Exception:
            print("SMS error:", e)
        return {"ok": False, "status": 0, "body": {"error": str(e)}}


def send_sms_template(
    mobile: str,
    template_id: int,
    parameters: dict | None = None,
    api_key: str | None = None,
) -> dict:
    """
    ارسال پیامک با قالب آماده (Ultra Fast/Verify API در sms.ir).
    """
    url = "https://api.sms.ir/v1/send/verify"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": (api_key or get_sms_api_key()),
    }
    params_list = []
    if parameters:
        for name, value in parameters.items():
            params_list.append({"name": str(name), "value": str(value)})
    payload = {
        "mobile": normalize_iran_mobile(mobile) or str(mobile),
        "templateId": int(template_id),
        "parameters": params_list,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        content_type = resp.headers.get("content-type", "")
        body = (
            resp.json()
            if content_type.lower().startswith("application/json")
            else {"raw": resp.text}
        )
        ok = _sms_ir_response_ok(resp.status_code, body)
        return {"ok": ok, "status": resp.status_code, "body": body}
    except Exception as e:
        try:
            current_app.logger.error("SMS template error: %s", e)
        except Exception:
            print("SMS template error:", e)
        return {"ok": False, "status": 0, "body": {"error": str(e)}}


def send_sms_direct(
    mobile: str,
    message: str,
    line_number: str | None = None,
    api_key: str | None = None,
) -> dict:
    """ارسال پیامک مستقیم بدون قالب (bulk API در sms.ir)."""
    final_line_number = line_number or get_sms_line_number()
    url = "https://api.sms.ir/v1/send/bulk"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": (api_key or get_sms_api_key()),
    }
    payload = {
        "lineNumber": str(final_line_number),
        "messageText": str(message),
        "mobiles": [normalize_iran_mobile(mobile) or str(mobile)],
        "sendDateTime": None,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        content_type = resp.headers.get("content-type", "")
        body = (
            resp.json()
            if content_type.lower().startswith("application/json")
            else {"raw": resp.text}
        )
        ok = _sms_ir_response_ok(resp.status_code, body)
        return {"ok": ok, "status": resp.status_code, "body": body}
    except Exception as e:
        try:
            current_app.logger.error("SMS direct error: %s", e)
        except Exception:
            print("SMS direct error:", e)
        return {"ok": False, "status": 0, "body": {"error": str(e)}}
