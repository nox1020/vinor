# -*- coding: utf-8 -*-
"""لینک‌های عمومی کوتاه — دعوت (/r) و دانلود APK (/d)."""
from __future__ import annotations

from typing import Any, Dict, Optional


def apk_file_url_from_settings(settings: Optional[Dict[str, Any]] = None) -> str:
    """مسیر واقعی فایل APK در تنظیمات (برای چک داخلی)."""
    if settings is None:
        try:
            from ..utils.storage import load_settings

            settings = load_settings() or {}
        except Exception:
            settings = {}
    return str((settings or {}).get("android_apk_url") or "").strip()


def public_apk_download_url(
    settings: Optional[Dict[str, Any]] = None,
    *,
    external: bool = True,
) -> str:
    """لینک کوتاه دانلود: /d"""
    if not apk_file_url_from_settings(settings):
        return ""
    try:
        from flask import has_request_context, url_for

        if has_request_context():
            return url_for("main.short_apk_download", _external=external)
    except Exception:
        pass
    return "/d"


def public_referral_url(ref_token: str, *, external: bool = True) -> str:
    """لینک کوتاه دعوت: /r/<token>"""
    token = str(ref_token or "").strip()
    if not token:
        return ""
    try:
        from flask import has_request_context, url_for

        if has_request_context():
            return url_for("main.short_referral", ref=token, _external=external)
    except Exception:
        pass
    return f"/r/{token}"
