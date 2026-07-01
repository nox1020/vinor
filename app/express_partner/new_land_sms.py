# -*- coding: utf-8 -*-
"""پیامک «فایل جدید اکسپرس» به همه همکاران تأییدشده."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import Flask, current_app, url_for

from ..services.sms import (
    is_valid_iran_mobile,
    normalize_iran_mobile,
    send_sms_direct,
)
from ..services.sms_config import get_sms_line_number
from ..utils.storage import load_express_partners, load_settings, load_sms_history, save_sms_history

_APPROVED_PARTNER_STATUSES = frozenset({"approved", "active", "enabled", "ok", "true", "1"})


def _format_toman(amount: Any) -> str:
    try:
        v = max(0, int(str(amount).replace(",", "").strip() or "0"))
    except Exception:
        v = 0
    if v == 0:
        return "0"
    return f"{v:,}".replace(",", "،")


def _is_partner_approved(profile: Dict[str, Any]) -> bool:
    if not isinstance(profile, dict):
        return False
    status = str(profile.get("status") or "").strip().lower()
    return profile.get("status") is True or status in _APPROVED_PARTNER_STATUSES


def _express_land_price_int(land: Dict[str, Any]) -> int:
    try:
        raw = str(land.get("price_total") or land.get("price") or "0").replace(",", "").strip()
        return int(raw) if raw else 0
    except (TypeError, ValueError):
        return 0


def resolve_express_land_commission_amount(land: Dict[str, Any]) -> int:
    """مبلغ پورسانت همکار — همان منطق کارت/جزئیات فایل."""
    extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
    comm_amt = extras.get("express_commission_amount", land.get("express_commission_amount"))
    if comm_amt not in (None, ""):
        try:
            return max(0, int(comm_amt))
        except (TypeError, ValueError):
            pass

    pct_raw = extras.get("express_commission_pct", land.get("express_commission_pct"))
    try:
        pct = float(pct_raw) if pct_raw not in (None, "") else 0.0
    except (TypeError, ValueError):
        pct = 0.0

    price_int = _express_land_price_int(land)
    if price_int and pct:
        return int(round(price_int * (pct / 100.0)))
    return 0


def _express_land_detail_url(land_code: str) -> str:
    code = str(land_code or "").strip()
    if not code:
        return ""
    try:
        return url_for("express_partner.land_detail", code=code, _external=True)
    except Exception:
        return f"https://vinor.ir/express/partner/lands/{code}"


def build_new_land_partner_sms_message(*, commission_amount: int, detail_url: str = "") -> str:
    amt = _format_toman(commission_amount)
    lines = [
        "⚡ فایل جدید در وینور ثبت شد",
        "",
        f"این معامله می‌تواند {amt} تومان برای شما درآمد داشته باشد.",
    ]
    link = (detail_url or "").strip()
    if link:
        lines.extend(["", link])
    return "\n".join(lines)


def list_approved_express_partners() -> List[Dict[str, str]]:
    try:
        partners = load_express_partners(current_app) or []
    except Exception:
        partners = []

    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for p in partners if isinstance(partners, list) else []:
        if not isinstance(p, dict) or not _is_partner_approved(p):
            continue
        phone = normalize_iran_mobile(str(p.get("phone") or "").strip())
        if not is_valid_iran_mobile(phone) or phone in seen:
            continue
        seen.add(phone)
        out.append({
            "phone": phone,
            "name": str(p.get("name") or p.get("full_name") or phone).strip(),
        })
    return out


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
        current_app.logger.exception("Failed to append new-land SMS history")


def notify_all_partners_new_express_land(land: Dict[str, Any]) -> Dict[str, Any]:
    """ارسال پیامک فایل جدید به همه همکاران تأییدشده."""
    if not land.get("is_express"):
        return {"ok": False, "skipped": True, "reason": "not_express"}

    land_code = str(land.get("code") or "").strip()
    commission_amount = resolve_express_land_commission_amount(land)
    detail_url = _express_land_detail_url(land_code)
    message = build_new_land_partner_sms_message(
        commission_amount=commission_amount,
        detail_url=detail_url,
    )

    settings = load_settings(current_app) or {}
    line_number = (
        settings.get("sms_line_number") or get_sms_line_number() or "09981801922"
    ).strip()

    partners = list_approved_express_partners()
    if not partners:
        current_app.logger.warning(
            "New express land SMS skipped: no approved partners land=%s", land_code
        )
        return {"ok": False, "skipped": True, "reason": "no_partners", "land_code": land_code}

    sent = 0
    failed = 0
    for partner in partners:
        phone = partner["phone"]
        try:
            result = send_sms_direct(mobile=phone, message=message, line_number=line_number)
            ok = bool(result.get("ok"))
            if ok:
                sent += 1
            else:
                failed += 1
            _append_sms_history({
                "type": "new_express_land",
                "mobile": phone,
                "recipient_name": partner.get("name"),
                "land_code": land_code,
                "detail_url": detail_url,
                "commission_amount": _format_toman(commission_amount),
                "message": message,
                "success": ok,
                "ok": ok,
                "status_code": result.get("status", 0),
                "response": result.get("body", {}),
                "source": "new_express_land_broadcast",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "error": None if ok else str((result.get("body") or {}).get("message") or "sms_failed"),
            })
        except Exception as exc:
            failed += 1
            current_app.logger.exception(
                "New express land SMS failed land=%s phone=%s", land_code, phone
            )
            _append_sms_history({
                "type": "new_express_land",
                "mobile": phone,
                "recipient_name": partner.get("name"),
                "land_code": land_code,
                "detail_url": detail_url,
                "commission_amount": _format_toman(commission_amount),
                "message": message,
                "success": False,
                "ok": False,
                "source": "new_express_land_broadcast",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "error": str(exc),
            })

    current_app.logger.info(
        "New express land SMS land=%s commission=%s sent=%s failed=%s total=%s",
        land_code,
        commission_amount,
        sent,
        failed,
        len(partners),
    )
    return {
        "ok": sent > 0,
        "land_code": land_code,
        "commission_amount": commission_amount,
        "sent": sent,
        "failed": failed,
        "total": len(partners),
    }


def _run_new_land_sms_batch(app: Flask, land: Dict[str, Any]) -> None:
    with app.app_context():
        try:
            notify_all_partners_new_express_land(land)
        except Exception:
            app.logger.exception(
                "Background new express land SMS failed land=%s", land.get("code")
            )


def notify_all_partners_new_express_land_background(land: Dict[str, Any]) -> None:
    """ارسال غیرمسدودکننده — بعد از ثبت فایل در پس‌زمینه."""
    app = current_app._get_current_object()
    land_snapshot = dict(land)
    extras = land.get("extras")
    if isinstance(extras, dict):
        land_snapshot["extras"] = dict(extras)
    threading.Thread(
        target=_run_new_land_sms_batch,
        args=(app, land_snapshot),
        daemon=True,
        name=f"vinor-new-land-sms-{land_snapshot.get('code') or 'x'}",
    ).start()
