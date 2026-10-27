# -*- coding: utf-8 -*-
"""احراز هویت Invest API — session وینور پس از OTP."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable
from urllib.parse import unquote

from flask import current_app, g, jsonify, make_response, request, session

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
        return _with_idempotency(view, args, kwargs)

    return wrapped


# --- Idempotency-Key for offline-queue retries (additive) -------------------
# PWO / biz / projects keep their own snapshot-replay keys; every other write
# (assets, trades, checks, settings, me) stores its first response so a retry
# with the same key returns it without writing again.
_IDEM_RE = re.compile(r"^[A-Za-z0-9_\-]{8,100}$")
_IDEM_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_OWN_KEY_PREFIXES = ("/invest/api/v1/pwo", "/invest/api/v1/biz", "/invest/api/v1/projects")


def _with_idempotency(view: Callable, args, kwargs):
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if (not key or request.method not in _IDEM_METHODS
            or request.path.startswith(_OWN_KEY_PREFIXES)):
        return view(*args, **kwargs)
    if not _IDEM_RE.match(key):
        return jsonify({"success": False, "error": "validation",
                        "message": "کلید تکرارنشدن نامعتبر است."}), 400
    try:
        from backend.context import get_request_context
        conn = get_request_context().conn
        conn.execute(_IDEM_TABLE)
        row = conn.execute("SELECT method, path, status, body FROM idempotency_responses WHERE key=?",
                           (key,)).fetchone()
    except Exception:  # noqa: BLE001 — never block a write on the replay layer
        current_app.logger.warning("idempotency lookup failed", exc_info=True)
        return view(*args, **kwargs)
    if row:
        if row[0] != request.method or row[1] != request.path:
            return jsonify({"success": False, "error": "idempotency_conflict",
                            "message": "این کلید قبلاً برای درخواست دیگری استفاده شده."}), 409
        resp = current_app.response_class(row[3], status=int(row[2]), mimetype="application/json")
        resp.headers["Idempotent-Replayed"] = "true"
        return resp
    resp = make_response(view(*args, **kwargs))
    if resp.status_code < 500 and resp.mimetype == "application/json":
        try:
            conn.execute("INSERT OR IGNORE INTO idempotency_responses "
                         "(key, method, path, status, body, created_at) VALUES (?,?,?,?,?,?)",
                         (key, request.method, request.path, resp.status_code,
                          resp.get_data(as_text=True), datetime.now(timezone.utc).isoformat()))
            conn.commit()
        except Exception:  # noqa: BLE001
            current_app.logger.warning("idempotency store failed", exc_info=True)
    return resp


_IDEM_TABLE = ("CREATE TABLE IF NOT EXISTS idempotency_responses (key TEXT PRIMARY KEY, "
               "method TEXT NOT NULL, path TEXT NOT NULL, status INTEGER NOT NULL, "
               "body TEXT NOT NULL, created_at TEXT NOT NULL)")
