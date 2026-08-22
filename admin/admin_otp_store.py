# -*- coding: utf-8 -*-
"""Cleanup leftover admin OTP session keys. Codes live in otp_challenges only."""
from __future__ import annotations

import os

from flask import current_app, session


def clear_admin_otp() -> None:
    for key in (
        "admin_otp_pending",
        "admin_otp_code",
        "admin_otp_phone",
        "admin_otp_expires_at",
        "admin_otp_last_sent_at",
    ):
        session.pop(key, None)
    try:
        path = os.path.join(current_app.instance_path, "data", "admin_login_otp.json")
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass
