# -*- coding: utf-8 -*-
"""پیامک بروزرسانی APK به گروه گیرندگان انتخاب‌شده."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Flask, current_app

from admin.sms_recipients import (
    RECIPIENT_GROUP_ALL_USERS,
    RECIPIENT_GROUP_LABELS,
    load_sms_recipients,
    recipient_group_label,
)
from ..services.sms import send_sms_direct
from ..services.sms_config import get_sms_line_number
from ..utils.storage import load_settings, load_sms_history, save_sms_history

DEFAULT_APK_UPDATE_SMS = (
    "نسخه {version}\n"
    "📢 وینور بروزرسانی شد!\n"
    "برای تجربه بهتر، نسخه جدید رو از لینک زیر دریافت کنید 👇\n"
    "🌐 {link}"
)
DEFAULT_APK_UPDATE_LINK = "https://vinor.ir/d"
DEFAULT_APK_UPDATE_RECIPIENT_GROUP = RECIPIENT_GROUP_ALL_USERS


def default_apk_update_sms_message() -> str:
    return DEFAULT_APK_UPDATE_SMS


def default_apk_update_sms_recipient_group() -> str:
    return DEFAULT_APK_UPDATE_RECIPIENT_GROUP


def normalize_apk_update_sms_group(value: Optional[str]) -> str:
    key = (value or DEFAULT_APK_UPDATE_RECIPIENT_GROUP).strip().lower()
    if key in RECIPIENT_GROUP_LABELS:
        return key
    return DEFAULT_APK_UPDATE_RECIPIENT_GROUP


def normalize_apk_update_link(link: Optional[str] = None) -> str:
    """لینک پیامک را به https مطلق روی vinor.ir نرمال می‌کند."""
    from urllib.parse import urlparse

    href = (link or "").strip() or DEFAULT_APK_UPDATE_LINK
    if href.startswith("//"):
        href = "https:" + href
    elif "://" not in href:
        href = "https://" + href.lstrip("/")
    try:
        host = (urlparse(href).hostname or "").lower().removeprefix("www.")
    except Exception:
        host = ""
    if host == "vinor.ir" or host.endswith(".vinor.ir"):
        return href
    try:
        from ..utils.short_urls import canonical_public_apk_download_url

        canon = canonical_public_apk_download_url()
        if canon:
            return canon
    except Exception:
        pass
    return DEFAULT_APK_UPDATE_LINK


def render_apk_update_sms_message(
    template: str,
    *,
    version: str,
    link: str = DEFAULT_APK_UPDATE_LINK,
) -> str:
    tpl = (template or "").strip() or DEFAULT_APK_UPDATE_SMS
    ver = (version or "").strip() or "—"
    href = normalize_apk_update_link(link)
    out = (
        tpl.replace("{version}", ver)
        .replace("{VERSION}", ver)
        .replace("{link}", href)
        .replace("{LINK}", href)
        .replace("{url}", href)
        .replace("{URL}", href)
    )
    return out.strip()


def _append_sms_history(entry: dict) -> None:
    try:
        history = load_sms_history(current_app) or []
        if not isinstance(history, list):
            history = []
        history.append(entry)
        if len(history) > 10000:
            history = history[-10000:]
        save_sms_history(history, current_app)
    except Exception:
        current_app.logger.exception("Failed to append apk-update SMS history")


def notify_partners_apk_update(
    *,
    version: str,
    message: Optional[str] = None,
    link: str = DEFAULT_APK_UPDATE_LINK,
    recipient_group: Optional[str] = None,
) -> Dict[str, Any]:
    """ارسال پیامک بروزرسانی اپ به گروه گیرندگان انتخاب‌شده."""
    settings = load_settings(current_app) or {}
    line_number = (
        settings.get("sms_line_number") or get_sms_line_number() or "09981801922"
    ).strip()
    group = normalize_apk_update_sms_group(
        recipient_group
        if recipient_group is not None
        else settings.get("android_apk_update_sms_recipient_group")
    )
    group_label = recipient_group_label(group)
    template = (message or settings.get("android_apk_update_sms_message") or "").strip()
    body = render_apk_update_sms_message(template, version=version, link=link)
    if not body:
        return {"ok": False, "skipped": True, "reason": "empty_message", "recipient_group": group}

    recipients = load_sms_recipients(group, limit=None, offset=0, validate=False)
    if not recipients:
        current_app.logger.warning(
            "APK update SMS skipped: no recipients group=%s version=%s", group, version
        )
        return {
            "ok": False,
            "skipped": True,
            "reason": "no_recipients",
            "version": version,
            "recipient_group": group,
            "recipient_group_label": group_label,
        }

    sent = 0
    failed = 0
    for partner in recipients:
        phone = partner["phone"]
        try:
            result = send_sms_direct(mobile=phone, message=body, line_number=line_number)
            ok = bool(result.get("ok"))
            if ok:
                sent += 1
            else:
                failed += 1
            _append_sms_history({
                "type": "android_apk_update",
                "mobile": phone,
                "recipient_name": partner.get("name"),
                "version": version,
                "link": link,
                "recipient_group": group,
                "message": body,
                "success": ok,
                "ok": ok,
                "status_code": result.get("status", 0),
                "response": result.get("body", {}),
                "source": "android_apk_update_broadcast",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "error": None if ok else str((result.get("body") or {}).get("message") or "sms_failed"),
            })
        except Exception as exc:
            failed += 1
            current_app.logger.exception(
                "APK update SMS failed version=%s phone=%s group=%s", version, phone, group
            )
            _append_sms_history({
                "type": "android_apk_update",
                "mobile": phone,
                "recipient_name": partner.get("name"),
                "version": version,
                "link": link,
                "recipient_group": group,
                "message": body,
                "success": False,
                "ok": False,
                "source": "android_apk_update_broadcast",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "error": str(exc),
            })

    current_app.logger.info(
        "APK update SMS version=%s group=%s sent=%s failed=%s total=%s",
        version,
        group,
        sent,
        failed,
        len(recipients),
    )
    return {
        "ok": sent > 0,
        "version": version,
        "recipient_group": group,
        "recipient_group_label": group_label,
        "sent": sent,
        "failed": failed,
        "total": len(recipients),
        "message": body,
    }


def _run_apk_update_sms_batch(
    app: Flask,
    *,
    version: str,
    message: str,
    link: str,
    recipient_group: str,
) -> None:
    with app.app_context():
        try:
            notify_partners_apk_update(
                version=version,
                message=message,
                link=link,
                recipient_group=recipient_group,
            )
        except Exception:
            app.logger.exception("Background APK update SMS failed version=%s", version)


def notify_partners_apk_update_background(
    *,
    version: str,
    message: Optional[str] = None,
    link: str = DEFAULT_APK_UPDATE_LINK,
    recipient_group: Optional[str] = None,
) -> None:
    """ارسال غیرمسدودکننده بعد از آپلود APK."""
    app = current_app._get_current_object()
    settings = load_settings(app) or {}
    template = (message or settings.get("android_apk_update_sms_message") or "").strip()
    body_tpl = template or DEFAULT_APK_UPDATE_SMS
    group = normalize_apk_update_sms_group(
        recipient_group
        if recipient_group is not None
        else settings.get("android_apk_update_sms_recipient_group")
    )
    threading.Thread(
        target=_run_apk_update_sms_batch,
        kwargs={
            "app": app,
            "version": str(version or "").strip(),
            "message": body_tpl,
            "link": (link or DEFAULT_APK_UPDATE_LINK).strip(),
            "recipient_group": group,
        },
        daemon=True,
        name=f"vinor-apk-update-sms-{version or 'x'}",
    ).start()
