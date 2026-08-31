# -*- coding: utf-8 -*-
"""احراز هویت Invest API — session وینور پس از OTP."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, jsonify, session

from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile


def current_invest_phone() -> str:
    phone = (
        session.get("user_phone")
        or session.get("user_id")
        or session.get("phone")
        or ""
    )
    return normalize_iran_mobile(str(phone).strip()) or ""


def require_invest_auth(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        phone = current_invest_phone()
        if not is_valid_iran_mobile(phone):
            return jsonify({
                "success": False,
                "error": "auth_required",
                "message": "ابتدا با OTP وارد شوید.",
            }), 401
        g.invest_phone = phone
        return view(*args, **kwargs)

    return wrapped
