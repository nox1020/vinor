# -*- coding: utf-8 -*-
"""احراز هویت Invest API — session وینور پس از OTP."""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable
from urllib.parse import unquote

from flask import current_app, g, jsonify, request, session

from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile


def _phone_from_mapping(data: Any) -> str:
    if not hasattr(data, "get"):
        return ""
    raw = data.get("user_phone") or data.get("user_id") or data.get("phone") or ""
    return normalize_iran_mobile(str(raw).strip()) or ""


def _bearer_token() -> str:
    header = (request.headers.get("Authorization") or "").strip()
    if len(header) < 8 or not header.lower().startswith("bearer "):
        return ""
    token = header[7:].strip()
    if token.lower().startswith("vinor_session="):
        token = token.split("=", 1)[1].strip()
    return unquote(token)


def _session_from_token(token: str) -> dict:
    try:
        serializer = current_app.session_interface.get_signing_serializer(current_app)
        if serializer is None or not token:
            return {}
        data = serializer.loads(token)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def current_invest_phone() -> str:
    phone = _phone_from_mapping(session)
    if is_valid_iran_mobile(phone):
        return phone
    token = _bearer_token()
    if not token:
        return ""
    return _phone_from_mapping(_session_from_token(token))


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
