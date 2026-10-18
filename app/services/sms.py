# app/services/sms.py
"""
sms.ir — ارسال OTP و پیامک قالب‌دار/مستقیم.

کلید و قالب از متغیرهای محیطی (SMS_API_KEY و تنظیمات غیرمحرمانه SMS_*).
"""
import re
import threading

import requests
from flask import current_app
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, Timeout

from app.services.sms_config import (
    get_sms_api_key,
    get_sms_line_number,
    get_sms_retriever_hash,
    get_sms_template_id,
)

# اتصال گرم به sms.ir — TLS/TCP برای OTP دوباره برقرار نشود
_SMS_SESSION: requests.Session | None = None
_SMS_SESSION_LOCK = threading.Lock()
# connect, read — sms.ir OTP Verify; no retry (one request = one SMS)

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


def normalize_otp_code(code: str, *, max_digits: int = 6) -> str:
    """کد OTP — فقط ارقام لاتین. ورود فعلی ۵ رقم است؛ /auth تا ۶ رقم می‌پذیرد."""
    if not code:
        return ""
    limit = max_digits if 4 <= int(max_digits) <= 8 else 6
    s = str(code).strip().translate(_DIGIT_TRANSLATION)
    return re.sub(r"\D+", "", s)[:limit]


def format_otp_sms_message(code: str) -> str:
    """متن OTP برای خط اختصاصی وینور — Web OTP + SMS Retriever.

    نمونه:
        کد تایید:
        <#> 32564
        @vinor.ir #32564
        4R707/AKLt0
    """
    digits = normalize_otp_code(code)
    retriever_hash = get_sms_retriever_hash() or "4R707/AKLt0"
    return (
        "کد تایید:\n"
        f"<#> {digits}\n"
        f"@vinor.ir #{digits}\n"
        f"{retriever_hash}"
    )


def sms_ir_error_message(body: object, fallback: str = "خطای ارسال پیامک") -> str:
    """استخراج پیام خطا از پاسخ sms.ir."""
    if not isinstance(body, dict):
        text = fallback if body is None else str(body)[:200]
        return _friendly_sms_error(text) or text
    for key in ("message", "Message", "error", "Error", "title", "detail", "Description"):
        val = body.get(key)
        if val is not None and str(val).strip():
            text = str(val).strip()
            return _friendly_sms_error(text) or text
    raw = body.get("raw")
    if raw is not None and str(raw).strip():
        text = str(raw).strip()[:200]
        return _friendly_sms_error(text) or text
    return fallback


