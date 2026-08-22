# -*- coding: utf-8 -*-
"""SMS-only OTP delivery via sms.ir."""
from __future__ import annotations

import logging
import uuid

from .crypto import hash_identifier
from .providers.base import KIND_UNEXPECTED, OTPDeliveryResult
from .providers.sms import SmsOTPProvider
from . import store

_log = logging.getLogger(__name__)
_sms = SmsOTPProvider()


def dispatch_otp(phone: str, code: str, *, challenge_id: str = "", request_id: str = "") -> OTPDeliveryResult:
    rid = (request_id or str(uuid.uuid4())).strip()
    try:
        result = _sms.send_otp(phone, code, request_id=rid)
    except Exception:
        _log.exception("otp sms provider crashed phone_hash=%s request_id=%s", hash_identifier(phone), rid)
        result = OTPDeliveryResult(
            success=False,
            provider="sms",
            request_id=rid,
            error_code="unexpected",
            failure_kind=KIND_UNEXPECTED,
        )
    if challenge_id:
        store.mark_delivery(challenge_id, provider="sms", success=result.success, request_id=rid)
    _log.info(
        "otp requested phone_hash=%s provider=sms_ir request_id=%s result=%s",
        hash_identifier(phone),
        rid,
        "success" if result.success else (result.failure_kind or "failed"),
    )
    return result
