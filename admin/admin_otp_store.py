# -*- coding: utf-8 -*-
"""ذخیرهٔ OTP ورود ادمین — session + فایل سرور (وقتی کوکی سشن روی HTTP کار نمی‌کند)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from flask import current_app, session


def _otp_file_path() -> str:
    data_dir = os.path.join(current_app.instance_path, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "admin_login_otp.json")


def save_admin_otp(code: str, *, last_sent_at: float | None = None) -> Dict[str, Any]:
    now = datetime.utcnow()
    sent_at = float(last_sent_at if last_sent_at is not None else now.timestamp())
    expires_at = (now + timedelta(hours=1)).timestamp()
    payload = {
        "code": str(code),
        "expires_at": expires_at,
        "last_sent_at": sent_at,
    }
    session.permanent = True
    session["admin_otp_pending"] = True
    session["admin_otp_code"] = payload["code"]
    session["admin_otp_expires_at"] = expires_at
    session["admin_otp_last_sent_at"] = sent_at
    try:
        session.modified = True
    except Exception:
        pass
    try:
        with open(_otp_file_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception as e:
        current_app.logger.warning("admin OTP file save failed: %s", e)
    return payload


def load_admin_otp() -> Optional[Dict[str, Any]]:
    code = session.get("admin_otp_code")
    expires_at = session.get("admin_otp_expires_at")
    last_sent = session.get("admin_otp_last_sent_at")
    if code and expires_at:
        return {
            "code": str(code),
            "expires_at": float(expires_at),
            "last_sent_at": float(last_sent or 0),
        }
    path = _otp_file_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not data.get("code"):
            return None
        return {
            "code": str(data["code"]),
            "expires_at": float(data.get("expires_at") or 0),
            "last_sent_at": float(data.get("last_sent_at") or 0),
        }
    except Exception:
        return None


def clear_admin_otp() -> None:
    for key in (
        "admin_otp_pending",
        "admin_otp_code",
        "admin_otp_expires_at",
        "admin_otp_last_sent_at",
    ):
        session.pop(key, None)
    try:
        path = _otp_file_path()
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass
