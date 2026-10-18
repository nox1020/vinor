# -*- coding: utf-8 -*-
"""sms.ir OTP sender — one HTTP attempt, no duplicate fallback send."""
from __future__ import annotations

import logging

from app.auth.otp.crypto import hash_identifier
from app.auth.otp.providers.base import (
    KIND_FAILED,
    KIND_INVALID_CREDENTIALS,
    KIND_INVALID_PHONE,
    KIND_RATE_LIMITED,
    KIND_SERVER_ERROR,
    KIND_SUCCESS,
    KIND_TIMEOUT,
    KIND_UNEXPECTED,
    OTPDeliveryResult,
)

_log = logging.getLogger(__name__)


def _kind_from_sms_result(result: dict) -> str:
    if result.get("ok"):
        return KIND_SUCCESS
    body = result.get("body") if isinstance(result.get("body"), dict) else {}
    err = str((body or {}).get("error") or "").lower()
    if err == "invalid_mobile":
        return KIND_INVALID_PHONE
    if any(tok in err for tok in ("timeout", "timed out")):
        return KIND_TIMEOUT
    try:
        status = int(result.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    if status in (401, 403):
        return KIND_INVALID_CREDENTIALS
    if status == 429:
        return KIND_RATE_LIMITED
    if 500 <= status < 600:
        return KIND_SERVER_ERROR
    if status == 0 and err:
        return KIND_TIMEOUT if "connection" in err else KIND_FAILED
    return KIND_FAILED


class SmsOTPProvider:
    name = "sms"

    def send_otp(self, phone: str, code: str, *, request_id: str = "") -> OTPDeliveryResult:
        from app.services.sms import send_sms_code

        try:
            result = send_sms_code(phone, code)
        except Exception:
            _log.exception(
                "otp delivery crashed provider=sms phone_hash=%s request_id=%s",
                hash_identifier(phone),
                request_id,
            )
            return OTPDeliveryResult(
                success=False,
                provider=self.name,
                request_id=request_id,
                error_code="unexpected",
                failure_kind=KIND_UNEXPECTED,
            )

        payload = result if isinstance(result, dict) else {}
        kind = _kind_from_sms_result(payload)
        ok = kind == KIND_SUCCESS
        attempts = payload.get("attempts") if isinstance(payload.get("attempts"), list) else None
        gateway = {"attempts": attempts} if attempts else None
        if ok:
            _log.info(
                "otp requested phone_hash=%s provider=sms_ir request_id=%s result=success",
                hash_identifier(phone),
                request_id,
            )
        else:
            _log.warning(
                "otp requested phone_hash=%s provider=sms_ir request_id=%s result=%s status=%s",
                hash_identifier(phone),
                request_id,
                kind,
                payload.get("status"),
            )
        return OTPDeliveryResult(
            success=ok,
            provider=self.name,
            request_id=request_id,
            error_code="" if ok else kind,
            retryable=kind in (KIND_TIMEOUT, KIND_SERVER_ERROR),
            configured=True,
            failure_kind=kind,
            gateway=gateway,
        )