def _friendly_sms_error(text: str) -> str:
    """خلاصهٔ خطاهای شبکه/زیرساخت برای نمایش در پنل."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if not sms_is_infrastructure_error(raw):
        return raw
    low = raw.lower()
    if "proxy" in low:
        return "خطای اتصال (پروکسی)"
    if "getaddrinfo" in low or "failed to resolve" in low or "name resolution" in low:
        return "خطای DNS / اتصال اینترنت"
    if "ssl" in low or "certificate" in low:
        return "خطای SSL در اتصال به sms.ir"
    if "timeout" in low or "timed out" in low:
        return "اتمام مهلت اتصال به sms.ir"
    if "refused" in low or "unreachable" in low:
        return "سرور sms.ir در دسترس نیست"
    return "خطای شبکه در ارسال پیامک"


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


def _sms_http_session() -> requests.Session:
    global _SMS_SESSION
    sess = _SMS_SESSION
    if sess is not None:
        return sess
    with _SMS_SESSION_LOCK:
        if _SMS_SESSION is None:
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            _SMS_SESSION = s
        return _SMS_SESSION


def _sms_request_post(
    url: str,
    *,
    headers: dict,
    json_payload: dict,
    timeout: float | tuple = 12,
    retry: bool = False,
) -> requests.Response:
    """POST به sms.ir روی Session مشترک. OTP retry ندارد تا تأخیر دوبل نشود."""
    sess = _sms_http_session()
    attempts = 2 if retry else 1
    last_err = None
    for attempt in range(attempts):
        try:
            return sess.post(url, headers=headers, json=json_payload, timeout=timeout)
        except Timeout as e:
            last_err = e
            if retry and attempt == 0:
                try:
                    current_app.logger.warning("SMS API timeout (retrying): %s", url)
                except Exception:
                    pass
                continue
            raise
        except RequestException:
            raise
    if last_err:
        raise last_err
    raise RuntimeError("SMS request failed")


def _template_message_preview(parameters: dict | None, template_id: int) -> str:
    params = parameters or {}
    for key in ("MESSAGE", "message", "text", "body"):
        val = params.get(key)
        if val:
            return str(val).strip()[:500]
    return f"قالب #{template_id}"


def _send_otp_verify(mobile: str, digits: str) -> dict:
    url = "https://api.sms.ir/v1/send/verify"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": get_sms_api_key(),
    }
    payload = {
        "mobile": mobile,
        "templateId": get_sms_template_id(),
        "parameters": [
            {"name": "CODE", "value": digits},
            {"name": "HASH", "value": get_sms_retriever_hash() or "4R707/AKLt0"},
        ],
    }
    try:
        resp = _sms_request_post(
            url,
            headers=headers,
            json_payload=payload,
            timeout=(3.05, 12),
            retry=False,
        )
        content_type = resp.headers.get("content-type", "")
        body = (
            resp.json()
            if content_type.lower().startswith("application/json")
            else {"raw": resp.text}
        )
        ok = _sms_ir_response_ok(resp.status_code, body)
        return {"ok": ok, "status": resp.status_code, "body": body}
    except Exception as e:
        return {"ok": False, "status": 0, "body": {"error": str(e)}}


def _verify_explicitly_rejected(result: dict) -> bool:
    """sms.ir said it did not accept the template. Timeout and 5xx are not this."""
    if not isinstance(result, dict) or result.get("ok"):
        return False
    try:
        status = int(result.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    if status == 0 or status == 429 or status >= 500:
        return False
    return True


def _log_otp_failure(mobile: str, result: dict) -> None:
    """Log the gateway status. Never log the code or the full number."""
    try:
        from app.auth.otp.crypto import mask_phone

        body = result.get("body")
        detail = sms_ir_error_message(body, fallback="")
        digits = re.sub(r"\D+", "", detail)
        if len(digits) >= 4:
            detail = re.sub(r"\d{4,}", "*****", detail)
        current_app.logger.error(
            "OTP SMS failed | phone=%s | status=%s | provider=%s",
            mask_phone(mobile),
            result.get("status"),
            (detail or "")[:180],
        )
    except Exception:
        pass


def send_sms_code(
    phone: str,
    code: str,
    *,
    history_source: str = "otp",
    recipient_name: str | None = None,
    record_history: bool = True,
) -> dict:
    """OTP from the sms.ir verify template. One bulk send only if verify refuses."""
    mobile = normalize_iran_mobile(phone)
    if not is_valid_iran_mobile(mobile):
        return {
            "ok": False,
            "status": 0,
            "body": {"error": "invalid_mobile", "mobile": mobile},
        }
    digits = normalize_otp_code(code)
    if not digits:
        return {
            "ok": False,
            "status": 0,
            "body": {"error": "invalid_otp_code"},
        }

    if not (get_sms_api_key() or "").strip():
        return {
            "ok": False,
            "status": 401,
            "body": {"error": "missing_api_key"},
        }

    template_id = get_sms_template_id()
    result = _send_otp_verify(mobile, digits)
    used_template = bool(result.get("ok"))
    if not used_template and _verify_explicitly_rejected(result):
        # The template was refused, so no SMS left. One direct send on the service line.
        _log_otp_failure(mobile, result)
        result = send_sms_direct(
            mobile,
            format_otp_sms_message(digits),
            line_number=get_sms_line_number() or "09981801922",
            history_source=history_source,
            recipient_name=recipient_name,
            record_history=False,
        )
        used_template = False

    if not result.get("ok"):
        _log_otp_failure(mobile, result)

    if record_history and mobile:
        try:
            from app.services.sms_history import record_sms_send_result

            record_sms_send_result(
                result,
                mobile=mobile,
                source=history_source,
                recipient_name=recipient_name,
                message=format_otp_sms_message("******"),
                template_id=template_id if used_template else None,
                record_history=True,
            )
        except Exception:
            pass
    return result


def send_sms_template(
    mobile: str,
    template_id: int,
    parameters: dict | None = None,
    api_key: str | None = None,
    *,
    history_source: str = "system",
    recipient_name: str | None = None,
    record_history: bool = True,
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
    norm_mobile = normalize_iran_mobile(mobile) or str(mobile)
    payload = {
        "mobile": norm_mobile,
        "templateId": int(template_id),
        "parameters": params_list,
    }
    try:
        resp = _sms_request_post(url, headers=headers, json_payload=payload, timeout=12, retry=False)
        content_type = resp.headers.get("content-type", "")
        body = (
            resp.json()
            if content_type.lower().startswith("application/json")
            else {"raw": resp.text}
        )
        ok = _sms_ir_response_ok(resp.status_code, body)
        result = {"ok": ok, "status": resp.status_code, "body": body}
    except Exception as e:
        try:
            current_app.logger.error("SMS template error: %s", e)
        except Exception:
            print("SMS template error:", e)
        result = {"ok": False, "status": 0, "body": {"error": str(e)}}

    if record_history:
        from app.services.sms_history import record_sms_send_result

        record_sms_send_result(
            result,
            mobile=norm_mobile,
            source=history_source,
            recipient_name=recipient_name,
            message=_template_message_preview(parameters, int(template_id)),
            template_id=int(template_id),
            parameters=parameters,
            record_history=True,
        )
    return result


def send_sms_direct(
    mobile: str,
    message: str,
    line_number: str | None = None,
    api_key: str | None = None,
    *,
    history_source: str = "system",
    recipient_name: str | None = None,
    record_history: bool = True,
) -> dict:
    """ارسال پیامک مستقیم بدون قالب (bulk API در sms.ir) از خط اختصاصی."""
    final_line_number = (line_number or "").strip() or get_sms_line_number() or "09981801922"
    url = "https://api.sms.ir/v1/send/bulk"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": (api_key or get_sms_api_key()),
    }
    norm_mobile = normalize_iran_mobile(mobile) or str(mobile)
    payload = {
        "lineNumber": str(final_line_number),
        "messageText": str(message),
        "mobiles": [norm_mobile],
    }
    try:
        resp = _sms_request_post(url, headers=headers, json_payload=payload, timeout=12, retry=False)
        content_type = resp.headers.get("content-type", "")
        body = (
            resp.json()
            if content_type.lower().startswith("application/json")
            else {"raw": resp.text}
        )
        ok = _sms_ir_response_ok(resp.status_code, body)
        result = {"ok": ok, "status": resp.status_code, "body": body}
    except Exception as e:
        try:
            current_app.logger.error("SMS direct error: %s", e)
        except Exception:
            print("SMS direct error:", e)
        result = {"ok": False, "status": 0, "body": {"error": str(e)}}

    if record_history:
        from app.services.sms_history import record_sms_send_result

        record_sms_send_result(
            result,
            mobile=norm_mobile,
            source=history_source,
            recipient_name=recipient_name,
            message=str(message)[:500],
            record_history=True,
        )
    return result
