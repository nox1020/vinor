# -*- coding: utf-8 -*-
"""لینک‌های عمومی کوتاه — دعوت (/r) و دانلود APK (/d)."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, Tuple

_SAFE_VER = re.compile(r"[^A-Za-z0-9._\-]+")


def _load_settings_safe(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if settings is not None:
        return settings if isinstance(settings, dict) else {}
    try:
        from ..utils.storage import load_settings

        return load_settings() or {}
    except Exception:
        return {}


def apk_file_url_from_settings(settings: Optional[Dict[str, Any]] = None) -> str:
    """مسیر واقعی فایل APK در تنظیمات (برای چک داخلی)."""
    return str(_load_settings_safe(settings).get("android_apk_url") or "").strip()


def apk_public_download_filename(
    settings: Optional[Dict[str, Any]] = None,
    *,
    version: Optional[str] = None,
) -> str:
    """نام فایل هنگام دانلود کاربر — مثلاً vinor-1.0.253.apk"""
    data = _load_settings_safe(settings)
    ver = (version if version is not None else data.get("android_apk_version") or "").strip()
    safe = _SAFE_VER.sub("", ver.replace(" ", ""))
    if safe:
        return f"vinor-{safe}.apk"
    return "vinor.apk"


def resolve_apk_filesystem_path(
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """(absolute_path, download_filename) برای فایل APK فعلی."""
    from flask import current_app, has_app_context

    from ..utils.storage import data_dir, legacy_dir

    data = _load_settings_safe(settings)
    url = apk_file_url_from_settings(data)
    download_name = apk_public_download_filename(data)
    if not url or url.startswith(("http://", "https://")):
        return None, download_name

    rel = url.lstrip("/")
    if rel.startswith("uploads/"):
        rel = rel[len("uploads/") :]
    rel = os.path.normpath(rel).replace("\\", "/")
    if rel.startswith("..") or not rel:
        return None, download_name

    candidates = []
    if has_app_context():
        base_cfg = current_app.config.get("UPLOAD_FOLDER")
        if base_cfg:
            candidates.append(os.path.join(base_cfg, rel))
    candidates.extend(
        [
            os.path.join(data_dir(), "uploads", rel),
            os.path.join(legacy_dir(), "uploads", rel),
        ]
    )
    for fp in candidates:
        try:
            if os.path.isfile(fp):
                return fp, download_name
        except OSError:
            continue
    return None, download_name


_PUBLIC_HOST = "vinor.ir"


def canonical_public_apk_download_url(
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """لینک مطلق پایدار برای کلاینت‌ها (اپ، پیامک، API) — همیشه https://vinor.ir/d/..."""
    data = _load_settings_safe(settings)
    if not apk_file_url_from_settings(data):
        return ""
    name = apk_public_download_filename(data)
    # Prefer versioned path (no trailing-slash 308). Bare /d is also valid.
    path = f"/d/{name}" if name else "/d/"
    return f"https://{_PUBLIC_HOST}{path}"


def public_apk_download_url(
    settings: Optional[Dict[str, Any]] = None,
    *,
    external: bool = True,
) -> str:
    """لینک کوتاه دانلود: /d/vinor-{version}.apk (یا /d).

    برای مصرف‌کننده‌های خارجی (Android / SMS) از canonical_public_apk_download_url
    استفاده کنید تا host اشتباه (localhost / proxy) در URL نیاید.
    """
    data = _load_settings_safe(settings)
    if not apk_file_url_from_settings(data):
        return ""
    name = apk_public_download_filename(data)
    if external:
        # Absolute URL for emails/SMS/native — prefer canonical production host
        # so Android trust checks (vinor.ir) never see an internal origin.
        return canonical_public_apk_download_url(data)
    try:
        from flask import has_request_context, url_for

        if has_request_context():
            return url_for(
                "main.short_apk_download",
                download_name=name,
                _external=False,
            )
    except Exception:
        pass
    return f"/d/{name}" if name else "/d"


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
