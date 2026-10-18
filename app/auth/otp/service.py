# -*- coding: utf-8 -*-
"""OTP lifecycle — generation, hashed storage, verify, rate limits. No auth/session here."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import store
from .config import (
    admin_otp_resend_cooldown_seconds,
    expose_otp_in_dev,
    otp_digits,
    otp_ip_hourly_limit,
    otp_phone_hourly_limit,
    otp_resend_cooldown_seconds,
    sms_otp_enabled,
)
from .crypto import generate_otp, hash_identifier
from .errors import (
    GENERIC_REQUEST_MESSAGE,
    OTP_COOLDOWN,
    OTP_DELIVERY_FAILED,
    OTP_INVALID,
    OTP_INVALID_PHONE,
    OTP_PROVIDER_UNAVAILABLE,
    OTP_RATE_LIMITED,
)
from .phone import canonical_mobile, canonical_otp_code, is_canonical_mobile
from .request_meta import ip_is_public
from .providers.base import (
    KIND_INVALID_CREDENTIALS,
    KIND_RATE_LIMITED,
    KIND_SERVER_ERROR,
    KIND_TIMEOUT,
)

_log = logging.getLogger(__name__)

PURPOSE_PARTNER = "partner_login"
PURPOSE_ADMIN = "admin_login"
PURPOSE_AUTH_API = "auth_api"


@dataclass
class OTPRequestResult:
    accepted: bool
    error: str = ""
    message: str = GENERIC_REQUEST_MESSAGE
    challenge_id: str = ""
    debug_code: str = ""
    retry_after: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class OTPVerifyResult:
    ok: bool
    error: str = ""
    phone: str = ""
    extra: dict = field(default_factory=dict)


def _rate_limited(phone: str, ip: str) -> tuple[bool, int]:
    import time

    now = time.time()
    phone_hash = hash_identifier(f"phone:{phone}")
    ip_hash = hash_identifier(f"ip:{ip or 'unknown'}")
    hour_ago = now - 3600
    phone_n = store.count_rate_events("phone_sent", phone_hash, since=hour_ago)
    if phone_n >= otp_phone_hourly_limit():
        return True, 3600
    if ip_is_public(ip):
        ip_n = store.count_rate_events("ip_sent", ip_hash, since=hour_ago)
        if ip_n >= otp_ip_hourly_limit():
            return True, 3600
    return False, 0


def _note_send(phone: str, ip: str) -> None:
    """Count only after the gateway accepted the SMS, or the result was ambiguous."""
    store.record_rate_event("phone_sent", hash_identifier(f"phone:{phone}"))
    if ip_is_public(ip):
        store.record_rate_event("ip_sent", hash_identifier(f"ip:{ip or 'unknown'}"))


def _cooldown_left(phone: str, purpose: str) -> int:
    import time

    last = store.last_sent_at(phone, purpose)
    if not last:
        return 0
    window = (
        admin_otp_resend_cooldown_seconds()
        if purpose == PURPOSE_ADMIN
        else otp_resend_cooldown_seconds()
    )
    left = int(window - (time.time() - last))
    return left if left > 0 else 0


def invalidate_otp(*, phone: str, purpose: str) -> None:
    mobile = canonical_mobile(phone)
    if is_canonical_mobile(mobile):
        store.invalidate_active(mobile, purpose)


def request_otp(
    *,
    phone: str,
    purpose: str,
    digits: int | None = None,
    ip: str = "",
    user_agent: str = "",
) -> OTPRequestResult:
    mobile = canonical_mobile(phone)
    if not is_canonical_mobile(mobile):
        return OTPRequestResult(accepted=False, error=OTP_INVALID_PHONE)

    if not sms_otp_enabled():
        return OTPRequestResult(accepted=False, error=OTP_PROVIDER_UNAVAILABLE)

    limited, retry_after = _rate_limited(mobile, ip)
    if limited:
        _log.warning("otp requested phone_hash=%s error=rate_limited", hash_identifier(mobile))
        return OTPRequestResult(accepted=False, error=OTP_RATE_LIMITED, retry_after=retry_after)

    wait = _cooldown_left(mobile, purpose)
    if wait > 0:
        return OTPRequestResult(accepted=False, error=OTP_COOLDOWN, retry_after=wait)

    n_digits = digits if digits is not None else otp_digits()
    code = generate_otp(n_digits)
    rec = store.create_challenge(
        phone=mobile,
        purpose=purpose,
        code=code,
        ip_hash=hash_identifier(ip) if ip else "",
        ua_hash=hash_identifier(user_agent) if user_agent else "",
    )

    from .dispatch import dispatch_otp

    delivery = dispatch_otp(mobile, code, challenge_id=rec["id"], request_id=rec.get("request_id") or "")
    debug_code = code if expose_otp_in_dev() else ""
    uncertain = delivery.failure_kind in (KIND_TIMEOUT, KIND_SERVER_ERROR, KIND_RATE_LIMITED)
    # Dispatch records this too. Repeat it here so a rejected send cannot keep
    # the last_sent_at that create_challenge stored before the gateway answered.
    store.mark_delivery(
        rec["id"],
        provider=delivery.provider or "sms",
        success=delivery.success,
        request_id=delivery.request_id,
        count_as_sent=uncertain,
    )
    if delivery.success or uncertain:
        _note_send(mobile, ip)
    if not delivery.success:
        kind = delivery.failure_kind or ""
        if kind == KIND_TIMEOUT:
            err = OTP_PROVIDER_UNAVAILABLE
        elif kind == KIND_INVALID_CREDENTIALS:
            err = OTP_PROVIDER_UNAVAILABLE
        else:
            err = OTP_DELIVERY_FAILED
        extra = {}
        if delivery.gateway:
            extra["gateway"] = delivery.gateway
        return OTPRequestResult(
            accepted=False,
            error=err,
            challenge_id=rec["id"],
            debug_code=debug_code,
            extra=extra,
        )
    return OTPRequestResult(accepted=True, challenge_id=rec["id"], debug_code=debug_code)


def resend_otp(
    *,
    phone: str,
    purpose: str,
    digits: int | None = None,
    ip: str = "",
    user_agent: str = "",
) -> OTPRequestResult:
    return request_otp(
        phone=phone,
        purpose=purpose,
        digits=digits,
        ip=ip,
        user_agent=user_agent,
    )


def verify_otp(*, phone: str, purpose: str, code: str, digits: int | None = None) -> OTPVerifyResult:
    mobile = canonical_mobile(phone)
    if not is_canonical_mobile(mobile):
        return OTPVerifyResult(ok=False, error=OTP_INVALID_PHONE)

    expected_digits = digits if digits is not None else otp_digits()
    norm = canonical_otp_code(code, expected_digits)
    if not norm:
        status, _rec = store.consume_challenge(phone=mobile, purpose=purpose, code=str(code or "x"))
        return OTPVerifyResult(ok=False, error=status if status != "ok" else OTP_INVALID)

    status, rec = store.consume_challenge(phone=mobile, purpose=purpose, code=norm)
    if status == "ok":
        return OTPVerifyResult(ok=True, phone=mobile, extra={"challenge_id": (rec or {}).get("id")})
    return OTPVerifyResult(ok=False, error=status or OTP_INVALID, phone=mobile)


def partner_login_digits() -> int:
    return otp_digits()
