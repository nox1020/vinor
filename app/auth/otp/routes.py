# -*- coding: utf-8 -*-
"""POST /auth/request-otp and POST /auth/verify-otp — additive, non-breaking."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .config import expose_otp_in_dev, otp_digits
from .errors import (
    GENERIC_REQUEST_MESSAGE,
    GENERIC_VERIFY_MESSAGE,
    OTP_ALREADY_USED,
    OTP_COOLDOWN,
    OTP_DELIVERY_FAILED,
    OTP_EXPIRED,
    OTP_INVALID,
    OTP_INVALID_PHONE,
    OTP_LOCKED,
    OTP_PROVIDER_UNAVAILABLE,
    OTP_RATE_LIMITED,
    OTP_TOO_MANY_ATTEMPTS,
    OTP_USED,
)
from .openapi import OPENAPI
from .phone import canonical_mobile
from .request_meta import client_ip, client_user_agent
from .service import PURPOSE_AUTH_API, request_otp, verify_otp

auth_otp_bp = Blueprint("auth_otp", __name__, url_prefix="/auth")

_VERIFY_HTTP = {
    OTP_INVALID: 400,
    OTP_EXPIRED: 400,
    OTP_ALREADY_USED: 400,
    OTP_USED: 400,
    OTP_TOO_MANY_ATTEMPTS: 429,
    OTP_LOCKED: 429,
    OTP_RATE_LIMITED: 429,
    OTP_COOLDOWN: 429,
    OTP_INVALID_PHONE: 400,
    OTP_DELIVERY_FAILED: 502,
    OTP_PROVIDER_UNAVAILABLE: 503,
}


def _client_ip() -> str:
    return client_ip()


def _user_agent() -> str:
    return client_user_agent()


@auth_otp_bp.get("/openapi.json")
def openapi_spec():
    return jsonify(OPENAPI)


@auth_otp_bp.post("/request-otp")
def request_otp_view():
    """
    Request OTP (unauthenticated).

    Rate limits: 1 / 60s / phone, 5 / hour / phone, 20 / hour / IP.
    Always generic success copy except malformed phone and rate-limit.
    Never returns the OTP in production.
    """
    data = request.get_json(silent=True) or {}
    phone = canonical_mobile(data.get("phone") or request.form.get("phone") or "")
    result = request_otp(
        phone=phone,
        purpose=PURPOSE_AUTH_API,
        digits=otp_digits(),
        ip=_client_ip(),
        user_agent=_user_agent(),
    )
    if result.error == OTP_INVALID_PHONE:
        return jsonify(
            {
                "success": False,
                "error": OTP_INVALID_PHONE,
                "message": "شماره موبایل معتبر نیست.",
            }
        ), 400
    if result.error in (OTP_RATE_LIMITED, OTP_COOLDOWN):
        body = {
            "success": False,
            "error": OTP_RATE_LIMITED if result.error == OTP_RATE_LIMITED else OTP_COOLDOWN,
            "message": "لطفاً کمی صبر کنید و دوباره تلاش کنید.",
        }
        if result.retry_after:
            body["retry_after"] = result.retry_after
        resp = jsonify(body)
        resp.status_code = 429
        if result.retry_after:
            resp.headers["Retry-After"] = str(result.retry_after)
        return resp

    if result.error in (OTP_DELIVERY_FAILED, OTP_PROVIDER_UNAVAILABLE):
        return jsonify(
            {
                "success": False,
                "error": result.error,
                "message": "ارسال کد ممکن نشد. کمی بعد دوباره تلاش کنید.",
            }
        ), _VERIFY_HTTP.get(result.error, 502)

    payload = {
        "success": True,
        "message": GENERIC_REQUEST_MESSAGE,
    }
    if expose_otp_in_dev() and result.debug_code:
        payload["debug_code"] = result.debug_code
    return jsonify(payload)


@auth_otp_bp.post("/verify-otp")
def verify_otp_view():
    """
    Verify OTP and create the existing partner Flask session (cookie vinor_session).
    """
    data = request.get_json(silent=True) or {}
    phone = data.get("phone") or request.form.get("phone") or ""
    code = data.get("code") or request.form.get("code") or request.form.get("otp_code") or ""
    result = verify_otp(
        phone=phone,
        purpose=PURPOSE_AUTH_API,
        code=str(code),
        digits=otp_digits(),
    )
    if not result.ok:
        err = result.error or OTP_INVALID
        status = _VERIFY_HTTP.get(err, 400)
        messages = {
            OTP_EXPIRED: "کد تأیید منقضی شده است.",
            OTP_ALREADY_USED: "کد تأیید قبلاً استفاده شده است.",
            OTP_TOO_MANY_ATTEMPTS: "تعداد تلاش بیش از حد است. کد جدید درخواست کنید.",
            OTP_INVALID_PHONE: "شماره موبایل معتبر نیست.",
        }
        return jsonify(
            {
                "success": False,
                "error": err,
                "message": messages.get(err, GENERIC_VERIFY_MESSAGE),
            }
        ), status

    from app.express_partner.routes import _finalize_partner_login

    dest = _finalize_partner_login(result.phone)
    return jsonify(
        {
            "success": True,
            "message": "ورود با موفقیت انجام شد.",
            "redirect": dest,
        }
    )
