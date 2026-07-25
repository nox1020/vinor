# -*- coding: utf-8 -*-
"""پیامک بروزرسانی APK به همکاران تأییدشده."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Flask, current_app

from .new_land_sms import list_approved_express_partners
from ..services.sms import send_sms_direct
from ..services.sms_config import get_sms_line_number
from ..utils.storage import load_settings, load_sms_history, save_sms_history

DEFAULT_APK_UPDATE_SMS = (
    "نسخه {version}\n"
    "📢 وینور بروزرسانی شد!\n"
    "برای تجربه بهتر، نسخه جدید رو از لینک زیر دریافت کنید 👇\n"
    "🌐 {link}"
)
DEFAULT_APK_UPDATE_LINK = "vinor.ir/d"


def default_apk_update_sms_message() -> str:
    return DEFAULT_APK_UPDATE_SMS


def render_apk_update_sms_message(
    template: str,
    *,
    version: str,
    link: str = DEFAULT_APK_UPDATE_LINK,
) -> str:
    tpl = (template or "").strip() or DEFAULT_APK_UPDATE_SMS
    ver = (version or "").strip() or "—"
    href = (link or "").strip() or DEFAULT_APK_UPDATE_LINK
    # پشتیبانی از هر دو شکل placeholder
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
) -> Dict[str, Any]:
    """ارسال پیامک بروزرسانی اپ به همه همکاران تأییدشده."""
    settings = load_settings(current_app) or {}
    line_number = (
        settings.get("sms_line_number") or get_sms_line_number() or "09981801922"
    ).strip()
    template = (message or settings.get("android_apk_update_sms_message") or "").strip()
    body = render_apk_update_sms_message(template, version=version, link=link)
    if not body:
        return {"ok": False, "skipped": True, "reason": "empty_message"}

    partners = list_approved_express_partners()
    if not partners:
        current_app.logger.warning(
            "APK update SMS skipped: no approved partners version=%s", version
        )
        return {"ok": False, "skipped": True, "reason": "no_partners", "version": version}

    sent = 0
    failed = 0
    for partner in partners:
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
                "APK update SMS failed version=%s phone=%s", version, phone
            )
            _append_sms_history({
                "type": "android_apk_update",
                "mobile": phone,
                "recipient_name": partner.get("name"),
                "version": version,
                "link": link,
                "message": body,
                "success": False,
                "ok": False,
                "source": "android_apk_update_broadcast",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "error": str(exc),
            })

    current_app.logger.info(
        "APK update SMS version=%s sent=%s failed=%s total=%s",
        version,
        sent,
        failed,
        len(partners),
    )
    return {
        "ok": sent > 0,
        "version": version,
        "sent": sent,
        "failed": failed,
        "total": len(partners),
        "message": body,
    }


def _run_apk_update_sms_batch(
    app: Flask,
    *,
    version: str,
    message: str,
    link: str,
) -> None:
    with app.app_context():
        try:
            notify_partners_apk_update(version=version, message=message, link=link)
        except Exception:
            app.logger.exception("Background APK update SMS failed version=%s", version)


def notify_partners_apk_update_background(
    *,
    version: str,
    message: Optional[str] = None,
    link: str = DEFAULT_APK_UPDATE_LINK,
) -> None:
    """ارسال غیرمسدودکننده بعد از آپلود APK."""
    app = current_app._get_current_object()
    settings = load_settings(app) or {}
    template = (message or settings.get("android_apk_update_sms_message") or "").strip()
    body_tpl = template or DEFAULT_APK_UPDATE_SMS
    threading.Thread(
        target=_run_apk_update_sms_batch,
        kwargs={
            "app": app,
            "version": str(version or "").strip(),
            "message": body_tpl,
            "link": (link or DEFAULT_APK_UPDATE_LINK).strip(),
        },
        daemon=True,
        name=f"vinor-apk-update-sms-{version or 'x'}",
    ).start()
