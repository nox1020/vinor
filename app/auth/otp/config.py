# -*- coding: utf-8 -*-
"""OTP + sms.ir settings. Secrets come from the environment only.

OTP delivery is SMS-only (sms.ir). Unset any leftover messenger-OTP env vars
on the server and rotate those API keys at the provider dashboard.
"""
from __future__ import annotations

import hashlib
import hmac
import os


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def sms_otp_enabled() -> bool:
    return _env_bool("VINOR_OTP_SMS_ENABLED", "1")


def otp_ttl_seconds() -> int:
    return max(60, _env_int("VINOR_OTP_TTL_SECONDS", 120))


def otp_max_attempts() -> int:
    return max(1, _env_int("VINOR_OTP_MAX_ATTEMPTS", 5))


def otp_resend_cooldown_seconds() -> int:
    return max(1, _env_int("VINOR_OTP_RESEND_COOLDOWN_SECONDS", 60))


def admin_otp_resend_cooldown_seconds() -> int:
    return max(1, _env_int("VINOR_ADMIN_OTP_RESEND_COOLDOWN_SECONDS", 20))


def otp_phone_hourly_limit() -> int:
    return max(1, _env_int("VINOR_OTP_PHONE_HOURLY_LIMIT", 5))


def otp_ip_hourly_limit() -> int:
    # Carrier NAT shares one public address across many phones. The per-phone
    # cap is the real limit; this only stops a single public address from
    # flooding the gateway.
    return max(1, _env_int("VINOR_OTP_IP_HOURLY_LIMIT", 80))


def otp_digits() -> int:
    """All Vinor login surfaces use the same length (default 5 for SMS/Android)."""
    n = _env_int("VINOR_OTP_DIGITS", 5)
    return n if 4 <= n <= 8 else 5


def expose_otp_in_dev() -> bool:
    return _env_bool("VINOR_OTP_EXPOSE_IN_DEV", "0")


def otp_retain_days() -> int:
    return max(1, _env_int("VINOR_OTP_RETAIN_DAYS", 7))


def hmac_secret_dedicated() -> bool:
    return bool((os.environ.get("VINOR_OTP_HMAC_SECRET") or "").strip())


def hmac_secret_bytes() -> bytes:
    dedicated = (os.environ.get("VINOR_OTP_HMAC_SECRET") or "").strip()
    if dedicated:
        return dedicated.encode("utf-8")
    session_secret = (os.environ.get("SECRET_KEY") or "").strip()
    if not session_secret:
        raise RuntimeError(
            "Refusing to derive OTP HMAC: missing required environment variable(s): SECRET_KEY"
        )
    return hmac.new(
        session_secret.encode("utf-8"),
        b"vinor-otp-hmac-v1",
        hashlib.sha256,
    ).digest()


def sms_otp_configured() -> bool:
    try:
        from app.utils.secrets import get_sms_api_key

        return bool((get_sms_api_key() or "").strip())
    except Exception:
        return False


def sms_health() -> dict:
    return {
        "enabled": sms_otp_enabled(),
        "configured": sms_otp_configured(),
    }


def log_otp_startup(logger) -> None:
    if not sms_otp_enabled():
        logger.error("OTP SMS disabled | VINOR_OTP_SMS_ENABLED=0")
    elif not sms_otp_configured():
        logger.error("OTP SMS enabled but sms.ir API key is missing")
    else:
        logger.info("OTP SMS enabled | provider=sms_ir | configured=true")
    if not hmac_secret_dedicated():
        logger.error(
            "VINOR_OTP_HMAC_SECRET is unset; OTP HMAC is derived from SECRET_KEY. "
            "Set a dedicated VINOR_OTP_HMAC_SECRET before production."
        )
