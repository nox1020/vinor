# -*- coding: utf-8 -*-
"""تنظیمات بک‌اند Invest داخل وینور — جدا از هستهٔ اصلی."""
from __future__ import annotations

import os
from pathlib import Path

INVEST_ROOT = Path(__file__).resolve().parent.parent


def invest_enabled() -> bool:
    return (os.environ.get("VINOR_INVEST_ENABLED") or "1").strip().lower() in (
        "1", "true", "yes", "on",
    )


def invest_instance_root(flask_app=None) -> Path:
    from flask import current_app

    app = flask_app or current_app._get_current_object()
    root = Path(app.instance_path) / "invest"
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_db_path(phone: str, flask_app=None) -> Path:
    from app.services.sms import normalize_iran_mobile

    mobile = normalize_iran_mobile(phone) or (phone or "").strip()
    safe = mobile.replace("+", "").replace(" ", "")
    data_dir = invest_instance_root(flask_app) / "users" / safe
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "invest.db"


def user_profile_path(phone: str, flask_app=None) -> Path:
    from app.services.sms import normalize_iran_mobile

    mobile = normalize_iran_mobile(phone) or (phone or "").strip()
    safe = mobile.replace("+", "").replace(" ", "")
    profiles = invest_instance_root(flask_app) / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    return profiles / f"{safe}.json"
