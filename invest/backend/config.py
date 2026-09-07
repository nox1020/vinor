# -*- coding: utf-8 -*-
"""تنظیمات بک‌اند Invest داخل وینور — جدا از هستهٔ اصلی."""
from __future__ import annotations

import os
from pathlib import Path

INVEST_ROOT = Path(__file__).resolve().parent.parent
_VERSION_FILE = Path(__file__).resolve().parent / "VERSION"


def invest_api_version() -> str:
    """API version for mobile sync — env override, then VERSION file, then default."""
    env = (os.environ.get("VINOR_INVEST_API_VERSION") or "").strip()
    if env:
        return env
    try:
        if _VERSION_FILE.is_file():
            text = _VERSION_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except OSError:
        pass
    return "1.0.0"


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


def market_index_db_path(flask_app=None) -> Path:
    """Shared (not per-user) SQLite for شاخص snapshots."""
    root = invest_instance_root(flask_app)
    return root / "market_index.db"
